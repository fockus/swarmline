"""Integration: CircuitBreaker + ToolPolicy + ModelPolicy - resilience workflow. Scenario: MCP-server fails -> circuit breaker otkryvaetsya ->
model escalation from-za tool failures.
"""

import time

from swarmline.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
)
from swarmline.runtime.model_policy import ModelPolicy
import pytest

pytestmark = pytest.mark.integration


class TestCircuitBreakerEscalation:
    """Otkazy MCP -> circuit breaker + model escalation."""

    def test_failures_open_circuit_and_escalate_model(self) -> None:
        """3 otkaza -> circuit open -> model escalation."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        policy = ModelPolicy(escalate_on_tool_failures=3)

        # Simuliruem 3 otkaza ISS MCP
        tool_failures = 0
        for _ in range(3):
            cb.record_failure()
            tool_failures += 1

        # Circuit otkryt
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

        # Model escalation
        model = policy.select("coach", tool_failure_count=tool_failures)
        assert model == "opus"

    def test_recovery_after_cooldown(self) -> None:
        """Posle cooldown circuit -> HALF_OPEN -> uspeshnyy query -> CLOSED."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.01)

        # Otkryvaem circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait cooldown
        time.sleep(0.02)

        # Probuem query - perehod in HALF_OPEN
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

        # Uspeshnyy query - zakryvaem circuit
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self) -> None:
        """Notudacha in HALF_OPEN -> obratno in OPEN."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.01)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        cb.allow_request()  # HALF_OPEN
        cb.record_failure()  # Snova OPEN
        assert cb.state == CircuitState.OPEN


class TestRegistryWithMultipleServers:
    """Registry: notzavisimye breakers for raznyh serverov."""

    def test_independent_circuits(self) -> None:
        """Kazhdyy server_id imeet svoy circuit breaker."""
        registry = CircuitBreakerRegistry(failure_threshold=2, cooldown_seconds=60)

        iss_cb = registry.get("iss")
        fin_cb = registry.get("finuslugi")

        # ISS fails
        iss_cb.record_failure()
        iss_cb.record_failure()

        # ISS zakryt, finuslugi otkryt
        assert iss_cb.state == CircuitState.OPEN
        assert fin_cb.state == CircuitState.CLOSED
        assert fin_cb.allow_request() is True

    def test_registry_returns_same_instance(self) -> None:
        """get() returns odin and tot zhe breaker for odnogo server_id."""
        registry = CircuitBreakerRegistry()
        cb1 = registry.get("iss")
        cb2 = registry.get("iss")
        assert cb1 is cb2

    def test_registry_creates_distinct_breakers(self) -> None:
        """Kazhdyy get() for novogo server_id sozdaet otdelnyy breaker."""
        registry = CircuitBreakerRegistry()
        iss = registry.get("iss")
        fin = registry.get("finuslugi")
        funds = registry.get("funds")
        assert iss is not fin
        assert fin is not funds
