"""Retry / Fallback Policy for LLM calls.

Provides pluggable retry strategies for ThinRuntime:
- ExponentialBackoff: retry with exponential backoff + jitter
- ModelFallbackChain: switch to next model on rate limit
- ProviderFallback: switch to alternative provider on outage
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class RetryPolicy(Protocol):
    """Decides whether to retry a failed LLM call."""

    def should_retry(self, error: Exception, attempt: int) -> tuple[bool, float]:
        """Returns (should_retry, delay_seconds).

        Args:
            error: The exception that caused the failure.
            attempt: Zero-based attempt number (0 = first retry candidate).

        Returns:
            Tuple of (should_retry, delay_in_seconds).
            If should_retry is False, delay is ignored.
        """
        ...


@dataclass(frozen=True)
class ExponentialBackoff:
    """Retry with exponential backoff + jitter.

    Delay formula: min(base_delay * 2^attempt, max_delay) * jitter_factor
    where jitter_factor is uniform(0.5, 1.5) if jitter=True, else 1.0.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: bool = True

    def should_retry(self, error: Exception, attempt: int) -> tuple[bool, float]:
        """Check if retry should happen and compute delay."""
        if attempt >= self.max_retries:
            return False, 0.0
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        if self.jitter:
            delay *= random.uniform(0.5, 1.5)
        return True, delay


@dataclass(frozen=True)
class ModelFallbackChain:
    """On rate limit errors, switch to next model in chain.

    Usage:
        chain = ModelFallbackChain(models=["gpt-4o", "claude-sonnet", "gemini-pro"])
        next_model = chain.next_model("gpt-4o")  # -> "claude-sonnet"
    """

    models: list[str] = field(default_factory=list)

    def next_model(self, current_model: str) -> str | None:
        """Return next model in chain, or None if at end / not found."""
        try:
            idx = self.models.index(current_model)
            if idx + 1 < len(self.models):
                return self.models[idx + 1]
        except ValueError:
            pass
        return None


@dataclass(frozen=True)
class ProviderFallback:
    """On provider outage, switch to alternative provider.

    Usage:
        fb = ProviderFallback(fallback_model="openai:gpt-4o")
    """

    fallback_model: str = ""
