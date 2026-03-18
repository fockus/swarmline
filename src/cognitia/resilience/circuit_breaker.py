"""CircuitBreaker - protection from cascading MCP failures (architecture section 13).

One breaker per server_id.
States: CLOSED -> OPEN -> HALF_OPEN -> CLOSED (or back to OPEN).
"""

from __future__ import annotations

import enum
import time


class CircuitState(enum.Enum):
    """Circuit breaker state."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Rejects requests
    HALF_OPEN = "half_open"  # One probe attempt


class CircuitBreaker:
    """Circuit breaker for a single MCP server.

    - failure_threshold: number of consecutive failures before opening
    - cooldown_seconds: time spent in OPEN before transitioning to HALF_OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        """Current breaker state."""
        return self._state

    def allow_request(self) -> bool:
        """Allow the request? If OPEN and cooldown has elapsed -> HALF_OPEN."""
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._cooldown:
                self._state = CircuitState.HALF_OPEN
                return True
            return False

        # HALF_OPEN - allow one probe attempt
        return True

    def record_success(self) -> None:
        """Record a successful call."""
        self._consecutive_failures = 0
        if self._state in (CircuitState.HALF_OPEN, CircuitState.CLOSED):
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failure."""
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # Probe failed - back to OPEN
            self._state = CircuitState.OPEN
            return

        if self._consecutive_failures >= self._threshold:
            self._state = CircuitState.OPEN


class CircuitBreakerRegistry:
    """Registry of circuit breakers per server_id."""

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, server_id: str) -> CircuitBreaker:
        """Get or create a breaker for the server."""
        if server_id not in self._breakers:
            self._breakers[server_id] = CircuitBreaker(
                failure_threshold=self._threshold,
                cooldown_seconds=self._cooldown,
            )
        return self._breakers[server_id]
