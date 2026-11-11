from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
from threading import Thread
import unittest
from unittest.mock import patch

from hermes_plugin import GatewayError, SCHEMAS, TavrelClient, make_handlers
from tests.support import GatewayCase


class PluginTests(GatewayCase):
    def test_tools_round_trip_purchase_pending_and_receipt(self):
        handlers = make_handlers(lambda: self.agent)
        status = json.loads(handlers["tavrel_status"]({}, task_id="ignored", user_id="ignored"))
        self.assertEqual(status["result"]["task"]["id"], self.task_id)
        self.engine.update_task(self.task_id, {"threshold_cents": 0})
        arguments = {"service": "search_brief", "query": "Query", "request_key": "key"}
        pending = json.loads(handlers["tavrel_purchase"](arguments))["result"]
        self.assertEqual(pending["status"], "pending_approval")
        self.assertIsNone(pending["output"])
        self.engine.decide(pending["id"], "approve", pending["approval_hash"])
        receipt = json.loads(handlers["tavrel_receipt"]({"request_id": pending["id"]}))["result"]
        self.assertEqual(receipt["status"], "settled")
        self.assertEqual(json.loads(handlers["tavrel_purchase"](arguments))["result"]["id"], pending["id"])
        self.assertEqual(len(self.service.calls), 1)

    def test_arguments_cannot_override_price_or_authorization(self):
        handlers = make_handlers(lambda: self.agent)
        cases = [("tavrel_status", {"task_id": "other"}), ("tavrel_purchase", {"service": "search_brief", "query": "Query", "request_key": "key", "approved": True}), ("tavrel_purchase", {}), ("tavrel_receipt", {"request_id": "../operator/status"}), ("tavrel_status", [])]
        for tool, arguments in cases:
            with self.subTest(tool=tool):
                response = json.loads(handlers[tool](arguments))
                self.assertFalse(response["ok"])
        self.assertEqual(self.service.calls, [])

    def test_standalone_plugin_registers_documented_contract_without_gateway_imports(self):
        # Load only the distributable plugin file, as a host plugin loader would.
        path = Path(__file__).resolve().parents[1] / "hermes_plugin" / "__init__.py"
        spec = importlib.util.spec_from_file_location("standalone_tavrel", path)
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)

        class Context:
            def __init__(self):
                self.tools, self.commands = {}, {}

            def register_tool(self, *, name, toolset, schema, handler):
                self.tools[name] = (toolset, schema, handler)

            def register_command(self, name, handler, description):
                self.commands[name] = (handler, description)

        ctx = Context()
        with patch.dict(os.environ, {"TAVREL_URL": self.url, "TAVREL_TASK_TOKEN": self.task_token}):
            plugin.register(ctx)
            self.assertEqual(set(ctx.tools), set(SCHEMAS))
            self.assertEqual(set(ctx.commands), {"budget"})
            for name, (toolset, schema, handler) in ctx.tools.items():
                self.assertEqual(toolset, "tavrel")
                self.assertEqual(schema["name"], name)
                self.assertTrue(callable(handler))
            budget = ctx.commands["budget"][0]("", session_id="test-session")
        self.assertIn("Allowance $1.00", budget)
        self.assertIn("simulated spend", budget)

    def test_missing_token_is_a_structured_plugin_error(self):
        handlers = make_handlers(lambda: TavrelClient(self.url, ""))
        response = json.loads(handlers["tavrel_status"]({}))
        self.assertEqual(response["error"]["code"], "missing_task_token")

    def test_loopback_calls_ignore_environment_proxies(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": ""}):
            client = TavrelClient(self.url, self.task_token)
            self.assertEqual(client.request("GET", "/v1/agent/status")["task"]["id"], self.task_id)


class ClientTests(unittest.TestCase):
    def test_http_error_with_reset_body_remains_a_structured_rejection(self):
        from io import BytesIO
        from unittest.mock import Mock
        from urllib.error import HTTPError

        class ResetResponse(BytesIO):
            def read(self, *args, **kwargs):
                raise ConnectionResetError("Response body was reset")

        response = ResetResponse(b"")
        client = TavrelClient("http://127.0.0.1:8787", "synthetic-token")
        client.opener = Mock()
        client.opener.open.side_effect = HTTPError(client.url, 403, "Forbidden", {}, response)
        with self.assertRaises(GatewayError) as error:
            client.request("PATCH", "/v1/operator/account", {"limit_cents": 100})
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(error.exception.code, "gateway_http_error")
        self.assertTrue(response.closed)

    def test_invalid_or_unencrypted_remote_origins_are_rejected(self):
        for url in ("http://remote.example", "ftp://127.0.0.1", "http://user:pass@localhost", "http://localhost/path", "http://localhost?token=value", "http://localhost#fragment", "http://localhost:bad", "http://localhost:65536", "http://localhost:0", "http://[broken"):
            with self.subTest(url=url), self.assertRaises(GatewayError):
                TavrelClient(url, "test-token")

    def test_redirect_is_refused_before_credential_can_reach_target(self):
        class Redirect(BaseHTTPRequestHandler):
            targets = 0

            def do_GET(self):
                if self.path == "/target":
                    Redirect.targets += 1
                    self.send_response(200)
                else:
                    self.send_response(302)
                    self.send_header("Location", "/target")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            client = TavrelClient(f"http://127.0.0.1:{server.server_address[1]}", "synthetic-token")
            with self.assertRaises(GatewayError) as error:
                client.request("GET", "/redirect")
            self.assertEqual(error.exception.code, "redirect_refused")
            self.assertEqual(Redirect.targets, 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
