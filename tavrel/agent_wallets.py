"""User-enabled automatic signing from a separate, encrypted agent wallet."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import shutil
import subprocess
from threading import Event, Lock, Thread

from .engine import PolicyError, now
from .key_vault import KeyVault
from .payments import units, wallet_address


def wallet_operation(action, seed, **values):
    script = Path(__file__).with_name('agent_wallet.bundle.mjs')
    if not script.exists():
        script = script.with_name('agent_wallet.mjs')
    try:
        result = subprocess.run([shutil.which('node') or 'node', str(script)], input=json.dumps(
            {'action': action, 'seed': '0x' + seed.hex(), **values}), capture_output=True, text=True, timeout=25)
        response = json.loads(result.stdout)
        if result.returncode or response.get('ok') is not True:
            raise ValueError('wallet operation failed')
        return response['result']
    except (OSError, ValueError, subprocess.SubprocessError):
        raise PolicyError('agent_wallet_unavailable', 'The agent wallet could not complete its signing operation.', 503) from None


class AgentWallets:
    def __init__(self, settlement, vault=None, operate=wallet_operation):
        self.settlement = settlement
        self.payments = settlement.payments
        self.engine = self.payments.engine
        self.vault = vault or KeyVault(Path(self.engine.database).parent)
        self.operate = operate
        self.lock = Lock()
        self.stopping = Event()
        self.thread = None
        with self.engine.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS agent_wallets (
                task_id TEXT PRIMARY KEY REFERENCES tasks(id), address TEXT NOT NULL UNIQUE,
                encrypted_seed TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
                policy_version INTEGER, fee_cap_units TEXT NOT NULL DEFAULT '0',
                expires_at TEXT, last_error TEXT, created_at TEXT NOT NULL)''')

    def start(self):
        if self.thread is None:
            self.thread = Thread(target=self._work, name='tavrel-agent-wallet', daemon=True)
            self.thread.start()

    def close(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=1)

    def get(self, task_id):
        with self.engine.connection() as db:
            task = self.engine.task(task_id, db)
            row = db.execute('SELECT * FROM agent_wallets WHERE task_id=?', (task_id,)).fetchone()
            if not row:
                return {'created': False, 'enabled': False}
            value = dict(row)
            value.pop('encrypted_seed')
            value['created'] = True
            value['wallet_address'] = wallet_address(value['address'])
            policy = db.execute('SELECT version,sender FROM payment_policies WHERE task_id=?', (task_id,)).fetchone()
            value['enabled'] = bool(value['enabled'])
            value['authorized'] = bool(value['enabled'] and policy and policy['version'] == value['policy_version']
                and not task['paused'] and policy['sender'] == value['address'] and value['expires_at'] and value['expires_at'] > now())
            return value

    def create(self, task_id):
        with self.lock:
            current = self.get(task_id)
            if current['created']:
                return current
            seed = secrets.token_bytes(32)
            protected = self.vault.encrypt(seed)
            account = self.operate('public', seed)
            with self.engine.transaction() as db:
                self.engine.task(task_id, db)
                db.execute('INSERT INTO agent_wallets(task_id,address,encrypted_seed,created_at) VALUES(?,?,?,?)',
                    (task_id, account['address'], protected, now()))
                self.engine.event(db, 'agent_wallet_created', 'Created a separate agent wallet. It has no funds or signing permission yet.', task_id)
            return self.get(task_id)

    def configure(self, task_id, enabled, expected_version, fee_cap='0.001', hours=24):
        if type(enabled) is not bool or type(expected_version) is not int or type(hours) is not int or not 1 <= hours <= 168:
            raise PolicyError('invalid_agent_wallet_permission', 'Choose a signing permission lasting 1 to 168 hours with the reviewed policy version.')
        fee = units(fee_cap, False)
        with self.engine.transaction() as db:
            wallet = db.execute('SELECT * FROM agent_wallets WHERE task_id=?', (task_id,)).fetchone()
            if not wallet:
                raise PolicyError('agent_wallet_missing', 'Create an agent wallet first.', 409)
            policy = self.payments.policy(task_id, db)
            if enabled and (policy['version'] != expected_version or policy['sender'] != wallet['address']):
                raise PolicyError('agent_wallet_policy_mismatch', 'Set this agent wallet as the policy’s sender and review the latest rules before enabling signing.', 409)
            expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec='milliseconds')
            db.execute('UPDATE agent_wallets SET enabled=?,policy_version=?,fee_cap_units=?,expires_at=?,last_error=NULL WHERE task_id=?',
                (int(enabled), policy['version'], str(fee), expires, task_id))
            self.engine.event(db, 'agent_wallet_permission', 'Enabled bounded agent-wallet signing.' if enabled else 'Stopped future agent-wallet signing. Saved transactions remain recoverable.', task_id)
        return self.get(task_id)

    def send(self, payment_id):
        # Serialize automatic signers and revocation. Never approve a payment.
        with self.lock:
            payment = self.payments.intent(payment_id)
            wallet = self.get(payment['task_id'])
            if not wallet.get('authorized') or payment['sender'] != wallet['address'] or payment['policy_version'] != wallet['policy_version']:
                raise PolicyError('agent_wallet_not_authorized', 'Automatic signing is disabled, expired, or the policy changed.', 409)
            if payment['status'] not in ('ready_for_signature', 'exported'):
                raise PolicyError('payment_not_authorized', 'This payment still needs approval or cannot be sent.', 409)
            quote = self.settlement.quote(payment_id, payment['approval_hash'])
            if not quote['enough_funds']:
                raise PolicyError('agent_wallet_unfunded', 'Fund the agent wallet with enough tVFY for this payment, fees, and the account minimum.', 409)
            if int(quote['fee_units']) > int(wallet['fee_cap_units']):
                raise PolicyError('agent_wallet_fee_limit', 'The current fee exceeds your automatic signing fee cap.', 409)
            # Recheck permission after network access and before signing.
            current = self.get(payment['task_id'])
            if not current['authorized'] or current['policy_version'] != wallet['policy_version']:
                raise PolicyError('agent_wallet_not_authorized', 'Signing permission changed during fee review.', 409)
            with self.engine.connection() as db:
                encrypted = db.execute('SELECT encrypted_seed FROM agent_wallets WHERE task_id=?', (payment['task_id'],)).fetchone()['encrypted_seed']
            signed = self.operate('sign', self.vault.decrypt(encrypted), sender=payment['sender'], payload=quote['payload'])
            if self.stopping.is_set():
                raise PolicyError('agent_wallet_stopped', 'Automatic signing stopped before transaction submission.', 409)
            # Settlement independently validates the signature and latest rules.
            return self.settlement.submit(payment_id, payment['approval_hash'], quote['quote_id'], signed['signature'],
                signer_permission={'task_id': payment['task_id'], 'policy_version': wallet['policy_version']})

    def tick(self):
        with self.engine.connection() as db:
            ids = [row['id'] for row in db.execute("""SELECT p.id FROM payment_intents p JOIN agent_wallets w ON p.task_id=w.task_id
                WHERE w.enabled=1 AND p.status IN ('ready_for_signature','exported') ORDER BY p.created_at LIMIT 8""")]
        for payment_id in ids:
            if self.stopping.is_set():
                return
            payment = self.payments.intent(payment_id)
            if not self.get(payment['task_id']).get('authorized'):
                continue
            try:
                self.send(payment_id)
                error = None
            except PolicyError as failure:
                error = str(failure)
            except Exception:
                error = 'Automatic signing paused after an unexpected error. Review this payment.'
            with self.engine.transaction() as db:
                db.execute('UPDATE agent_wallets SET last_error=? WHERE task_id=?', (error, payment['task_id']))

    def _work(self):
        while not self.stopping.wait(15):
            self.tick()
