"""Result - unified request result for the Agent facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Result:
    """Immutable result of a query/stream request.

    ok=True if error is None (request succeeded).
    """

    text: str = ""
    session_id: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    structured_output: Any = None
    native_metadata: dict[str, Any] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True if the request completed without error."""
        return self.error is None
