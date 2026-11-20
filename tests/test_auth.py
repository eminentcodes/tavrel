import json
from pathlib import Path
import shutil
import subprocess
import time
from http.client import HTTPConnection
from unittest import skipUnless

from tavrel.auth import WalletAuth
from tavrel.engine import PolicyError
from tests.support import EngineCase, GatewayCase


@skipUnless(shutil.which('node') and Path('node_modules/@polkadot/util-crypto').exists(), 'Wallet authentication requires npm install and Node')
class WalletAuthTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.auth = WalletAuth(self.engine)
        self.origin = 'http://127.0.0.1:8787'
        self.account = self.fixture()['account']

    def fixture(self, message=None, label='operator'):
        result = subprocess.run(['node', str(Path(__file__).with_name('wallet-fixture.mjs'))],
            input=json.dumps({'message': message, 'label': label}), capture_output=True, text=True, timeout=15, check=True)
        return json.loads(result.stdout)

    def begin(self, account=None):
        return self.auth.challenge(account or self.account, self.origin, self.auth.pairing_ticket)

    def login(self):
        challenge = self.begin()
        signed = self.fixture(challenge['message'])
        return self.auth.verify(challenge['challenge_id'], signed['signature'], self.origin)

    def test_initial_operator_requires_local_registration_authority(self):
        for ticket in (None, 'wrong'):
            with self.assertRaises(PolicyError) as error:
                self.auth.challenge(self.account, self.origin, ticket)
            self.assertEqual(error.exception.status, 403)
        self.assertFalse(self.auth.configured())

    def test_actual_native_signature_creates_persistent_revocable_session(self):
        result, cookie = self.login()
        self.assertTrue(result['authenticated'])
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        self.assertEqual(self.auth.session(cookie)['account'], self.account)
        restarted = WalletAuth(self.engine)
        self.assertEqual(restarted.session(cookie)['account'], self.account)
        restarted.logout(cookie)
        self.assertIsNone(self.auth.session(cookie))

    def test_signature_binds_account_message_origin_and_one_use_challenge(self):
        challenge = self.begin()
        other = self.fixture(challenge['message'], 'other')
        with self.assertRaises(PolicyError):
            self.auth.verify(challenge['challenge_id'], other['signature'], self.origin)
        signed = self.fixture(challenge['message'])
        with self.assertRaises(PolicyError):
            self.auth.verify(challenge['challenge_id'], signed['signature'], 'http://localhost:8787')
        self.auth.verify(challenge['challenge_id'], signed['signature'], self.origin)
        with self.assertRaises(PolicyError):
            self.auth.verify(challenge['challenge_id'], signed['signature'], self.origin)

    def test_expired_challenge_and_expired_session_fail(self):
        challenge = self.begin()
        signed = self.fixture(challenge['message'])
        with self.engine.transaction() as db:
            db.execute('UPDATE wallet_challenges SET expires=?', (time.time() - 1,))
        with self.assertRaises(PolicyError):
            self.auth.verify(challenge['challenge_id'], signed['signature'], self.origin)
        _, cookie = self.login()
        with self.engine.transaction() as db:
            db.execute('UPDATE operator_sessions SET expires=?', (time.time() - 1,))
        self.assertIsNone(self.auth.session(cookie))

    def test_setup_ticket_cannot_replace_an_existing_operator(self):
        other_account = self.fixture(label='other')['account']
        other = self.begin(other_account)
        self.login()
        signed = self.fixture(other['message'], 'other')
        with self.assertRaises(PolicyError):
            self.auth.verify(other['challenge_id'], signed['signature'], self.origin)
        with self.assertRaises(PolicyError):
            self.auth.challenge(other_account, self.origin, self.auth.pairing_ticket)
        # The original account can authenticate without the setup ticket.
        self.auth.challenge(self.account, self.origin)


@skipUnless(shutil.which('node') and Path('node_modules/@polkadot/util-crypto').exists(), 'Wallet authentication requires npm install and Node')
class WalletBrowserAuthTests(GatewayCase):
    fixture = WalletAuthTests.fixture

    def post(self, path, body, headers=None):
        connection = HTTPConnection('127.0.0.1', self.gateway.server_address[1], timeout=15)
        try:
            connection.request('POST', path, json.dumps(body), {
                'Content-Type': 'application/json', 'Origin': self.url,
                'Sec-Fetch-Site': 'same-origin', **(headers or {})})
            with connection.getresponse() as response:
                return response.status, dict(response.getheaders()), json.loads(response.read())
        finally:
            connection.close()

    def test_browser_registers_first_wallet_only_after_real_signature(self):
        account = self.fixture()['account']
        status, _, result = self.post('/v1/auth/challenge', {'address': account})
        self.assertEqual(status, 200)
        self.assertFalse(self.gateway.wallet_auth.configured())
        challenge = result['result']
        signed = self.fixture(challenge['message'])
        status, headers, result = self.post('/v1/auth/verify', {
            'challenge_id': challenge['challenge_id'], 'signature': signed['signature']})
        self.assertEqual(status, 200)
        self.assertTrue(result['result']['authenticated'])
        cookie = headers['Set-Cookie']
        self.assertEqual(self.gateway.wallet_auth.session(cookie)['account'], account)
        other = self.fixture(label='other')['account']
        status, _, result = self.post('/v1/auth/challenge', {'address': other})
        self.assertEqual(status, 403)
        self.assertEqual(result['error']['code'], 'operator_wallet_required')
        self.assertEqual(self.gateway.wallet_auth.session(cookie)['account'], account)
        self.assertEqual(self.post('/v1/auth/challenge', {'address': account})[0], 200)

    def test_bootstrap_rejects_missing_browser_provenance_and_task_credentials(self):
        account = '0x' + '12' * 32
        for headers in ({'Origin': ''}, {'Sec-Fetch-Site': ''},
                        {'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'https://attacker.example'},
                        {'Authorization': 'Bearer ' + self.task_token}):
            with self.subTest(headers=headers):
                self.assertEqual(self.post('/v1/auth/challenge', {'address': account}, headers)[0], 403)
        self.assertFalse(self.gateway.wallet_auth.configured())
        self.assertEqual(self.post('/v1/auth/challenge', {'address': account, 'browser_setup': True})[0], 400)
