# Attribution: adapted from hermes (MIT)
# Upstream file: agent/chat_completion_helpers.py
# Copyright: (c) Nous Research and contributors
# Changes: generalized to scope_id + str tiers + injected attempt callable;
#          CooldownStatePort replaces product cooldown port; no LlmRuntimePort
#          coupling — caller supplies a generic AttemptCallable instead;
#          RETRY action added with retry-in-place semantics + budget control.
"""FallbackResolver — cascade executor for provider fallback chains.

The cascade algorithm (skip-cooled snapshot, dedup guard, RETRY/FAILOVER/ABORT/
COMPRESS/unknown-action routing) is adapted from hermes ``try_activate_fallback``
(MIT © Nous Research).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from swarmline.runtime.fallback._cooldown import CooldownStatePort
from swarmline.runtime.fallback._types import (
    ClassifiedError,
    FallbackChain,
    FallbackEntry,
    RemediationAction,
)

logger = logging.getLogger(__name__)

_DEFAULT_COOLDOWN_SECONDS = 60
_DEFAULT_MAX_RETRIES = 2

# Attempt callable: caller closes over its own messages / API context.
AttemptCallable = Callable[[FallbackEntry], Awaitable[object | ClassifiedError]]

__all__ = ["FallbackResolver"]


class FallbackResolver:
    """Cascade executor: walks a FallbackChain until success or a terminal error.

    The cascade algorithm is adapted from hermes ``try_activate_fallback``
    (MIT © Nous Research, agent/chat_completion_helpers.py).

    Injection points
    ----------------
    cooldown_port
        Per-scope provider cooldown state (CooldownStatePort).
    now_factory
        Injectable clock — defaults to ``datetime.now(UTC)``.  Inject a fixed
        factory in tests for deterministic cooldown assertions.
    cooldown_seconds
        Cooldown duration after a FAILOVER (default 60 s, matching hermes).
    max_retries_per_entry
        Maximum number of in-place retries per entry on RETRY errors (default 2).
        A value of 0 means: attempt once, then treat persistent RETRY as FAILOVER.

    Usage
    -----
    Build an ``attempt`` callable that closes over your LLM context::

        async def attempt(entry: FallbackEntry) -> object | ClassifiedError:
            return await my_llm_port.invoke(entry, messages)

        result = await resolver.run(chain=chain, scope_id=scope, attempt=attempt)
    """

    def __init__(
        self,
        *,
        cooldown_port: CooldownStatePort,
        now_factory: Callable[[], datetime] | None = None,
        cooldown_seconds: int = _DEFAULT_COOLDOWN_SECONDS,
        max_retries_per_entry: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        self._cooldown = cooldown_port
        self._now_factory: Callable[[], datetime] = now_factory or (
            lambda: datetime.now(UTC)
        )
        self._cooldown_seconds = cooldown_seconds
        self._max_retries = max_retries_per_entry

    async def run(
        self,
        *,
        chain: FallbackChain,
        scope_id: str,
        attempt: AttemptCallable,
    ) -> object | ClassifiedError:
        """Walk *chain* until a successful result or a non-cascadable error.

        Returns ``object`` on success, ``ClassifiedError(COMPRESS)`` for
        context-overflow, ``ClassifiedError(ABORT)`` for hard stops, or
        ``ClassifiedError(FAILOVER)`` when the chain is exhausted.
        """
        tried: set[tuple[str, str]] = set()
        last_error: ClassifiedError | None = None

        # Snapshot cooldown state BEFORE the walk.  Providers already cooling
        # are skipped for the entire invocation; cooldowns set mid-walk (on
        # FAILOVER) only take effect on the NEXT run() call — hermes semantics.
        start_now = self._now_factory()
        pre_cooldown: frozenset[str] = frozenset(
            entry.provider.lower()
            for entry in chain
            if self._cooldown.is_in_cooldown(
                scope_id, entry.provider.lower(), start_now
            )
        )

        for entry in chain:
            provider_key = entry.provider.lower()

            # Gate 1: skip providers in cooldown at call-start.
            if provider_key in pre_cooldown:
                logger.debug(
                    "FallbackResolver: skip %s/%s scope=%s — pre-invoke cooldown",
                    provider_key,
                    entry.model,
                    scope_id,
                )
                tried.add((entry.provider, entry.model))
                continue

            # Gate 2: skip duplicate (provider, model) within this run.
            normalised = (entry.provider.lower(), entry.model.lower())
            if normalised in {(p.lower(), m.lower()) for p, m in tried}:
                logger.warning(
                    "FallbackResolver: skip duplicate %s/%s in chain",
                    provider_key,
                    entry.model,
                )
                continue

            tried.add((entry.provider, entry.model))
            result = await attempt(entry)

            if not isinstance(result, ClassifiedError):
                return result  # success

            error: ClassifiedError = result
            last_error = error

            # RETRY: re-invoke the SAME entry in place, up to max_retries_per_entry
            # additional times.  No cooldown is set and the cascade does NOT advance
            # during retries — this is a transient error on the same provider/model.
            # If the budget exhausts and action is still RETRY, treat as FAILOVER.
            if error.action == RemediationAction.RETRY:
                for _ in range(self._max_retries):
                    retry_result = await attempt(entry)
                    if not isinstance(retry_result, ClassifiedError):
                        return retry_result  # retry succeeded
                    error = retry_result
                    last_error = error
                    if error.action != RemediationAction.RETRY:
                        # Different action on retry — fall through to dispatch below.
                        break
                else:
                    # for-loop completed without break: budget exhausted, still RETRY.
                    # Treat as FAILOVER: set cooldown and advance the cascade.
                    logger.warning(
                        "FallbackResolver: RETRY budget exhausted for %s/%s scope=%s"
                        " — treating as FAILOVER",
                        provider_key,
                        entry.model,
                        scope_id,
                    )
                    self._set_cooldown(scope_id, provider_key)
                    continue  # advance to next entry

            # Dispatch `error` — reached when: (a) initial non-RETRY action, or
            # (b) a retry returned a different (non-RETRY) action.
            if error.action == RemediationAction.ABORT:
                logger.warning(
                    "FallbackResolver: ABORT %s/%s scope=%s — %s",
                    provider_key,
                    entry.model,
                    scope_id,
                    error.message,
                )
                return error

            if error.action == RemediationAction.COMPRESS:
                logger.info(
                    "FallbackResolver: COMPRESS %s/%s scope=%s",
                    provider_key,
                    entry.model,
                    scope_id,
                )
                return error

            if error.action == RemediationAction.FAILOVER:
                self._set_cooldown(scope_id, provider_key)
                logger.info(
                    "FallbackResolver: FAILOVER %s/%s scope=%s — %s",
                    provider_key,
                    entry.model,
                    scope_id,
                    error.message,
                )
                continue

            # Unknown action — treat as FAILOVER to be safe.
            logger.warning(
                "FallbackResolver: unknown action %r for %s/%s — treating as FAILOVER",
                error.action,
                provider_key,
                entry.model,
            )
            self._set_cooldown(scope_id, provider_key)

        # Chain exhausted.
        if last_error is not None:
            return last_error
        # Defensive: all entries were pre-cooled or otherwise skipped.
        return ClassifiedError(
            retryable=False,
            action=RemediationAction.FAILOVER,
            message="FallbackResolver: chain exhausted with no invocation attempt",
        )

    def _set_cooldown(self, scope_id: str, provider_key: str) -> None:
        now = self._now_factory()
        expires_at = now + timedelta(seconds=self._cooldown_seconds)
        self._cooldown.set_cooldown(scope_id, provider_key, expires_at)
