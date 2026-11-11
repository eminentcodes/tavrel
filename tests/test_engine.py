from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from tavrel.engine import Engine, PolicyError
from tavrel.services import ProviderRejected, UncertainCharge
from tests.support import EngineCase, RecordingService


class SpendingTests(EngineCase):
    def test_exact_remaining_budget_and_threshold_are_allowed(self):
        task_id = self.create(budget=24, threshold=24)["task"]["id"]
        receipt = self.purchase(task_id)
        self.assertEqual(receipt["status"], "settled")
        self.assert_accounting(task_id, 24, 0)
        self.assertEqual(len(self.service.calls), 1)

    def test_blocked_attempt_does_not_execute_or_reserve(self):
        task_id = self.create(budget=23)["task"]["id"]
        self.assertEqual(self.purchase(task_id)["status"], "blocked")
        self.assert_accounting(task_id, 0, 0)
        self.assertEqual(self.service.calls, [])

    def test_unknown_price_and_invalid_money_fail_closed(self):
        task_id = self.create()["task"]["id"]
        with self.assertRaises(PolicyError):
            self.engine.purchase(task_id, "unknown", {"query": "Query"}, "key")
        for invalid in (True, 1.0, "100", -1, 100_000_001):
            with self.subTest(value=invalid), self.assertRaises(PolicyError):
                self.engine.create_task("Task", invalid, 100, [self.service.id])
        self.assertEqual(self.service.calls, [])

    def test_invalid_input_and_request_keys_never_execute(self):
        task_id = self.create()["task"]["id"]
        for payload in ({"query": " "}, {"query": "x" * 4001}, {"query": "x", "cost": 0}, [], {"query": None}):
            with self.subTest(payload=type(payload)), self.assertRaises(PolicyError):
                self.engine.purchase(task_id, self.service.id, payload, "key")
        for key in ("", "../key", "x" * 101, None):
            with self.subTest(key=key), self.assertRaises(PolicyError):
                self.purchase(task_id, key)
        self.assertEqual(self.service.calls, [])

    def test_pending_approval_holds_budget_and_denial_releases_it(self):
        task_id = self.create(budget=30, threshold=0)["task"]["id"]
        pending = self.purchase(task_id)
        self.assertEqual(pending["status"], "pending_approval")
        self.assert_accounting(task_id, 0, 24)
        self.assertEqual(self.purchase(task_id, "second")["status"], "blocked")
        self.assertEqual(self.service.calls, [])
        denied = self.engine.decide(pending["id"], "deny", pending["approval_hash"])
        self.assertEqual(denied["status"], "denied")
        self.assert_accounting(task_id, 0, 0)
        self.assertEqual(self.purchase(task_id, "third")["status"], "pending_approval")

    def test_approval_is_bound_to_request_and_is_single_use(self):
        task_id = self.create(threshold=0)["task"]["id"]
        first = self.purchase(task_id, "first")
        second = self.purchase(task_id, "second")
        for fingerprint in (second["approval_hash"], "incorrect", "é"):
            with self.subTest(fingerprint=fingerprint), self.assertRaises(PolicyError):
                self.engine.decide(first["id"], "approve", fingerprint)
        self.assertEqual(self.service.calls, [])
        self.engine.decide(first["id"], "approve", first["approval_hash"])
        with self.assertRaises(PolicyError):
            self.engine.decide(first["id"], "approve", first["approval_hash"])
        self.assertEqual(len(self.service.calls), 1)
        self.assert_accounting(task_id, 24, 24)

    def test_approval_cannot_override_pause_or_removed_permission(self):
        task_id = self.create(threshold=0)["task"]["id"]
        pending = self.purchase(task_id)
        self.engine.update_task(task_id, {"paused": True})
        with self.assertRaises(PolicyError):
            self.engine.decide(pending["id"], "approve", pending["approval_hash"])
        self.assert_accounting(task_id, 0, 24)
        self.engine.update_task(task_id, {"paused": False, "allowed_services": []})
        blocked = self.engine.decide(pending["id"], "approve", pending["approval_hash"])
        self.assertEqual(blocked["status"], "blocked")
        self.assert_accounting(task_id, 0, 0)
        self.assertEqual(self.service.calls, [])

    def test_budget_cannot_be_lowered_below_committed_costs(self):
        task_id = self.create(threshold=0)["task"]["id"]
        pending = self.purchase(task_id)
        for change in (lambda: self.engine.update_task(task_id, {"limit_cents": 23}), lambda: self.engine.update_account(23)):
            with self.assertRaises(PolicyError):
                change()
        self.engine.decide(pending["id"], "approve", pending["approval_hash"])
        with self.assertRaises(PolicyError):
            self.engine.update_task(task_id, {"limit_cents": 23})
        self.assert_accounting(task_id, 24, 0)

    def test_sequential_retry_returns_receipt_and_changed_intent_conflicts(self):
        task_id = self.create()["task"]["id"]
        first = self.purchase(task_id)
        retry = self.purchase(task_id)
        self.assertEqual(first, retry)
        with self.assertRaises(PolicyError) as error:
            self.purchase(task_id, query="Changed query")
        self.assertEqual(error.exception.code, "idempotency_conflict")
        self.assertEqual(len(self.service.calls), 1)
        self.assert_accounting(task_id, 24, 0)

    def test_workspace_limit_applies_across_tasks(self):
        self.engine.update_account(24)
        first = self.create()["task"]["id"]
        second = self.create()["task"]["id"]
        self.assertEqual(self.purchase(first)["status"], "settled")
        self.assertEqual(self.purchase(second)["status"], "blocked")
        self.assert_accounting(second, 0, 0)
        self.assertEqual(len(self.service.calls), 1)

    def test_concurrent_distinct_requests_cannot_overspend_task(self):
        task_id = self.create(budget=48)["task"]["id"]
        barrier = Barrier(12)

        def purchase(index):
            barrier.wait(timeout=10)
            return self.purchase(task_id, "concurrent_" + str(index))

        with ThreadPoolExecutor(max_workers=12) as pool:
            receipts = list(pool.map(purchase, range(12)))
        self.assertEqual(sum(item["status"] == "settled" for item in receipts), 2)
        self.assertEqual(len(self.service.calls), 2)
        self.assert_accounting(task_id, 48, 0)

    def test_concurrent_tasks_cannot_overspend_workspace(self):
        self.engine.update_account(48)
        tasks = [self.create()["task"]["id"] for _ in range(8)]
        barrier = Barrier(8)

        def purchase(task_id):
            barrier.wait(timeout=10)
            return self.purchase(task_id)

        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(purchase, tasks))
        self.assertEqual(sum(item["status"] == "settled" for item in receipts), 2)
        self.assertEqual(len(self.service.calls), 2)
        self.assertEqual(self.engine.snapshot()["account"]["spent_cents"], 48)

    def test_concurrent_retries_execute_once_with_reservation_visible(self):
        started, finish = Event(), Event()
        service = RecordingService(started=started, finish=finish)
        self.engine.services[service.id] = service
        task_id = self.create()["task"]["id"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            first = pool.submit(self.purchase, task_id)
            try:
                self.assertTrue(started.wait(10))
                self.assert_accounting(task_id, 0, 24)
                retries = list(pool.map(lambda _: self.purchase(task_id), range(6)))
                self.assertTrue(all(item["status"] == "executing" for item in retries))
                self.assertEqual(len({item["id"] for item in retries}), 1)
            finally:
                finish.set()
            receipt = first.result(timeout=10)
        self.assertEqual(receipt["status"], "settled")
        self.assertEqual(len(service.calls), 1)
        self.assert_accounting(task_id, 24, 0)

    def test_unused_quote_is_released_after_lower_actual_cost(self):
        self.service.cost = 10
        task_id = self.create()["task"]["id"]
        self.assertEqual(self.purchase(task_id)["actual_cents"], 10)
        self.assert_accounting(task_id, 10, 0)

    def test_confirmed_rejection_releases_reservation_without_retry(self):
        self.service.error = ProviderRejected("No work performed")
        task_id = self.create()["task"]["id"]
        self.assertEqual(self.purchase(task_id)["status"], "failed")
        self.assertEqual(self.purchase(task_id)["status"], "failed")
        self.assertEqual(len(self.service.calls), 1)
        self.assert_accounting(task_id, 0, 0)

    def test_uncertain_failures_hold_maximum_and_never_retry(self):
        for error in (UncertainCharge("Unknown billing"), TimeoutError("Timeout"), RuntimeError("Unexpected exception")):
            with self.subTest(error=type(error)):
                self.service.error = error
                task_id = self.create(budget=24)["task"]["id"]
                receipt = self.purchase(task_id)
                self.assertEqual(receipt["status"], "uncertain")
                self.assertEqual(self.purchase(task_id)["id"], receipt["id"])
                self.assertEqual(self.purchase(task_id, "new")["status"], "blocked")
                self.assert_accounting(task_id, 0, 24)
        self.assertEqual(len(self.service.calls), 3)

    def test_invalid_service_receipts_hold_the_quote(self):
        for cost in (25, -1, True, 1.2):
            with self.subTest(cost=cost):
                self.service.cost = cost
                task_id = self.create()["task"]["id"]
                self.assertEqual(self.purchase(task_id)["status"], "uncertain")
                self.assert_accounting(task_id, 0, 24)

    def test_restart_preserves_pending_and_uncertain_and_task_auth(self):
        pending_task = self.create(threshold=0)
        pending = self.purchase(pending_task["task"]["id"])
        self.service.error = TimeoutError()
        uncertain_task = self.create()
        uncertain = self.purchase(uncertain_task["task"]["id"])
        restarted = Engine(self.engine.database, self.engine.services)
        restarted.recover_interrupted()
        self.assertEqual(restarted.request(pending["id"])["status"], "pending_approval")
        self.assertEqual(restarted.request(uncertain["id"])["status"], "uncertain")
        self.assertEqual(restarted.authenticate_task(pending_task["task_token"]), pending_task["task"]["id"])
        self.assertEqual(restarted.snapshot()["account"]["reserved_cents"], 48)

    def test_interrupted_execution_recovers_as_uncertain_without_reexecution(self):
        task_id = self.create(threshold=0)["task"]["id"]
        pending = self.purchase(task_id)
        # Model a process crash after its durable execution claim but before a receipt.
        with self.engine.transaction() as db:
            db.execute("UPDATE requests SET status='executing' WHERE id=?", (pending["id"],))
        self.engine.recover_interrupted()
        self.engine.recover_interrupted()
        self.assertEqual(self.purchase(task_id)["status"], "uncertain")
        self.assertEqual(self.service.calls, [])
        self.assert_accounting(task_id, 0, 24)

    def test_price_change_before_approval_blocks_before_execution(self):
        task_id = self.create(threshold=0)["task"]["id"]
        pending = self.purchase(task_id)
        self.service.price_cents = self.service.cost = 30
        receipt = self.engine.decide(pending["id"], "approve", pending["approval_hash"])
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(self.service.calls, [])
        self.assert_accounting(task_id, 0, 0)

    def test_rotated_token_is_revoked_and_not_returned_in_ledger(self):
        created = self.create()
        task_id = created["task"]["id"]
        replacement = self.engine.rotate_token(task_id)
        with self.assertRaises(PolicyError):
            self.engine.authenticate_task(created["task_token"])
        self.assertEqual(self.engine.authenticate_task(replacement["task_token"]), task_id)
        self.assertNotIn("token_hash", self.engine.task(task_id))
        self.assertNotIn(replacement["task_token"], str(self.engine.snapshot()))
