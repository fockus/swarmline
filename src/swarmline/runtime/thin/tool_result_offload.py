"""Tool-result offload — Stage 4 (context-engineering-manus-parity).

Filesystem as context (Manus "restorable compression"): a large tool result
is written to an external ``ScratchpadProvider`` and replaced in the context
with a restorable head+tail projection (summary text + scratch key + size)
-- never the full body. This module is the pure decision/projection half of
that contract, mirroring ``tool_schema_snapshot.py``'s shape: react_strategy.py
is the only caller, and it persists/reloads the frozen-projection set through
the SAME OSS-T4 checkpoint substrate (``CheckpointWriter``, keyed by
``run_id``) -- no new persistence mechanism, no taskloom coupling.

OpenClaw-derived constants: the plan text gives the stepped char threshold
(16k / 32k for >=100k-token windows) and the two ceiling ratios (0.3 per
result, 0.5 aggregate) directly; ``MIN_KEEP_CHARS`` is NOT sourced from
OpenClaw's exact literal (unavailable here) -- it is a documented best-effort
floor, open to adjustment.

Fix-cycle 1 (codex round 1): two behavioural corrections.
- (5, MAJOR) Below ``LARGE_WINDOW_TOKENS`` offload is COMPLETELY disabled
  (``resolve_offload_threshold_chars`` returns ``None``), not merely gated by
  a smaller (16k) threshold -- a small-window model's context is already
  tight enough that the scratchpad round-trip is not worth it below the
  window size OpenClaw itself gates offload on.
- (2, MINOR) ``AGGREGATE_SOFT_TARGET_RATIO`` (renamed from
  ``AGGREGATE_CEILING_RATIO``) is a SOFT target: ``MIN_KEEP_CHARS`` always
  wins over it. Offload always shrinks the inline footprint versus the raw
  body, so falling back to the full body when the soft target is exhausted
  would be strictly WORSE, not safer -- the floor intentionally overrides the
  target rather than the other way around.

Fix-cycle 2 (codex round 2): the 3a fail-safe fallback (full body kept inline
after a scratchpad write failure) and a SUCCESSFUL offload projection are now
tracked in two SEPARATE maps (``frozen_projections`` / ``frozen_full_fallbacks``),
not conflated into one ``dict[call_id, str]``:
- a write-failure fallback is verbatim-stable across rebuilds (same as
  before), but does NOT count against the aggregate soft target (there is no
  scratch key backing it -- counting it would shrink a LATER successful
  projection's budget for no reason), and does NOT count as "this run has
  successfully offloaded something" for the sticky scratch_read re-add in
  react_strategy.py (there is nothing to restore for it).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from swarmline.scratchpad.types import ScratchpadEntry

logger = logging.getLogger(__name__)

#: Reserved checkpoint state key for the frozen tool-result-offload projection
#: map (``dict[call_id, projection_text]``) -- mirrors
#: ``tool_schema_snapshot.CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT``. ONLY
#: successful offloads (a real scratch key was written) live here -- see
#: ``CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD_FALLBACKS`` for write-failure fallbacks.
CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD = "_tool_result_offload"

#: Reserved checkpoint state key for the SEPARATE write-failure full-body
#: fallback map (fix-cycle 2, codex round 2): kept apart from
#: ``CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD`` so a fallback (no real scratch key
#: behind it) never counts against the aggregate soft target and never
#: triggers the sticky scratch_read re-add in react_strategy.py.
CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD_FALLBACKS = "_tool_result_offload_fallbacks"

#: OpenClaw stepped threshold for windows >= LARGE_WINDOW_TOKENS. Below that
#: window size, offload is DISABLED entirely (see resolve_offload_threshold_chars) --
#: there is no smaller threshold; a "16k" step was the plan's ORIGINAL reading
#: of the OpenClaw ladder, but codex round 1 (fix-cycle 1, MAJOR-5) found that
#: enabling offload for windows too small to make the scratchpad round-trip
#: worthwhile was itself the bug -- corrected to a hard window gate instead.
OFFLOAD_THRESHOLD_CHARS_LARGE_WINDOW: int = 32_000

#: Window size (tokens) at/above which offload is enabled at all.
LARGE_WINDOW_TOKENS: int = 100_000

#: Floor: an offloaded projection is NEVER shrunk below this many characters,
#: even under aggregate soft-target pressure ("MIN_KEEP пол" in the plan
#: text). Best-effort literal (see module docstring) -- not sourced from OpenClaw.
MIN_KEEP_CHARS: int = 4_000

#: Fraction of the context window (chars) a SINGLE offloaded projection may occupy.
PER_RESULT_CEILING_RATIO: float = 0.3

#: Fraction of the context window ALL offloaded projections (this run, combined)
#: SHOULD occupy -- a SOFT target: MIN_KEEP_CHARS always wins over it (fix-cycle
#: 1, MINOR-2). Renamed from AGGREGATE_CEILING_RATIO to make that non-hardness
#: explicit in the name itself, not just in a comment.
AGGREGATE_SOFT_TARGET_RATIO: float = 0.5

#: chars-per-token approximation, matching context/budget.py's estimate_tokens/
#: truncate_to_budget convention -- reused, not reinvented.
_CHARS_PER_TOKEN: int = 4


class ScratchpadWriter(Protocol):
    """The single method this module needs from a ``ScratchpadProvider``."""

    async def write(
        self, key: str, content: str, tags: tuple[str, ...] = ()
    ) -> ScratchpadEntry:
        """Persist ``content`` under ``key``; return the stored entry."""


def resolve_offload_threshold_chars(context_window_tokens: int) -> int | None:
    """Char threshold above which a result is offloaded, or ``None`` when
    offload is disabled entirely for this window size (fix-cycle 1, MAJOR-5:
    below ``LARGE_WINDOW_TOKENS`` there is NO threshold at all -- every result
    passes through untouched, byte-identical to pre-Stage-4 behaviour)."""
    if context_window_tokens < LARGE_WINDOW_TOKENS:
        return None
    return OFFLOAD_THRESHOLD_CHARS_LARGE_WINDOW


def scratch_key_for_call(call_id: str) -> str:
    """Scratchpad key convention for an offloaded tool result: ``tool:<call_id>``."""
    return f"tool:{call_id}"


def _build_projection_text(result: str, keep_chars: int, *, key: str) -> str:
    """Build the restorable context projection for ``result``.

    - If the full result (plus the restoration marker) already fits within
      ``keep_chars``, it is returned UNCHANGED plus the marker appended --
      offload is governed purely by the THRESHOLD, not by whether truncation
      is strictly needed.
    - Otherwise: head+tail truncation, split evenly around the marker.
      Diagnostics (errors/tracebacks) commonly live at the END of a tool's
      output, so the TAIL is always kept alongside the head, never dropped.
    """
    total_len = len(result)
    marker = (
        f"\n... [offloaded: {total_len} chars, mime=text/plain, "
        f"scratch_read(key={key!r}) to restore full result] ...\n"
    )
    if total_len + len(marker) <= keep_chars:
        return result + marker

    available = max(keep_chars - len(marker), 0)
    head_len = available // 2
    tail_len = available - head_len
    head = result[:head_len]
    tail = result[-tail_len:] if tail_len > 0 else ""
    return head + marker + tail


_MARKER_RE = re.compile(
    r"\n\.\.\. \[offloaded: (?P<total>\d+) chars, mime=text/plain, "
    r"scratch_read\(key=(?P<key>'[^'\n]*')\) to restore full result\] \.\.\.\n"
)


def split_offload_projection(text: str, key: str) -> tuple[str, str, str] | None:
    """Split a projection built by ``_build_projection_text`` into (head, marker, tail).

    Only for text KNOWN to be an offload projection for ``key`` (the caller holds
    ``OffloadOutcome.offloaded``). The harness marker is identified by position, not
    by its text, so a look-alike marker inside the tool's own output stays in head
    or tail: fits-case -> the marker ends the text and ``len(text) == total + len``;
    truncated -> it starts at ``(len(text) - len(marker)) // 2``. ``None`` when no
    candidate sits there (callers then render the text as it is).
    """
    size = len(text)
    for match in _MARKER_RE.finditer(text):
        if match.group("key") != repr(key):
            continue
        width = match.end() - match.start()
        full = size == int(match.group("total")) + width
        if (full and match.end() == size) or (
            not full and match.start() == (size - width) // 2
        ):
            return text[: match.start()], match.group(0), text[match.end() :]
    return None


@dataclass(frozen=True)
class OffloadOutcome:
    """Outcome of ``resolve_tool_result_offload()`` for one tool result."""

    #: What goes into the context: either ``result`` untouched, or a
    #: restorable head+tail projection, or (write-failure fallback) the full
    #: body verbatim.
    text: str
    #: True only for a SUCCESSFUL offload (a real scratch key backs ``text``).
    #: False for passthrough AND for a write-failure fallback -- fallbacks are
    #: frozen/stable, but nothing was actually offloaded (fix-cycle 2).
    offloaded: bool
    #: Updated map of SUCCESSFUL offload projections to persist (unchanged
    #: object when nothing new was frozen this call). Counts against the
    #: aggregate soft target and triggers the sticky scratch_read re-add.
    frozen_projections: dict[str, str]
    #: Updated map of write-failure full-body fallbacks to persist (fix-cycle
    #: 2, codex round 2). Kept SEPARATE from ``frozen_projections``: a
    #: fallback has no scratch key behind it, so it must never count against
    #: the aggregate soft target and must never make react_strategy.py think
    #: "this run has successfully offloaded something" for the sticky
    #: scratch_read re-add -- there is nothing to restore for it.
    frozen_full_fallbacks: dict[str, str]


async def resolve_tool_result_offload(
    *,
    call_id: str,
    result: str,
    context_window_tokens: int,
    scratchpad_provider: ScratchpadWriter | None,
    scratch_read_available: bool,
    frozen_projections: dict[str, str],
    frozen_full_fallbacks: dict[str, str],
) -> OffloadOutcome:
    """Resolve the effective context text for one tool result.

    - Already frozen (either map) for this ``call_id`` -> return that text
      VERBATIM (byte-identical across every context rebuild), regardless of
      what a fresh computation would produce now. A successful-projection
      match is checked first (arbitrary but deterministic precedence; the two
      maps are mutually exclusive in practice -- a call_id is written to
      exactly one of them, never both).
    - Offload disabled for this window size (``resolve_offload_threshold_chars``
      returns ``None``), or the result is at/below the enabled threshold ->
      pass through untouched, never offloaded.
    - ``scratch_read`` is not available/enabled this run (Stage 3 pin/mask) ->
      offloading would break restorability, so this is a hard skip: pass
      through untouched. Restorability is a HARDER requirement than context
      size here -- an unrestorable truncation is strictly worse than a large
      but complete result.
    - ``scratchpad_provider`` is ``None`` -> same hard skip (nothing to write
      to; matches the byte-identical-when-off default).
    - Otherwise: compute a head+tail projection sized by the per-result
      ceiling / aggregate SOFT target (``MIN_KEEP_CHARS`` as an unconditional
      floor -- it always wins over the soft target, fix-cycle 1 MINOR-2).
      The soft-target accounting sums ONLY ``frozen_projections`` (fix-cycle 2,
      codex round 2, 3a-c): a write-failure fallback has no scratch key behind
      it, so counting its size here would shrink a LATER successful
      projection's budget for no reason -- budget corruption from an
      unrelated failure.
      Then attempt to persist the FULL body via ``scratchpad_provider.write()``.

      Fix-cycle 1 (CRITICAL-3a, codex round 1): a write failure is fail-SAFE
      to the FULL body, NOT fail-open to the truncated projection -- returning
      a projection that points at a key which was never actually written
      would be silent, total data loss (the model sees a pointer to nothing).
      The full body is frozen as-is (not the projection, and never retried on
      a later rebuild, and in its OWN ``frozen_full_fallbacks`` map, fix-cycle
      2): stable-prefix requires this call_id's context text to never change
      again once decided, so the fallback must be just as durable a decision
      as a successful offload -- but it must not be mistaken for one.
    """
    if call_id in frozen_projections:
        return OffloadOutcome(
            text=frozen_projections[call_id],
            offloaded=True,
            frozen_projections=frozen_projections,
            frozen_full_fallbacks=frozen_full_fallbacks,
        )
    if call_id in frozen_full_fallbacks:
        return OffloadOutcome(
            text=frozen_full_fallbacks[call_id],
            offloaded=False,
            frozen_projections=frozen_projections,
            frozen_full_fallbacks=frozen_full_fallbacks,
        )

    threshold = resolve_offload_threshold_chars(context_window_tokens)
    if threshold is None or len(result) <= threshold:
        return OffloadOutcome(
            text=result,
            offloaded=False,
            frozen_projections=frozen_projections,
            frozen_full_fallbacks=frozen_full_fallbacks,
        )

    if scratchpad_provider is None or not scratch_read_available:
        return OffloadOutcome(
            text=result,
            offloaded=False,
            frozen_projections=frozen_projections,
            frozen_full_fallbacks=frozen_full_fallbacks,
        )

    window_chars = context_window_tokens * _CHARS_PER_TOKEN
    per_result_ceiling = int(window_chars * PER_RESULT_CEILING_RATIO)
    soft_target = int(window_chars * AGGREGATE_SOFT_TARGET_RATIO)
    # fix-cycle 2 (3a-c): ONLY successful offloads count against the soft
    # target -- frozen_full_fallbacks is deliberately excluded from this sum.
    already_offloaded_chars = sum(len(v) for v in frozen_projections.values())
    remaining_soft_budget = max(soft_target - already_offloaded_chars, 0)
    keep_chars = max(MIN_KEEP_CHARS, min(per_result_ceiling, remaining_soft_budget))

    key = scratch_key_for_call(call_id)
    projection_text = _build_projection_text(result, keep_chars, key=key)

    try:
        await scratchpad_provider.write(key, result)
    except Exception:
        logger.error(
            "tool_result_offload: scratchpad write FAILED for key=%s -- "
            "fail-SAFE: keeping/freezing the FULL result inline (in the "
            "SEPARATE fallback map, not counted against budget or the sticky "
            "scratch_read re-add) instead of a truncated projection (which "
            "would point at a key that was never actually written -- total "
            "data loss)",
            key,
            exc_info=True,
        )
        updated_fallbacks = {**frozen_full_fallbacks, call_id: result}
        return OffloadOutcome(
            text=result,
            offloaded=False,
            frozen_projections=frozen_projections,
            frozen_full_fallbacks=updated_fallbacks,
        )

    updated_projections = {**frozen_projections, call_id: projection_text}
    return OffloadOutcome(
        text=projection_text,
        offloaded=True,
        frozen_projections=updated_projections,
        frozen_full_fallbacks=frozen_full_fallbacks,
    )


__all__ = [
    "AGGREGATE_SOFT_TARGET_RATIO",
    "CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD",
    "CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD_FALLBACKS",
    "LARGE_WINDOW_TOKENS",
    "MIN_KEEP_CHARS",
    "OFFLOAD_THRESHOLD_CHARS_LARGE_WINDOW",
    "PER_RESULT_CEILING_RATIO",
    "OffloadOutcome",
    "resolve_offload_threshold_chars",
    "resolve_tool_result_offload",
    "scratch_key_for_call",
    "split_offload_projection",
]
