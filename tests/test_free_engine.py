from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tavrel.engine import Engine, PolicyError
from tavrel.live_services import FREE_SERVICES
from tavrel.services import ProviderRejected, Receipt, SERVICES


class FreeEngineTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="tavrel-free-test-")
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "ledger.sqlite3"
        self.engine = Engine(self.database)
        self.created = self.engine.create_task("Free research", 0, 0, list(FREE_SERVICES))
        self.task_id = self.created["task"]["id"]

    def purchase(self, service="summary", key="free", query="First. Second. Third. Fourth."):
        return self.engine.purchase(self.task_id, service, {"query": query}, key)

    def test_default_catalog_and_workspace_allowance_have_no_paid_path(self):
        status = self.engine.snapshot()
        self.assertEqual(status["mode"], "live_free")
        self.assertFalse(status["paid_execution_enabled"])
        self.assertEqual(status["account"]["limit_cents"], 0)
        self.assertTrue(all(item["billing"] == "free" and item["price_cents"] == 0 for item in status["services"]))
        result = self.purchase()
        self.assertEqual((result["status"], result["actual_cents"], result["billing"]), ("settled", 0, "free"))
        self.assertFalse(result["output"]["simulated"])
        self.assertEqual(self.engine.task(self.task_id)["available_cents"], 0)

    def test_approval_all_waits_before_free_provider_execution_and_retries_once(self):
        self.engine.update_task(self.task_id, {"require_approval": True})
        fixture = ({"items": [], "total_count": 0}, {"kind": "http_response", "billing": "free"})
        with patch("tavrel.live_services.public_json", return_value=fixture) as fetch:
            pending = self.purchase("search_brief", query="agents")
            self.assertEqual(pending["status"], "pending_approval")
            self.assertEqual(pending["quote_cents"], 0)
            fetch.assert_not_called()
            approved = self.engine.decide(pending["id"], "approve", pending["approval_hash"])
            self.assertEqual(approved["status"], "settled")
            retry = self.purchase("search_brief", query="agents")
            self.assertEqual(retry["id"], approved["id"])
            self.assertEqual(retry["evidence"], approved["evidence"])
            self.assertEqual(fetch.call_count, 1)
        restarted = Engine(self.database)
        self.assertTrue(restarted.task(self.task_id)["require_approval"])

    def test_free_denial_pause_and_removed_permission_prevent_provider_call(self):
        with patch("tavrel.live_services.public_json") as fetch:
            self.engine.update_task(self.task_id, {"require_approval": True})
            pending = self.purchase("search_brief", query="agents")
            self.assertEqual(self.engine.decide(pending["id"], "deny", pending["approval_hash"])["status"], "denied")
            self.engine.update_task(self.task_id, {"paused": True})
            self.assertEqual(self.purchase("search_brief", "paused", "agents")["status"], "blocked")
            self.engine.update_task(self.task_id, {"paused": False, "allowed_services": ["summary"]})
            self.assertEqual(self.purchase("search_brief", "removed", "agents")["status"], "blocked")
        fetch.assert_not_called()

    def test_free_provider_rejection_stays_failed_and_does_not_retry(self):
        with patch("tavrel.live_services.public_json", side_effect=ProviderRejected("Free provider rate limit. No charge.")) as fetch:
            result = self.purchase("search_brief", query="agents")
            self.assertEqual(result["status"], "failed")
            self.assertIn("rate limit", result["reason"])
            self.assertIsNone(result["output"])
            self.assertEqual(self.purchase("search_brief", query="agents")["id"], result["id"])
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(self.engine.snapshot()["account"]["reserved_cents"], 0)

    def test_free_uncertain_outcome_can_only_be_reconciled_at_zero_without_output(self):
        with patch("tavrel.live_services.FreeService.execute", side_effect=RuntimeError("Unknown result")) as execute:
            request = self.purchase()
            self.assertEqual(request["status"], "uncertain")
            with self.assertRaises(PolicyError):
                self.engine.reconcile(request["id"], 1, "test", "Observed zero-cost local operation.", request["approval_hash"])
            result = self.engine.reconcile(request["id"], 0, "test", "Observed zero-cost local operation.", request["approval_hash"])
            self.assertEqual(result["status"], "reconciled")
            self.assertIsNone(result["output"])
            self.assertEqual(result["billing"], "free")
            self.assertFalse(result["evidence"]["provider_verified"])
            self.assertEqual(self.purchase()["id"], request["id"])
            self.assertEqual(execute.call_count, 1)

    def test_wrong_billing_or_nonzero_receipt_is_never_a_free_success(self):
        for receipt in (Receipt(1, {}, {"billing": "free"}), Receipt(0, {}, {"billing": "paid"})):
            with self.subTest(receipt=receipt):
                with patch("tavrel.live_services.FreeService.execute", return_value=receipt):
                    result = self.purchase(key="bad_" + receipt.evidence["billing"])
                self.assertEqual(result["status"], "uncertain")
                self.assertIsNone(result["output"])

    def test_cannot_reinterpret_simulated_ledger_as_free_or_free_as_simulated(self):
        result = self.purchase()
        with self.assertRaises(PolicyError) as error:
            Engine(self.database, SERVICES)
        self.assertEqual(error.exception.code, "database_mode_mismatch")
        self.assertEqual(Engine(self.database).request(result["id"])["billing"], "free")
        simulated_database = self.database.with_name("simulation.sqlite3")
        simulation = Engine(simulated_database, SERVICES)
        created = simulation.create_task("Simulation", 100, 100, ["search_brief"])
        receipt = simulation.purchase(created["task"]["id"], "search_brief", {"query": "Fixture"}, "sim")
        with self.assertRaises(PolicyError):
            Engine(simulated_database)
        saved = Engine(simulated_database, SERVICES).request(receipt["id"])
        self.assertEqual((saved["billing"], saved["actual_cents"]), ("simulated", 24))

    def test_legacy_simulation_migration_preserves_holds_tokens_and_original_billing(self):
        legacy = self.database.with_name("legacy.sqlite3")
        simulation = Engine(legacy, SERVICES)
        created = simulation.create_task("Legacy", 250, 100, ["research_report"])
        pending = simulation.purchase(created["task"]["id"], "research_report", {"query": "Legacy fixture"}, "pending")
        with closing(sqlite3.connect(legacy)) as db:
            db.execute("DROP TABLE metadata")
            db.execute("ALTER TABLE tasks DROP COLUMN require_approval")
            db.execute("ALTER TABLE requests DROP COLUMN billing")
            db.execute("ALTER TABLE requests DROP COLUMN service_name")
            db.commit()
        with self.assertRaises(PolicyError):
            Engine(legacy)
        migrated = Engine(legacy, SERVICES)
        self.assertEqual(migrated.authenticate_task(created["task_token"]), created["task"]["id"])
        saved = migrated.request(pending["id"])
        self.assertEqual((saved["status"], saved["billing"], saved["quote_cents"]), ("pending_approval", "simulated", 160))
        self.assertEqual(saved["service_name"], "Research report")
        self.assertEqual(migrated.task(created["task"]["id"])["reserved_cents"], 160)

    def test_paid_or_mixed_service_catalog_is_rejected_before_database_creation(self):
        class PaidService:
            price_cents = 1

            def public(self):
                return {"billing": "paid"}

        for catalog in ({"paid": PaidService()}, {**FREE_SERVICES, "paid": PaidService()},
                        {**FREE_SERVICES, "search_brief": SERVICES["search_brief"]}):
            with self.subTest(catalog=list(catalog)):
                path = self.database.with_name("blocked.sqlite3")
                with self.assertRaises(PolicyError):
                    Engine(path, catalog)
                self.assertFalse(path.exists())
