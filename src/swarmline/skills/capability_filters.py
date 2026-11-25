"""Pluggable filters for gating CapabilityDoc candidates.

REQ-OSS-051: no product coupling — policy is injected at the caller layer.
`RuntimeFilter` and `AvailabilityFilter` are concrete default implementations;
consumers may supply any callable or subclass for custom gating logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from swarmline.skills.capability import CapabilityDoc


@dataclass(slots=True, frozen=True)
class FilterResult:
    """Decision produced by a capability filter gate."""

    allowed: bool
    reason: str
    details: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class CapabilityFilter(Protocol):
    """Pluggable gate protocol for capability candidates.

    Implementations may be stateless (AvailabilityFilter) or
    stateful / context-carrying (RuntimeFilter).
    """

    def evaluate(self, capability: CapabilityDoc) -> FilterResult:
        """Return a FilterResult describing whether the capability passes."""
        ...


class RuntimeFilter:
    """Gate based on runtime compatibility and required-capabilities list.

    Constructed with the *active* runtime name and the set of capabilities
    the current environment can provide (e.g. ``{"mcp", "filesystem"}``).
    Pluggable: subclass or replace with any callable that returns FilterResult.
    """

    def __init__(
        self,
        available_runtime: str,
        available_capabilities: set[str] | None = None,
    ) -> None:
        self._runtime = available_runtime
        self._caps: set[str] = available_capabilities or set()

    def evaluate(self, capability: CapabilityDoc) -> FilterResult:
        missing = [c for c in capability.required_capabilities if c not in self._caps]
        runtime_match = self._runtime in capability.runtime_allow
        allowed = (not missing) and runtime_match
        reason = "runtime_allowed" if allowed else "runtime_unavailable"
        return FilterResult(
            allowed=allowed,
            reason=reason,
            details={"missing": missing, "runtime_match": runtime_match},
        )


class AvailabilityFilter:
    """Gate based solely on the ``enabled`` flag — stateless."""

    def evaluate(self, capability: CapabilityDoc) -> FilterResult:
        allowed = capability.enabled
        return FilterResult(
            allowed=allowed,
            reason="available" if allowed else "disabled",
            details={"missing": [] if allowed else ["disabled"]},
        )
