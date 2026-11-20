"""Optional real FFLONK artifacts. Generation never certifies chain settlement."""
import json
from pathlib import Path
import shutil
import subprocess
from threading import Lock

from .engine import PolicyError, encode
from .settlement import GENESIS

ROOT = Path(__file__).resolve().parents[1]


class PolicyProofs:
    def __init__(self, settlement):
        self.settlement = settlement
        self.payments = settlement.payments
        self.engine = settlement.engine
        self.lock = Lock()
        with self.engine.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS payment_proofs(payment_id TEXT PRIMARY KEY REFERENCES payment_intents(id), approval_hash TEXT NOT NULL, bundle TEXT NOT NULL)')

    def available(self):
        directory = ROOT / '.tavrel-proofs'
        return all((directory / file).is_file() for file in ('manifest.json','verification_key.json','payment_policy.zkey','payment_policy_js/payment_policy.wasm'))

    def generate(self, payment_id, expected_hash):
        if not self.available():
            raise PolicyError('proof_setup_required', 'Build the verified policy proving artifacts first with npm run proof:setup.', 409)
        if not self.lock.acquire(blocking=False):
            raise PolicyError('proof_in_progress', 'Another policy proof is being generated. Try again when it finishes.', 409)
        try:
            payment = self.payments.intent(payment_id)
            self.payments._confirm(payment, expected_hash)
            if payment['status'] in ('ready_for_signature', 'exported'):
                payment = self.settlement.authorize(payment_id, expected_hash)
            elif payment['status'] not in ('submitting','submitted','settled','failed','expired'):
                raise PolicyError('payment_not_authorized', 'Only an authorized payment can have this policy proof.', 409)
            with self.engine.connection() as db:
                saved = db.execute('SELECT * FROM payment_proofs WHERE payment_id=? AND approval_hash=?', (payment_id, expected_hash)).fetchone()
                if saved:
                    return json.loads(saved['bundle'])
                snapshot = db.execute('SELECT snapshot FROM payment_policy_snapshots WHERE payment_id=? AND approval_hash=?', (payment_id, expected_hash)).fetchone()
            if not snapshot:
                raise PolicyError('proof_snapshot_missing', 'Review payment fees first to record the authorized policy snapshot.', 409)
            node = shutil.which('node')
            if not node:
                raise PolicyError('proof_unavailable', 'Install the documented Node version.', 503)
            try:
                process = subprocess.run([node, str(ROOT / 'tavrel/policy_proof.mjs')], cwd=ROOT,
                    input=json.dumps({'action': 'generate', 'payment': payment, 'snapshot': json.loads(snapshot['snapshot']), 'genesis_hash': GENESIS}),
                    capture_output=True, text=True, timeout=240)
                result = json.loads(process.stdout)
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                raise PolicyError('proof_unavailable', 'Proof generation did not complete. No proof reference was recorded.', 503) from error
            if result.get('ok') is not True:
                raise PolicyError('proof_failed', result.get('error', 'Proof verification failed.'), 409)
            bundle = result['result']
            with self.engine.transaction() as db:
                current = self.payments._intent(payment_id, db)
                self.payments._confirm(current, expected_hash)
                current_snapshot = db.execute('SELECT snapshot FROM payment_policy_snapshots WHERE payment_id=? AND approval_hash=?', (payment_id, expected_hash)).fetchone()
                if not current_snapshot or current_snapshot['snapshot'] != snapshot['snapshot']:
                    raise PolicyError('proof_snapshot_changed', 'The reviewed allowance snapshot changed. Generate the proof again.', 409)
                db.execute('INSERT INTO payment_proofs VALUES(?,?,?) ON CONFLICT(payment_id) DO UPDATE SET approval_hash=excluded.approval_hash,bundle=excluded.bundle', (payment_id, expected_hash, encode(bundle)))
                self.engine.event(db, 'payment_policy_proved', 'Generated and locally verified the committed recipient and allowance claim. No zkVerify proof transaction was submitted.', payment['task_id'], payment_id)
            return bundle
        finally:
            self.lock.release()
