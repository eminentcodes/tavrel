"""Durable native submission. Only independently checked finality clears holds."""
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
from threading import Event, Lock, Thread
import time

from .engine import PolicyError, encode, now

GENESIS = '0xff7fe5a610f15fe7a0c52f94f86313fb7db7d3786e7f8acf2b66c11d5be7c242'


def rpc(action, **values):
    node = shutil.which('node')
    if not node:
        raise PolicyError('network_unavailable', 'Install Node and the project dependencies.', 503)
    try:
        script = Path(__file__).with_name('native_rpc.bundle.mjs')
        if not script.exists():
            script = Path(__file__).with_name('native_rpc.mjs')
        process = subprocess.run([node, str(script)],
            input=json.dumps({'action': action, 'genesis_hash': GENESIS, **values}),
            capture_output=True, text=True, timeout=45)
        result = json.loads(process.stdout)
        if result.get('ok') is not True:
            raise PolicyError('network_check_failed', result.get('error', 'Network check failed.'), 503)
        return result['result']
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise PolicyError('network_unavailable', 'The network did not respond. Existing payment holds remain reserved; check again.', 503) from error


class Settlement:
    def __init__(self, payments, network=rpc):
        self.payments = payments
        self.engine = payments.engine
        self.network = network
        self.lock = Lock()
        self.stop_event = Event()
        self.worker = None
        with self.engine.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS payment_quotes(id TEXT PRIMARY KEY,
                payment_id TEXT NOT NULL REFERENCES payment_intents(id), approval_hash TEXT NOT NULL,
                quote TEXT NOT NULL, expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS payment_policy_snapshots(payment_id TEXT PRIMARY KEY REFERENCES payment_intents(id),
                approval_hash TEXT NOT NULL, snapshot TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS payment_proofs(payment_id TEXT PRIMARY KEY REFERENCES payment_intents(id),
                approval_hash TEXT NOT NULL, bundle TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS payment_transactions(
                payment_id TEXT PRIMARY KEY REFERENCES payment_intents(id), tx_hash TEXT UNIQUE NOT NULL,
                signed_hex TEXT NOT NULL, nonce TEXT NOT NULL, scan_height INTEGER NOT NULL,
                expires_height INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, receipt TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            ''')

    def authorize(self, payment_id, expected_hash):
        with self.engine.transaction() as db:
            payment = self.payments._intent(payment_id, db)
            self.payments._confirm(payment, expected_hash)
            if payment['status'] not in ('ready_for_signature', 'exported'):
                raise PolicyError('payment_not_authorized', 'This payment is not ready to send.', 409)
            refreshed = self.payments._refresh(db, payment)
        # Commit policy changes/hold release before asking for a new review.
        if refreshed['status'] not in ('ready_for_signature', 'exported') or refreshed['approval_hash'] != expected_hash:
            raise PolicyError('payment_review_changed', 'The rules changed. Review the payment again.', 409)
        return refreshed

    def _save_policy_snapshot(self, db, payment_id, approval_hash, snapshot):
        encoded = encode(snapshot)
        prior = db.execute('SELECT * FROM payment_policy_snapshots WHERE payment_id=?', (payment_id,)).fetchone()
        if not prior or prior['approval_hash'] != approval_hash or prior['snapshot'] != encoded:
            db.execute('DELETE FROM payment_proofs WHERE payment_id=?', (payment_id,))
        db.execute('INSERT INTO payment_policy_snapshots VALUES(?,?,?) ON CONFLICT(payment_id) DO UPDATE SET approval_hash=excluded.approval_hash,snapshot=excluded.snapshot',
            (payment_id, approval_hash, encoded))

    def quote(self, payment_id, expected_hash):
        payment = self.authorize(payment_id, expected_hash)
        quote = self.network('quote', payment=payment)
        self.authorize(payment_id, expected_hash)
        quote_id = secrets.token_hex(16)
        with self.engine.transaction() as db:
            current = self.payments._intent(payment_id, db)
            self.payments._confirm(current, expected_hash)
            policy = self.payments.policy(current['task_id'], db)
            account = self.payments._account(db)
            snapshot = {'recipients': sorted(set(policy['recipients'].values())), 'cap_units': policy['per_payment_units'],
                'task_available_units': str(int(policy['available_units']) + int(current['amount_units'])),
                'account_available_units': str(int(account['limit_units']) - int(account['reserved_units']) - int(account['spent_units']) + int(current['amount_units']))}
            quote['policy_snapshot'] = snapshot
            db.execute('DELETE FROM payment_quotes WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO payment_quotes VALUES(?,?,?,?,?)',
                (quote_id, payment_id, expected_hash, encode(quote), time.time() + 180))
            self._save_policy_snapshot(db, payment_id, expected_hash, snapshot)
        return {key: value for key, value in {**quote, 'quote_id': quote_id}.items() if key != 'policy_snapshot'}

    def submit(self, payment_id, expected_hash, quote_id, signature, signed_hex=None):
        if not isinstance(signature, str) or re.fullmatch(r'0x[0-9a-fA-F]{128,132}', signature) is None:
            raise PolicyError('invalid_transaction', 'Provide the exact wallet signature.')
        if signed_hex is not None and (not isinstance(signed_hex, str) or re.fullmatch(r'0x(?:[0-9a-fA-F]{2}){50,16000}', signed_hex) is None):
            raise PolicyError('invalid_transaction', 'Provide the exact wallet-signed transaction.')
        with self.lock:
            with self.engine.connection() as db:
                prior = db.execute('SELECT * FROM payment_transactions WHERE payment_id=?', (payment_id,)).fetchone()
                saved = db.execute('SELECT * FROM payment_quotes WHERE id=? AND payment_id=?', (quote_id, payment_id)).fetchone()
            if prior:
                # Never create a replacement for a request with durable signed bytes.
                self.payments._confirm(self.payments.intent(payment_id), expected_hash)
                return self.payments.intent(payment_id)
            if not saved or saved['expires'] <= time.time() or saved['approval_hash'] != expected_hash:
                raise PolicyError('quote_expired', 'The fee review expired. Review fees again before signing.', 409)
            payment = self.authorize(payment_id, expected_hash)
            quote = json.loads(saved['quote'])
            inspection = self.network('inspect', payment=payment, quote=quote, signature=signature, signed_hex=signed_hex)
            self.authorize(payment_id, expected_hash)
            with self.engine.transaction() as db:
                current = self.payments._intent(payment_id, db)
                self.payments._confirm(current, expected_hash)
                if current['status'] not in ('ready_for_signature', 'exported'):
                    raise PolicyError('payment_not_authorized', 'This request is no longer eligible to send.', 409)
                policy = self.payments.policy(current['task_id'], db)
                if policy['version'] != current['policy_version'] or self.payments._reason(db, policy, current['recipient'], int(current['amount_units'])):
                    raise PolicyError('payment_review_changed', 'Review the updated payment before signing.', 409)
                if db.execute("SELECT 1 FROM payment_transactions t JOIN payment_intents p ON p.id=t.payment_id WHERE p.sender=? AND t.nonce=? AND t.status IN ('submitting','submitted')", (payment['sender'], inspection['nonce'])).fetchone():
                    raise PolicyError('signer_nonce_in_use', 'Another payment uses this wallet nonce. Wait for its result, then review fees again.', 409)
                stamp = now()
                db.execute('INSERT INTO payment_transactions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (payment_id, inspection['tx_hash'], inspection['signed_hex'], inspection['nonce'], quote['finalized_height'],
                     quote['expires_height'], 'submitting', None, None, stamp, stamp))
                self._save_policy_snapshot(db, payment_id, expected_hash, quote['policy_snapshot'])
                db.execute("UPDATE payment_intents SET status='submitting',updated_at=? WHERE id=?", (stamp, payment_id))
                self.engine.event(db, 'payment_signed', 'Saved the verified wallet signature and exact transaction before submission.', payment['task_id'], payment_id)
            return self.payments.intent(payment_id)

    def reconcile(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            with self.engine.connection() as db:
                rows = [dict(row) for row in db.execute("SELECT t.*,p.sender,p.recipient,p.amount_units FROM payment_transactions t JOIN payment_intents p ON p.id=t.payment_id WHERE t.status IN ('submitting','submitted') ORDER BY t.updated_at LIMIT 10")]
            if not rows:
                return
            checked = self.network('scan', payments=[{key: row[key] for key in ('payment_id','tx_hash','scan_height','expires_height','sender','recipient','amount_units')} for row in rows])
            for item in checked['payments']:
                self.record_verified(item)
            # Scan before retrying; restart always resends identical signed bytes.
            for row in rows:
                if self.stop_event.is_set():
                    break
                current = self.payments.intent(row['payment_id'])
                if current['status'] not in ('submitting', 'submitted'):
                    continue
                try:
                    outcome = self.network('submit', payment=current, signed_hex=row['signed_hex'])
                    stamp = now()
                    with self.engine.transaction() as db:
                        state = 'submitted' if outcome.get('submitted') else current['status']
                        db.execute('UPDATE payment_transactions SET status=?,error=?,updated_at=? WHERE payment_id=?',
                            (state, outcome.get('error'), stamp, row['payment_id']))
                        db.execute('UPDATE payment_intents SET status=?,updated_at=? WHERE id=?', (state, stamp, row['payment_id']))
                except PolicyError:
                    pass  # A timeout never releases the hold.
        finally:
            self.lock.release()

    def record_verified(self, checked):
        with self.engine.transaction() as db:
            transaction = db.execute('SELECT * FROM payment_transactions WHERE payment_id=?', (checked['payment_id'],)).fetchone()
            if not transaction or transaction['tx_hash'] != checked['tx_hash'] or transaction['status'] not in ('submitting','submitted'):
                return
            receipt = checked.get('receipt')
            payment = self.payments._intent(checked['payment_id'], db)
            if not receipt:
                if checked.get('expired') is True:
                    if checked.get('genesis_hash') != GENESIS or checked.get('finalized_height', -1) < transaction['expires_height'] or checked['scan_height'] <= transaction['expires_height']:
                        raise PolicyError('receipt_mismatch', 'Transaction expiry has not been independently verified.', 409)
                    state, error = 'expired', 'The signed transaction expired without inclusion in finalized chain history. Prepare a new request if you still want to pay.'
                    self.payments._release(db, payment)
                    db.execute('UPDATE payment_transactions SET status=?,error=?,updated_at=? WHERE payment_id=?', (state, error, now(), payment['id']))
                    db.execute('UPDATE payment_intents SET status=?,reason=?,updated_at=? WHERE id=?', (state, error, now(), payment['id']))
                    self.engine.event(db, 'payment_expired', error, payment['task_id'], payment['id'])
                else:
                    db.execute('UPDATE payment_transactions SET scan_height=?,updated_at=? WHERE payment_id=?', (checked['scan_height'], now(), checked['payment_id']))
                return
            if receipt.get('genesis_hash') != GENESIS or receipt.get('finality_verified') is not True or type(receipt.get('success')) is not bool or any(receipt.get(key) != payment[key] for key in ('sender','recipient','amount_units')) or receipt.get('tx_hash') != transaction['tx_hash']:
                raise PolicyError('receipt_mismatch', 'The verified transaction does not match this request.', 409)
            state = 'settled' if receipt['success'] else 'failed'
            self.payments._release(db, payment)
            if receipt['success']:
                for table, condition, params in (('payment_account','id=1',()), ('payment_policies','task_id=?',(payment['task_id'],))):
                    current = db.execute(f'SELECT spent_units FROM {table} WHERE {condition}', params).fetchone()['spent_units']
                    db.execute(f'UPDATE {table} SET spent_units=? WHERE {condition}', (str(int(current) + int(payment['amount_units'])), *params))
            db.execute('UPDATE payment_transactions SET status=?,receipt=?,error=?,updated_at=? WHERE payment_id=?',
                (state, encode(receipt), receipt.get('error'), now(), checked['payment_id']))
            db.execute('UPDATE payment_intents SET status=?,reason=?,updated_at=? WHERE id=?',
                (state, receipt.get('error'), now(), checked['payment_id']))
            self.engine.event(db, 'payment_' + state, 'Verified native transaction in a finalized zkVerify block.', payment['task_id'], payment['id'])

    def start(self):
        def work():
            while not self.stop_event.wait(5):
                try:
                    self.reconcile()
                except (PolicyError, OSError):
                    pass
        self.worker = Thread(target=work, daemon=True, name='tavrel-finality')
        self.worker.start()

    def close(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=46)
