"""Loopback-only HTTP gateway with separate operator and task credentials."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
from pathlib import Path
import mimetypes
from urllib.parse import parse_qs, urlsplit

from .engine import Engine, PolicyError
from .payments import PaymentLedger
from .auth import WalletAuth
from .settlement import Settlement
from .proofs import PolicyProofs


IDENTIFIER = re.compile(r"(?:tsk|req)_[a-f0-9]{16}")


def fields(body, required, optional=()):
    if not isinstance(body, dict) or set(required) - set(body) or set(body) - set(required) - set(optional):
        raise PolicyError("invalid_fields", "The request has missing or unsupported fields.")
    return body


class Gateway(ThreadingHTTPServer):
    daemon_threads = False
    allow_reuse_address = True

    def __init__(self, address, engine: Engine, operator_token: str, quiet=False):
        if address[0] not in ("127.0.0.1", "localhost"):
            raise ValueError("This prototype binds only to loopback.")
        self.engine = engine
        self.payments = PaymentLedger(engine)
        self.wallet_auth = WalletAuth(engine)
        self.settlement = Settlement(self.payments)
        self.policy_proofs = PolicyProofs(self.settlement)
        self.operator_token = operator_token
        self.quiet = quiet
        super().__init__(address, Handler)

    def serve_forever(self, poll_interval=0.5):
        self.settlement.start()
        try:
            super().serve_forever(poll_interval)
        finally:
            self.settlement.close()

    def server_close(self):
        self.settlement.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Tavrel/0.1"

    def log_message(self, format, *args):
        if not self.server.quiet:
            # Deliberately omit URLs, query strings, credentials, and input data.
            print(f"[tavrel] {self.command} request completed", flush=True)

    def respond(self, status, payload):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        if getattr(self, "response_cookie", None):
            self.send_header("Set-Cookie", self.response_cookie)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(encoded)

    def guard_origin(self):
        port = self.server.server_address[1]
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "").lower() not in allowed_hosts:
            raise PolicyError("invalid_host", "The gateway accepts only its loopback hostname.", 403)
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in allowed_hosts}:
            raise PolicyError("invalid_origin", "Cross-origin requests are not allowed.", 403)

    def bearer(self):
        value = self.headers.get("Authorization", "")
        if not value.startswith("Bearer ") or not value[7:]:
            raise PolicyError("unauthorized", "An access token is required.", 401)
        return value[7:]

    def operator(self):
        if not self.headers.get("Authorization") and self.server.wallet_auth.session(self.headers.get("Cookie")):
            return
        token = self.bearer()
        if not token.isascii() or not secrets.compare_digest(token, self.server.operator_token):
            raise PolicyError("forbidden", "Operator access is required for this action.", 403)

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            raise PolicyError("invalid_body", "Chunked request bodies are not supported.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise PolicyError("invalid_body", "Invalid request length.") from None
        if not 0 < length <= 65_536:
            # Discard a bounded modest overflow before closing. On Windows,
            # unread inbound bytes can reset the socket and erase the JSON error.
            if 65_536 < length <= 131_072:
                self._body_bytes_read = len(self.rfile.read(length))
            raise PolicyError("invalid_body", "Provide a JSON body no larger than 64 KB.")
        try:
            data = self.rfile.read(length)
            self._body_bytes_read = len(data)
            if len(data) != length:
                raise ValueError("incomplete body")
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise PolicyError("invalid_json", "The request body must be valid UTF-8 JSON.") from None

    def discard_body(self):
        """Drain only bounded, declared bytes before an early authorization error.

        Closing an unread POST/PATCH body can reset a Windows socket and hide the
        error response. This never parses the body or authorizes its operation.
        """
        if self.headers.get("Transfer-Encoding"):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        remaining = length - getattr(self, "_body_bytes_read", 0)
        if 0 < length <= 131_072 and remaining > 0:
            try:
                self._body_bytes_read = length - remaining + len(self.rfile.read(remaining))
            except (OSError, TimeoutError):
                pass

    def route(self):
        self.connection.settimeout(10)
        self.guard_origin()
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        method = self.command
        engine = self.server.engine
        payments = self.server.payments
        auth = self.server.wallet_auth
        origin = "http://" + self.headers["Host"].lower()
        if method == "GET" and path == "/v1/auth/status":
            session = auth.session(self.headers.get("Cookie"))
            return {"authenticated": bool(session), "account": session["account"] if session else None,
                "configured": auth.configured(), "method": "Substrate signed-message login"}
        if method == "POST" and path == "/v1/auth/challenge":
            body = fields(self.body(), ("address",), ("ticket",))
            return auth.challenge(origin=origin, **body)
        if method == "POST" and path == "/v1/auth/verify":
            body = fields(self.body(), ("challenge_id", "signature"))
            result, self.response_cookie = auth.verify(origin=origin, **body)
            return result
        if method == "POST" and path == "/v1/auth/logout":
            fields(self.body(), ())
            self.response_cookie = auth.logout(self.headers.get("Cookie"))
            return {"authenticated": False}
        if method == "GET" and path in ("/", "/health"):
            return {"name": "Tavrel", "status": "ready", "network": "zkverify-volta", "interface": "Agent payment app and task-scoped API", "wallet_transfers_enabled": True}
        if path.startswith("/v1/agent/"):
            task_id = engine.authenticate_task(self.bearer())
            if method == "GET" and path == "/v1/agent/payments/status":
                return payments.status(task_id)
            if method == "POST" and path == "/v1/agent/payments/prepare":
                body = fields(self.body(), ("recipient", "amount", "purpose", "request_key"))
                return payments.prepare(task_id, **body)
            if method == "POST" and path == "/v1/agent/payments/task":
                body = fields(self.body(), ("task_key", "payments"))
                return payments.plan_batch(task_id, **body)
            match = re.fullmatch(r"/v1/agent/payments/(pay_[a-f0-9]{16})", path)
            if method == "GET" and match:
                return payments.intent(match[1], task_id)
            if method == "GET" and path == "/v1/agent/status":
                return engine.agent_status(task_id)
            if method == "POST" and path == "/v1/agent/requests":
                body = fields(self.body(), ("service", "payload", "request_key"))
                return engine.purchase(task_id, body["service"], body["payload"], body["request_key"])
            match = re.fullmatch(r"/v1/agent/requests/(req_[a-f0-9]{16})", path)
            if method == "GET" and match:
                return engine.request(match[1], task_id)
        elif path.startswith("/v1/operator/"):
            self.operator()
            query = parse_qs(parsed.query)
            if method == "GET" and path == "/v1/operator/payments/status":
                return {**payments.status(query.get("task_id", [None])[0]), 'proofs_available': self.server.policy_proofs.available()}
            if method == "PATCH" and path == "/v1/operator/payments/account":
                body = fields(self.body(), ("budget",))
                return payments.set_account(**body)
            if method == "POST" and path == "/v1/operator/payments/prepare":
                body = fields(self.body(), ("task_id", "recipient", "amount", "purpose", "request_key"))
                return payments.prepare(**body, actor="operator")
            match = re.fullmatch(r"/v1/operator/payments/policies/(tsk_[a-f0-9]{16})", path)
            if method == "PATCH" and match:
                body = fields(self.body(), ("sender", "budget", "approval", "per_payment", "recipients"), ("require_approval",))
                return payments.configure(match[1], **body)
            match = re.fullmatch(r"/v1/operator/payments/(pay_[a-f0-9]{16})(/decision|/export|/quote|/submit|/proof)?", path)
            if match:
                if method == "GET" and not match[2]:
                    return payments.intent(match[1])
                if method == "POST" and match[2] == "/decision":
                    body = fields(self.body(), ("decision", "expected_hash"))
                    return payments.decide(match[1], **body)
                if method == "POST" and match[2] == "/export":
                    body = fields(self.body(), ("expected_hash",))
                    return payments.export(match[1], **body)
                if method == "POST" and match[2] == "/quote":
                    body = fields(self.body(), ("expected_hash",))
                    return self.server.settlement.quote(match[1], **body)
                if method == "POST" and match[2] == "/submit":
                    body = fields(self.body(), ("expected_hash", "quote_id", "signature"), ("signed_hex",))
                    return self.server.settlement.submit(match[1], **body)
                if method == "POST" and match[2] == "/proof":
                    body = fields(self.body(), ("expected_hash",))
                    return self.server.policy_proofs.generate(match[1], **body)
            if method == "GET" and path == "/v1/operator/status":
                return engine.snapshot(query.get("task_id", [None])[0])
            if method == "GET" and path == "/v1/operator/services":
                return {"services": engine.service_list(), "mode": engine.mode}
            if method == "GET" and path == "/v1/operator/requests":
                try:
                    limit = int(query.get("limit", [50])[0])
                    offset = int(query.get("offset", [0])[0])
                except (ValueError, TypeError):
                    raise PolicyError("invalid_pagination", "Limit and offset must be integers.") from None
                return engine.ledger(query.get("task_id", [None])[0], limit, offset)
            if method == "POST" and path == "/v1/operator/tasks":
                body = fields(self.body(), ("name", "limit_cents", "threshold_cents", "allowed_services"), ("description", "require_approval"))
                return engine.create_task(**body)
            if method == "PATCH" and path == "/v1/operator/account":
                body = fields(self.body(), ("limit_cents",))
                engine.update_account(body["limit_cents"])
                return engine.snapshot()
            match = re.fullmatch(r"/v1/operator/tasks/(tsk_[a-f0-9]{16})(/token)?", path)
            if match:
                if method == "PATCH" and not match[2]:
                    return engine.update_task(match[1], self.body())
                if method == "POST" and match[2]:
                    fields(self.body(), ())
                    return engine.rotate_token(match[1])
                if method == "GET" and not match[2]:
                    return engine.task(match[1])
            match = re.fullmatch(r"/v1/operator/requests/(req_[a-f0-9]{16})(/decision|/reconcile)?", path)
            if match:
                if method == "GET" and not match[2]:
                    return engine.request(match[1])
                if method == "POST" and match[2] == "/decision":
                    body = fields(self.body(), ("decision", "expected_hash"))
                    return engine.decide(match[1], body["decision"], body["expected_hash"])
                if method == "POST" and match[2] == "/reconcile":
                    body = fields(self.body(), ("actual_cents", "reference", "note", "expected_hash"))
                    return engine.reconcile(match[1], **body)
        raise PolicyError("not_found", "Endpoint not found.", 404)

    def handle_request(self):
        try:
            if self.serve_frontend():
                return
            result = self.route()
        except PolicyError as exc:
            self.discard_body()
            self.respond(exc.status, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            self.discard_body()
            self.respond(500, {"ok": False, "error": {"code": "gateway_error", "message": "The gateway could not complete this request. Existing reservations remain held."}})
        else:
            self.respond(200, {"ok": True, "result": result})

    def serve_frontend(self):
        """Serve only built assets or known browser routes, with the API's host guard."""
        if self.command != "GET":
            return False
        path = urlsplit(self.path).path
        if path == "/health" or path.startswith("/v1/"):
            return False
        web = Path(__file__).parent / "web"
        browser_route = path in {"/", "/connect", "/dashboard", "/agents", "/vendors", "/approvals", "/ledger", "/settings", "/docs"} or re.fullmatch(r"/(?:agents/tsk_[a-f0-9]{16}(?:/policy)?|payments/pay_[a-f0-9]{16})", path)
        public_asset = path in {"/favicon.svg", "/tavrel-mark.svg", "/apple-touch-icon.png", "/payment-preview.png", "/ledger-preview.png"}
        if not browser_route and not public_asset and not path.startswith("/assets/"):
            return False
        if not (web / "index.html").is_file():
            return False
        self.connection.settimeout(10)
        self.guard_origin()
        target = web / "index.html" if browser_route else web / path.lstrip("/")
        target = target.resolve()
        if not target.is_relative_to(web.resolve()) or not target.is_file():
            raise PolicyError("not_found", "Asset not found.", 404)
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(body)
        return True

    do_GET = handle_request
    do_POST = handle_request
    do_PATCH = handle_request

