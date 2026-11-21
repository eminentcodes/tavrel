"""Separate-wallet authorization and real encryption/signature tests."""
import json
from pathlib import Path
from unittest.mock import patch
import os

from cryptography.fernet import Fernet
from tavrel.agent_wallets import AgentWallets, wallet_operation
from tavrel.engine import PolicyError
from tavrel.key_vault import KeyVault
from tavrel.settlement import Settlement
from tests.test_settlement import NetworkFixture, SIGNATURE
from tests.test_payments import policy_arguments
from tests.support import EngineCase


class AutomaticWalletTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.task_id = self.create()['task']['id']
        from tavrel.payments import PaymentLedger
        self.payments = PaymentLedger(self.engine)
        self.payments.set_account('10')
        self.network = NetworkFixture()
        self.settlement = Settlement(self.payments, self.network)
        self.seed_inputs = []
        self.address = '0x' + '34' * 32
        self.environment = patch.dict(os.environ, {'TAVREL_WALLET_VAULT_KEY': Fernet.generate_key().decode()})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        def operate(action, seed, **args):
            self.seed_inputs.append((action, seed, args))
            return {'address': self.address, 'signature': SIGNATURE}
        self.wallets = AgentWallets(self.settlement, operate=operate)
        self.wallet = self.wallets.create(self.task_id)
        self.payments.configure(self.task_id, **policy_arguments(sender=self.address))
        self.policy = self.payments.status(self.task_id)['policies'][0]

    def enable(self):
        return self.wallets.configure(self.task_id, True, self.policy['version'], fee_cap='0.001')

    def payment(self, amount='2', key='invoice'):
        return self.payments.prepare(self.task_id, 'search', amount, 'Invoice', key)

    def test_generated_key_is_encrypted_and_no_secret_is_in_public_response(self):
        with self.engine.connection() as db:
            cipher = db.execute('SELECT encrypted_seed FROM agent_wallets').fetchone()[0]
        seed = self.seed_inputs[0][1]
        self.assertEqual(self.wallets.vault.decrypt(cipher), seed)
        self.assertNotIn(seed.hex(), json.dumps(self.wallet))
        self.assertFalse(self.wallet['enabled'])
        self.assertNotIn('encrypted_seed', self.wallet)
        self.assertEqual(self.wallets.create(self.task_id)['address'], self.wallet['address'])
        self.assertEqual(len(self.seed_inputs), 1)

    def test_eligible_payment_uses_separate_wallet_and_durable_submission(self):
        self.enable()
        payment = self.payment()
        result = self.wallets.send(payment['id'])
        self.assertEqual(result['status'], 'submitting')
        self.assertEqual(self.seed_inputs[-1][0], 'sign')
        self.assertEqual(self.seed_inputs[-1][2]['sender'], self.address)
        self.assertEqual(self.payments.status()['account']['reserved_units'], '2000000000000000000')
        self.assertEqual([call[0] for call in self.network.calls], ['quote', 'inspect'])

    def test_pending_approval_is_not_approved_by_automatic_signer(self):
        self.enable()
        payment = self.payment('4')
        with self.assertRaises(PolicyError):
            self.wallets.send(payment['id'])
        self.assertEqual(self.payments.intent(payment['id'])['status'], 'pending_approval')
        self.assertEqual(len(self.seed_inputs), 1)

    def test_wallet_funding_and_fee_estimate_are_checked_before_signing(self):
        self.enable()
        payment = self.payment()
        actual = self.settlement.network
        def insufficient(action, **args):
            result = actual(action, **args)
            if action == 'quote': result['enough_funds'] = False
            return result
        self.settlement.network = insufficient
        with self.assertRaises(PolicyError) as missing:
            self.wallets.send(payment['id'])
        self.assertEqual(missing.exception.code, 'agent_wallet_unfunded')
        self.settlement.network = actual
        self.wallets.configure(self.task_id, True, self.policy['version'], fee_cap='0.000000000000000001')
        with self.assertRaises(PolicyError) as expensive:
            self.wallets.send(payment['id'])
        self.assertEqual(expensive.exception.code, 'agent_wallet_fee_limit')
        self.assertEqual(len(self.seed_inputs), 1)

    def test_changed_rules_or_expired_permission_stop_signing(self):
        self.enable()
        payment = self.payment()
        self.payments.configure(self.task_id, **policy_arguments(sender=self.address, per_payment='6'))
        self.assertFalse(self.wallets.get(self.task_id)['authorized'])
        with self.assertRaises(PolicyError):
            self.wallets.send(payment['id'])
        self.assertEqual(len(self.seed_inputs), 1)

    def test_wrong_sender_cannot_enable_permission(self):
        self.payments.configure(self.task_id, **policy_arguments())
        with self.assertRaises(PolicyError) as error:
            self.enable()
        self.assertEqual(error.exception.code, 'agent_wallet_policy_mismatch')

    def test_revoking_permission_keeps_holds_and_saved_transactions(self):
        self.enable()
        payment = self.payment()
        self.wallets.configure(self.task_id, False, self.policy['version'])
        with self.assertRaises(PolicyError):
            self.wallets.send(payment['id'])
        self.assertEqual(self.payments.intent(payment['id'])['status'], 'ready_for_signature')
        self.assertEqual(self.payments.status()['account']['reserved_units'], '2000000000000000000')

    def test_revocation_during_inspection_prevents_transaction_storage(self):
        self.enable()
        payment = self.payment()
        actual = self.settlement.network
        def revoke_on_inspect(action, **args):
            if action == 'inspect':
                self.wallets.configure(self.task_id, False, self.policy['version'])
            return actual(action, **args)
        self.settlement.network = revoke_on_inspect
        with self.assertRaises(PolicyError) as revoked:
            self.wallets.send(payment['id'])
        self.assertEqual(revoked.exception.code, 'agent_wallet_not_authorized')
        self.assertIsNone(self.payments.intent(payment['id'])['transaction'])

    def test_real_offline_wallet_derivation_and_windows_profile_encryption(self):
        seed = bytes(range(1, 33))
        public = wallet_operation('public', seed)
        self.assertRegex(public['address'], r'^0x[0-9a-f]{64}$')
        from tavrel.payments import account_id
        self.assertEqual(account_id(public['wallet_address']), public['address'])
        if os.name == 'nt':
            with patch.dict(os.environ, {}, clear=True):
                vault = KeyVault(self.directory / 'profile-vault')
                encrypted = vault.encrypt(seed)
                self.assertEqual(vault.decrypt(encrypted), seed)
                self.assertNotIn(seed, vault.path.read_bytes())
