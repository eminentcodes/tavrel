"""Deterministic invoice batches, durable retries, cancellation, and task scope."""
import json
from unittest.mock import patch

from tavrel.agent_runs import AgentRuns, EXECUTOR
from tavrel.engine import PolicyError, now
from tavrel.payments import PaymentLedger, units
from tests.support import EngineCase, GatewayCase
from tests.test_payments import policy_arguments


def invoice(**changes):
    return {'invoice_reference': 'INV-1', 'recipient': 'search', 'amount': '2', 'purpose': 'Invoice one', **changes}


class RunTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.task_id = self.create()['task']['id']
        self.payments = PaymentLedger(self.engine)
        self.payments.set_account('10')
        self.payments.configure(self.task_id, **policy_arguments())
        self.runs = AgentRuns(self.payments)

    def create_run(self, invoices=None, key='invoices'):
        return self.runs.create(self.task_id, 'Service invoices', key, invoices or [invoice()])

    def execute(self, invoices=None, key='invoices'):
        run = self.create_run(invoices, key)
        self.runs.advance(run['id'])
        return self.runs.get(run['id'])

    def test_actual_ledger_ready_approval_and_blocked_outcomes(self):
        result = self.execute([invoice(), invoice(invoice_reference='INV-2', amount='4'),
            invoice(invoice_reference='INV-3', recipient=policy_arguments()['sender'])])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([p['status'] for p in result['payments']], ['ready_for_signature', 'pending_approval', 'blocked'])
        self.assertEqual(self.payments.status()['account']['reserved_units'], str(units('6')))
        self.assertTrue(all(not p['broadcast'] for p in result['payments']))
        self.assertEqual([a['name'] for a in result['actions']], ['read_rules','read_source','prepare_payment','prepare_payment','prepare_payment','finish'])
        self.assertEqual(result['executor'], EXECUTOR)
        self.assertNotIn('model', result)

    def test_invalid_later_invoice_rejected_before_any_request(self):
        with self.assertRaises(PolicyError):
            self.create_run([invoice(), invoice(invoice_reference='INV-2', amount='missing')])
        self.assertEqual(self.payments.status()['intents'], [])
        self.assertEqual(self.runs.list(self.task_id)['runs'], [])

    def test_arbitrary_fields_and_missing_amount_are_rejected(self):
        for changes in ({'task_id': 'other'}, {'approve': True}, {'amount': 2}, {'recipient': 'Unknown name'}):
            with self.subTest(changes=changes), self.assertRaises(PolicyError):
                self.create_run([invoice(**changes)])
        item = invoice()
        item.pop('amount')
        with self.assertRaises(PolicyError):
            self.create_run([item])
        self.assertEqual(self.payments.status()['intents'], [])

    def test_batch_is_bounded_and_references_are_unique(self):
        for invoices in ([invoice()] * 2, [invoice(invoice_reference=str(i)) for i in range(21)]):
            with self.assertRaises(PolicyError):
                self.create_run(invoices)
        with self.assertRaises(PolicyError):
            self.runs.create(self.task_id, 'Empty task', 'empty', [])

    def test_same_task_key_returns_same_run_and_rejects_changed_data(self):
        original = self.execute()
        self.assertEqual(self.create_run()['id'], original['id'])
        with self.assertRaises(PolicyError) as failure:
            self.create_run([invoice(amount='3')])
        self.assertEqual(failure.exception.code, 'idempotency_conflict')
        self.assertEqual(self.payments.status()['account']['reserved_units'], str(units('2')))

    def test_same_invoice_across_batches_reuses_the_payment(self):
        first = self.execute()
        second = self.execute(key='later-batch')
        self.assertEqual(first['payments'][0]['id'], second['payments'][0]['id'])
        self.assertEqual(self.payments.status()['account']['reserved_units'], str(units('2')))
        changed = self.execute([invoice(amount='3')], key='conflict')
        self.assertEqual(changed['status'], 'failed')
        self.assertEqual(changed['actions'][2]['result']['error'], 'idempotency_conflict')
        self.assertEqual(len(self.payments.status()['intents']), 1)

    def test_different_invoice_references_can_have_identical_amount_and_purpose(self):
        result = self.execute([invoice(), invoice(invoice_reference='INV-2')])
        self.assertEqual(len(result['payments']), 2)
        self.assertEqual(self.payments.status()['account']['reserved_units'], str(units('4')))

    def test_crash_after_payment_commit_replays_without_second_hold(self):
        run = self.create_run()
        actual = self.payments.prepare
        def commit_then_interrupt(*args, **kwargs):
            actual(*args, **kwargs)
            raise RuntimeError('Interrupted after committing the payment')
        with patch.object(self.payments, 'prepare', side_effect=commit_then_interrupt):
            self.runs.advance(run['id'])
        self.assertEqual(self.runs.get(run['id'])['status'], 'failed')
        self.assertEqual(self.payments.status()['account']['reserved_units'], str(units('2')))
        self.runs.resume(run['id'])
        self.runs.advance(run['id'])
        result = self.runs.get(run['id'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['payments']), 1)
        self.assertEqual(self.payments.status()['account']['reserved_units'], str(units('2')))

    def test_cancel_after_first_invoice_stops_next_and_preserves_hold(self):
        run = self.create_run([invoice(), invoice(invoice_reference='INV-2')])
        actual = self.runs._action
        def process_then_cancel(row, action):
            actual(row, action)
            if action['name'] == 'prepare_payment':
                self.runs.cancel(row['id'])
        with patch.object(self.runs, '_action', side_effect=process_then_cancel):
            self.runs.advance(run['id'])
        result = self.runs.get(run['id'])
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(len(result['payments']), 1)
        self.assertEqual(self.payments.status()['account']['reserved_units'], str(units('2')))
        with self.assertRaises(PolicyError):
            self.runs.resume(run['id'])

    def test_cancel_before_execution_makes_no_request(self):
        run = self.create_run()
        self.runs.cancel(run['id'])
        self.runs.advance(run['id'])
        self.assertEqual(self.payments.status()['intents'], [])

    def test_restart_requires_explicit_resume_with_saved_actions(self):
        run = self.create_run()
        replacement = AgentRuns(self.payments)
        replacement.advance(run['id'])
        self.assertEqual(replacement.get(run['id'])['status'], 'interrupted')
        replacement.resume(run['id'])
        replacement.advance(run['id'])
        self.assertEqual(replacement.get(run['id'])['status'], 'completed')

    def test_recipient_alias_changes_cannot_retarget_a_saved_invoice(self):
        run = self.create_run()
        original = run['invoices'][0]['recipient']
        arguments = policy_arguments()
        arguments['recipients'] = {'search': arguments['sender']}
        self.payments.configure(self.task_id, **arguments)
        self.runs.advance(run['id'])
        payment = self.runs.get(run['id'])['payments'][0]
        self.assertEqual(payment['recipient'], original)
        self.assertEqual(payment['reason'], 'RECIPIENT_NOT_ALLOWED')
        self.assertEqual(self.create_run()['id'], run['id'])

    def test_zero_shared_allowance_is_a_real_block_without_hold(self):
        self.payments.set_account('0')
        result = self.execute()
        self.assertEqual(result['payments'][0]['reason'], 'WORKSPACE_PAYMENT_BUDGET')
        self.assertEqual(self.payments.status()['account']['reserved_units'], '0')

    def test_other_task_cannot_read_resume_or_cancel_a_run(self):
        run = self.create_run()
        other = self.create()['task']['id']
        for operation in (self.runs.get, self.runs.resume, self.runs.cancel):
            with self.assertRaises(PolicyError) as failure:
                operation(run['id'], other)
            self.assertEqual(failure.exception.status, 404)

    def test_old_model_history_cannot_run_or_resume(self):
        run = self.create_run()
        with self.engine.transaction() as db:
            db.execute("UPDATE agent_runs SET executor='legacy_model',source='old invoice text',status='failed' WHERE id=?", (run['id'],))
        self.runs.advance(run['id'])
        self.assertEqual(self.runs.get(run['id'])['invoices'], [])
        with self.assertRaises(PolicyError) as failure:
            self.runs.resume(run['id'])
        self.assertEqual(failure.exception.code, 'legacy_agent_task')
        self.assertEqual(self.payments.status()['intents'], [])

    def test_queue_is_bounded(self):
        for index in range(8):
            self.create_run(key=f'queued-{index}')
        with self.assertRaises(PolicyError) as failure:
            self.create_run(key='queue-overflow')
        self.assertEqual(failure.exception.code, 'agent_queue_full')


class RunGatewayTests(GatewayCase):
    def test_task_scoped_batch_runs_without_model_configuration(self):
        self.gateway.payments.set_account('10')
        self.gateway.payments.configure(self.task_id, **policy_arguments())
        result = self.agent.request('POST', '/v1/agent/runs', {'goal': 'Service invoices', 'request_key': 'gateway', 'invoices': [invoice()]})
        read = self.agent.request('GET', '/v1/agent/runs/' + result['id'])
        self.assertEqual(read['executor'], EXECUTOR)
        other = self.create()
        from tavrel.client import TavrelClient
        client = TavrelClient(self.url, other['task_token'])
        with self.assertRaises(Exception) as hidden:
            client.request('GET', '/v1/agent/runs/' + result['id'])
        self.assertEqual(hidden.exception.status, 404)
        with self.assertRaises(Exception) as forbidden:
            self.agent.request('POST', '/v1/agent/runs', {'goal': 'Forbidden', 'request_key': 'no-approval', 'invoices': [invoice()], 'approve': True})
        self.assertEqual(forbidden.exception.status, 400)
