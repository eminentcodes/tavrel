"""Controlled RPC responses test accounting/recovery, never real chain settlement."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor

from tavrel.engine import PolicyError
from tavrel.payments import PaymentLedger, units
from tavrel.settlement import Settlement, GENESIS
from tests.support import EngineCase, GatewayCase
from tests.test_payments import policy_arguments


SIGNATURE = '0x' + '11' * 65


class NetworkFixture:
    def __init__(self):
        self.calls = []
        self.outcome = {'submitted': True}
        self.scan = None
        self.inspect_error = False

    def __call__(self, action, **args):
        self.calls.append((action, copy.deepcopy(args)))
        if action == 'quote':
            return {'genesis_hash': GENESIS, 'finalized_height': 100, 'expires_height': 164,
                    'nonce': '1', 'enough_funds': True, 'fee_units': '100', 'payload': {'method': 'test-only'}}
        if action == 'inspect':
            if self.inspect_error:
                raise PolicyError('invalid_signature', 'Fixture signature mismatch')
            return {'tx_hash': '0x' + args['payment']['id'][4:].ljust(64, '0'),
                    'signed_hex': '0x' + 'aa' * 128, 'nonce': args['quote']['nonce']}
        if action == 'submit':
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome
        if action == 'scan':
            if self.scan:
                return {'payments': self.scan}
            return {'payments': [{**p, 'scan_height': 101, 'receipt': None} for p in args['payments']]}
        raise AssertionError(action)


class SettlementTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.payments = PaymentLedger(self.engine)
        self.task_id = self.create()['task']['id']
        self.payments.set_account('10')
        self.payments.configure(self.task_id, **policy_arguments())
        self.network = NetworkFixture()
        self.settlement = Settlement(self.payments, self.network)
        self.payment = self.payments.prepare(self.task_id, 'search', '2', 'Invoice', 'invoice')

    def send(self):
        self.quote = self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
        return self.settlement.submit(self.payment['id'], self.payment['approval_hash'], self.quote['quote_id'], SIGNATURE)

    def evidence(self, success=True):
        payment = self.payments.intent(self.payment['id'])
        tx = payment['transaction']
        return {'payment_id': payment['id'], 'tx_hash': tx['tx_hash'], 'scan_height': 112,
            'receipt': {'genesis_hash': GENESIS, 'finality_verified': True, 'success': success,
                'sender': payment['sender'], 'recipient': payment['recipient'], 'amount_units': payment['amount_units'],
                'tx_hash': tx['tx_hash'], 'block_hash': '0x' + 'cc' * 32, 'block_number': 111,
                'extrinsic_index': 2, 'fee_units': '100', 'error': None if success else 'InsufficientBalance'}}

    def accounting(self, spent='0', held='2'):
        status = self.payments.status()
        for row in (status['account'], status['policies'][0]):
            self.assertEqual(row['spent_units'], str(units(spent)))
            self.assertEqual(row['reserved_units'], str(units(held)))
            self.assertEqual(int(row['available_units']), units('10') - units(spent) - units(held))

    def test_signed_bytes_persist_before_any_submission_and_are_never_returned(self):
        saved = self.send()
        self.assertEqual(saved['status'], 'submitting')
        self.assertNotIn('signed_hex', saved['transaction'])
        self.assertNotIn('submit', [action for action, _ in self.network.calls])
        with self.engine.connection() as db:
            self.assertEqual(db.execute('SELECT signed_hex FROM payment_transactions').fetchone()[0], '0x' + 'aa' * 128)
        self.accounting()

    def test_concurrent_retry_saves_one_transaction_and_one_hold(self):
        self.send()
        with ThreadPoolExecutor(max_workers=8) as pool:
            result = list(pool.map(lambda _: self.settlement.submit(self.payment['id'], self.payment['approval_hash'], self.quote['quote_id'], SIGNATURE), range(12)))
        self.assertEqual({p['status'] for p in result}, {'submitting'})
        self.assertEqual(sum(action == 'inspect' for action, _ in self.network.calls), 1)
        self.accounting()

    def test_restart_retries_identical_saved_transaction_after_scan(self):
        self.send()
        restarted = Settlement(PaymentLedger(self.engine), self.network)
        restarted.reconcile()
        self.assertEqual(self.payments.intent(self.payment['id'])['status'], 'submitted')
        self.assertEqual(self.network.calls[-2][0], 'scan')
        self.assertEqual(self.network.calls[-1][1]['signed_hex'], '0x' + 'aa' * 128)
        self.accounting()

    def test_timeout_and_pool_rejection_preserve_holds(self):
        self.send()
        for outcome in (PolicyError('network_unavailable', 'timeout', 503), {'submitted': False, 'error': 'Pool response ambiguous'}):
            self.network.outcome = outcome
            self.settlement.reconcile()
            self.assertEqual(self.payments.intent(self.payment['id'])['status'], 'submitting')
            self.accounting()

    def test_finalized_success_moves_principal_to_spent_once(self):
        self.send()
        evidence = self.evidence()
        self.settlement.record_verified(evidence)
        self.settlement.record_verified(evidence)
        self.accounting('2', '0')
        payment = self.payments.intent(self.payment['id'])
        self.assertTrue(payment['settlement_verified'])
        self.assertEqual(payment['transaction']['receipt']['fee_units'], '100')
        self.assertEqual(self.payments.prepare(self.task_id, 'search', '2', 'Invoice', 'invoice')['id'], payment['id'])

    def test_failed_included_transaction_releases_principal_without_spend(self):
        self.send()
        self.settlement.record_verified(self.evidence(False))
        self.accounting('0', '0')
        self.assertEqual(self.payments.intent(self.payment['id'])['status'], 'failed')

    def test_forged_or_unfinalized_receipts_do_not_release(self):
        self.send()
        evidence = self.evidence()
        for key, value in (('genesis_hash', 'wrong'), ('finality_verified', False), ('recipient', 'wrong'), ('sender', 'wrong'), ('amount_units', '1'), ('success', 'true'), ('tx_hash', 'wrong')):
            tampered = copy.deepcopy(evidence)
            tampered['receipt'][key] = value
            with self.subTest(key=key), self.assertRaises(PolicyError):
                self.settlement.record_verified(tampered)
            self.accounting()

    def test_expiry_requires_finalized_scan_of_entire_signed_lifetime(self):
        self.send()
        checked = {'payment_id': self.payment['id'], 'tx_hash': self.evidence()['tx_hash'],
            'scan_height': 164, 'receipt': None, 'expired': True, 'finalized_height': 164, 'genesis_hash': GENESIS}
        with self.assertRaises(PolicyError):
            self.settlement.record_verified(checked)
        self.accounting()
        checked['scan_height'] = 165
        self.settlement.record_verified(checked)
        self.settlement.record_verified(checked)
        self.accounting('0', '0')
        self.assertEqual(self.payments.intent(self.payment['id'])['status'], 'expired')

    def test_stale_policy_and_paused_agent_cannot_quote_or_submit(self):
        quote = self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
        self.payments.configure(self.task_id, **policy_arguments(recipients={}))
        with self.assertRaises(PolicyError):
            self.settlement.submit(self.payment['id'], self.payment['approval_hash'], quote['quote_id'], SIGNATURE)
        self.accounting('0', '0')
        self.assertEqual(self.payments.intent(self.payment['id'])['status'], 'blocked')

    def test_quote_is_bound_to_request_hash_and_expiration(self):
        quote = self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
        with self.engine.transaction() as db:
            db.execute('UPDATE payment_quotes SET expires=0')
        with self.assertRaises(PolicyError):
            self.settlement.submit(self.payment['id'], self.payment['approval_hash'], quote['quote_id'], SIGNATURE)
        self.accounting()

    def test_invalid_signature_never_creates_transaction(self):
        self.network.inspect_error = True
        with self.assertRaises(PolicyError):
            self.send()
        self.assertIsNone(self.payments.intent(self.payment['id'])['transaction'])
        self.accounting()

    def test_snapshot_includes_own_hold_and_deducts_other_payments(self):
        self.payments.prepare(self.task_id, 'search', '3', 'Other invoice', 'other')
        self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
        with self.engine.connection() as db:
            snapshot = json.loads(db.execute('SELECT snapshot FROM payment_policy_snapshots WHERE payment_id=?', (self.payment['id'],)).fetchone()[0])
        self.assertEqual(snapshot['task_available_units'], str(units('7')))
        self.assertEqual(snapshot['account_available_units'], str(units('7')))
        self.assertIn(self.payment['recipient'], snapshot['recipients'])

    def test_new_snapshot_invalidates_proof_and_submission_restores_signed_quote(self):
        quote = self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
        with self.engine.transaction() as db:
            db.execute('INSERT INTO payment_proofs VALUES(?,?,?)', (self.payment['id'], self.payment['approval_hash'], '{}'))
        self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
        with self.engine.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM payment_proofs').fetchone()[0], 1)
        self.payments.prepare(self.task_id, 'search', '3', 'Other invoice', 'other')
        self.settlement.quote(self.payment['id'], self.payment['approval_hash'])
        with self.engine.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM payment_proofs').fetchone()[0], 0)
            db.execute('INSERT INTO payment_proofs VALUES(?,?,?)', (self.payment['id'], self.payment['approval_hash'], '{}'))
        self.settlement.submit(self.payment['id'], self.payment['approval_hash'], quote['quote_id'], SIGNATURE)
        with self.engine.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM payment_proofs').fetchone()[0], 0)
            snapshot = json.loads(db.execute('SELECT snapshot FROM payment_policy_snapshots').fetchone()[0])
            self.assertEqual(snapshot['task_available_units'], str(units('10')))

    def test_spent_principal_cannot_be_reused_or_removed_by_policy_update(self):
        self.send()
        self.settlement.record_verified(self.evidence())
        for change in (lambda: self.payments.set_account('1'), lambda: self.payments.configure(self.task_id, **policy_arguments(budget='1'))):
            with self.assertRaises(PolicyError):
                change()
        self.payments.configure(self.task_id, **policy_arguments(per_payment='10'))
        blocked = self.payments.prepare(self.task_id, 'search', '9', 'Second invoice', 'second')
        self.assertEqual(blocked['reason'], 'TASK_PAYMENT_BUDGET')
        self.accounting('2', '0')


class SettlementAPITests(GatewayCase):
    def test_task_token_cannot_quote_sign_or_submit_its_own_payment(self):
        self.gateway.settlement.network = NetworkFixture()
        self.gateway.payments.set_account('10')
        self.gateway.payments.configure(self.task_id, **policy_arguments())
        payment = self.gateway.payments.prepare(self.task_id, 'search', '2', 'Invoice', 'invoice')
        from hermes_plugin import GatewayError
        for action, body in (('quote', {'expected_hash': payment['approval_hash']}),
            ('submit', {'expected_hash': payment['approval_hash'], 'quote_id': 'invalid', 'signature': SIGNATURE})):
            with self.assertRaises(GatewayError):
                self.agent.request('POST', f"/v1/operator/payments/{payment['id']}/{action}", body)
        quote = self.operator.request('POST', f"/v1/operator/payments/{payment['id']}/quote", {'expected_hash': payment['approval_hash']})
        sent = self.operator.request('POST', f"/v1/operator/payments/{payment['id']}/submit", {'expected_hash': payment['approval_hash'], 'quote_id': quote['quote_id'], 'signature': SIGNATURE})
        self.assertEqual(sent['status'], 'submitting')
