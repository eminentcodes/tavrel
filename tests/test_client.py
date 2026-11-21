from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from threading import Thread
import unittest
from unittest.mock import patch

from tavrel.client import GatewayError, TavrelClient
from tests.support import GatewayCase


class ClientGatewayTests(GatewayCase):
    def test_task_client_reads_prepares_and_retries_the_same_request(self):
        self.assertEqual(self.agent.request("GET", "/v1/agent/status")["task"]["id"], self.task_id)
        self.engine.update_task(self.task_id, {"threshold_cents": 0})
        arguments = {"service": "search_brief", "payload": {"query": "Query"}, "request_key": "key"}
        pending = self.agent.request("POST", "/v1/agent/requests", arguments)
        self.assertEqual(pending["status"], "pending_approval")
        self.assertIsNone(pending["output"])
        self.engine.decide(pending["id"], "approve", pending["approval_hash"])
        receipt = self.agent.request("GET", "/v1/agent/requests/" + pending["id"])
        self.assertEqual(receipt["status"], "settled")
        self.assertEqual(self.agent.request("POST", "/v1/agent/requests", arguments)["id"], pending["id"])
        self.assertEqual(len(self.service.calls), 1)

    def test_missing_token_is_a_structured_client_error(self):
        with self.assertRaises(GatewayError) as error:
            TavrelClient(self.url, "").request("GET", "/v1/agent/status")
        self.assertEqual(error.exception.code, "missing_task_token")

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
