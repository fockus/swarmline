"""Structured helpers for security-relevant operator decisions."""

from __future__ import annotations

from typing import Any


def log_security_decision(
    logger: Any,
    *,
    component: str,
    event_name: str,
    reason: str,
    decision: str = "deny",
    target: str | None = None,
    route: str | None = None,
    url: str | None = None,
    **metadata: Any,
) -> None:
    """Emit a consistent structured log payload for security decisions."""
    payload: dict[str, Any] = {
        "event_name": event_name,
        "component": component,
        "decision": decision,
        "reason": reason,
    }
    if target is not None:
        payload["target"] = target
    if route is not None:
        payload["route"] = route
    if url is not None:
        payload["url"] = url[:200]
    payload.update(metadata)
    logger.warning("security_decision", **payload)
