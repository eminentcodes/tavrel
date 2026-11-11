"""Real, unauthenticated research APIs. No payment or credential path exists."""

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from http.client import HTTPException
from html.parser import HTMLParser
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .services import ProviderRejected, Receipt


PUBLIC_APIS = {
    "GitHub public API": ("api.github.com", "/search/repositories"),
    "Crossref public API": ("api.crossref.org", "/works"),
}
MAX_RESPONSE_BYTES = 1_048_576


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


@lru_cache(maxsize=1)
def public_opener():
    return build_opener(NoRedirect)


def public_json(url, provider):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.port in (None, 443)
                 and not parsed.username and not parsed.password and not parsed.fragment
                 and (parsed.hostname, parsed.path) == PUBLIC_APIS.get(provider))
    except ValueError:
        valid = False
    if not valid:
        raise ProviderRejected("This endpoint is not an approved free public API. No request was sent.")
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Tavrel/0.2 (public research; no authentication)"})
    try:
        with public_opener().open(request, timeout=12) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ProviderRejected("The free provider response exceeded the supported size; no charge occurred.")
            if response.status != 200:
                raise ProviderRejected("The free provider returned an unsupported response status. No charge occurred.")
            value = json.loads(raw.decode("utf-8"), parse_constant=invalid_constant)
            evidence = {
                "kind": "http_response", "provider": provider,
                "reference": response.headers.get("X-GitHub-Request-Id") or "sha256:" + hashlib.sha256(raw).hexdigest(),
                "endpoint": url, "http_status": response.status,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "billing": "free", "charge_cents": 0,
                "note": "Unauthenticated public API retrieval. No payment or model call was made.",
            }
            return value, evidence
    except HTTPError as exc:
        try:
            if exc.code == 429 or (exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0"):
                message = "The free provider rate limit was reached. Try a new request later."
            elif 300 <= exc.code < 400:
                message = "The free provider redirected the request; redirects are disabled."
            else:
                message = f"The free provider returned HTTP {exc.code}."
            raise ProviderRejected(message + " No charge occurred.") from None
        finally:
            exc.close()
    except (URLError, TimeoutError, OSError, HTTPException):
        raise ProviderRejected("The free provider could not be reached. No charge occurred; try a new request later.") from None
    except (ValueError, UnicodeDecodeError):
        raise ProviderRejected("The free provider returned an invalid JSON response. No charge occurred.") from None


def invalid_constant(value):
    raise ValueError("Non-finite JSON number: " + value)


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value, maximum=3000):
    if not isinstance(value, str):
        return ""
    parser = TextOnly()
    parser.feed(value[:20_000])
    return " ".join(" ".join(parser.parts).split())[:maximum]


def repository_source(item):
    if (not isinstance(item, dict) or not isinstance(item.get("full_name"), str)
            or not item["full_name"].strip() or not isinstance(item.get("html_url"), str)):
        raise ProviderRejected("GitHub returned incomplete repository data. No charge occurred.")
    license_info = item.get("license")
    stars = item.get("stargazers_count")
    return {
        "title": item["full_name"], "url": item["html_url"],
        "description": plain(item.get("description")),
        "stars": stars if type(stars) is int and stars >= 0 else None,
        "language": plain(item.get("language"), 100) or None,
        "updated_at": plain(item.get("updated_at"), 100) or None,
        "license": plain(license_info.get("spdx_id"), 100) or None if isinstance(license_info, dict) else None,
    }


def publication_source(item):
    if (not isinstance(item, dict) or not isinstance(item.get("DOI"), str)
            or not item["DOI"].strip() or not isinstance(item.get("title"), list)
            or not item["title"] or not plain(item["title"][0])):
        raise ProviderRejected("Crossref returned incomplete publication data. No charge occurred.")
    authors = item.get("author")
    names = []
    if isinstance(authors, list):
        for author in authors[:8]:
            if isinstance(author, dict):
                name = " ".join(part for part in (plain(author.get("given"), 100), plain(author.get("family"), 100)) if part)
                if name:
                    names.append(name)
    published = item.get("published") or item.get("issued")
    date_parts = published.get("date-parts") if isinstance(published, dict) else None
    return {
        "title": plain(item["title"][0]), "url": "https://doi.org/" + quote(item["DOI"], safe="/"),
        "doi": item["DOI"], "publisher": plain(item.get("publisher")),
        "authors": names, "published": date_parts if isinstance(date_parts, list) else None,
        "abstract": plain(item.get("abstract")) or None,
    }


@dataclass(frozen=True)
class FreeService:
    id: str
    name: str
    description: str
    provider: str
    price_cents: int = 0

    def public(self):
        return {"id": self.id, "name": self.name, "description": self.description,
                "provider": self.provider, "price_cents": 0, "billing": "free",
                "fixed_price": True, "network_access": self.id != "summary"}

    def execute(self, payload, request_id):
        query = payload["query"].strip()
        if self.id == "search_brief":
            url = "https://api.github.com/search/repositories?" + urlencode({"q": query, "per_page": 5})
            value, evidence = public_json(url, self.provider)
            if not isinstance(value, dict) or not isinstance(value.get("items"), list):
                raise ProviderRejected("GitHub returned an unexpected search response. No charge occurred.")
            sources = [repository_source(item) for item in value["items"][:5]]
            output = {"title": "Repository research", "query": query, "sources": sources,
                      "total_results": value.get("total_count"), "incomplete_results": value.get("incomplete_results", False),
                      "summary": f"Retrieved {len(sources)} repository matches from GitHub. Descriptions and counts are provider data, not a generated comparison.",
                      "simulated": False}
        elif self.id == "research_report":
            url = "https://api.crossref.org/works?" + urlencode({"query": query, "rows": 5, "filter": "type:journal-article"})
            value, evidence = public_json(url, self.provider)
            message = value.get("message") if isinstance(value, dict) else None
            if not isinstance(message, dict) or not isinstance(message.get("items"), list):
                raise ProviderRejected("Crossref returned an unexpected research response. No charge occurred.")
            sources = [publication_source(item) for item in message["items"][:5]]
            output = {"title": "Publication research digest", "query": query, "sources": sources,
                      "total_results": message.get("total-results"),
                      "summary": f"Retrieved {len(sources)} publications from Crossref. Abstracts are included only where the publisher supplied them. Full texts were not retrieved.",
                      "simulated": False}
        elif self.id == "summary":
            sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", query) if part.strip()]
            output = {"title": "Extractive text summary", "query": query, "summary": " ".join(sentences[:3]),
                      "method": "First three sentences, extracted locally without a language model.", "simulated": False}
            evidence = {"kind": "local_processing", "provider": self.provider,
                        "reference": "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest(),
                        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "billing": "free", "charge_cents": 0,
                        "note": "Local text extraction; no external API or model call."}
        else:
            raise ProviderRejected("This free service is unsupported. No charge occurred.")
        return Receipt(0, output, evidence)


FREE_SERVICES = {service.id: service for service in (
    FreeService("search_brief", "Repository search", "Search public GitHub repositories and retrieve real descriptions, stars, and source links.", "GitHub public API"),
    FreeService("research_report", "Publication research", "Retrieve real publications, DOIs, authors, and available abstracts from Crossref.", "Crossref public API"),
    FreeService("summary", "Local text summary", "Extract the first three sentences locally; no model or network call.", "Local text processor"),
)}
