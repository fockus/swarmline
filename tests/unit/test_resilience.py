"""Tests for CircuitBreaker and retry (architecture section 13). CircuitBreaker per server_id:
- closed -> half_open -> open
- opens after N consecutive failures
- closes after cooldown + successful probe"""

import time

from swarmline.resilience.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreaker:
    """CircuitBreaker — per server_id."""

    def test_initial_state_closed(self) -> None:
        """The initial state is CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=5)
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_on_success(self) -> None:
        """Successful calls do not change state."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=5)
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self) -> None:
        """OPEN after N consecutive errors."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=5)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_rejects_calls(self) -> None:
        """In the OPEN state - allow_request() = False."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow_request() is False

    def test_half_open_after_cooldown(self) -> None:
        """After cooldown -> HALF_OPEN, one attempt is allowed."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # Wait cooldown
        time.sleep(0.15)
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self) -> None:
        """Success in HALF_OPEN -> CLOSED."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.allow_request()  # Go to HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self) -> None:
        """Error in HALF_OPEN -> OPEN again."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.allow_request()  # → HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self) -> None:
        """Success resets the error counter."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=5)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # Reset
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # 1 error, not 3


class TestCircuitBreakerRegistry:
    """Registry breakers per server_id."""

    def test_get_or_create(self) -> None:
        """Get or create breaker for server_id."""
        from swarmline.resilience.circuit_breaker import CircuitBreakerRegistry

        registry = CircuitBreakerRegistry(failure_threshold=3, cooldown_seconds=5)
        cb1 = registry.get("iss")
        cb2 = registry.get("iss")
        assert cb1 is cb2  # Same object

    def test_different_servers(self) -> None:
        """Different servers - different breakers."""
        from swarmline.resilience.circuit_breaker import CircuitBreakerRegistry

        registry = CircuitBreakerRegistry(failure_threshold=3, cooldown_seconds=5)
        cb_iss = registry.get("iss")
        cb_funds = registry.get("funds")
        assert cb_iss is not cb_funds
