"""Unit tests for swarmline.runtime.fallback — OSS-T5 Half A.

Covers:
- FallbackEntry: blank model/provider validation (ValueError), frozen, str tier.
- FallbackChain: non-empty invariant, __len__/__iter__, remaining_after
  case-insensitive dedup, build_from_tier walks str tier_order from requested
  downward (ValueError on unknown requested).
- InMemoryCooldownState: set/is_in_cooldown (respects now vs expires_at)/clear.
- FallbackResolver cascade:
    * success returns immediately
    * ABORT returns immediately, later entries NOT attempted
    * COMPRESS returns to caller, no cascade
    * FAILOVER advances with cooldown set for scope
    * chain exhausted → returns last error
    * pre-cooldown snapshot skips already-cooled providers for whole invocation
    * duplicate (provider, model) skipped within a single run
    * unknown action treated as FAILOVER (sets cooldown + advances)
- Determinism: now_factory injected so cooldown timing is testable without real clock.

No product coupling: no taskloom / tenant / FastAPI / SQLAlchemy / AccessContext.
"""

from __future__ import annotations

import pytest

from swarmline.runtime.fallback import (
    ClassifiedError,
    CooldownStatePort,
    FallbackChain,
    FallbackEntry,
    FallbackResolver,
    InMemoryCooldownState,
    RemediationAction,
)
from datetime import UTC, datetime, timedelta
from collections.abc import Awaitable, Callable


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_entry(
    tier: str = "standard",
    model: str = "gpt-4",
    provider: str = "openai",
) -> FallbackEntry:
    return FallbackEntry(tier=tier, model=model, provider=provider)


def _make_chain(*entries: FallbackEntry) -> FallbackChain:
    return FallbackChain(entries=tuple(entries))


def _fixed_now(ts: datetime) -> Callable[[], datetime]:
    """Return a now_factory that always returns *ts*."""
    return lambda: ts


def _success_attempt(
    result: object,
) -> Callable[[FallbackEntry], Awaitable[object | ClassifiedError]]:
    """Return an attempt callable that always returns *result*."""

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        return result

    return _attempt


def _error_attempt(
    error: ClassifiedError,
) -> Callable[[FallbackEntry], Awaitable[object | ClassifiedError]]:
    """Return an attempt callable that always returns *error*."""

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        return error

    return _attempt


def _sequenced_attempt(
    responses: list[object | ClassifiedError],
) -> Callable[[FallbackEntry], Awaitable[object | ClassifiedError]]:
    """Return an attempt callable that returns responses in sequence (one per call)."""
    it = iter(responses)
    calls: list[FallbackEntry] = []

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        calls.append(entry)
        return next(it)

    # Attach the call log for assertions
    _attempt.calls = calls  # type: ignore[attr-defined]
    return _attempt


# ---------------------------------------------------------------------------
# FallbackEntry — construction and validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model, provider",
    [
        ("", "openai"),
        (" ", "openai"),
        ("\t", "openai"),
        ("gpt-4", ""),
        ("gpt-4", "   "),
    ],
)
def test_fallback_entry_blank_field_raises_value_error(
    model: str, provider: str
) -> None:
    """Blank (or whitespace-only) model or provider must raise ValueError."""
    with pytest.raises(ValueError):
        FallbackEntry(tier="standard", model=model, provider=provider)


def test_fallback_entry_valid_construction_uses_str_tier() -> None:
    """FallbackEntry accepts any str as tier — no ModelTier coupling."""
    entry = FallbackEntry(tier="MAX", model="claude-3", provider="anthropic")
    assert entry.tier == "MAX"
    assert entry.model == "claude-3"
    assert entry.provider == "anthropic"


def test_fallback_entry_frozen_cannot_reassign() -> None:
    entry = _make_entry()
    with pytest.raises((AttributeError, TypeError)):
        entry.model = "new-model"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FallbackChain — invariants and queries
# ---------------------------------------------------------------------------


def test_fallback_chain_empty_entries_raises_value_error() -> None:
    with pytest.raises(ValueError):
        FallbackChain(entries=())


def test_fallback_chain_single_entry_ok() -> None:
    chain = _make_chain(_make_entry())
    assert len(chain) == 1


def test_fallback_chain_len_matches_entries() -> None:
    chain = _make_chain(
        _make_entry("max"), _make_entry("standard"), _make_entry("fast")
    )
    assert len(chain) == 3


def test_fallback_chain_iter_yields_entries_in_order() -> None:
    e1 = _make_entry("max", "gpt-4o", "openai")
    e2 = _make_entry("standard", "gpt-4", "openai")
    chain = _make_chain(e1, e2)
    assert list(chain) == [e1, e2]


def test_fallback_chain_remaining_after_empty_tried_returns_all() -> None:
    e1 = _make_entry("max")
    e2 = _make_entry("standard", "gpt-3.5", "openai")
    chain = _make_chain(e1, e2)
    remaining = chain.remaining_after(frozenset())
    assert remaining == (e1, e2)


def test_fallback_chain_remaining_after_excludes_tried_pair() -> None:
    e1 = _make_entry("max", "gpt-4", "openai")
    e2 = _make_entry("standard", "gpt-3.5", "openai")
    chain = _make_chain(e1, e2)
    remaining = chain.remaining_after(frozenset({("openai", "gpt-4")}))
    assert remaining == (e2,)


def test_fallback_chain_remaining_after_case_insensitive_dedup() -> None:
    """(provider, model) matching must be case-insensitive (hermes semantics)."""
    e1 = _make_entry("max", "GPT-4", "OpenAI")
    e2 = _make_entry("standard", "gpt-3.5", "openai")
    chain = _make_chain(e1, e2)
    # Tried with lowercased pair — must still match the entry with original casing
    remaining = chain.remaining_after(frozenset({("openai", "gpt-4")}))
    assert remaining == (e2,)


def test_fallback_chain_frozen_cannot_reassign() -> None:
    chain = _make_chain(_make_entry())
    with pytest.raises((AttributeError, TypeError)):
        chain.entries = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FallbackChain.build_from_tier
# ---------------------------------------------------------------------------

_TIER_ORDER = ("max", "standard", "fast")
_TIER_MAP = {
    "max": _make_entry("max", "claude-3-opus", "anthropic"),
    "standard": _make_entry("standard", "claude-3-sonnet", "anthropic"),
    "fast": _make_entry("fast", "claude-3-haiku", "anthropic"),
}


def test_build_from_tier_starting_from_max_includes_all() -> None:
    chain = FallbackChain.build_from_tier(
        "max", tier_order=_TIER_ORDER, tier_map=_TIER_MAP
    )
    assert len(chain) == 3
    assert list(chain)[0].tier == "max"
    assert list(chain)[1].tier == "standard"
    assert list(chain)[2].tier == "fast"


def test_build_from_tier_starting_from_standard_excludes_max() -> None:
    chain = FallbackChain.build_from_tier(
        "standard", tier_order=_TIER_ORDER, tier_map=_TIER_MAP
    )
    assert len(chain) == 2
    assert list(chain)[0].tier == "standard"
    assert list(chain)[1].tier == "fast"


def test_build_from_tier_starting_from_fast_returns_only_fast() -> None:
    chain = FallbackChain.build_from_tier(
        "fast", tier_order=_TIER_ORDER, tier_map=_TIER_MAP
    )
    assert len(chain) == 1
    assert list(chain)[0].tier == "fast"


def test_build_from_tier_unknown_requested_raises_value_error() -> None:
    with pytest.raises(ValueError):
        FallbackChain.build_from_tier(
            "ultra", tier_order=_TIER_ORDER, tier_map=_TIER_MAP
        )


def test_build_from_tier_skips_tiers_missing_from_map() -> None:
    """Tiers present in tier_order but absent from tier_map are silently skipped."""
    sparse_map = {
        "max": _make_entry("max", "claude-3-opus", "anthropic"),
        "fast": _make_entry("fast", "claude-3-haiku", "anthropic"),
        # "standard" intentionally absent
    }
    chain = FallbackChain.build_from_tier(
        "max", tier_order=_TIER_ORDER, tier_map=sparse_map
    )
    # standard is skipped; only max + fast
    assert len(chain) == 2
    tiers = [e.tier for e in chain]
    assert tiers == ["max", "fast"]


# ---------------------------------------------------------------------------
# InMemoryCooldownState
# ---------------------------------------------------------------------------

_EPOCH = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_cooldown_state_not_in_cooldown_initially() -> None:
    state = InMemoryCooldownState()
    assert state.is_in_cooldown("scope-1", "openai", _EPOCH) is False


def test_cooldown_state_is_in_cooldown_before_expiry() -> None:
    state = InMemoryCooldownState()
    expires_at = _EPOCH + timedelta(seconds=60)
    state.set_cooldown("scope-1", "openai", expires_at)
    # Check at a time BEFORE expiry
    check_time = _EPOCH + timedelta(seconds=30)
    assert state.is_in_cooldown("scope-1", "openai", check_time) is True


def test_cooldown_state_not_in_cooldown_after_expiry() -> None:
    state = InMemoryCooldownState()
    expires_at = _EPOCH + timedelta(seconds=60)
    state.set_cooldown("scope-1", "openai", expires_at)
    # Check at exactly expiry time (boundary: NOT in cooldown at == expires_at)
    check_at_expiry = expires_at
    assert state.is_in_cooldown("scope-1", "openai", check_at_expiry) is False


def test_cooldown_state_not_in_cooldown_past_expiry() -> None:
    state = InMemoryCooldownState()
    expires_at = _EPOCH + timedelta(seconds=60)
    state.set_cooldown("scope-1", "openai", expires_at)
    check_past = _EPOCH + timedelta(seconds=120)
    assert state.is_in_cooldown("scope-1", "openai", check_past) is False


def test_cooldown_state_clear_removes_cooldown() -> None:
    state = InMemoryCooldownState()
    expires_at = _EPOCH + timedelta(seconds=60)
    state.set_cooldown("scope-1", "openai", expires_at)
    state.clear_cooldown("scope-1", "openai")
    check_time = _EPOCH + timedelta(seconds=30)
    assert state.is_in_cooldown("scope-1", "openai", check_time) is False


def test_cooldown_state_clear_nonexistent_is_noop() -> None:
    """clear_cooldown on a key that was never set must not raise."""
    state = InMemoryCooldownState()
    state.clear_cooldown("never-set", "openai")  # must not raise


def test_cooldown_state_different_scopes_independent() -> None:
    state = InMemoryCooldownState()
    expires_at = _EPOCH + timedelta(seconds=60)
    state.set_cooldown("scope-A", "openai", expires_at)
    check = _EPOCH + timedelta(seconds=30)
    assert state.is_in_cooldown("scope-A", "openai", check) is True
    assert state.is_in_cooldown("scope-B", "openai", check) is False


def test_cooldown_state_satisfies_protocol() -> None:
    """InMemoryCooldownState must be runtime-checkable as CooldownStatePort."""
    state = InMemoryCooldownState()
    assert isinstance(state, CooldownStatePort)


# ---------------------------------------------------------------------------
# FallbackResolver cascade — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_success_on_first_entry_returns_result() -> None:
    """Success on the first entry returns immediately without trying others."""
    tracker: list[FallbackEntry] = []

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        tracker.append(entry)
        return {"content": "hello"}

    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(cooldown_port=InMemoryCooldownState())

    result = await resolver.run(chain=chain, scope_id="s1", attempt=_attempt)
    assert result == {"content": "hello"}
    # Only the first entry was attempted
    assert tracker == [e1]


@pytest.mark.asyncio
async def test_resolver_success_on_second_entry_after_failover() -> None:
    """FAILOVER on first entry → attempt second entry → success returned."""
    failover = ClassifiedError(
        retryable=True, action=RemediationAction.FAILOVER, message="overloaded"
    )
    success = {"content": "ok"}

    attempt = _sequenced_attempt([failover, success])
    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(cooldown_port=InMemoryCooldownState())

    result = await resolver.run(chain=chain, scope_id="s1", attempt=attempt)
    assert result == success


# ---------------------------------------------------------------------------
# FallbackResolver cascade — ABORT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_abort_returns_error_immediately() -> None:
    """ABORT action must be returned immediately without cascading."""
    abort_err = ClassifiedError(
        retryable=False, action=RemediationAction.ABORT, message="auth_permanent"
    )
    tracker: list[FallbackEntry] = []

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        tracker.append(entry)
        return abort_err

    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(cooldown_port=InMemoryCooldownState())

    result = await resolver.run(chain=chain, scope_id="s1", attempt=_attempt)
    assert result is abort_err
    # e2 must NOT have been attempted
    assert tracker == [e1]


# ---------------------------------------------------------------------------
# FallbackResolver cascade — COMPRESS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_compress_returns_to_caller_without_cascade() -> None:
    """COMPRESS action is returned to caller; later entries must not be attempted."""
    compress_err = ClassifiedError(
        retryable=False, action=RemediationAction.COMPRESS, message="context_overflow"
    )
    tracker: list[FallbackEntry] = []

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        tracker.append(entry)
        return compress_err

    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(cooldown_port=InMemoryCooldownState())

    result = await resolver.run(chain=chain, scope_id="s1", attempt=_attempt)
    assert result is compress_err
    assert tracker == [e1]


# ---------------------------------------------------------------------------
# FallbackResolver cascade — FAILOVER + cooldown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_failover_sets_cooldown_for_scope_and_provider() -> None:
    """FAILOVER must set cooldown keyed by (scope_id, provider_key)."""
    now = _EPOCH
    cooldown = InMemoryCooldownState()

    failover = ClassifiedError(
        retryable=True, action=RemediationAction.FAILOVER, message="rate_limit"
    )
    success = {"content": "ok"}
    attempt = _sequenced_attempt([failover, success])

    e1 = _make_entry("max", "model-a", "ProvA")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(
        cooldown_port=cooldown,
        now_factory=_fixed_now(now),
        cooldown_seconds=60,
    )

    await resolver.run(chain=chain, scope_id="scope-x", attempt=attempt)

    # cooldown for (scope-x, prova) must have been set with future expiry
    check_after = now + timedelta(seconds=30)
    assert cooldown.is_in_cooldown("scope-x", "prova", check_after) is True


@pytest.mark.asyncio
async def test_resolver_chain_exhausted_returns_last_error() -> None:
    """When all entries FAILOVER and chain is exhausted, last error is returned."""
    err1 = ClassifiedError(
        retryable=True, action=RemediationAction.FAILOVER, message="err1"
    )
    err2 = ClassifiedError(
        retryable=True, action=RemediationAction.FAILOVER, message="err2"
    )

    attempt = _sequenced_attempt([err1, err2])
    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(cooldown_port=InMemoryCooldownState())

    result = await resolver.run(chain=chain, scope_id="s1", attempt=attempt)
    assert isinstance(result, ClassifiedError)
    assert result.message == "err2"


# ---------------------------------------------------------------------------
# FallbackResolver cascade — pre-cooldown snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_pre_cooldown_skips_provider_for_whole_invocation() -> None:
    """Providers already in cooldown at call-start must be skipped for the entire run."""
    now = _EPOCH
    cooldown = InMemoryCooldownState()
    # Put prov-a in cooldown before the resolver is called
    cooldown.set_cooldown("scope-1", "prov-a", now + timedelta(seconds=60))

    tracker: list[FallbackEntry] = []

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        tracker.append(entry)
        return {"content": "ok"}

    e1 = _make_entry("max", "model-a", "prov-a")  # should be skipped
    e2 = _make_entry("standard", "model-b", "prov-b")  # should succeed
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(
        cooldown_port=cooldown,
        now_factory=_fixed_now(now),
    )

    result = await resolver.run(chain=chain, scope_id="scope-1", attempt=_attempt)
    assert result == {"content": "ok"}
    # prov-a must not have been attempted
    assert tracker == [e2]


@pytest.mark.asyncio
async def test_resolver_cooldown_set_mid_run_does_not_skip_later_entries_same_turn() -> (
    None
):
    """Cooldown set during cascade (for FAILOVER) applies next turn, not current run.

    If two entries share the same provider but different models, the second is
    already filtered by the duplicate-entry dedup guard (not the cooldown).  This
    test uses DIFFERENT providers so neither dedup nor pre-snapshot stops the second.
    The first FAILOVERs (setting cooldown for prov-a); the second (prov-b) must
    still be attempted in this same run.
    """
    now = _EPOCH
    cooldown = InMemoryCooldownState()
    failover = ClassifiedError(
        retryable=True, action=RemediationAction.FAILOVER, message="rate_limit"
    )
    success = {"content": "ok"}

    attempt = _sequenced_attempt([failover, success])
    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(
        cooldown_port=cooldown,
        now_factory=_fixed_now(now),
    )

    result = await resolver.run(chain=chain, scope_id="s1", attempt=attempt)
    # prov-b must have been attempted even though prov-a is now in cooldown
    assert result == success
    assert attempt.calls == [e1, e2]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# FallbackResolver cascade — duplicate (provider, model) dedup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_duplicate_provider_model_skipped_within_run() -> None:
    """Duplicate (provider, model) entries in the chain are skipped (once tried)."""
    tracker: list[FallbackEntry] = []

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        tracker.append(entry)
        return ClassifiedError(
            retryable=True, action=RemediationAction.FAILOVER, message="x"
        )

    e1 = _make_entry("max", "GPT-4", "OpenAI")
    # e2 is a duplicate of e1 (case-insensitive)
    e2 = _make_entry("standard", "gpt-4", "openai")
    e3 = _make_entry("fast", "model-c", "prov-c")
    chain = _make_chain(e1, e2, e3)
    resolver = FallbackResolver(cooldown_port=InMemoryCooldownState())

    await resolver.run(chain=chain, scope_id="s1", attempt=_attempt)
    # e2 must have been skipped; e1 and e3 attempted
    attempted_models = [e.model for e in tracker]
    assert "GPT-4" in attempted_models
    assert "gpt-4" not in attempted_models  # duplicate skipped
    assert "model-c" in attempted_models


# ---------------------------------------------------------------------------
# FallbackResolver cascade — unknown action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_unknown_action_treated_as_failover() -> None:
    """An unrecognised RemediationAction value advances the cascade and sets cooldown."""
    now = _EPOCH
    cooldown = InMemoryCooldownState()

    # Craft a ClassifiedError with a novel action value (not one of the four enum members).
    # We use the string constructor path: StrEnum allows unknown values at construction in
    # Python 3.11+, but ClassifiedError.action is typed as RemediationAction so we bypass
    # typing to simulate a future action value the resolver hasn't heard of yet.
    class _FakeAction(str):
        pass

    unknown_action = _FakeAction("supersede")  # not in RemediationAction

    unknown_err = ClassifiedError(
        retryable=True, action=unknown_action, message="future_action"
    )  # type: ignore[arg-type]
    success = {"content": "ok"}

    attempt = _sequenced_attempt([unknown_err, success])
    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(
        cooldown_port=cooldown,
        now_factory=_fixed_now(now),
        cooldown_seconds=60,
    )

    result = await resolver.run(chain=chain, scope_id="s1", attempt=attempt)
    # Treated as FAILOVER → advanced to e2 → success
    assert result == success
    # Cooldown set for prov-a
    check = now + timedelta(seconds=30)
    assert cooldown.is_in_cooldown("s1", "prov-a", check) is True


# ---------------------------------------------------------------------------
# FallbackResolver — injected now_factory + custom cooldown_seconds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_now_factory_and_cooldown_seconds_control_expiry() -> None:
    """Injected now_factory + cooldown_seconds determine exact expiry time."""
    fixed_now = _EPOCH
    cooldown_secs = 120
    cooldown = InMemoryCooldownState()

    failover = ClassifiedError(
        retryable=True, action=RemediationAction.FAILOVER, message="rate_limit"
    )
    success = {"content": "ok"}

    attempt = _sequenced_attempt([failover, success])
    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(
        cooldown_port=cooldown,
        now_factory=_fixed_now(fixed_now),
        cooldown_seconds=cooldown_secs,
    )

    await resolver.run(chain=chain, scope_id="s1", attempt=attempt)

    # Just before expiry (119s) → still in cooldown
    assert (
        cooldown.is_in_cooldown("s1", "prov-a", fixed_now + timedelta(seconds=119))
        is True
    )
    # At exact expiry (120s from now) → NOT in cooldown (boundary: expiry exclusive)
    assert (
        cooldown.is_in_cooldown("s1", "prov-a", fixed_now + timedelta(seconds=120))
        is False
    )


# ---------------------------------------------------------------------------
# FallbackResolver cascade — RETRY (retry-in-place semantics)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_retry_then_success_on_same_entry_no_advance_no_cooldown() -> (
    None
):
    """RETRY then success on the same entry: no cooldown set, next entry NOT attempted."""
    cooldown = InMemoryCooldownState()
    retry_err = ClassifiedError(
        retryable=True, action=RemediationAction.RETRY, message="transient"
    )
    success = {"content": "ok"}

    calls: list[FallbackEntry] = []

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        calls.append(entry)
        if len([c for c in calls if c is entry]) == 1:
            # First call on this entry → RETRY
            return retry_err
        return success  # second call → success

    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(
        cooldown_port=cooldown,
        now_factory=_fixed_now(_EPOCH),
        max_retries_per_entry=2,
    )

    result = await resolver.run(chain=chain, scope_id="s1", attempt=_attempt)

    assert result == success
    # e1 was attempted twice (initial + one retry)
    e1_calls = [c for c in calls if c is e1]
    assert len(e1_calls) == 2
    # e2 must NOT have been attempted
    e2_calls = [c for c in calls if c is e2]
    assert len(e2_calls) == 0
    # No cooldown set for prov-a
    assert (
        cooldown.is_in_cooldown("s1", "prov-a", _EPOCH + timedelta(seconds=30)) is False
    )


@pytest.mark.asyncio
async def test_resolver_retry_budget_exhausted_advances_and_sets_cooldown() -> None:
    """RETRY budget exhausted → treated as FAILOVER: advances to next entry + sets cooldown."""
    now = _EPOCH
    cooldown = InMemoryCooldownState()
    retry_err = ClassifiedError(
        retryable=True, action=RemediationAction.RETRY, message="still_transient"
    )
    success = {"content": "ok"}

    e1_calls: list[FallbackEntry] = []
    e2_calls: list[FallbackEntry] = []

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        if entry.provider == "prov-a":
            e1_calls.append(entry)
            return retry_err  # always RETRY
        e2_calls.append(entry)
        return success

    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(
        cooldown_port=cooldown,
        now_factory=_fixed_now(now),
        cooldown_seconds=60,
        max_retries_per_entry=2,
    )

    result = await resolver.run(chain=chain, scope_id="s1", attempt=_attempt)

    assert result == success
    # e1 attempted exactly max_retries_per_entry+1 times (1 initial + 2 retries)
    assert len(e1_calls) == 3
    # e2 was reached after e1 budget exhausted
    assert len(e2_calls) == 1
    # Cooldown set for prov-a (budget-exhausted FAILOVER)
    assert cooldown.is_in_cooldown("s1", "prov-a", now + timedelta(seconds=30)) is True


@pytest.mark.asyncio
async def test_resolver_retry_then_abort_dispatches_abort() -> None:
    """RETRY on first call, ABORT on retry → ABORT returned immediately; e2 NOT attempted."""
    retry_err = ClassifiedError(
        retryable=True, action=RemediationAction.RETRY, message="transient"
    )
    abort_err = ClassifiedError(
        retryable=False, action=RemediationAction.ABORT, message="auth_fail"
    )

    calls: list[FallbackEntry] = []

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        calls.append(entry)
        if entry.provider == "prov-b":
            return {"content": "should_not_reach"}
        # e1: RETRY on first call, ABORT on second
        return retry_err if len([c for c in calls if c is entry]) == 1 else abort_err

    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(
        cooldown_port=InMemoryCooldownState(),
        max_retries_per_entry=2,
    )

    result = await resolver.run(chain=chain, scope_id="s1", attempt=_attempt)

    assert result is abort_err
    # e2 must NOT have been attempted
    e2_calls = [c for c in calls if c is e2]
    assert len(e2_calls) == 0


@pytest.mark.parametrize(
    "max_retries, expected_e1_attempts",
    [
        (0, 1),  # no retries: initial call only, then FAILOVER
        (1, 2),  # one retry: initial + 1
        (3, 4),  # three retries: initial + 3
    ],
)
@pytest.mark.asyncio
async def test_resolver_max_retries_per_entry_respected(
    max_retries: int, expected_e1_attempts: int
) -> None:
    """Exact attempt count per entry matches max_retries_per_entry + 1."""
    now = _EPOCH
    cooldown = InMemoryCooldownState()
    retry_err = ClassifiedError(
        retryable=True, action=RemediationAction.RETRY, message="transient"
    )
    success = {"content": "ok"}

    e1_calls: list[FallbackEntry] = []
    e2_calls: list[FallbackEntry] = []

    async def _attempt(entry: FallbackEntry) -> object | ClassifiedError:
        if entry.provider == "prov-a":
            e1_calls.append(entry)
            return retry_err  # always RETRY so budget always exhausts
        e2_calls.append(entry)
        return success

    e1 = _make_entry("max", "model-a", "prov-a")
    e2 = _make_entry("standard", "model-b", "prov-b")
    chain = _make_chain(e1, e2)
    resolver = FallbackResolver(
        cooldown_port=cooldown,
        now_factory=_fixed_now(now),
        max_retries_per_entry=max_retries,
    )

    result = await resolver.run(chain=chain, scope_id="s1", attempt=_attempt)

    assert result == success  # e2 provides success after e1 budget exhausts
    assert len(e1_calls) == expected_e1_attempts
    assert len(e2_calls) == 1


# ---------------------------------------------------------------------------
# __all__ export surface
# ---------------------------------------------------------------------------


def test_all_exports_public_types() -> None:
    from swarmline.runtime.fallback import __all__

    expected = {
        "RemediationAction",
        "ClassifiedError",
        "FallbackEntry",
        "FallbackChain",
        "CooldownStatePort",
        "InMemoryCooldownState",
        "FallbackResolver",
    }
    assert expected.issubset(set(__all__))


def test_no_product_coupling_in_module() -> None:
    """Verify zero product coupling — no product imports in fallback.py.

    Checks that no forbidden product-specific module/symbol appears in an
    ``import`` or ``from ... import`` statement.  Plain mentions in comments
    (e.g. architectural notes) are allowed; executable coupling is not.
    """
    import ast
    import importlib.util
    import pathlib

    spec = importlib.util.find_spec("swarmline.runtime.fallback")
    assert spec is not None
    src_path = pathlib.Path(spec.origin)  # type: ignore[arg-type]
    source = src_path.read_text()
    tree = ast.parse(source)

    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.append(node.module)

    # None of the product-specific namespaces must appear in import statements.
    product_namespaces = ["taskloom", "fastapi", "sqlalchemy"]
    for name in imported_names:
        for ns in product_namespaces:
            assert not name.lower().startswith(ns), (
                f"Product import found: '{name}' in fallback.py (matches '{ns}')"
            )
