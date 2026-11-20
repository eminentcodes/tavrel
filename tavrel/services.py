"""Shared service receipt and failure types. Execution adapters use real sources."""

from dataclasses import dataclass
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
