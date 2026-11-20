"""Proof cache and snapshot lifecycle; fixture results are not cryptographic evidence."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from tavrel.engine import PolicyError
from tavrel.proofs import PolicyProofs
from tavrel.payments import PaymentLedger
from tavrel.settlement import Settlement
from tests import test_settlement
from tests.test_payments import policy_arguments
from tests.support import EngineCase


class PolicyProofTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.payments = PaymentLedger(self.engine)
        self.task_id = self.create()['task']['id']
        self.payments.set_account('10')
        self.payments.configure(self.task_id, **policy_arguments())
        self.settlement = Settlement(self.payments, test_settlement.NetworkFixture())
        self.payment = self.payments.prepare(self.task_id, 'search', '2', 'Invoice', 'invoice')

    def test_generation_rejects_snapshot_changed_during_proving(self):
        self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
        proofs = PolicyProofs(self.settlement)
        def generate(*args, **kwargs):
            self.payments.prepare(self.task_id, 'search', '3', 'Other invoice', 'other')
            self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
            return SimpleNamespace(stdout=json.dumps({'ok': True, 'result': {'reference': 'fixture-only'}}))
        with patch.object(proofs, 'available', return_value=True), patch('tavrel.proofs.subprocess.run', side_effect=generate):
            with self.assertRaises(PolicyError) as error:
                proofs.generate(self.payment['id'], self.payment['approval_hash'])
        self.assertEqual(error.exception.code, 'proof_snapshot_changed')
        with self.engine.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM payment_proofs').fetchone()[0], 0)

    def test_cached_artifact_is_reused_until_snapshot_changes(self):
        self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
        proofs = PolicyProofs(self.settlement)
        result = SimpleNamespace(stdout=json.dumps({'ok': True, 'result': {'reference': 'fixture-only'}}))
        with patch.object(proofs, 'available', return_value=True), patch('tavrel.proofs.subprocess.run', return_value=result) as runner:
            first = proofs.generate(self.payment['id'], self.payment['approval_hash'])
            self.assertEqual(proofs.generate(self.payment['id'], self.payment['approval_hash']), first)
            self.assertEqual(runner.call_count, 1)
            self.payments.prepare(self.task_id, 'search', '3', 'Other invoice', 'other')
            self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
            proofs.generate(self.payment['id'], self.payment['approval_hash'])
            self.assertEqual(runner.call_count, 2)

    def test_missing_setup_and_unreviewed_payment_do_not_record_reference(self):
        proofs = PolicyProofs(self.settlement)
        with patch.object(proofs, 'available', return_value=False), self.assertRaises(PolicyError) as error:
            proofs.generate(self.payment['id'], self.payment['approval_hash'])
        self.assertEqual(error.exception.code, 'proof_setup_required')
        with patch.object(proofs, 'available', return_value=True), self.assertRaises(PolicyError) as error:
            proofs.generate(self.payment['id'], self.payment['approval_hash'])
        self.assertEqual(error.exception.code, 'proof_snapshot_missing')
