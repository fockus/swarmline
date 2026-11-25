"""Tests for swarmline.runtime.thin.tool_result_offload -- Stage 4 (OpenClaw-style
filesystem-as-context offload).

TDD file: written BEFORE any wiring into react_strategy.py. Covers the pure
resolve_tool_result_offload() decision function in isolation, against an
InMemoryScratchpadProvider double.

Fix-cycle 1 (codex round 1, Stage 4): rewritten for two behavioural changes
codex required:
- (5, MAJOR) offload is now COMPLETELY disabled for windows below
  LARGE_WINDOW_TOKENS (100k) -- resolve_offload_threshold_chars() returns
  None, not a smaller (16k) threshold. Every test that exercises real offload
  behaviour now uses a >=100k-token window.
- (3a, CRITICAL) a scratchpad write failure is fail-SAFE to the FULL body
  (not fail-open to a truncated, now-unrestorable projection).
- (2, MINOR) the aggregate ceiling is a SOFT target: MIN_KEEP_CHARS always
  wins over it. Renamed AGGREGATE_CEILING_RATIO -> AGGREGATE_SOFT_TARGET_RATIO
  and added an explicit test documenting the floor-wins-over-target behaviour.

Fix-cycle 2 (codex round 2): 3a's write-failure fallback and a successful
offload projection are now tracked in TWO SEPARATE maps
(frozen_projections / frozen_full_fallbacks) -- codex found the original
single-map design let a write-failure fallback corrupt the aggregate soft
target's budget accounting (TestWriteFailureFallbackBudgetIsolation) and
falsely look like "this run has offloaded something" for the sticky
scratch_read re-add (covered at the react_strategy.py integration level in
test_react_stage4_offload.py). TestResolveToolResultOffload_FailSafeOnWriteFailure
below is rewritten for the new dedicated frozen_full_fallbacks map.
"""

from __future__ import annotations

import pytest

from swarmline.runtime.thin.tool_result_offload import (
    AGGREGATE_SOFT_TARGET_RATIO,
    LARGE_WINDOW_TOKENS,
    MIN_KEEP_CHARS,
    OFFLOAD_THRESHOLD_CHARS_LARGE_WINDOW,
    resolve_offload_threshold_chars,
    resolve_tool_result_offload,
    scratch_key_for_call,
)
from swarmline.scratchpad.inmemory_provider import InMemoryScratchpadProvider

#: A window comfortably above the 100k enable-boundary, used by every test
#: that exercises REAL offload behaviour (not the disabled-below-100k gate).
_ENABLED_WINDOW = (
    200_000  # window_chars=800_000, per_result=240_000, soft_target=400_000
)


class _FailingProvider:
    async def write(self, key: str, content: str, tags: tuple = ()) -> None:
        raise OSError("disk full")


class TestResolveOffloadThresholdChars:
    def test_large_window_uses_32k_threshold(self) -> None:
        assert (
            resolve_offload_threshold_chars(LARGE_WINDOW_TOKENS)
            == OFFLOAD_THRESHOLD_CHARS_LARGE_WINDOW
        )

    def test_just_below_large_window_boundary_is_disabled(self) -> None:
        assert resolve_offload_threshold_chars(LARGE_WINDOW_TOKENS - 1) is None

    def test_small_window_is_disabled(self) -> None:
        assert resolve_offload_threshold_chars(50_000) is None


class TestScratchKeyForCall:
    def test_key_convention_is_tool_prefixed(self) -> None:
        assert scratch_key_for_call("abc123") == "tool:abc123"


class TestResolveToolResultOffload_WindowGate:
    """(5, MAJOR fix): below LARGE_WINDOW_TOKENS, offload is a hard no-op --
    NOT a smaller threshold. A huge result on a small window passes through
    completely untouched, byte-identical to pre-Stage-4 behaviour."""

    @pytest.mark.asyncio
    async def test_huge_result_on_small_window_is_never_offloaded(self) -> None:
        provider = InMemoryScratchpadProvider()
        raw = "H" * 1_000_000  # would trivially exceed any threshold/ceiling
        outcome = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=50_000,
            scratchpad_provider=provider,
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        assert outcome.text == raw
        assert outcome.offloaded is False
        assert await provider.read("tool:c1") is None


class TestResolveToolResultOffload_BelowThreshold:
    @pytest.mark.asyncio
    async def test_short_result_passes_through_unchanged_and_not_offloaded(
        self,
    ) -> None:
        provider = InMemoryScratchpadProvider()
        outcome = await resolve_tool_result_offload(
            call_id="c1",
            result="short result",
            context_window_tokens=_ENABLED_WINDOW,
            scratchpad_provider=provider,
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        assert outcome.text == "short result"
        assert outcome.offloaded is False
        assert outcome.frozen_projections == {}
        assert outcome.frozen_full_fallbacks == {}
        assert await provider.read("tool:c1") is None


class TestResolveToolResultOffload_AboveThreshold:
    @pytest.mark.asyncio
    async def test_large_result_is_offloaded_and_written_to_scratchpad(self) -> None:
        provider = InMemoryScratchpadProvider()
        raw = "X" * 40_000  # > 32k threshold for a >=100k-token window
        outcome = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=_ENABLED_WINDOW,
            scratchpad_provider=provider,
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        assert outcome.offloaded is True
        assert "tool:c1" in outcome.text
        stored = await provider.read("tool:c1")
        assert stored is not None
        assert stored.content == raw  # full body persisted, restorable

    @pytest.mark.asyncio
    async def test_offloaded_projection_keeps_head_and_tail(self) -> None:
        """Diagnostics live in the tail -- both ends must survive truncation."""
        provider = InMemoryScratchpadProvider()
        raw = "HEAD_MARKER_XYZ" + ("." * 400_000) + "TAIL_MARKER_ABC"
        outcome = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=100_000,  # per-result ceiling=120_000 < len(raw)
            scratchpad_provider=provider,
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        assert "HEAD_MARKER_XYZ" in outcome.text
        assert "TAIL_MARKER_ABC" in outcome.text

    @pytest.mark.asyncio
    async def test_projection_respects_per_result_ceiling(self) -> None:
        provider = InMemoryScratchpadProvider()
        raw = "Y" * 900_000
        window_tokens = 100_000  # window_chars=400_000; per-result ceiling=120_000
        outcome = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=window_tokens,
            scratchpad_provider=provider,
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        # Comfortable slack for the marker overhead, still far below len(raw).
        assert len(outcome.text) <= 120_100

    @pytest.mark.asyncio
    async def test_result_just_over_threshold_but_under_ceiling_is_not_truncated(
        self,
    ) -> None:
        """Offload is governed by the THRESHOLD, not by whether truncation is
        strictly necessary: a result just over 32k (for a 100k-token window,
        ceiling=120k) is still offloaded (written externally), but its
        projection is the FULL text plus a restoration marker -- no content
        loss when it already fits the budget."""
        provider = InMemoryScratchpadProvider()
        raw = "Z" * 40_000
        outcome = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=100_000,
            scratchpad_provider=provider,
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        assert outcome.offloaded is True
        assert raw in outcome.text  # untruncated, marker merely appended


class TestResolveToolResultOffload_MinKeepFloor:
    @pytest.mark.asyncio
    async def test_min_keep_floor_wins_when_aggregate_budget_exhausted(self) -> None:
        provider = InMemoryScratchpadProvider()
        raw = "W" * 900_000
        # Aggregate soft target already fully consumed by prior (frozen) offloads.
        frozen = {"prior": "P" * 10_000_000}
        outcome = await resolve_tool_result_offload(
            call_id="c2",
            result=raw,
            context_window_tokens=100_000,
            scratchpad_provider=provider,
            scratch_read_available=True,
            frozen_projections=frozen,
            frozen_full_fallbacks={},
        )
        assert outcome.offloaded is True
        # Even with zero remaining aggregate budget, MIN_KEEP_CHARS is honored.
        assert len(outcome.text) >= MIN_KEEP_CHARS
        assert len(outcome.text) <= MIN_KEEP_CHARS + 200  # marker overhead slack


class TestResolveToolResultOffload_AggregateSoftTarget:
    """(2, MINOR fix): the aggregate is a SOFT target -- MIN_KEEP_CHARS always
    wins over it. This is intentional: offload ALWAYS shrinks the inline
    footprint versus the raw body, so "keep the full body instead" when the
    soft target is exhausted would be strictly worse, not safer."""

    @pytest.mark.asyncio
    async def test_later_results_shrink_as_soft_target_is_consumed(self) -> None:
        """N large results offloaded in sequence: each subsequent projection is
        no larger than the previous one, honoring the soft aggregate target."""
        provider = InMemoryScratchpadProvider()
        window_tokens = (
            100_000  # window_chars=400_000; per-result=120_000; soft_target=200_000
        )
        frozen: dict[str, str] = {}
        sizes: list[int] = []
        for i in range(4):
            raw = "V" * 900_000
            outcome = await resolve_tool_result_offload(
                call_id=f"c{i}",
                result=raw,
                context_window_tokens=window_tokens,
                scratchpad_provider=provider,
                scratch_read_available=True,
                frozen_projections=frozen,
                frozen_full_fallbacks={},
            )
            frozen = outcome.frozen_projections
            sizes.append(len(outcome.text))

        assert sizes == sorted(sizes, reverse=True), (
            f"expected non-increasing projection sizes as the soft target is "
            f"consumed, got {sizes}"
        )
        assert sizes[-1] <= MIN_KEEP_CHARS + 200

    @pytest.mark.asyncio
    async def test_floor_can_intentionally_exceed_the_soft_target_when_many_results(
        self,
    ) -> None:
        """Documented behaviour: when N * MIN_KEEP_CHARS alone would already
        exceed the soft aggregate target, the floor STILL wins for every
        result -- the soft target is exceeded on purpose. This is the
        intentional tension codex flagged: MIN_KEEP_CHARS is a hard floor,
        AGGREGATE_SOFT_TARGET_RATIO is a soft target the floor may override,
        never the other way around (the floor never shrinks to respect the
        target)."""
        provider = InMemoryScratchpadProvider()
        # window_chars = 100_000*4 = 400_000; soft_target = 0.5*400_000 = 200_000.
        # 200_000 // MIN_KEEP_CHARS(4000) = 50 -- so 60 results * 4000 = 240_000
        # already exceeds the soft target on floor alone.
        window_tokens = 100_000
        frozen: dict[str, str] = {}
        for i in range(60):
            raw = "F" * 900_000
            outcome = await resolve_tool_result_offload(
                call_id=f"f{i}",
                result=raw,
                context_window_tokens=window_tokens,
                scratchpad_provider=provider,
                scratch_read_available=True,
                frozen_projections=frozen,
                frozen_full_fallbacks={},
            )
            frozen = outcome.frozen_projections
            # The floor is honored on EVERY single result, never shrunk below it.
            assert len(outcome.text) >= MIN_KEEP_CHARS

        total_offloaded_chars = sum(len(v) for v in frozen.values())
        window_chars = window_tokens * 4
        soft_target = int(window_chars * AGGREGATE_SOFT_TARGET_RATIO)
        assert total_offloaded_chars > soft_target, (
            "this test's whole point is that the floor intentionally pushes "
            "the total past the soft target -- if this assertion fails, the "
            "floor stopped winning over the target"
        )


class TestWriteFailureFallbackBudgetIsolation:
    """(3a-c, CRITICAL fix, codex round 2): a write-failure fallback must NOT
    count against the aggregate soft target -- there is no scratch key behind
    it, so counting its size would shrink a LATER successful projection's
    budget for a reason unrelated to any REAL offload having happened."""

    @pytest.mark.asyncio
    async def test_prior_write_failure_does_not_shrink_a_later_successful_projection(
        self,
    ) -> None:
        window_tokens = 100_000  # per-result ceiling=120_000; soft_target=200_000
        failing_provider = _FailingProvider()
        working_provider = InMemoryScratchpadProvider()

        # --- First: a write FAILS on a huge (900k) result -> full-body fallback.
        first = await resolve_tool_result_offload(
            call_id="c-fail",
            result="F" * 900_000,
            context_window_tokens=window_tokens,
            scratchpad_provider=failing_provider,
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        assert first.offloaded is False
        assert "c-fail" in first.frozen_full_fallbacks
        assert "c-fail" not in first.frozen_projections

        # --- Second: a DIFFERENT call_id, write SUCCEEDS this time. Its budget
        # must be the FULL per-result ceiling (120_000), NOT reduced by the
        # 900_000-char fallback from the first (failed) call.
        second = await resolve_tool_result_offload(
            call_id="c-ok",
            result="S" * 900_000,
            context_window_tokens=window_tokens,
            scratchpad_provider=working_provider,
            scratch_read_available=True,
            frozen_projections=first.frozen_projections,  # still {} (isolated)
            frozen_full_fallbacks=first.frozen_full_fallbacks,
        )
        assert second.offloaded is True
        # Comfortable slack above the untouched per-result ceiling (120_000);
        # WITHOUT the fix this would have been squeezed down to MIN_KEEP_CHARS
        # (4_000) by the fallback's 900_000 chars being wrongly counted.
        assert len(second.text) > MIN_KEEP_CHARS + 200
        assert len(second.text) <= 120_100


class TestResolveToolResultOffload_FrozenReuse:
    @pytest.mark.asyncio
    async def test_already_frozen_call_id_reuses_projection_verbatim(self) -> None:
        """The KEY invariant: a call_id already in frozen_projections returns
        that text VERBATIM, even given a completely different fresh result and
        NO scratchpad_provider/scratch_read_available/enabled-window at all."""
        prior_projection = "FROZEN_PROJECTION_TEXT_UNIQUE_MARKER"
        outcome = await resolve_tool_result_offload(
            call_id="c1",
            result="a totally different fresh result body",
            context_window_tokens=50_000,  # even a disabled-gate window
            scratchpad_provider=None,
            scratch_read_available=False,
            frozen_projections={"c1": prior_projection},
            frozen_full_fallbacks={},
        )
        assert outcome.text == prior_projection
        assert outcome.offloaded is True
        assert outcome.frozen_projections == {"c1": prior_projection}

    @pytest.mark.asyncio
    async def test_repeated_resolution_is_byte_identical(self) -> None:
        """Simulates rebuilding context N times for the SAME call_id/result:
        every resolution after the first must reproduce byte-identical text."""
        provider = InMemoryScratchpadProvider()
        raw = "R" * 200_000
        first = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=_ENABLED_WINDOW,
            scratchpad_provider=provider,
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        second = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=_ENABLED_WINDOW,
            scratchpad_provider=provider,
            scratch_read_available=True,
            frozen_projections=first.frozen_projections,
            frozen_full_fallbacks=first.frozen_full_fallbacks,
        )
        assert second.text == first.text
        assert second.frozen_projections == first.frozen_projections


class TestResolveToolResultOffload_ScratchReadUnavailable:
    @pytest.mark.asyncio
    async def test_scratch_read_not_available_skips_offload_entirely(self) -> None:
        """Restorability is a HARDER requirement than context size: if the
        model cannot call scratch_read this run (masked/absent from the pinned
        schema), a large result stays untouched rather than becoming an
        unrecoverable truncation."""
        provider = InMemoryScratchpadProvider()
        raw = "Q" * 40_000
        outcome = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=100_000,
            scratchpad_provider=provider,
            scratch_read_available=False,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        assert outcome.text == raw
        assert outcome.offloaded is False
        assert await provider.read("tool:c1") is None

    @pytest.mark.asyncio
    async def test_no_scratchpad_provider_skips_offload_entirely(self) -> None:
        raw = "Q" * 40_000
        outcome = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=100_000,
            scratchpad_provider=None,
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        assert outcome.text == raw
        assert outcome.offloaded is False


class TestResolveToolResultOffload_FailSafeOnWriteFailure:
    """(3a, CRITICAL fix, codex round 1+2): a scratchpad write failure must
    fail-SAFE to the FULL body, never fail-open to a truncated projection
    pointing at a key that was never actually written -- that combination is
    total, silent data loss (the model sees a pointer to nothing). The full
    body is frozen in its OWN frozen_full_fallbacks map (fix-cycle 2) as-is
    (never re-attempted/recomputed on a later rebuild), because stable-prefix
    requires this call_id's context text to never change again once decided
    -- but it must not be mistaken for a successful offload."""

    @pytest.mark.asyncio
    async def test_write_failure_returns_and_freezes_the_full_body(self) -> None:
        raw = "F" * 40_000
        outcome = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=100_000,
            scratchpad_provider=_FailingProvider(),
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        assert outcome.text == raw  # FULL body, not a truncated projection
        assert outcome.offloaded is False  # nothing was actually offloaded
        assert outcome.frozen_full_fallbacks["c1"] == raw  # frozen, own map
        assert "c1" not in outcome.frozen_projections  # NEVER in the success map

    @pytest.mark.asyncio
    async def test_write_failure_is_stable_across_repeated_resolution(self) -> None:
        """A write failure's fallback must ALSO be frozen/stable -- a second
        rebuild for the same call_id must reproduce the same full body, not
        retry the write or recompute a (possibly different) truncation."""
        raw = "F" * 40_000
        first = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=100_000,
            scratchpad_provider=_FailingProvider(),
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        second = await resolve_tool_result_offload(
            call_id="c1",
            result="a different fresh result -- must be IGNORED, frozen wins",
            context_window_tokens=100_000,
            scratchpad_provider=_FailingProvider(),
            scratch_read_available=True,
            frozen_projections=first.frozen_projections,
            frozen_full_fallbacks=first.frozen_full_fallbacks,
        )
        assert second.text == raw
        assert second.frozen_projections == first.frozen_projections
        assert second.frozen_full_fallbacks == first.frozen_full_fallbacks

    @pytest.mark.asyncio
    async def test_fallback_never_counts_as_offloaded_on_reuse(self) -> None:
        """Reusing an already-frozen fallback (2nd+ resolution) must ALSO
        report offloaded=False -- a fallback is never "offloaded", on first
        computation or on any later verbatim reuse."""
        raw = "F" * 40_000
        first = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=100_000,
            scratchpad_provider=_FailingProvider(),
            scratch_read_available=True,
            frozen_projections={},
            frozen_full_fallbacks={},
        )
        second = await resolve_tool_result_offload(
            call_id="c1",
            result=raw,
            context_window_tokens=100_000,
            scratchpad_provider=_FailingProvider(),
            scratch_read_available=True,
            frozen_projections=first.frozen_projections,
            frozen_full_fallbacks=first.frozen_full_fallbacks,
        )
        assert second.offloaded is False
