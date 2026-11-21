from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from tavrel.client import GatewayError
from tavrel.engine import Engine, PolicyError
from tavrel.services import ProviderRejected
from tests.support import EngineCase, GatewayCase


class ReconciliationTests(EngineCase):
    def uncertain(self, key="unknown", task_id=None):
        self.service.error = TimeoutError("Outcome unknown")
        task_id = task_id or self.create(budget=100)["task"]["id"]
        request = self.purchase(task_id, key)
        self.assertEqual(request["status"], "uncertain")
        return request

    def reconcile(self, request, cost=10, **changes):
        arguments = {"actual_cents": cost, "reference": "local-test-evidence",
                     "note": "Operator reviewed the fixture outcome.", "expected_hash": request["approval_hash"]}
        return self.engine.reconcile(request["id"], **{**arguments, **changes})

    def test_reconciliation_records_attestation_and_releases_unused_hold_without_retry(self):
        request = self.uncertain()
        result = self.reconcile(request)
        self.assertEqual((result["status"], result["actual_cents"]), ("reconciled", 10))
        self.assertIsNone(result["output"])
        self.assertFalse(result["evidence"]["provider_verified"])
        self.assertEqual(result["evidence"]["source"], "operator_attestation")
        self.assertEqual(result["billing"], "simulated")
        self.assertEqual(self.purchase(request["task_id"], "unknown")["id"], request["id"])
        self.assertEqual(len(self.service.calls), 1)
        self.assert_accounting(request["task_id"], 10, 0)
        restarted = Engine(self.engine.database, self.engine.services)
        restarted.recover_interrupted()
        self.assertEqual(restarted.request(request["id"])["evidence"], result["evidence"])
        with self.assertRaises(PolicyError):
            self.reconcile(request)
        self.assert_accounting(request["task_id"], 10, 0)

    def test_zero_cost_reconciliation_releases_entire_original_reservation(self):
        request = self.uncertain()
        self.reconcile(request, cost=0)
        self.assert_accounting(request["task_id"], 0, 0)
        self.assertEqual(len(self.service.calls), 1)

    def test_invalid_cost_evidence_and_confirmation_preserve_the_reservation(self):
        request = self.uncertain()
        cases = (
            {"actual_cents": 25}, {"actual_cents": -1}, {"actual_cents": True},
            {"actual_cents": 1.5}, {"reference": " "}, {"reference": "r" * 501},
            {"note": " "}, {"note": "n" * 2001}, {"expected_hash": "wrong"},
            {"expected_hash": "é" * 64},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(PolicyError):
                self.reconcile(request, **changes)
            self.assert_accounting(request["task_id"], 0, 24)
            self.assertEqual(self.engine.request(request["id"])["status"], "uncertain")

    def test_pending_failed_and_settled_requests_cannot_be_reconciled(self):
        task_id = self.create(threshold=0)["task"]["id"]
        pending = self.purchase(task_id)
        with self.assertRaises(PolicyError) as error:
            self.reconcile(pending)
        self.assertEqual(error.exception.code, "request_not_uncertain")
        self.assert_accounting(task_id, 0, 24)
        denied = self.engine.decide(pending["id"], "deny", pending["approval_hash"])
        with self.assertRaises(PolicyError):
            self.reconcile(denied)
        task_id = self.create()["task"]["id"]
        settled = self.purchase(task_id)
        with self.assertRaises(PolicyError):
            self.reconcile(settled)
        self.assert_accounting(task_id, 24, 0)
        self.service.error = ProviderRejected("No billable work")
        failed = self.purchase(task_id, "failed")
        with self.assertRaises(PolicyError):
            self.reconcile(failed)
        self.assert_accounting(task_id, 24, 0)

    def test_concurrent_reconciliation_commits_cost_exactly_once(self):
        request = self.uncertain()
        barrier = Barrier(2)

        def run():
            barrier.wait(timeout=5)
            try:
                return self.reconcile(request)["status"]
            except PolicyError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertCountEqual(results, ["reconciled", "request_not_uncertain"])
        self.assert_accounting(request["task_id"], 10, 0)
        self.assertEqual(len(self.service.calls), 1)


class ReconciliationGatewayTests(GatewayCase):
    def test_agent_cannot_reconcile_and_operator_action_is_visible_to_task(self):
        self.service.error = TimeoutError()
        request = self.purchase(self.task_id)
        body = {"actual_cents": 0, "reference": "http-test-evidence",
                "note": "Operator reviewed a no-cost test outcome.", "expected_hash": request["approval_hash"]}
        path = f"/v1/operator/requests/{request['id']}/reconcile"
        with self.assertRaises(GatewayError) as error:
            self.agent.request("POST", path, body)
        self.assertEqual(error.exception.status, 403)
        with self.assertRaises(GatewayError):
            self.agent.request("POST", f"/v1/agent/requests/{request['id']}/reconcile", body)
        self.assert_accounting(self.task_id, 0, 24)
        result = self.operator.request("POST", path, body)
        self.assertEqual(result["status"], "reconciled")
        read = self.agent.request("GET", f"/v1/agent/requests/{request['id']}")
        self.assertEqual(read["evidence"], result["evidence"])
        self.assertFalse(read["evidence"]["provider_verified"])
        self.assert_accounting(self.task_id, 0, 0)
