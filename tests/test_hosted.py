from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import subprocess
from threading import Thread
import unittest

from tavrel.hosted import public_origin, settings
from tavrel.payments import wallet_address
from tavrel.runtime import operator_key
from tavrel.server import Gateway
from tests.support import EngineCase


class HostedSettingsTests(unittest.TestCase):
    def test_https_origin_and_railway_port_are_explicit(self):
        owner = '0x' + '12' * 32
        config = settings({'RAILWAY_PUBLIC_DOMAIN': 'tavrel.up.railway.app',
            'TAVREL_OWNER_WALLET': wallet_address(owner), 'PORT': '3000'})
        self.assertEqual(config['origin'], 'https://tavrel.up.railway.app')
        self.assertEqual(config['owner'], owner)
        self.assertEqual(config['port'], 3000)
        self.assertEqual(public_origin('https://TAVREL.example:443/'), 'https://tavrel.example')
        for origin in ('http://tavrel.example', 'https://user:pass@tavrel.example',
                       'https://tavrel.example/path', 'https://tavrel.example?x=1',
                       'https://tavrel.example#fragment', 'https://tavrel.example:8787'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                public_origin(origin)
        for changes in ({'RAILWAY_PUBLIC_DOMAIN': ''}, {'TAVREL_OWNER_WALLET': ''}, {'PORT': '0'}, {'PORT': 'bad'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                settings({'RAILWAY_PUBLIC_DOMAIN': 'tavrel.example', 'TAVREL_OWNER_WALLET': owner, **changes})


@unittest.skipUnless(shutil.which('node') and Path('node_modules/@polkadot/util-crypto').exists(), 'Requires Node and npm install')
class HostedGatewayTests(EngineCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = cls.fixture()['account']

    @staticmethod
    def fixture(message=None):
        result = subprocess.run(['node', 'tests/wallet-fixture.mjs'],
            input=json.dumps({'message': message, 'label': 'hosted-owner'}),
            capture_output=True, text=True, check=True, timeout=15)
        return json.loads(result.stdout)

    def setUp(self):
        super().setUp()
        self.origin = 'https://tavrel.example'
        self.key = operator_key(self.directory, create=True)
        self.gateway = Gateway(('127.0.0.1', 0), self.engine, self.key, quiet=True,
            public_origin=self.origin, owner_wallet=self.owner)
        self.thread = Thread(target=self.gateway.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.gateway.shutdown()
        self.gateway.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.gateway.server_address[1], timeout=20)
        try:
            connection.request(method, path, json.dumps(body) if body is not None else None,
                {'Host': 'tavrel.example', 'Origin': self.origin, 'Content-Type': 'application/json',
                 'Sec-Fetch-Site': 'same-origin', **(headers or {})})
            with connection.getresponse() as response:
                return response.status, dict(response.getheaders()), json.loads(response.read())
        finally:
            connection.close()

    def test_pinned_host_origin_and_limited_healthcheck_exception(self):
        self.assertEqual(self.request('GET', '/health')[0], 200)
        for headers in ({'Host': 'attacker.example', 'X-Forwarded-Host': 'tavrel.example'},
                        {'Origin': 'https://attacker.example'}, {'Origin': 'null'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('GET', '/v1/auth/status', headers=headers)[0], 403)
        probe = {'Host': 'healthcheck.railway.app', 'Origin': ''}
        self.assertEqual(self.request('GET', '/health', headers=probe)[0], 200)
        self.assertEqual(self.request('GET', '/v1/auth/status', headers=probe)[0], 403)

    def test_only_configured_owner_can_get_a_login_challenge(self):
        self.assertTrue(self.gateway.wallet_auth.configured())
        self.assertEqual(self.request('POST', '/v1/auth/challenge', {'address': '0x' + '34' * 32})[0], 403)
        status, _, result = self.request('POST', '/v1/auth/challenge', {'address': self.owner})
        self.assertEqual(status, 200)
        self.assertIn('Origin: ' + self.origin, result['result']['message'])
        self.assertIsNone(self.gateway.wallet_auth.session(None))

    def test_actual_owner_signature_gets_secure_cookie_and_public_address(self):
        _, _, response = self.request('POST', '/v1/auth/challenge', {'address': self.owner})
        challenge = response['result']
        signed = self.fixture(challenge['message'])
        status, headers, response = self.request('POST', '/v1/auth/verify',
            {'challenge_id': challenge['challenge_id'], 'signature': signed['signature']})
        self.assertEqual(status, 200)
        self.assertIn('; Secure', headers['Set-Cookie'])
        self.assertEqual(response['result']['address'], wallet_address(self.owner))
        self.assertEqual(self.gateway.wallet_auth.session(headers['Set-Cookie'])['account'], self.owner)
        self.assertIn('; Secure', self.request('POST', '/v1/auth/logout', {},
            {'Cookie': headers['Set-Cookie']})[1]['Set-Cookie'])
        self.assertIsNone(self.gateway.wallet_auth.session(headers['Set-Cookie']))

    def test_reconfigured_owner_does_not_replace_existing_ownership(self):
        with self.assertRaises(ValueError):
            Gateway(('127.0.0.1', 0), self.engine, self.key, public_origin=self.origin,
                owner_wallet='0x' + '56' * 32)
        with self.engine.connection() as db:
            self.assertEqual([row['account'] for row in db.execute('SELECT account FROM operator_wallets')], [self.owner])
        with self.assertRaises(ValueError):
            Gateway(('0.0.0.0', 0), self.engine, self.key)
        with self.assertRaises(ValueError):
            Gateway(('127.0.0.1', 0), self.engine, self.key, public_origin=self.origin)
