"""Этап 25c fix-cycle 1 MINOR — harden `run_buffered_llm_call`'s retry loop against a
misbehaving injectable `retry_policy`.

`run_buffered_llm_call` blindly trusts whatever `(should_retry, delay)` the injected
policy returns. A buggy/malicious/misconfigured policy that returns a non-finite delay
(NaN/inf) or a negative delay, or that always says "retry", can turn one caller's retry
loop into a tight loop hammering the provider — the same class of defect Этап 25c itself
exists to prevent, just one level further down the trust chain (the retry seam we
opened must defend itself against its own extension point).
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from swarmline.runtime.thin.errors import ThinLlmError, provider_runtime_crash
from swarmline.runtime.thin.llm_client import run_buffered_llm_call


class _NonFiniteDelayPolicy:
    """Always says "retry", but with a NaN or +inf delay — must fail CLOSED (no retry)."""

    def __init__(self, delay: float) -> None:
        self._delay = delay
        self.calls: list[int] = []

    def should_retry(self, error: Exception, attempt: int) -> tuple[bool, float]:  # noqa: ARG002
        self.calls.append(attempt)
        return True, self._delay


class _NegativeDelayPolicy:
    """Always says "retry" with a negative delay — must clamp to 0, not sleep negative."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def should_retry(self, error: Exception, attempt: int) -> tuple[bool, float]:  # noqa: ARG002
        self.calls.append(attempt)
        return True, -5.0


class _AlwaysRetryPolicy:
    """Never stops retrying (no max_retries of its own) — the hard cap must save us."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def should_retry(self, error: Exception, attempt: int) -> tuple[bool, float]:  # noqa: ARG002
        self.calls.append(attempt)
        return True, 0.0


async def _always_fail_llm_call(*_args: Any, **_kwargs: Any) -> str:
    raise provider_runtime_crash("anthropic", TimeoutError("always times out"))


class TestRetryLoopGuardsAgainstMisbehavingPolicy:
    async def test_nan_delay_fails_closed_no_retry(self) -> None:
        policy = _NonFiniteDelayPolicy(delay=math.nan)

        with pytest.raises(ThinLlmError):
            await run_buffered_llm_call(
                _always_fail_llm_call, [], "hello", retry_policy=policy
            )

        assert len(policy.calls) == 1, (
            "a NaN delay must not be retried — exactly one should_retry() call, then raise"
        )

    async def test_infinite_delay_fails_closed_no_retry(self) -> None:
        policy = _NonFiniteDelayPolicy(delay=math.inf)

        with pytest.raises(ThinLlmError):
            await run_buffered_llm_call(
                _always_fail_llm_call, [], "hello", retry_policy=policy
            )

        assert len(policy.calls) == 1

    async def test_negative_delay_is_clamped_not_rejected(self) -> None:
        """A negative delay is a "sleep for 0" bug, not "never retry" — clamp, don't fail closed."""
        policy = _NegativeDelayPolicy()

        call_count = 0

        async def flaky(*_args: Any, **_kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise provider_runtime_crash("anthropic", TimeoutError("timeout"))
            return "recovered"

        result = await run_buffered_llm_call(flaky, [], "hello", retry_policy=policy)

        assert result.raw == "recovered"
        assert call_count == 2
        assert len(policy.calls) == 1

    async def test_always_retry_policy_stops_at_hard_cap(self) -> None:
        """A policy with no max_retries of its own must still terminate — a hard cap
        independent of the injected policy is the last line of defense."""
        policy = _AlwaysRetryPolicy()

        with pytest.raises(ThinLlmError):
            await run_buffered_llm_call(
                _always_fail_llm_call, [], "hello", retry_policy=policy
            )

        assert len(policy.calls) <= 10, (
            f"hard cap must bound retries regardless of policy, got {len(policy.calls)} calls"
        )
        assert len(policy.calls) > 0
