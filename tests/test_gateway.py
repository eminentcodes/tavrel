from http.client import HTTPConnection
import json

from hermes_plugin import GatewayError
from tests.support import GatewayCase


class GatewayTests(GatewayCase):
    def raw(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.gateway.server_address[1], timeout=5)
        try:
            connection.request(method, path, body, headers or {})
            with connection.getresponse() as response:
                return response.status, dict(response.getheaders()), json.loads(response.read())
        finally:
            connection.close()

    def test_health_is_public_and_describes_real_payment_interface(self):
        status, headers, body = self.raw("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["network"], "zkverify-volta")
        self.assertTrue(body["result"]["wallet_transfers_enabled"])
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_agent_cannot_approve_change_policy_or_read_operator_ledger(self):
        self.engine.update_task(self.task_id, {"threshold_cents": 0})
        pending = self.purchase(self.task_id)
        attempts = [
            ("GET", "/v1/operator/status", None),
            ("GET", "/v1/operator/requests", None),
            ("PATCH", "/v1/operator/account", {"limit_cents": 1000}),
            ("PATCH", f"/v1/operator/tasks/{self.task_id}", {"limit_cents": 1000}),
            ("POST", f"/v1/operator/requests/{pending['id']}/decision", {"decision": "approve", "expected_hash": pending["approval_hash"]}),
        ]
        for method, path, body in attempts:
            with self.subTest(path=path), self.assertRaises(GatewayError) as error:
                self.agent.request(method, path, body)
            self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.service.calls, [])
        self.assert_accounting(self.task_id, 0, 24)

    def test_agent_cannot_read_another_task_or_choose_task_in_purchase(self):
        other = self.create()["task"]["id"]
        receipt = self.purchase(other)
        with self.assertRaises(GatewayError) as error:
            self.agent.request("GET", f"/v1/agent/requests/{receipt['id']}")
        self.assertEqual(error.exception.status, 404)
        with self.assertRaises(GatewayError):
            self.agent.request("POST", "/v1/agent/requests", {"task_id": other, "service": "search_brief", "payload": {"query": "Query"}, "request_key": "key"})
        self.assertEqual(self.agent.request("GET", "/v1/agent/status")["task"]["id"], self.task_id)

    def test_early_authorization_denial_returns_json_with_bounded_unread_body(self):
        for size in (32, 65_000, 130_000):
            with self.subTest(size=size):
                status, _, response = self.raw("PATCH", "/v1/operator/account", b"x" * size,
                                               {"Authorization": "Bearer " + self.task_token})
                self.assertEqual(status, 403)
                self.assertEqual(response["error"]["code"], "forbidden")
        self.assertEqual(self.service.calls, [])
        self.assert_accounting(self.task_id, 0, 0)

    def test_missing_bad_and_operator_tokens_fail_on_agent_routes(self):
        for token in (None, "bad-token", self.operator_token):
            headers = {"Authorization": "Bearer " + token} if token else {}
            with self.subTest(token=bool(token)):
                self.assertEqual(self.raw("GET", "/v1/agent/status", headers=headers)[0], 401)
        self.assertEqual(self.raw("GET", "/v1/operator/status", headers={"Authorization": "Bearer é"})[0], 403)

    def test_rotation_revokes_old_agent_token_over_http(self):
        result = self.operator.request("POST", f"/v1/operator/tasks/{self.task_id}/token", {})
        with self.assertRaises(GatewayError):
            self.agent.request("GET", "/v1/agent/status")
        self.assertNotEqual(result["task_token"], self.task_token)

    def test_host_and_cross_origin_browser_requests_are_rejected(self):
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"}, {"Origin": "null"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.raw("GET", "/health", headers=headers)[0], 403)
        self.assertEqual(self.raw("GET", "/health", headers={"Origin": self.url})[0], 200)

    def test_malformed_oversized_and_unsupported_json_are_rejected(self):
        headers = {"Authorization": "Bearer " + self.task_token, "Content-Type": "application/json"}
        for body in (b"{", b"\xff", b"[]", b"x" * 65_537, b'{"service":"search_brief","payload":{"query":"Query"},"request_key":"key","approval":true}'):
            with self.subTest(length=len(body)):
                self.assertEqual(self.raw("POST", "/v1/agent/requests", body, headers)[0], 400)
        self.assertEqual(self.service.calls, [])

    def test_operator_decision_and_ledger_are_persistent_and_task_scoped(self):
        self.engine.update_task(self.task_id, {"threshold_cents": 0})
        pending = self.agent.request("POST", "/v1/agent/requests", {"service": "search_brief", "payload": {"query": "Query"}, "request_key": "key"})
        receipt = self.operator.request("POST", f"/v1/operator/requests/{pending['id']}/decision", {"decision": "approve", "expected_hash": pending["approval_hash"]})
        self.assertEqual(receipt["status"], "settled")
        other = self.create()["task"]["id"]
        self.purchase(other)
        ledger = self.operator.request("GET", f"/v1/operator/requests?task_id={self.task_id}&limit=1")
        self.assertEqual(ledger["total"], 1)
        self.assertEqual(ledger["requests"][0]["id"], pending["id"])
        self.assertNotIn(self.task_token, json.dumps(ledger))

    def test_invalid_pagination_and_unicode_approval_return_policy_errors(self):
        for query in ("limit=0", "limit=201", "offset=-1", "limit=bad"):
            with self.subTest(query=query), self.assertRaises(GatewayError) as error:
                self.operator.request("GET", "/v1/operator/requests?" + query)
            self.assertEqual(error.exception.status, 400)
        self.engine.update_task(self.task_id, {"threshold_cents": 0})
        pending = self.purchase(self.task_id)
        with self.assertRaises(GatewayError) as error:
            self.operator.request("POST", f"/v1/operator/requests/{pending['id']}/decision", {"decision": "approve", "expected_hash": "é"})
        self.assertEqual(error.exception.code, "approval_mismatch")
