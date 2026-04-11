"""Unit tests for retry policy — Phase 7D.

Tests for ExponentialBackoff, ModelFallbackChain, ProviderFallback,
RetryPolicy protocol compliance, and integration with RuntimeConfig/RUNTIME_ERROR_KINDS.
"""

from __future__ import annotations

from swarmline.retry import (
    ExponentialBackoff,
    ModelFallbackChain,
    ProviderFallback,
    RetryPolicy,
)
from swarmline.runtime.types import RUNTIME_ERROR_KINDS, RuntimeConfig


# ---------------------------------------------------------------------------
# ExponentialBackoff
# ---------------------------------------------------------------------------


class TestExponentialBackoff:
    """ExponentialBackoff unit tests."""

    def test_should_retry_within_max_retries_returns_true(self) -> None:
        policy = ExponentialBackoff(max_retries=3, jitter=False)
        should, delay = policy.should_retry(RuntimeError("fail"), attempt=0)
        assert should is True
        assert delay > 0

    def test_should_retry_at_max_retries_returns_false(self) -> None:
        policy = ExponentialBackoff(max_retries=3)
        should, delay = policy.should_retry(RuntimeError("fail"), attempt=3)
        assert should is False
        assert delay == 0.0

    def test_should_retry_above_max_retries_returns_false(self) -> None:
        policy = ExponentialBackoff(max_retries=2)
        should, delay = policy.should_retry(RuntimeError("fail"), attempt=5)
        assert should is False
        assert delay == 0.0

    def test_delay_capped_at_max_delay(self) -> None:
        policy = ExponentialBackoff(
            max_retries=10, base_delay=10.0, max_delay=30.0, jitter=False
        )
        # attempt=5 -> 10 * 2^5 = 320, capped to 30
        _, delay = policy.should_retry(RuntimeError("fail"), attempt=5)
        assert delay == 30.0

    def test_jitter_varies_delay(self) -> None:
        policy = ExponentialBackoff(max_retries=5, base_delay=10.0, jitter=True)
        delays = set()
        for _ in range(20):
            _, delay = policy.should_retry(RuntimeError("fail"), attempt=1)
            delays.add(round(delay, 4))
        # With jitter, we expect at least a few different values
        assert len(delays) > 1

    def test_no_jitter_deterministic_delay(self) -> None:
        policy = ExponentialBackoff(max_retries=5, base_delay=2.0, jitter=False)
        _, delay0 = policy.should_retry(RuntimeError("fail"), attempt=0)
        _, delay1 = policy.should_retry(RuntimeError("fail"), attempt=1)
        _, delay2 = policy.should_retry(RuntimeError("fail"), attempt=2)
        assert delay0 == 2.0  # 2 * 2^0 = 2
        assert delay1 == 4.0  # 2 * 2^1 = 4
        assert delay2 == 8.0  # 2 * 2^2 = 8

    def test_default_values(self) -> None:
        policy = ExponentialBackoff()
        assert policy.max_retries == 3
        assert policy.base_delay == 1.0
        assert policy.max_delay == 60.0
        assert policy.jitter is True


# ---------------------------------------------------------------------------
# ModelFallbackChain
# ---------------------------------------------------------------------------


class TestModelFallbackChain:
    """ModelFallbackChain unit tests."""

    def test_next_model_returns_next_in_chain(self) -> None:
        chain = ModelFallbackChain(models=["gpt-4o", "claude-sonnet", "gemini-pro"])
        assert chain.next_model("gpt-4o") == "claude-sonnet"
        assert chain.next_model("claude-sonnet") == "gemini-pro"

    def test_next_model_at_end_returns_none(self) -> None:
        chain = ModelFallbackChain(models=["gpt-4o", "claude-sonnet"])
        assert chain.next_model("claude-sonnet") is None

    def test_next_model_unknown_model_returns_none(self) -> None:
        chain = ModelFallbackChain(models=["gpt-4o", "claude-sonnet"])
        assert chain.next_model("unknown-model") is None

    def test_empty_chain_returns_none(self) -> None:
        chain = ModelFallbackChain(models=[])
        assert chain.next_model("anything") is None


# ---------------------------------------------------------------------------
# ProviderFallback
# ---------------------------------------------------------------------------


class TestProviderFallback:
    """ProviderFallback unit tests."""

    def test_has_fallback_model(self) -> None:
        fb = ProviderFallback(fallback_model="openai:gpt-4o")
        assert fb.fallback_model == "openai:gpt-4o"

    def test_default_empty_fallback(self) -> None:
        fb = ProviderFallback()
        assert fb.fallback_model == ""


# ---------------------------------------------------------------------------
# RetryPolicy protocol compliance
# ---------------------------------------------------------------------------


class TestRetryPolicyProtocol:
    """Verify that implementations satisfy RetryPolicy protocol."""

    def test_exponential_backoff_is_retry_policy(self) -> None:
        policy = ExponentialBackoff()
        assert isinstance(policy, RetryPolicy)

    def test_custom_implementation_satisfies_protocol(self) -> None:
        class CustomRetry:
            def should_retry(self, error: Exception, attempt: int) -> tuple[bool, float]:
                return False, 0.0

        assert isinstance(CustomRetry(), RetryPolicy)


# ---------------------------------------------------------------------------
# RuntimeConfig integration
# ---------------------------------------------------------------------------


class TestRuntimeConfigRetryPolicy:
    """RuntimeConfig.retry_policy field tests."""

    def test_runtime_config_has_retry_policy_field(self) -> None:
        cfg = RuntimeConfig(runtime_name="thin")
        assert cfg.retry_policy is None

    def test_runtime_config_accepts_retry_policy(self) -> None:
        policy = ExponentialBackoff(max_retries=5)
        cfg = RuntimeConfig(runtime_name="thin", retry_policy=policy)
        assert cfg.retry_policy is policy
        assert cfg.retry_policy.max_retries == 5


# ---------------------------------------------------------------------------
# RUNTIME_ERROR_KINDS
# ---------------------------------------------------------------------------


class TestRuntimeErrorKinds:
    """Verify 'retry' is in RUNTIME_ERROR_KINDS."""

    def test_retry_in_error_kinds(self) -> None:
        assert "retry" in RUNTIME_ERROR_KINDS
