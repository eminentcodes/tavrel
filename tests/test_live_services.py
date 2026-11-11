"""Behavioral checks of free API contracts; every response fixture stays local."""

import hashlib
from http.client import HTTPException
from io import BytesIO
import json
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from tavrel.live_services import FREE_SERVICES, MAX_RESPONSE_BYTES, public_json
from tavrel.services import ProviderRejected


GITHUB_URL = "https://api.github.com/search/repositories?q=agents&per_page=5"


class HTTPResponse(BytesIO):
    status = 200

    def __init__(self, raw, headers=None):
        super().__init__(raw)
        self.headers = headers or {}


class PublicAPITests(TestCase):
    def test_http_receipt_fingerprints_original_bytes_without_credentials(self):
        raw = b'{"items":[],"total_count":0}'
        response = HTTPResponse(raw, {"X-GitHub-Request-Id": "public-request-123"})
        opener = Mock()
        opener.open.return_value = response
        with patch("tavrel.live_services.public_opener", return_value=opener):
            value, evidence = public_json(GITHUB_URL, "GitHub public API")
        self.assertEqual(value["items"], [])
        self.assertEqual(evidence["response_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(evidence["reference"], "public-request-123")
        self.assertEqual(evidence["endpoint"], GITHUB_URL)
        self.assertEqual((evidence["billing"], evidence["charge_cents"]), ("free", 0))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertNotIn("authorization", {key.lower() for key in request.headers})
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 12)
        self.assertTrue(response.closed)

    def test_unapproved_origins_paths_and_redirect_targets_never_send_request(self):
        urls = (
            "http://api.github.com/search/repositories?q=agents",
            "https://example.com/search/repositories",
            "https://api.github.com/user",
            "https://api.github.com:444/search/repositories",
            "https://api.github.com:invalid/search/repositories",
            "https://name:secret@api.github.com/search/repositories",
            GITHUB_URL + "#fragment",
            "https://api.github.com.evil.example/search/repositories",
        )
        with patch("tavrel.live_services.public_opener") as opener:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ProviderRejected):
                    public_json(url, "GitHub public API")
            with self.assertRaises(ProviderRejected):
                public_json(GITHUB_URL, "Unknown provider")
        opener.assert_not_called()

    def test_rate_limits_redirects_and_http_failures_close_the_response(self):
        for status, headers, expected in (
            (429, {}, "rate limit"),
            (403, {"X-RateLimit-Remaining": "0"}, "rate limit"),
            (302, {"Location": "https://example.com/paid"}, "redirect"),
            (503, {}, "HTTP 503"),
        ):
            with self.subTest(status=status):
                stream = BytesIO(b"provider error")
                error = HTTPError(GITHUB_URL, status, "error", headers, stream)
                opener = Mock()
                opener.open.side_effect = error
                with patch("tavrel.live_services.public_opener", return_value=opener):
                    with self.assertRaisesRegex(ProviderRejected, expected):
                        public_json(GITHUB_URL, "GitHub public API")
                self.assertTrue(stream.closed)
                self.assertEqual(opener.open.call_count, 1)

    def test_invalid_oversized_and_nonfinite_json_is_rejected_as_no_charge(self):
        for raw in (b"not json", b"\xff", b'{"items":NaN}', b"x" * (MAX_RESPONSE_BYTES + 1)):
            with self.subTest(size=len(raw)):
                response = HTTPResponse(raw)
                opener = Mock()
                opener.open.return_value = response
                with patch("tavrel.live_services.public_opener", return_value=opener):
                    with self.assertRaisesRegex(ProviderRejected, "no charge|No charge"):
                        public_json(GITHUB_URL, "GitHub public API")
                self.assertTrue(response.closed)

    def test_free_transport_failure_does_not_claim_a_charge_or_success(self):
        for error in (URLError("offline"), TimeoutError(), OSError(), HTTPException()):
            with self.subTest(error=type(error).__name__):
                opener = Mock()
                opener.open.side_effect = error
                with patch("tavrel.live_services.public_opener", return_value=opener):
                    with self.assertRaisesRegex(ProviderRejected, "No charge"):
                        public_json(GITHUB_URL, "GitHub public API")

    def test_repository_search_preserves_provider_fields_and_bounds_matches(self):
        item = {"full_name": "example/agent", "html_url": "https://github.com/example/agent",
                "description": "A <b>public</b> agent &amp; tools.", "stargazers_count": 12,
                "language": "Python", "updated_at": "2026-11-10T00:00:00Z",
                "license": {"spdx_id": "MIT"}}
        evidence = {"kind": "http_response", "billing": "free", "charge_cents": 0}
        with patch("tavrel.live_services.public_json", return_value=(
                {"items": [item] * 8, "total_count": 12, "incomplete_results": False}, evidence)) as fetch:
            receipt = FREE_SERVICES["search_brief"].execute({"query": "agent & tools"}, "req_test")
        self.assertEqual(receipt.cost_cents, 0)
        self.assertFalse(receipt.output["simulated"])
        self.assertEqual(len(receipt.output["sources"]), 5)
        self.assertEqual(receipt.output["sources"][0]["description"], "A public agent & tools.")
        self.assertEqual(receipt.output["sources"][0]["license"], "MIT")
        self.assertEqual(receipt.output["sources"][0]["stars"], 12)
        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)
        self.assertEqual(query["q"], ["agent & tools"])
        self.assertEqual(query["per_page"], ["5"])

    def test_publication_digest_uses_doi_and_supplied_metadata(self):
        item = {"DOI": "10.1234/example", "title": ["<i>Agent</i> research"],
                "author": [{"given": "Ada", "family": "Lovelace"}], "publisher": "Example Press",
                "published": {"date-parts": [[2026, 11, 10]]},
                "abstract": "<jats:p>Published abstract &amp; data.</jats:p>"}
        with patch("tavrel.live_services.public_json", return_value=(
                {"message": {"items": [item], "total-results": 1}}, {"billing": "free"})) as fetch:
            receipt = FREE_SERVICES["research_report"].execute({"query": "agent research"}, "req_test")
        source = receipt.output["sources"][0]
        self.assertEqual(source["title"], "Agent research")
        self.assertEqual(source["url"], "https://doi.org/10.1234/example")
        self.assertEqual(source["authors"], ["Ada Lovelace"])
        self.assertEqual(source["abstract"], "Published abstract & data.")
        self.assertEqual(receipt.cost_cents, 0)
        self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[0]).query)["rows"], ["5"])
        self.assertIn("Full texts were not retrieved", receipt.output["summary"])

    def test_missing_provider_metadata_cannot_become_a_successful_result(self):
        cases = (
            ("search_brief", {"items": [{}]}),
            ("search_brief", {"items": "not a list"}),
            ("research_report", {"message": {"items": [{}]}}),
            ("research_report", {"message": {"items": [{"DOI": "10.1234/example", "title": []}]}}),
        )
        for service, value in cases:
            with self.subTest(service=service, value=value):
                with patch("tavrel.live_services.public_json", return_value=(value, {"billing": "free"})):
                    with self.assertRaises(ProviderRejected):
                        FREE_SERVICES[service].execute({"query": "agents"}, "req_test")

    def test_local_summary_makes_no_network_call_and_identifies_its_method(self):
        text = "First sentence. Second sentence! Third sentence? Fourth sentence."
        with patch("tavrel.live_services.public_json") as fetch:
            receipt = FREE_SERVICES["summary"].execute({"query": text}, "req_test")
        fetch.assert_not_called()
        self.assertEqual(receipt.output["summary"], "First sentence. Second sentence! Third sentence?")
        self.assertFalse(receipt.output["simulated"])
        self.assertEqual(receipt.evidence["kind"], "local_processing")
        self.assertEqual(receipt.evidence["reference"], "sha256:" + hashlib.sha256(text.encode()).hexdigest())
        self.assertIn("without a language model", receipt.output["method"])
