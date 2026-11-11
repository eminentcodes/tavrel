"""Local fixed-price simulators. These never call or charge a remote provider."""

from dataclasses import dataclass
import re
from typing import Any


class ProviderRejected(Exception):
    """The provider confirms no billable work occurred."""


class UncertainCharge(Exception):
    """Work may have been billed; the reservation must stay held."""


@dataclass(frozen=True)
class Receipt:
    cost_cents: int
    output: dict[str, Any]
    evidence: dict[str, Any]


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    price_cents: int
    description: str
    icon: str

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "price_cents": self.price_cents,
            "description": self.description,
            "icon": self.icon,
            "provider": "Local simulator",
            "billing": "simulated",
            "fixed_price": True,
        }

    def execute(self, payload: dict[str, Any], request_id: str) -> Receipt:
        query = payload["query"]
        if self.id == "search_brief":
            output = {
                "title": "Search brief",
                "query": query,
                "summary": "A sample research result for the budget-control walkthrough. The sources below are illustrative links, not live search results.",
                "sources": [
                    {"title": "Hermes Agent documentation", "url": "https://hermes-agent.nousresearch.com/docs/", "note": "Persistent memory, tools, and plugin interfaces."},
                    {"title": "Hermes Agent repository", "url": "https://github.com/NousResearch/hermes-agent", "note": "Public source code and extension examples."},
                ],
                "simulated": True,
            }
        elif self.id == "research_report":
            output = {
                "title": "Research report",
                "query": query,
                "summary": "This simulated report demonstrates a larger purchase that requires an operator's approval. No research API was contacted.",
                "sections": [
                    {"heading": "Research scope", "body": query},
                    {"heading": "Suggested comparison", "body": "Compare features, integration effort, documented pricing, and the limits of each source."},
                    {"heading": "Next action", "body": "Verify the findings through a supported live research adapter before using them for a decision."},
                ],
                "simulated": True,
            }
        else:
            sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", query) if part.strip()]
            output = {"title": "Summary preview", "query": query, "summary": " ".join(sentences[:3]), "simulated": True}
        return Receipt(
            cost_cents=self.price_cents,
            output=output,
            evidence={"kind": "simulated", "provider": "Local simulator", "reference": f"sim_{request_id}", "note": "Synthetic receipt. No API charge or wallet payment occurred."},
        )


SERVICES = {
    service.id: service
    for service in (
        Service("search_brief", "Search brief", 24, "A small research request with illustrative sources.", "search"),
        Service("research_report", "Research report", 160, "A larger research purchase to demonstrate human approval.", "report"),
        Service("summary", "Summary preview", 8, "A local text preview to demonstrate smaller repeated calls.", "summary"),
    )
}

