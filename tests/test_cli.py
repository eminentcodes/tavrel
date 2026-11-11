import json
from pathlib import Path
from queue import Queue
import subprocess
import sys
from threading import Thread

from hermes_plugin import TavrelClient
from tavrel.engine import PolicyError
from tavrel.runtime import GatewayLock, operator_key, read_task_connection
from tests.support import GatewayCase


ROOT = Path(__file__).resolve().parents[1]


class CLITests(GatewayCase):
    def cli(self, *arguments):
        return subprocess.run([sys.executable, "-m", "tavrel", "--url", self.url, "--data-dir", str(self.directory), *arguments], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)

    def cli_json(self, *arguments):
        result = self.cli(*arguments, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(self.operator_token, result.stdout)
        self.assertNotIn(self.task_token, result.stdout)
        return json.loads(result.stdout)

    def test_full_operator_cli_flow_saves_token_and_requires_exact_approval(self):
        created = self.cli_json("task", "create", "CLI research", "--budget", "1.00", "--approval", "0.10", "--allow", "search_brief")
        task_id = created["task"]["id"]
        connection = read_task_connection(self.directory, task_id)
        self.assertNotIn(connection["task_token"], json.dumps(created))
        self.assertEqual(created["task"]["limit_cents"], 100)
        pending = self.cli_json("request", task_id, "--service", "search_brief", "--query", "CLI query", "--key", "cli_operation")
        self.assertEqual(pending["status"], "pending_approval")
        inspected = self.cli_json("inspect", pending["id"])
        refused = self.cli("approve", pending["id"], "--json")
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(self.service.calls, [])
        wrong = self.cli("approve", pending["id"], "--confirm", "wrong", "--json")
        self.assertEqual(wrong.returncode, 2)
        approved = self.cli_json("approve", pending["id"], "--confirm", inspected["approval_hash"])
        self.assertEqual(approved["status"], "settled")
        retry = self.cli_json("request", task_id, "--service", "search_brief", "--query", "CLI query", "--key", "cli_operation")
        self.assertEqual(retry["id"], approved["id"])
        status = self.cli_json("status", "--task", task_id)
        self.assertEqual(status["tasks"][0]["spent_cents"], 24)
        ledger = self.cli_json("ledger", "--task", task_id)
        self.assertEqual(ledger["total"], 1)
        self.assertEqual(len(self.service.calls), 1)

    def test_policy_denial_and_token_rotation_from_cli(self):
        created = self.cli_json("task", "create", "Policy task", "--budget", "1", "--approval", "0", "--allow", "search_brief")
        task_id = created["task"]["id"]
        original_token = read_task_connection(self.directory, task_id)["task_token"]
        pending = self.cli_json("request", task_id, "--service", "search_brief", "--query", "Query", "--key", "denied_request")
        denied = self.cli_json("deny", pending["id"], "--confirm", pending["approval_hash"])
        self.assertEqual(denied["status"], "denied")
        policy = self.cli_json("task", "policy", task_id, "--pause", "--budget", "2.50", "--approval", "0.24")
        self.assertTrue(policy["paused"])
        self.assertEqual(policy["limit_cents"], 250)
        self.assertEqual(policy["threshold_cents"], 24)
        self.cli_json("task", "token", task_id)
        new_token = read_task_connection(self.directory, task_id)["task_token"]
        self.assertNotEqual(new_token, original_token)
        with self.assertRaises(PolicyError) as error:
            self.engine.authenticate_task(original_token)
        self.assertEqual(error.exception.code, "unauthorized")
        account = self.cli_json("account", "--budget", "10")
        self.assertEqual(account["account"]["limit_cents"], 1000)

    def test_cli_rejects_fractional_cents_and_path_traversal(self):
        result = self.cli("task", "create", "Invalid", "--budget", "1.001", "--allow", "search_brief")
        self.assertEqual(result.returncode, 2)
        self.assertIn("two decimal places", result.stderr)
        result = self.cli("request", "../operator.key", "--service", "search_brief", "--query", "Query", "--key", "key")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(self.operator_token, result.stderr)

    def test_cli_reconciliation_requires_exact_confirmation_and_never_retries_work(self):
        self.service.error = TimeoutError("Unknown local fixture result")
        created = self.cli_json("task", "create", "Uncertain CLI task", "--budget", "1", "--allow", "search_brief")
        task_id = created["task"]["id"]
        request = self.cli_json("request", task_id, "--service", "search_brief", "--query", "Unknown result", "--key", "cli_unknown")
        self.assertEqual(request["status"], "uncertain")
        arguments = ("reconcile", request["id"], "--cost", "0.10", "--reference", "cli-test-evidence",
                     "--note", "Operator reviewed the fixture outcome.")
        refused = self.cli(*arguments, "--json")
        self.assertEqual(refused.returncode, 2)
        wrong = self.cli(*arguments, "--confirm", "wrong", "--json")
        self.assertEqual(wrong.returncode, 2)
        self.assert_accounting(task_id, 0, 24)
        result = self.cli_json(*arguments, "--confirm", request["approval_hash"])
        self.assertEqual((result["status"], result["actual_cents"]), ("reconciled", 10))
        self.assertFalse(result["evidence"]["provider_verified"])
        self.assertIsNone(result["output"])
        retry = self.cli_json("request", task_id, "--service", "search_brief", "--query", "Unknown result", "--key", "cli_unknown")
        self.assertEqual(retry["id"], request["id"])
        self.assertEqual(len(self.service.calls), 1)
        self.assert_accounting(task_id, 10, 0)

    def test_cli_approval_all_controls_zero_cost_requests_and_can_be_disabled(self):
        self.service.price_cents = self.service.cost = 0
        created = self.cli_json("task", "create", "Zero-cost CLI task", "--budget", "0", "--approval", "0",
                                "--allow", "search_brief", "--require-approval")
        task_id = created["task"]["id"]
        self.assertTrue(created["task"]["require_approval"])
        pending = self.cli_json("request", task_id, "--service", "search_brief", "--query", "Free fixture", "--key", "ask_first")
        self.assertEqual(pending["status"], "pending_approval")
        self.assertEqual(self.service.calls, [])
        self.cli_json("approve", pending["id"], "--confirm", pending["approval_hash"])
        policy = self.cli_json("task", "policy", task_id, "--no-require-approval")
        self.assertFalse(policy["require_approval"])
        receipt = self.cli_json("request", task_id, "--service", "search_brief", "--query", "Next free fixture", "--key", "no_approval")
        self.assertEqual((receipt["status"], receipt["actual_cents"]), ("settled", 0))
        self.assertEqual(len(self.service.calls), 2)

    def test_process_lock_refuses_duplicate_writer(self):
        first = GatewayLock(self.directory)
        try:
            with self.assertRaises(RuntimeError):
                GatewayLock(self.directory)
        finally:
            first.close()
        second = GatewayLock(self.directory)
        second.close()

    def test_demo_isolated_from_existing_workspace_and_proof_has_no_tokens(self):
        proof_path = self.directory / "proof.json"
        result = self.cli("demo", "--output", str(proof_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        proof_text = proof_path.read_text(encoding="utf-8")
        proof = json.loads(proof_text)
        self.assertEqual(proof["task"]["spent_cents"], 184)
        self.assertEqual(proof["task"]["available_cents"], 66)
        self.assertTrue(proof["idempotent_retry_same_id"])
        self.assertEqual(proof["paid_calls"], 0)
        self.assertFalse(proof["live_hermes_session"])
        self.assertNotIn("task_token", proof_text)
        self.assertNotIn("token_hash", proof_text)
        self.assertNotIn(self.operator_token, proof_text)
        self.assertEqual(len(self.engine.snapshot()["tasks"]), 1)

    def test_serve_process_preserves_pending_reservations_and_refuses_duplicate(self):
        directory = self.directory / "server-lifecycle"
        commands = [sys.executable, "-m", "tavrel", "--data-dir", str(directory), "serve", "--mode", "simulation", "--port", "0", "--quiet"]

        def start():
            process = subprocess.Popen(commands, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            lines = Queue()
            reader = Thread(target=lambda: [lines.put(line) for line in process.stdout], daemon=True)
            reader.start()
            try:
                first_line = lines.get(timeout=15)
                self.assertTrue(first_line.startswith("Tavrel gateway ready at "), first_line)
                url = first_line.strip().split(" at ", 1)[1]
                return process, reader, url
            except BaseException:
                stop(process, reader)
                raise

        def stop(process, reader):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            reader.join(timeout=5)
            process.stdout.close()
            process.stderr.close()

        process, reader, url = start()
        try:
            operator_token = operator_key(directory)
            operator = TavrelClient(url, operator_token)
            created = operator.request("POST", "/v1/operator/tasks", {"name": "Restart task", "limit_cents": 250, "threshold_cents": 100, "allowed_services": ["research_report"]})
            agent = TavrelClient(url, created["task_token"])
            pending = agent.request("POST", "/v1/agent/requests", {"service": "research_report", "payload": {"query": "Restart test"}, "request_key": "restart_report"})
            self.assertEqual(pending["status"], "pending_approval")
            duplicate = subprocess.run(commands, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(duplicate.returncode, 2)
            self.assertIn("already running", duplicate.stderr)
        finally:
            stop(process, reader)
        process, reader, url = start()
        try:
            self.assertEqual(operator_key(directory), operator_token)
            operator = TavrelClient(url, operator_token)
            receipt = operator.request("GET", f"/v1/operator/requests/{pending['id']}")
            self.assertEqual(receipt["status"], "pending_approval")
            self.assertEqual(operator.request("GET", "/v1/operator/status")["account"]["reserved_cents"], 160)
        finally:
            stop(process, reader)
