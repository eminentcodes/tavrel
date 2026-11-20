"""Standalone invoice runner against real HTTP routes with isolated account data."""
import json
from pathlib import Path
import subprocess
import sys

from tavrel.agent import run_task
from tavrel.client import GatewayError, TavrelClient
from tests.support import GatewayCase
from tests.test_payments import policy_arguments


class InvoiceAgentTests(GatewayCase):
    def setUp(self):
        super().setUp()
        self.gateway.payments.set_account('10')
        self.gateway.payments.configure(self.task_id, **policy_arguments())
        self.connection = {'task_id': self.task_id, 'gateway_url': self.url, 'task_token': self.task_token}
        self.invoices = [{'recipient': 'search', 'amount': '2', 'purpose': 'Invoice one'},
                         {'recipient': 'search', 'amount': '4', 'purpose': 'Invoice two'}]

    def test_runner_routes_invoices_and_retries_existing_ids_without_operator_access(self):
        client, result = run_task(self.connection, self.invoices, 'invoices')
        self.assertIsInstance(client, TavrelClient)
        self.assertEqual([p['status'] for p in result['intents']], ['ready_for_signature', 'pending_approval'])
        self.assertEqual(run_task(self.connection, self.invoices, 'invoices')[1], result)
        payment = result['intents'][0]
        self.assertEqual(client.request('GET', '/v1/agent/payments/' + payment['id'])['id'], payment['id'])
        with self.assertRaises(GatewayError) as error:
            client.request('POST', '/v1/operator/payments/' + payment['id'] + '/quote', {'expected_hash': payment['approval_hash']})
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.gateway.payments.status()['account']['reserved_units'], '6000000000000000000')

    def test_documented_cli_uses_downloaded_connection_and_reports_real_decisions(self):
        connection_file = self.directory / 'task-connection.json'
        connection_file.write_text(json.dumps(self.connection), encoding='utf-8')
        invoices_file = self.directory / 'invoices.json'
        invoices_file.write_text(json.dumps(self.invoices), encoding='utf-8')
        result = subprocess.run([sys.executable, '-m', 'tavrel.agent', self.task_id,
            '--connection', str(connection_file), '--file', str(invoices_file), '--key', 'cli-invoices'],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ready_for_signature', result.stdout)
        self.assertIn('pending_approval', result.stdout)
        self.assertIn(self.url + '/payments/pay_', result.stdout)
        self.assertNotIn(self.task_token, result.stdout + result.stderr)
