"""Тесты для CircuitBreaker и retry (секция 13 архитектуры).

CircuitBreaker per server_id:
- closed → half_open → open
- opens after N consecutive failures
- closes after cooldown + successful probe
"""

import time

from cognitia.resilience.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreaker:
    """CircuitBreaker — per server_id."""

    def test_initial_state_closed(self) -> None:
        """Начальное состояние — CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=5)
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_on_success(self) -> None:
        """Успешные вызовы не меняют состояние."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=5)
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self) -> None:
        """OPEN после N последовательных ошибок."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=5)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_rejects_calls(self) -> None:
        """В состоянии OPEN — allow_request() = False."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow_request() is False

    def test_half_open_after_cooldown(self) -> None:
        """После cooldown → HALF_OPEN, одна попытка разрешена."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # Ждём cooldown
        time.sleep(0.15)
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self) -> None:
        """Успех в HALF_OPEN → CLOSED."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.allow_request()  # Переходим в HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self) -> None:
        """Ошибка в HALF_OPEN → снова OPEN."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.allow_request()  # → HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self) -> None:
        """Успех сбрасывает счётчик ошибок."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=5)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # Сброс
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # 1 ошибка, не 3


class TestCircuitBreakerRegistry:
    """Реестр breakers per server_id."""

    def test_get_or_create(self) -> None:
        """Получить или создать breaker для server_id."""
        from cognitia.resilience.circuit_breaker import CircuitBreakerRegistry

        registry = CircuitBreakerRegistry(failure_threshold=3, cooldown_seconds=5)
        cb1 = registry.get("iss")
        cb2 = registry.get("iss")
        assert cb1 is cb2  # Тот же объект

    def test_different_servers(self) -> None:
        """Разные серверы — разные breakers."""
        from cognitia.resilience.circuit_breaker import CircuitBreakerRegistry

        registry = CircuitBreakerRegistry(failure_threshold=3, cooldown_seconds=5)
        cb_iss = registry.get("iss")
        cb_funds = registry.get("funds")
        assert cb_iss is not cb_funds
