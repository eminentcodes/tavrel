"""Task-scoped Tavrel HTTP client using the Python standard library."""

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
