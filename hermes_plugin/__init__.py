"""Self-contained Hermes plugin. Only Python's standard library is required."""

import json
import os
import re
from functools import lru_cache
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class GatewayError(Exception):
    def __init__(self, code, message, status=0):
        super().__init__(message)
        self.code = code
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward task/operator credentials to a redirected destination.
        return None


@lru_cache(maxsize=1)
def loopback_opener():
    # These handlers keep no request/session state. Reuse the verified TLS
    # defaults built by urllib instead of repeatedly loading Windows trust stores.
    return build_opener(NoRedirect, ProxyHandler({}))


class TavrelClient:
    def __init__(self, url=None, token=None, timeout=25):
        self.url = (url or os.environ.get("TAVREL_URL", "http://127.0.0.1:8787")).rstrip("/")
        self.token = token if token is not None else os.environ.get("TAVREL_TASK_TOKEN", "")
        self.timeout = timeout
        try:
            parsed = urlsplit(self.url)
            port = parsed.port
        except ValueError:
            raise GatewayError("invalid_gateway_url", "Configure a valid gateway origin and port.") from None
        if port is not None and not 1 <= port <= 65535:
            raise GatewayError("invalid_gateway_url", "Configure a gateway port between 1 and 65535.")
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise GatewayError("invalid_gateway_url", "Configure a gateway origin without credentials, a path, query, or fragment.")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise GatewayError("insecure_gateway_url", "Unencrypted HTTP is supported only for loopback gateways.")
        # Local task credentials must never travel through an environment proxy.
        self.opener = loopback_opener() if parsed.hostname in ("localhost", "127.0.0.1", "::1") else build_opener(NoRedirect)

    def request(self, method, path, body=None):
        if not self.token:
            raise GatewayError("missing_task_token", "Set TAVREL_TASK_TOKEN to the task's restricted access token.")
        if not path.startswith("/") or path.startswith("//"):
            raise GatewayError("invalid_path", "Use a relative gateway API path.")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = Request(self.url + path, data=data, method=method, headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(8_388_609)
                if len(raw) > 8_388_608:
                    raise GatewayError("response_too_large", "The gateway response exceeds the supported size.")
                payload = json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            try:
                if 300 <= exc.code < 400:
                    raise GatewayError("redirect_refused", "Gateway redirects are refused to protect access credentials.", exc.code) from None
                try:
                    value = json.loads(exc.read(65_536))
                    error = value["error"]
                    if not isinstance(error, dict) or not isinstance(error.get("code"), str) or not isinstance(error.get("message"), str):
                        raise ValueError("invalid error")
                    raise GatewayError(error["code"], error["message"], exc.code) from None
                except (ValueError, KeyError, TypeError, OSError, HTTPException):
                    raise GatewayError("gateway_http_error", "The gateway rejected this request.", exc.code) from None
            finally:
                exc.close()
        except (URLError, TimeoutError, OSError, HTTPException):
            raise GatewayError("gateway_unavailable", "The gateway is unavailable. Start it and verify the configured address; do not retry an uncertain purchase with a new request key.") from None
        except (ValueError, UnicodeDecodeError):
            raise GatewayError("invalid_gateway_response", "The gateway returned an invalid response.") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True or "result" not in payload:
            raise GatewayError("invalid_gateway_response", "The gateway returned an unexpected response.")
        return payload["result"]


def make_handlers(client_factory=TavrelClient):
    def wrap(name, operation):
        def handler(params, **kwargs):
            del kwargs
            try:
                if not isinstance(params, dict):
                    raise GatewayError("invalid_arguments", "Tool arguments must be a JSON object.")
                schema = SCHEMAS[name]["parameters"]
                if set(params) - set(schema["properties"]) or set(schema.get("required", [])) - set(params):
                    raise GatewayError("invalid_arguments", "Tool arguments contain missing or unsupported fields.")
                result = operation(client_factory(), params)
                return json.dumps({"ok": True, "result": result}, ensure_ascii=False)
            except GatewayError as exc:
                return json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}})
        return handler

    def receipt(client, params):
        request_id = params.get("request_id", "")
        if not isinstance(request_id, str) or re.fullmatch(r"req_[a-f0-9]{16}", request_id) is None:
            raise GatewayError("invalid_request_id", "Provide the request ID returned by tavrel_purchase.")
        return client.request("GET", "/v1/agent/requests/" + request_id)

    def status(client, params):
        return client.request("GET", "/v1/agent/status")

    def purchase(client, params):
        return client.request("POST", "/v1/agent/requests", {"service": params["service"], "payload": {"query": params["query"]}, "request_key": params["request_key"]})

    def payment_receipt(client, params):
        payment_id = params.get("payment_id", "")
        if not isinstance(payment_id, str) or re.fullmatch(r"pay_[a-f0-9]{16}", payment_id) is None:
            raise GatewayError("invalid_payment_id", "Provide the payment ID returned by Tavrel.")
        return client.request("GET", "/v1/agent/payments/" + payment_id)

    return {
        "tavrel_status": wrap("tavrel_status", status),
        "tavrel_purchase": wrap("tavrel_purchase", purchase),
        "tavrel_receipt": wrap("tavrel_receipt", receipt),
        "tavrel_payment_status": wrap("tavrel_payment_status", lambda client, params: client.request("GET", "/v1/agent/payments/status")),
        "tavrel_prepare_payment": wrap("tavrel_prepare_payment", lambda client, params: client.request("POST", "/v1/agent/payments/prepare", params)),
        "tavrel_payment_intent": wrap("tavrel_payment_intent", payment_receipt),
        "tavrel_payment_task": wrap("tavrel_payment_task", lambda client, params: client.request("POST", "/v1/agent/payments/task", params)),
    }


SCHEMAS = {
    "tavrel_payment_status": {
        "name": "tavrel_payment_status",
        "description": "Read the bound task's native zkVerify Volta tVFY payment policy, approved recipients, and exact-unit holds. tVFY is a test token, not a stablecoin. No signing or broadcast is enabled. Payment allowances are separate from API-cost allowances.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "tavrel_prepare_payment": {
        "name": "tavrel_prepare_payment",
        "description": "Prepare an exact native tVFY transfer intent through deterministic recipient and budget checks. Use an operator-approved recipient name or valid native Substrate address. Amount is a decimal string with at most 18 places. The operator approves and exports separately. Ready or exported does not mean paid. Reuse the exact request key and arguments on retries.",
        "parameters": {"type": "object", "properties": {
            "recipient": {"type": "string"}, "amount": {"type": "string"},
            "purpose": {"type": "string", "minLength": 1, "maxLength": 1000},
            "request_key": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,100}$"}},
            "required": ["recipient", "amount", "purpose", "request_key"], "additionalProperties": False},
    },
    "tavrel_payment_intent": {
        "name": "tavrel_payment_intent", "description": "Read one native payment intent within the bound task. An approval or unsigned call is not settlement evidence. This tool cannot approve, export, sign, or broadcast.",
        "parameters": {"type": "object", "properties": {"payment_id": {"type": "string"}}, "required": ["payment_id"], "additionalProperties": False},
    },
    "tavrel_payment_task": {
        "name": "tavrel_payment_task", "description": "Plan 1 to 20 native tVFY payments in order under the bound policy. Each receives an independent policy verdict and stable retry key; the batch is not an atomic payout. Reuse the task_key and ordered instructions exactly. This deterministic task executor invokes no language model and makes no transfers.",
        "parameters": {"type": "object", "properties": {
            "task_key": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,70}$"},
            "payments": {"type": "array", "minItems": 1, "maxItems": 20, "items": {
                "type": "object", "properties": {"recipient": {"type": "string"}, "amount": {"type": "string"}, "purpose": {"type": "string"}},
                "required": ["recipient", "amount", "purpose"], "additionalProperties": False}}},
            "required": ["task_key", "payments"], "additionalProperties": False},
    },
    "tavrel_status": {
        "name": "tavrel_status",
        "description": "Read the bound Tavrel task's allowance, held reservations, policy, recent requests, and service catalog. Check each service's billing mode: the gateway supports free public APIs or an explicit simulation. Native Hermes model billing is outside its coverage.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "tavrel_purchase": {
        "name": "tavrel_purchase",
        "description": "Request a connected service through Tavrel's deterministic budget gateway. Read tavrel_status first for the current catalog and billing mode. Free mode provides real GitHub repository search, Crossref publication metadata, and local text extraction. Simulation returns labeled fixtures. Paid execution is disabled. The gateway may require operator approval even for free requests. Reuse the SAME request_key and exact arguments for retries. Read pending or uncertain state with tavrel_receipt; only the operator can approve or reconcile it. Report success only when status is settled and output exists.",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "enum": ["search_brief", "research_report", "summary"], "description": "In free mode: search_brief searches GitHub repositories; research_report retrieves Crossref publication metadata; summary extracts three sentences locally. Check the catalog because simulation uses different fixtures."},
                "query": {"type": "string", "minLength": 1, "maxLength": 4000, "description": "The exact query or text to send to this service."},
                "request_key": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,100}$", "description": "A stable operation identifier; keep it unchanged when retrying the same purchase."},
            },
            "required": ["service", "query", "request_key"],
            "additionalProperties": False,
        },
    },
    "tavrel_receipt": {
        "name": "tavrel_receipt",
        "description": "Read one request's status, exact input, reserved maximum, billing mode, result, and evidence. Restricted to the configured task. A reconciled cost is an operator attestation, not a verified service result. This cannot approve or reconcile requests or retry uncertain work.",
        "parameters": {"type": "object", "properties": {"request_id": {"type": "string", "description": "Request ID returned by tavrel_purchase."}}, "required": ["request_id"], "additionalProperties": False},
    },
}


def register(ctx):
    handlers = make_handlers()
    for name, schema in SCHEMAS.items():
        ctx.register_tool(name=name, toolset="tavrel", schema=schema, handler=handlers[name])

    def budget_command(args="", **kwargs):
        del args, kwargs
        response = json.loads(handlers["tavrel_status"]({}))
        if not response["ok"]:
            return response["error"]["message"]
        task = response["result"]["task"]
        spend_label = "simulated spend" if response["result"]["mode"] == "simulation" else "recorded cost"
        approval = "Approval required before every request." if task.get("require_approval") else f"Approval required above ${task['threshold_cents'] / 100:.2f}."
        return (
            f"Tavrel: {task['name']}\n"
            f"Allowance ${task['limit_cents'] / 100:.2f}; {spend_label} ${task['spent_cents'] / 100:.2f}; "
            f"held ${task['reserved_cents'] / 100:.2f}; available ${task['available_cents'] / 100:.2f}.\n"
            f"{approval} "
            "Only connected Tavrel services are covered. Operator approval happens outside the agent."
        )

    ctx.register_command("budget", budget_command, "Show the current Tavrel task allowance, recorded costs, and approval policy.")

