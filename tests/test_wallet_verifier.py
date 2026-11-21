from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from tavrel.engine import PolicyError
from tavrel.wallet_verifier import SignatureVerifier


@unittest.skipUnless(shutil.which('node') and Path('node_modules/@polkadot/util-crypto').exists(), 'Requires Node and npm install')
class SignatureWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.message = 'Tavrel persistent verifier fixture'
        fixture = subprocess.run(['node', str(Path(__file__).with_name('wallet-fixture.mjs'))],
            input=json.dumps({'message': cls.message, 'label': 'worker-test'}),
            capture_output=True, text=True, check=True, timeout=15)
        cls.signed = json.loads(fixture.stdout)

    def setUp(self):
        self.verifier = SignatureVerifier()
        self.addCleanup(self.verifier.close)

    def check(self, message=None):
        return self.verifier.verify(message or self.message, self.signed['signature'], self.signed['account'])

    def test_worker_reuses_native_crypto_and_rejects_changed_claims(self):
        self.verifier.start()
        self.assertTrue(self.check())
        process = self.verifier.process
        self.assertFalse(self.check('Different login message'))
        self.assertFalse(self.verifier.verify(self.message, self.signed['signature'], '0x' + '12' * 32))
        self.assertTrue(self.check())
        self.assertIs(self.verifier.process, process)

    def test_concurrent_signatures_cannot_consume_another_requests_result(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self.check, self.message if index % 2 == 0 else 'Wrong message') for index in range(8)]
            self.assertEqual([future.result() for future in futures], [index % 2 == 0 for index in range(8)])

    def test_failed_worker_restarts_and_closed_verifier_cannot_authenticate(self):
        self.assertTrue(self.check())
        process = self.verifier.process
        process.terminate()
        process.wait(timeout=5)
        self.assertTrue(self.check())
        self.assertIsNot(self.verifier.process, process)
        self.verifier.close()
        with self.assertRaises(PolicyError):
            self.check()

    def test_startup_timeout_fails_closed_and_next_explicit_attempt_can_retry(self):
        self.verifier.timeout = 0.001
        with self.assertRaises(PolicyError) as failure:
            self.check()
        self.assertEqual(failure.exception.status, 503)
        self.assertIsNone(self.verifier.process)
        self.verifier.timeout = 12
        self.assertTrue(self.check())
