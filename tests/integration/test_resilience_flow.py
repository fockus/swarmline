"""Integration: CircuitBreaker + ToolPolicy + ModelPolicy — resilience workflow.

Сценарий: MCP-сервер падает → circuit breaker открывается →
model escalation из-за tool failures.
"""

import time

from cognitia.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from cognitia.runtime.model_policy import ModelPolicy


class TestCircuitBreakerEscalation:
    """Отказы MCP → circuit breaker + model escalation."""

    def test_failures_open_circuit_and_escalate_model(self) -> None:
        """3 отказа → circuit open → model escalation."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        policy = ModelPolicy(escalate_on_tool_failures=3)

        # Симулируем 3 отказа ISS MCP
        tool_failures = 0
        for _ in range(3):
            cb.record_failure()
            tool_failures += 1

        # Circuit открыт
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

        # Model escalation
        model = policy.select("coach", tool_failure_count=tool_failures)
        assert model == "opus"

    def test_recovery_after_cooldown(self) -> None:
        """После cooldown circuit → HALF_OPEN → успешный запрос → CLOSED."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.01)

        # Открываем circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Ждём cooldown
        time.sleep(0.02)

        # Пробуем запрос — переход в HALF_OPEN
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

        # Успешный запрос — закрываем circuit
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self) -> None:
        """Неудача в HALF_OPEN → обратно в OPEN."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.01)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        cb.allow_request()  # HALF_OPEN
        cb.record_failure()  # Снова OPEN
        assert cb.state == CircuitState.OPEN


class TestRegistryWithMultipleServers:
    """Registry: независимые breakers для разных серверов."""

    def test_independent_circuits(self) -> None:
        """Каждый server_id имеет свой circuit breaker."""
        registry = CircuitBreakerRegistry(failure_threshold=2, cooldown_seconds=60)

        iss_cb = registry.get("iss")
        fin_cb = registry.get("finuslugi")

        # ISS падает
        iss_cb.record_failure()
        iss_cb.record_failure()

        # ISS закрыт, finuslugi открыт
        assert iss_cb.state == CircuitState.OPEN
        assert fin_cb.state == CircuitState.CLOSED
        assert fin_cb.allow_request() is True

    def test_registry_returns_same_instance(self) -> None:
        """get() возвращает один и тот же breaker для одного server_id."""
        registry = CircuitBreakerRegistry()
        cb1 = registry.get("iss")
        cb2 = registry.get("iss")
        assert cb1 is cb2

    def test_registry_creates_distinct_breakers(self) -> None:
        """Каждый get() для нового server_id создаёт отдельный breaker."""
        registry = CircuitBreakerRegistry()
        iss = registry.get("iss")
        fin = registry.get("finuslugi")
        funds = registry.get("funds")
        assert iss is not fin
        assert fin is not funds
