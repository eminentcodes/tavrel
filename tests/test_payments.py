from concurrent.futures import ThreadPoolExecutor
import copy
import json
import subprocess
import sys

from tavrel.client import GatewayError
from tavrel.engine import PolicyError
from tests.fixtures import demo_account
from tavrel.payments import PaymentLedger, account_id, token_amount, units
from tavrel.runtime import save_task_connection
from tests.support import EngineCase, GatewayCase


def policy_arguments(**changes):
    return {"sender": demo_account("operator"), "budget": "10", "approval": "3", "per_payment": "7",
            "recipients": {"search": demo_account("search"), "compute": demo_account("compute")}, **changes}


class PaymentTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.payments = PaymentLedger(self.engine)
        self.task_id = self.create()["task"]["id"]
        self.payments.set_account("10")
        self.configure()

    def configure(self, task_id=None, **changes):
        return self.payments.configure(task_id or self.task_id, **policy_arguments(**changes))

    def prepare(self, value="2", key="invoice", recipient="search", task_id=None):
        return self.payments.prepare(task_id or self.task_id, recipient, value, "Service invoice", key)

    def assert_holds(self, value):
        status = self.payments.status()
        self.assertEqual(status["account"]["reserved_units"], str(units(value)))
        self.assertEqual(int(status["account"]["reserved_units"]), sum(int(item["reserved_units"]) for item in status["policies"]))
        self.assertGreaterEqual(int(status["account"]["available_units"]), 0)
        self.assertEqual(status["settled_units"], "0")
        self.assertEqual(self.engine.task(self.task_id)["spent_cents"], 0)

    def test_exact_18_decimal_amounts_and_values_above_sqlite_integer_range(self):
        self.payments.set_account("100")
        self.configure(budget="100", per_payment="100", approval="100")
        dust = self.prepare("0.000000000000000001")
        large = self.prepare("50.000000000000000001", "large")
        self.assertEqual(dust["amount_units"], "1")
        self.assertEqual(large["amount_units"], "50000000000000000001")
        self.assertEqual(token_amount(int(large["amount_units"])), "50.000000000000000001")
        self.assert_holds("50.000000000000000002")
        for invalid in (1.5, True, 1, "1e3", "-1", "01", " 1", "1.0000000000000000001", "0", "999999999999999999999"):
            with self.subTest(invalid=invalid), self.assertRaises(PolicyError):
                self.prepare(invalid, "invalid")

    def test_ss58_is_verified_and_normalized_to_the_same_public_account(self):
        alice = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
        self.assertEqual(account_id(alice), "0xd43593c715fdd31c61141abd04a99fd6822c8558854ccde39a5684e7a56da27d")
        for address in (alice[:-1] + "4", "0x" + "11" * 20, "0x" + "00" * 32, None, [], "unknown-recipient"):
            with self.subTest(address=address), self.assertRaises(PolicyError):
                account_id(address)

    def test_policy_recipient_cap_and_workspace_budget_block_before_export(self):
        unknown = self.prepare("1", "unknown", demo_account("unknown"))
        capped = self.prepare("8", "cap")
        self.payments.set_account("1")
        account = self.prepare("2", "account")
        self.assertEqual([unknown["reason"], capped["reason"], account["reason"]],
                         ["RECIPIENT_NOT_ALLOWED", "PER_PAYMENT_LIMIT", "WORKSPACE_PAYMENT_BUDGET"])
        self.assertTrue(all(item["unsigned_call"] is None for item in (unknown, capped, account)))
        self.assert_holds("0")

    def test_threshold_equality_and_require_every_payment_policy(self):
        self.assertEqual(self.prepare("3")["status"], "ready_for_signature")
        self.configure(require_approval=True)
        pending = self.prepare("0.000000000000000001", "tiny")
        self.assertEqual(pending["status"], "pending_approval")

    def test_concurrent_reservations_do_not_overrun_task_or_workspace(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda i: self.prepare("2.000000000000000001", f"parallel_{i}"), range(12)))
        self.assertEqual(sum(item["status"] == "ready_for_signature" for item in results), 4)
        self.assertEqual(sum(item["status"] == "blocked" for item in results), 8)
        self.assert_holds("8.000000000000000004")

    def test_workspace_limit_is_atomic_across_distinct_task_policies(self):
        other = self.create()["task"]["id"]
        self.configure(other)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda task: self.prepare("6", task_id=task), [self.task_id, other]))
        self.assertEqual(sorted(item["status"] for item in results), ["blocked", "pending_approval"])
        self.assert_holds("6")

    def test_identical_concurrent_retries_create_one_intent_and_one_hold(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda i: self.prepare(), range(12)))
        self.assertEqual(len({item["id"] for item in results}), 1)
        with self.assertRaises(PolicyError) as error:
            self.prepare("3")
        self.assertEqual(error.exception.code, "idempotency_conflict")
        self.assert_holds("2")

    def test_request_bound_approval_and_recipient_removal_recheck(self):
        pending = self.prepare("6")
        with self.assertRaises(PolicyError):
            self.payments.decide(pending["id"], "approve", "wrong")
        self.configure(recipients={})
        blocked = self.payments.decide(pending["id"], "approve", pending["approval_hash"])
        self.assertEqual((blocked["status"], blocked["reason"]), ("blocked", "RECIPIENT_NOT_ALLOWED"))
        self.assert_holds("0")

    def test_policy_version_change_requires_reviewing_a_fresh_fingerprint(self):
        pending = self.prepare("6")
        self.configure()
        reviewed = self.payments.decide(pending["id"], "approve", pending["approval_hash"])
        self.assertEqual(reviewed["status"], "pending_approval")
        self.assertNotEqual(reviewed["approval_hash"], pending["approval_hash"])
        with self.assertRaises(PolicyError):
            self.payments.decide(pending["id"], "approve", pending["approval_hash"])
        approved = self.payments.decide(pending["id"], "approve", reviewed["approval_hash"])
        self.assertEqual(approved["authorization"], "operator")
        exported = self.payments.export(approved["id"], approved["approval_hash"])
        self.assertEqual(exported["unsigned_call"]["args"]["value"], str(units("6")))
        self.assertFalse(exported["settlement_verified"])

    def test_export_rechecks_new_approval_policy_and_paused_task(self):
        ready = self.prepare()
        self.configure(approval="0")
        pending = self.payments.export(ready["id"], ready["approval_hash"])
        self.assertEqual(pending["status"], "pending_approval")
        self.assertIsNone(pending["unsigned_call"])
        self.engine.update_task(self.task_id, {"paused": True})
        blocked = self.payments.decide(pending["id"], "approve", pending["approval_hash"])
        self.assertEqual(blocked["reason"], "TASK_PAUSED")
        self.assert_holds("0")

    def test_export_replay_is_stable_and_holds_cannot_be_released_after_export(self):
        ready = self.prepare()
        exported = self.payments.export(ready["id"], ready["approval_hash"])
        replay = self.payments.export(ready["id"], ready["approval_hash"])
        self.assertEqual(exported, replay)
        with self.assertRaises(PolicyError):
            self.payments.decide(ready["id"], "deny", ready["approval_hash"])
        self.assert_holds("2")
        self.assertEqual(self.payments.prepare(self.task_id, "search", "2", "Service invoice", "invoice")["status"], "exported")

    def test_denial_releases_once_and_an_identical_retry_remains_denied(self):
        pending = self.prepare("6")
        self.payments.decide(pending["id"], "deny", pending["approval_hash"])
        self.assertEqual(self.prepare("6")["status"], "denied")
        with self.assertRaises(PolicyError):
            self.payments.decide(pending["id"], "deny", pending["approval_hash"])
        self.assert_holds("0")

    def test_budget_reduction_and_signer_change_cannot_discard_holds(self):
        self.prepare("6")
        with self.assertRaises(PolicyError):
            self.configure(budget="5")
        with self.assertRaises(PolicyError):
            self.payments.set_account("5")
        with self.assertRaises(PolicyError):
            self.configure(sender=demo_account("replacement"))
        self.assert_holds("6")

    def test_restart_preserves_ids_approvals_and_exact_reservations(self):
        pending = self.prepare("6")
        restarted = PaymentLedger(self.engine)
        self.assertEqual(restarted.intent(pending["id"]), pending)
        self.assertEqual(restarted.prepare(self.task_id, "search", "6", "Service invoice", "invoice")["id"], pending["id"])
        self.assert_holds("6")

    def test_batch_key_binds_the_whole_instruction_list_and_reuses_intents(self):
        instructions = [{"recipient": "search", "amount": "2", "purpose": "First invoice"},
                        {"recipient": "compute", "amount": "6", "purpose": "Second invoice"}]
        first = self.payments.plan_batch(self.task_id, "task", instructions)
        retried = self.payments.plan_batch(self.task_id, "task", instructions)
        self.assertEqual(first["intents"], retried["intents"])
        changed = copy.deepcopy(instructions)
        changed.append({"recipient": "search", "amount": "1", "purpose": "Added invoice"})
        with self.assertRaises(PolicyError):
            self.payments.plan_batch(self.task_id, "task", changed)
        self.assert_holds("8")

    def test_batch_invalid_instruction_does_not_reserve_a_partial_task(self):
        for second in ({"recipient": [], "amount": "1", "purpose": "Bad"},
                       {"recipient": "search", "amount": 1, "purpose": "Bad"},
                       {"recipient": "search", "amount": "1", "purpose": "Bad", "approved": True}):
            with self.subTest(second=second), self.assertRaises(PolicyError):
                self.payments.plan_batch(self.task_id, "invalid", [{"recipient": "search", "amount": "2", "purpose": "Valid"}, second])
        self.assert_holds("0")


class PaymentGatewayTests(GatewayCase):
    def setUp(self):
        super().setUp()
        self.payments = self.gateway.payments
        self.payments.set_account("10")
        self.payments.configure(self.task_id, **policy_arguments())

    def prepare(self, amount="6"):
        return self.agent.request("POST", "/v1/agent/payments/prepare", {
            "recipient": "search", "amount": amount, "purpose": "Invoice", "request_key": "invoice"})

    def test_agent_cannot_approve_export_or_edit_payment_policy(self):
        pending = self.prepare()
        attempts = [
            ("POST", f"/v1/operator/payments/{pending['id']}/decision", {"decision": "approve", "expected_hash": pending["approval_hash"]}),
            ("POST", f"/v1/operator/payments/{pending['id']}/export", {"expected_hash": pending["approval_hash"]}),
            ("PATCH", "/v1/operator/payments/account", {"budget": "100"}),
            ("PATCH", "/v1/operator/payments/policies/" + self.task_id, policy_arguments()),
            ("POST", "/v1/operator/payments/prepare", {"task_id": self.task_id, "recipient": "search", "amount": "1", "purpose": "Invoice", "request_key": "operator_only"}),
        ]
        for method, path, body in attempts:
            with self.subTest(path=path), self.assertRaises(GatewayError) as error:
                self.agent.request(method, path, body)
            self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.payments.intent(pending["id"])["status"], "pending_approval")

    def test_agent_cannot_read_other_task_or_override_bound_task_or_network(self):
        other = self.create()["task"]["id"]
        self.payments.configure(other, **policy_arguments())
        payment = self.payments.prepare(other, "search", "1", "Other invoice", "other")
        with self.assertRaises(GatewayError) as error:
            self.agent.request("GET", "/v1/agent/payments/" + payment["id"])
        self.assertEqual(error.exception.status, 404)
        for extra in ({"task_id": other}, {"network": "mainnet"}, {"approved": True}, {"sender": demo_account("attacker")}):
            with self.subTest(extra=extra), self.assertRaises(GatewayError) as error:
                self.agent.request("POST", "/v1/agent/payments/prepare", {"recipient": "search", "amount": "1", "purpose": "Invoice", "request_key": "injected", **extra})
            self.assertEqual(error.exception.status, 400)

    def test_native_payment_client_round_trip_without_signing(self):
        task = self.agent.request("POST", "/v1/agent/payments/task", {"task_key": "native", "payments": [{"recipient": "search", "amount": "2", "purpose": "Invoice"}]})
        payment = self.agent.request("GET", "/v1/agent/payments/" + task["intents"][0]["id"])
        status = self.agent.request("GET", "/v1/agent/payments/status")
        self.assertEqual(payment["status"], "ready_for_signature")
        self.assertTrue(status["signing_enabled"])
        self.assertFalse(payment["broadcast"])
        direct = self.agent.request("POST", "/v1/agent/payments/prepare", {"recipient": "compute", "amount": "6", "purpose": "Invoice", "request_key": "direct"})
        self.assertEqual(direct["status"], "pending_approval")
        self.assertNotIn(self.task_token, json.dumps(status))

    def test_bad_recipient_types_are_rejected_as_policy_errors(self):
        for recipient in ([], {}, None, "0x" + "12" * 20):
            with self.subTest(recipient=recipient), self.assertRaises(GatewayError) as error:
                self.agent.request("POST", "/v1/agent/payments/prepare", {"recipient": recipient, "amount": "1", "purpose": "Invoice", "request_key": "bad"})
            self.assertEqual(error.exception.status, 400)

    def test_operator_cli_requires_review_and_preserves_task_credentials(self):
        save_task_connection(self.directory, self.task_id, self.task_token, self.url)
        base = [sys.executable, "-m", "tavrel", "--url", self.url, "--data-dir", str(self.directory), "payment"]
        prepared = subprocess.run(base + ["prepare", self.task_id, "--recipient", "search", "--amount", "6", "--purpose", "Invoice", "--key", "cli"], capture_output=True, text=True, timeout=20)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        payment = json.loads(prepared.stdout)
        refused = subprocess.run(base + ["approve", payment["id"]], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
        self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertEqual(self.payments.intent(payment["id"])["status"], "pending_approval")
        approved = subprocess.run(base + ["approve", payment["id"], "--confirm", payment["approval_hash"]], capture_output=True, text=True, timeout=20)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertEqual(json.loads(approved.stdout)["authorization"], "operator")
        self.assertNotIn(self.task_token, prepared.stdout + approved.stdout + refused.stderr)
