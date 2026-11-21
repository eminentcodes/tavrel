"""Two real wallet signatures against isolated hosted payment accounts; no transfers."""
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import subprocess
from threading import Thread
import unittest
from unittest.mock import patch

from tavrel.engine import Engine
from tavrel.payments import PaymentLedger
from tavrel.runtime import operator_key
from tavrel.server import Gateway
from tests.support import EngineCase


class PublicAccountMigrationTests(EngineCase):
    def gateway(self, owner=None):
        gateway = Gateway(('127.0.0.1', 0), self.engine, 'migration-test-key', quiet=True,
            public_origin='https://tavrel.example', owner_wallet=owner, multi_user=True)
        self.addCleanup(gateway.server_close)
        return gateway

    def test_empty_legacy_registry_with_multiple_wallets_recovers_separate_accounts(self):
        self.gateway().server_close()
        wallets = ['0x' + '12' * 32, '0x' + '34' * 32]
        with self.engine.transaction() as db:
            db.executemany('INSERT INTO operator_wallets VALUES(?,0)', [(wallet,) for wallet in wallets])
        gateway = self.gateway()
        accounts = [gateway.accounts.for_wallet(wallet) for wallet in wallets]
        self.assertNotEqual(accounts[0].engine.database, accounts[1].engine.database)
        self.assertTrue(all(account.engine.database != self.engine.database for account in accounts))
        self.assertTrue(all(account.engine.snapshot()['tasks'] == [] for account in accounts))

    def test_unowned_legacy_payments_require_assignment_without_erasing_data(self):
        created = self.engine.create_task('Existing agent', 0, 0, [])
        PaymentLedger(self.engine).set_account('1')
        with self.assertRaisesRegex(ValueError, 'existing unowned ledger'):
            self.gateway()
        wallet = '0x' + '12' * 32
        gateway = self.gateway(wallet)
        account = gateway.accounts.for_wallet(wallet)
        self.assertEqual(account.engine.database, self.engine.database)
        self.assertEqual(account.engine.snapshot()['tasks'][0]['id'], created['task']['id'])
        self.assertEqual(account.payments.status()['account']['limit_units'], str(10**18))


@unittest.skipUnless(shutil.which('node') and Path('node_modules/@polkadot/util-crypto').exists(), 'Requires Node and npm install')
class PublicAccountsTests(EngineCase):
    @staticmethod
    def fixture(label, message=None):
        result = subprocess.run(['node', 'tests/wallet-fixture.mjs'],
            input=json.dumps({'label': 'public-' + label, 'message': message}), text=True,
            capture_output=True, check=True, timeout=30)
        return json.loads(result.stdout)

    def setUp(self):
        super().setUp()
        self.origin = 'https://tavrel.example'
        self.key = operator_key(self.directory, create=True)
        self.cookies = {}
        self.wallets = {}
        self.start_gateway()
        self.addCleanup(self.stop_gateway)

    def start_gateway(self):
        self.gateway = Gateway(('127.0.0.1', 0), self.engine, self.key, quiet=True,
            public_origin=self.origin, multi_user=True)
        self.thread = Thread(target=self.gateway.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()

    def stop_gateway(self):
        self.gateway.shutdown()
        self.gateway.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None, wallet=None, token=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.gateway.server_address[1], timeout=30)
        try:
            outgoing = {'Host': 'tavrel.example', 'Origin': self.origin,
                'Sec-Fetch-Site': 'same-origin', 'Content-Type': 'application/json'}
            if wallet:
                outgoing['Cookie'] = self.cookies[wallet]
            if token:
                outgoing['Authorization'] = 'Bearer ' + token
            outgoing.update(headers or {})
            connection.request(method, path, json.dumps(body) if body is not None else None, outgoing)
            with connection.getresponse() as response:
                data = response.read()
                return response.status, dict(response.getheaders()), json.loads(data) if data.startswith(b'{') else data
        finally:
            connection.close()

    def login(self, label):
        wallet = self.fixture(label)['account']
        status, _, data = self.request('POST', '/v1/auth/challenge', {'address': wallet})
        self.assertEqual(status, 200)
        challenge = data['result']
        signed = self.fixture(label, challenge['message'])
        status, headers, data = self.request('POST', '/v1/auth/verify',
            {'challenge_id': challenge['challenge_id'], 'signature': signed['signature']})
        self.assertEqual(status, 200, data)
        self.assertIn('; Secure', headers['Set-Cookie'])
        self.cookies[label] = headers['Set-Cookie']
        self.wallets[label] = wallet
        return wallet

    def create_agent(self, label):
        status, _, data = self.request('POST', '/v1/operator/tasks',
            {'name': label + ' agent', 'limit_cents': 0, 'threshold_cents': 0, 'allowed_services': []}, wallet=label)
        self.assertEqual(status, 200)
        return data['result']

    def test_two_wallets_have_separate_agents_allowances_intents_and_approval_permissions(self):
        self.login('alice')
        self.login('bob')
        alice = self.create_agent('alice')
        bob = self.create_agent('bob')
        task = alice['task']['id']
        self.assertEqual(self.request('PATCH', '/v1/operator/payments/account', {'budget': '1'}, wallet='alice')[0], 200)
        policy = {'sender': self.wallets['alice'], 'budget': '1', 'approval': '0', 'per_payment': '1',
            'recipients': {'vendor': self.wallets['bob']}}
        status, _, result = self.request('PATCH', '/v1/operator/payments/policies/' + task, policy, wallet='alice')
        self.assertEqual(status, 200, result)
        status, _, result = self.request('POST', '/v1/operator/payments/prepare',
            {'task_id': task, 'recipient': 'vendor', 'amount': '0.01', 'purpose': 'Invoice', 'request_key': 'INV-1'}, wallet='alice')
        self.assertEqual(status, 200, result)
        payment = result['result']
        status, _, result = self.request('GET', '/v1/operator/status', wallet='bob')
        self.assertEqual([row['id'] for row in result['result']['tasks']], [bob['task']['id']])
        _, _, result = self.request('GET', '/v1/operator/payments/status', wallet='bob')
        self.assertEqual(result['result']['account']['limit_units'], '0')
        self.assertEqual(result['result']['intents'], [])
        # Equal invoice references in different wallet accounts must not share a request or allowance.
        bob_task = bob['task']['id']
        self.assertEqual(self.request('PATCH', '/v1/operator/payments/account', {'budget': '1'}, wallet='bob')[0], 200)
        self.assertEqual(self.request('PATCH', '/v1/operator/payments/policies/' + bob_task,
            {**policy, 'sender': self.wallets['bob'], 'recipients': {'vendor': self.wallets['alice']}}, wallet='bob')[0], 200)
        _, _, second = self.request('POST', '/v1/operator/payments/prepare',
            {'task_id': bob_task, 'recipient': 'vendor', 'amount': '0.01', 'purpose': 'Invoice', 'request_key': 'INV-1'}, wallet='bob')
        self.assertNotEqual(second['result']['id'], payment['id'])
        self.assertEqual(self.request('GET', '/v1/agent/payments/' + payment['id'], token=bob['task_token'])[0], 404)
        for label in ('alice', 'bob'):
            _, _, account = self.request('GET', '/v1/operator/payments/status', wallet=label)
            self.assertEqual(account['result']['account']['reserved_units'], str(10**16))
        for method, path, body in (
            ('GET', '/v1/operator/tasks/' + task, None),
            ('PATCH', '/v1/operator/payments/policies/' + task, policy),
            ('GET', '/v1/operator/payments/' + payment['id'], None),
            ('POST', '/v1/operator/payments/' + payment['id'] + '/decision', {'decision': 'approve', 'expected_hash': payment['approval_hash']}),
            ('POST', '/v1/operator/payments/' + payment['id'] + '/quote', {'expected_hash': payment['approval_hash']}),
            ('POST', '/v1/operator/tasks/' + task + '/token', {}),
            ('GET', '/v1/operator/tasks/' + task + '/wallet', None)):
            self.assertEqual(self.request(method, path, body, wallet='bob')[0], 404, path)
        _, _, own = self.request('GET', '/v1/operator/payments/' + payment['id'], wallet='alice')
        self.assertEqual(own['result']['status'], 'pending_approval')
        self.assertNotEqual(self.gateway.accounts.for_wallet(self.wallets['alice']).engine.database,
            self.gateway.accounts.for_wallet(self.wallets['bob']).engine.database)

    def test_agent_tokens_are_owner_scoped_and_rotation_revokes_the_old_token(self):
        self.login('alice')
        self.login('bob')
        alice, bob = self.create_agent('alice'), self.create_agent('bob')
        status, _, data = self.request('GET', '/v1/agent/status', token=alice['task_token'])
        self.assertEqual(status, 200)
        self.assertEqual(data['result']['task']['id'], alice['task']['id'])
        self.assertEqual(self.request('GET', '/v1/agent/payments/' + 'pay_' + '12'*8, token=bob['task_token'])[0], 404)
        self.assertEqual(self.request('GET', '/v1/operator/status', wallet='bob', token=alice['task_token'])[0], 401)
        self.assertEqual(self.request('GET', '/v1/operator/status', token=self.key)[0], 401)
        _, _, rotated = self.request('POST', '/v1/operator/tasks/' + alice['task']['id'] + '/token', {}, wallet='alice')
        self.assertEqual(self.request('GET', '/v1/agent/status', token=alice['task_token'])[0], 401)
        self.assertEqual(self.request('GET', '/v1/agent/status', token=rotated['result']['task_token'])[0], 200)

    def test_sessions_and_task_routing_survive_restart_without_sharing_ledgers(self):
        self.login('alice')
        self.login('bob')
        alice, bob = self.create_agent('alice'), self.create_agent('bob')
        self.stop_gateway()
        self.engine = Engine(self.directory / 'ledger.sqlite3', self.engine.services)
        self.start_gateway()
        for label, created in (('alice', alice), ('bob', bob)):
            _, _, data = self.request('GET', '/v1/operator/status', wallet=label)
            self.assertEqual([row['id'] for row in data['result']['tasks']], [created['task']['id']])
            self.assertEqual(self.request('GET', '/v1/agent/status', token=created['task_token'])[0], 200)
        self.assertEqual(self.request('POST', '/v1/auth/logout', {}, wallet='alice')[0], 200)
        self.assertEqual(self.request('GET', '/v1/operator/status', wallet='alice')[0], 401)
        self.assertEqual(self.request('GET', '/v1/operator/status', wallet='bob')[0], 200)

    def test_first_signup_cannot_use_a_forged_signature_or_missing_browser_provenance(self):
        wallet = self.fixture('alice')['account']
        self.assertEqual(self.request('POST', '/v1/auth/challenge', {'address': wallet}, headers={'Sec-Fetch-Site': ''})[0], 403)
        _, _, data = self.request('POST', '/v1/auth/challenge', {'address': wallet})
        challenge = data['result']
        signed = self.fixture('bob', challenge['message'])
        self.assertEqual(self.request('POST', '/v1/auth/verify', {'challenge_id': challenge['challenge_id'], 'signature': signed['signature']})[0], 401)
        with self.engine.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM public_accounts').fetchone()[0], 0)
        self.assertEqual(self.request('GET', '/v1/operator/status')[0], 401)
        self.assertEqual(self.request('GET', '/dashboard')[0], 200)

    def test_legacy_owner_keeps_existing_data_while_new_wallet_gets_empty_account(self):
        self.stop_gateway()
        wallet = self.fixture('alice')['account']
        with self.engine.transaction() as db:
            db.execute('INSERT INTO operator_wallets VALUES(?,0)', (wallet,))
        created = self.engine.create_task('Existing agent', 0, 0, [])
        PaymentLedger(self.engine).set_account('1')
        self.start_gateway()
        self.login('alice')
        self.login('bob')
        _, _, data = self.request('GET', '/v1/operator/status', wallet='alice')
        self.assertEqual([row['id'] for row in data['result']['tasks']], [created['task']['id']])
        _, _, data = self.request('GET', '/v1/operator/payments/status', wallet='alice')
        self.assertEqual(data['result']['account']['limit_units'], str(10**18))
        _, _, data = self.request('GET', '/v1/operator/status', wallet='bob')
        self.assertEqual(data['result']['tasks'], [])
        self.assertEqual(self.request('GET', '/v1/agent/status', token=created['task_token'])[0], 200)

    def test_signup_account_mapping_failure_rolls_back_and_same_signature_can_retry(self):
        wallet = self.fixture('alice')['account']
        _, _, data = self.request('POST', '/v1/auth/challenge', {'address': wallet})
        challenge = data['result']
        signed = self.fixture('alice', challenge['message'])
        body = {'challenge_id': challenge['challenge_id'], 'signature': signed['signature']}
        with patch.object(self.gateway.wallet_auth, 'account_registered', side_effect=RuntimeError('Interrupted account setup')):
            self.assertEqual(self.request('POST', '/v1/auth/verify', body)[0], 500)
        with self.engine.connection() as db:
            for table in ('operator_wallets', 'operator_sessions', 'public_accounts'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
        self.assertEqual(self.request('POST', '/v1/auth/verify', body)[0], 200)
