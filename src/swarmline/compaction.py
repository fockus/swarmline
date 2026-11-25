"""3-tier conversation compaction via InputFilter protocol.

Tier 1: Collapse old tool call/result pairs into compact summaries.
Tier 2: LLM summarization of oldest conversation segments.
Tier 3: Emergency truncation (drop oldest messages until under budget).

Usage::

    from swarmline.compaction import CompactionConfig, ConversationCompactionFilter

    config = CompactionConfig(threshold_tokens=80_000, preserve_recent_pairs=3)
    compaction = ConversationCompactionFilter(config=config)
    messages, system_prompt = await compaction.filter(messages, system_prompt)
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from swarmline.compaction_gate import (
    ARTIFACT_KEY,
    MIN_SAVINGS_RATIO,
    STRUCTURED_SUMMARY_SECTIONS as _STRUCTURED_SUMMARY_SECTIONS,
    SUMMARY_PREFIX as _SUMMARY_PREFIX,
    SummaryAcceptanceGate,
    build_summary_body,
    is_summary_message,
    previous_llm_part,
    render_transcript,
    savings_ratio,
    tier3_protected_indices,
)
from swarmline.compaction_turns import (
    latest_human_request_index,
    verbatim_budget_chars,
)
from swarmline.context.budget import (
    estimate_image_tokens,
    estimate_message_tokens,
    estimate_tokens,
)
from swarmline.domain_types import Message

logger = logging.getLogger(__name__)

# Max chars of ORDINARY (non-error) tool result to include in collapsed
# summary. Error-bearing results are exempt entirely (see _collapse_snippet
# — codex R2 [2]: Manus rule 6 / keep-errors-in-context must be truly
# verbatim, not merely "a bigger cap", since Tier 2 reads Tier 1's output).
_SNIPPET_MAX_CHARS = 100

_SUMMARIZE_PROMPT = """\
Summarize this conversation segment concisely (max 500 tokens).
Preserve: key decisions, tool call results, project instructions, task state.
Format: continuous text, third person.
"""

# Ступень A (Stage 6) — no-LLM dedup + templated one-liners.
DEDUP_MIN_CHARS = 200
DUPLICATE_TOOL_OUTPUT_MARKER = "[Duplicate tool output]"

# Threshold arithmetic: effective = window - max_output_reserve, floored for
# small windows (OpenClaw 16k-model pitfall: a reserve that eats nearly the
# whole window must never drive the target down to ~0 and cause the agent to
# stay in perpetual emergency-compaction mode across turns).
DEFAULT_MAX_OUTPUT_RESERVE_TOKENS = 8_000
MIN_EFFECTIVE_THRESHOLD_TOKENS = 2_000

# Anti-thrashing cooldown — in-run analog of taskloom's
# application/services/conversation_distiller.py compression_history
# (same numbers, same algorithm; ported, not imported — swarmline stays
# zero-coupled to taskloom and this filter operates on ephemeral in-run
# messages, not taskloom's persisted cross-run Conversation history).
ANTI_THRASHING_WINDOW = 2
# The cooldown lifts once the context has grown this much since the last
# recorded attempt -- derived from the persisted history, so resume-safe.
COOLDOWN_REGROWTH_RATIO = 0.25

#: Reserved OSS-T4 checkpoint key (resilience/checkpoint.py substrate) for the
#: Tier-2 anti-thrashing compression_history — distinct from every other
#: reserved key (`_step`, `_total_steps`, `_tool_schema_snapshot`,
#: `_tool_result_offload`, `_tool_result_offload_fallbacks`). Loaded/persisted
#: by the CALLER (runtime.py's compaction step, react_strategy.py's
#: load-before-persist-block sites) — this filter itself performs no I/O.
CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY = "_compaction_compression_history"

# Ступень C — structured summary with fixed sections + iterative UPDATE.
# Sections/prefix/savings arithmetic live in compaction_gate (re-exported).
_STRUCTURED_SUMMARY_PROMPT_FRESH = """\
Summarize this conversation segment into a structured continuity digest.
Respond with EXACTLY these sections, one per line, no extra headers:
Goal: <overall objective>
Constraints: <hard requirements/limits>
Progress: <what has been done so far>
Key Decisions: <agreements/choices made, and WHY>
Errors: <errors encountered, verbatim where possible, or 'none'>
Files: <files/paths touched or relevant, or 'none'>
Next Steps: <what remains to be done>
Rule: never mark the verbatim user request as done — the run owner resumes it.
"""
_STRUCTURED_SUMMARY_PROMPT_UPDATE_TEMPLATE = """\
Update the structured continuity digest below using the new conversation \
segment. For each section: PRESERVE facts that are still true and not \
mentioned again, ADD new facts from the new segment, UPDATE facts that have \
changed. Respond with EXACTLY these sections, one per line, no extra headers:
Goal: <overall objective>
Constraints: <hard requirements/limits>
Progress: <what has been done so far>
Key Decisions: <agreements/choices made, and WHY>
Errors: <errors encountered, verbatim where possible, or 'none'>
Files: <files/paths touched or relevant, or 'none'>
Next Steps: <what remains to be done>
Rule: never mark the verbatim user request as done — the run owner resumes it.

<previous-summary>
{previous_summary}
</previous-summary>
"""


class SummarizerAbortError(Exception):
    """Raise from ``llm_call`` to signal an auth/network failure.

    Compaction ABORTS (propagates this exception out of ``filter()``) rather
    than falling back to a local summary — the conversation history is left
    completely untouched this pass (Stage 6 safe-fail contract). Stdlib
    ``TimeoutError``/``ConnectionError``/``OSError`` raised directly by an
    unwrapped ``llm_call`` are treated the same way, so callers don't have to
    know about this class just to signal a network failure.
    """


_ABORT_EXCEPTIONS: tuple[type[Exception], ...] = (
    SummarizerAbortError,
    TimeoutError,
    ConnectionError,
    OSError,
)


def read_compression_history_checkpoint(
    d: dict[str, object] | None, key: str
) -> list[dict[str, int]]:
    """Fail-safe read of a persisted compression_history list from an OSS-T4
    checkpoint dict.

    Returns ``[]`` when ``d`` is ``None``, the key is absent, the value is
    not a list, or ANY entry doesn't match the exact
    ``{"tokens_before": int, "tokens_after": int}`` shape -- a malformed or
    foreign checkpoint value is treated as "no history yet" rather than
    crashing downstream (same fail-safe contract as
    ``react_strategy._read_frozen_offload_projections``).
    """
    if d is None:
        return []
    v = d.get(key)
    if not isinstance(v, list):
        return []
    result: list[dict[str, int]] = []
    for entry in v:
        if not isinstance(entry, dict):
            return []
        # ty narrows bare `isinstance(entry, dict)` to `dict[Never, Never]`
        # (no key/value type hints available from the runtime check alone),
        # so a literal-string .get() key reads as a type mismatch even
        # though it's correct at runtime for any dict.
        tokens_before = entry.get("tokens_before")  # ty: ignore[invalid-argument-type]  # bare-dict isinstance narrows to Never
        tokens_after = entry.get("tokens_after")  # ty: ignore[invalid-argument-type]  # bare-dict isinstance narrows to Never
        if not isinstance(tokens_before, int) or not isinstance(tokens_after, int):
            return []
        result.append({"tokens_before": tokens_before, "tokens_after": tokens_after})
    return result


def _build_structured_summary_prompt(previous_summary: str | None) -> str:
    """Ступень C: fixed-section prompt, fresh or iterative UPDATE."""
    if previous_summary is None:
        return _STRUCTURED_SUMMARY_PROMPT_FRESH
    return _STRUCTURED_SUMMARY_PROMPT_UPDATE_TEMPLATE.format(
        previous_summary=previous_summary
    )


# codex R2 [3b] / R3 [3]: a degenerate-but-non-empty response ("Summary.",
# bare "Goal:", or pure punctuation of sufficient LENGTH like "."*20) must
# not be silently accepted just because str.strip() is truthy or the raw
# character count crosses some threshold -- there has to be actual
# meaningful content, counted in WORDS, not characters.
_MIN_SUMMARY_WORDS = 3
_SUMMARY_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+")


def _looks_like_valid_summary(summary: str) -> bool:
    """Structural validation: strip out any recognized fixed-section label
    (``_STRUCTURED_SUMMARY_SECTIONS``, e.g. "Goal:") first -- a bare label
    with nothing after it must not count as content just because a label
    substring matched (codex R3 [3]). What remains must contain at least
    ``_MIN_SUMMARY_WORDS`` alphanumeric words -- this rejects both a bare
    label AND pure-punctuation filler of any length, while still accepting
    a real structured summary (labels + real content) and a substantive
    plain-prose summary (no labels at all -- backward compat with mock
    summaries used throughout the test suite)."""
    residual = summary
    for section in _STRUCTURED_SUMMARY_SECTIONS:
        residual = re.sub(rf"(?i){re.escape(section)}\s*:", "", residual)
    return len(_SUMMARY_WORD_PATTERN.findall(residual)) >= _MIN_SUMMARY_WORDS


_ERROR_LINE_PATTERN = re.compile(r"error|exception|traceback|failed", re.IGNORECASE)


def _build_local_fallback_summary_text(
    compactable: list[Message], previous_summary: str | None
) -> str:
    """Deterministic, non-LLM structured summary (safe-fail).

    Mechanically derived from the region — no model call. Errors are kept
    VERBATIM (grep-style) per the safe-fail contract; everything else that
    genuinely requires understanding falls back to an explicit
    "unavailable" marker rather than guessing.
    """
    goal = next(
        (m.content[:200] for m in compactable if m.role == "user"),
        "(unknown — summarizer unavailable)",
    )
    # codex R1 [3 MAJOR]: no arbitrary cap — errors are THE thing this
    # fallback must never lose (Manus rule 6 is the whole point of Stage 6);
    # anything still oversized is bounded downstream by Tier 3, not here.
    error_lines = [
        m.content for m in compactable if _ERROR_LINE_PATTERN.search(m.content)
    ]
    errors_section = "; ".join(error_lines) if error_lines else "none"
    files = sorted(
        {
            (m.metadata or {}).get("tool_call")
            for m in compactable
            if m.role == "assistant" and m.metadata and "tool_call" in m.metadata
        }
        - {None}
    )
    files_section = ", ".join(files) if files else "none"
    fresh_digest = (
        f"Goal: {goal}\n"
        "Constraints: (unavailable — local fallback, no LLM)\n"
        f"Progress: {len(compactable)} messages compacted without LLM (local fallback)\n"
        "Key Decisions: (unavailable — local fallback)\n"
        f"Errors: {errors_section}\n"
        f"Files: {files_section}\n"
        "Next Steps: (unavailable — local fallback)"
    )
    if previous_summary is None:
        return fresh_digest
    # codex R1 [3 MAJOR] / R2 [3c]: preserve the PRIOR summary's real
    # content VERBATIM -- no .strip() or any other transformation (there's
    # no LLM available to merge it) instead of just noting "updated" and
    # silently discarding/altering it -- losing (or even just whitespace-
    # normalizing) it would defeat the whole point of Ступень C's iterative
    # UPDATE the moment the summarizer degrades even once.
    return (
        f"{previous_summary}\n\n"
        "--- new segment (local fallback, no LLM to merge) ---\n"
        f"{fresh_digest}"
    )


@dataclass(frozen=True)
class CompactionConfig:
    """Configuration for conversation compaction pipeline."""

    enabled: bool = True
    threshold_tokens: int = 80_000
    preserve_recent_pairs: int = 3
    tier_1_enabled: bool = True
    tier_2_enabled: bool = True
    tier_3_enabled: bool = True
    # Ступень A: hash-dedup of identical tool results >= DEDUP_MIN_CHARS, plus
    # templated one-liners for tools declared reproducible/re-callable.
    # codex R1 [4 MAJOR]: opt-in (default False) — a caller who only ever set
    # threshold_tokens/preserve_recent_pairs (the pre-Stage-6 surface) must
    # get byte-identical Tier 1/2/3 behaviour, not a silently-added new tier.
    dedup_enabled: bool = False
    compactable_tool_names: frozenset[str] = field(default_factory=frozenset)
    # Threshold arithmetic — opt-in (None preserves pre-Stage-6 behaviour
    # byte-identically for every caller that only ever sets threshold_tokens).
    context_window_tokens: int | None = None
    max_output_reserve_tokens: int = DEFAULT_MAX_OUTPUT_RESERVE_TOKENS
    # Rendered as the summary's "## Context Recovery" section when set (e.g. a
    # host that exposes a history-search tool); None renders no section.
    recovery_hint: str | None = None
    # CE-9: re-check the budget before every model round of a ReAct run (not only
    # once per run) and compact down to threshold - round_hysteresis_tokens, so
    # the next round does not compact again right away. Opt-in (False keeps the
    # once-per-run behaviour byte-identical); see runtime/thin/round_context.py.
    per_round: bool = False
    round_hysteresis_tokens: int = 8_000

    @property
    def effective_threshold_tokens(self) -> int:
        """min(threshold_tokens, window - reserve), floored for tiny windows."""
        if self.context_window_tokens is None:
            return self.threshold_tokens
        window_based = max(
            self.context_window_tokens - self.max_output_reserve_tokens,
            MIN_EFFECTIVE_THRESHOLD_TOKENS,
        )
        return min(self.threshold_tokens, window_based)


class ConversationCompactionFilter:
    """3-tier conversation compaction implementing the InputFilter protocol.

    Tier 1 — collapse old tool call/result pairs into single summary messages.
    Tier 2 — LLM-based summarization of oldest conversation segment (Task 2).
    Tier 3 — emergency truncation: drop oldest messages (Task 2).
    """

    def __init__(
        self,
        config: CompactionConfig | None = None,
        llm_call: Callable[[str, str], Awaitable[str]] | None = None,
        compression_history: list[dict[str, int]] | None = None,
    ) -> None:
        self._config = config or CompactionConfig()
        self._llm_call = llm_call
        # Anti-thrashing history is caller-owned: loaded (e.g. from a
        # checkpoint) before construction, read back via the
        # ``compression_history`` property after ``filter()`` for the caller
        # to persist. This instance is short-lived (one per run() call).
        self._compression_history: list[dict[str, int]] = list(
            compression_history or []
        )
        # The deepest tier the last ``filter()`` call reached (None: under budget).
        self.last_tier: str | None = None

    @property
    def compression_history(self) -> list[dict[str, int]]:
        """Copy of the tracked Tier-2 (LLM) compression attempt history."""
        return list(self._compression_history)

    async def filter(
        self,
        messages: list[Message],
        system_prompt: str,
        *,
        target_tokens: int | None = None,
    ) -> tuple[list[Message], str]:
        """Apply compaction tiers until messages fit within token budget.

        ``target_tokens`` overrides the budget for this call (the per-round
        refresher compacts below the threshold, by its hysteresis).
        """
        self.last_tier = None
        if not self._config.enabled or not messages:
            return messages, system_prompt

        # codex R2 [3a]: captured BEFORE any tier runs. On ABORT, the TRUE
        # original input is returned -- never whatever Tier 0/1 already
        # produced. "History untouched" means untouched by THIS filter()
        # call entirely, not merely "no LLM output embedded".
        original_messages = messages

        threshold = (
            target_tokens
            if target_tokens is not None
            else self._config.effective_threshold_tokens
        )
        total = self._estimate_total(messages, system_prompt)
        if total <= threshold:
            return messages, system_prompt

        # Tier 0 (Ступень A): no-LLM dedup + templated one-liners — cheapest,
        # always attempted before any tier that costs an LLM call or drops
        # information outright.
        if self._config.dedup_enabled:
            self.last_tier = "dedup"
            messages = self._dedup_and_templatize(messages)
            total = self._estimate_total(messages, system_prompt)
            if total <= threshold:
                return messages, system_prompt

        # Tier 1: collapse old tool call/result pairs
        if self._config.tier_1_enabled:
            self.last_tier = "collapse"
            messages = self._collapse_tool_results(messages)
            total = self._estimate_total(messages, system_prompt)
            if total <= threshold:
                return messages, system_prompt

        # Tier 2: LLM summarization of oldest messages — gated by an
        # anti-thrashing cooldown (skip the LLM call, not the safety net).
        if self._config.tier_2_enabled and self._llm_call is not None:
            if self._tier2_thrashing(total):
                logger.info(
                    "Tier 2 skipped — anti-thrashing cooldown active "
                    "(last %d compactions each saved < %.0f%%)",
                    ANTI_THRASHING_WINDOW,
                    MIN_SAVINGS_RATIO * 100,
                )
            else:
                self.last_tier = "summary"
                tokens_before_tier2 = total
                try:
                    messages = await self._summarize_oldest(messages, system_prompt)
                    total = self._estimate_total(messages, system_prompt)
                    self._record_tier2_attempt(tokens_before_tier2, total)
                    if total <= threshold:
                        return messages, system_prompt
                except _ABORT_EXCEPTIONS:
                    # Safe-fail (codex R1 [3 MAJOR], corrected R2 [3a]):
                    # auth/network failure -> ABORT the WHOLE cascade this
                    # pass (skip Tier 3 too) and return the TRUE ORIGINAL
                    # input (from before Tier 0/1 ran too), UNCHANGED --
                    # never raise. A raised exception would crash the
                    # caller's run() entirely; returning the true original
                    # keeps the run alive (over budget this one turn is
                    # recoverable, a crashed run is not) and never risks
                    # embedding a corrupt/partial LLM response OR a partial
                    # Tier 0/1 transformation the caller never asked to keep
                    # on a pass that ultimately failed. Not recorded in
                    # compression_history -- no attempt was completed.
                    logger.warning(
                        "Tier 2 summarizer aborted (auth/network-class "
                        "failure) — returning the true original input, "
                        "history completely untouched",
                        exc_info=True,
                    )
                    return original_messages, system_prompt
                except Exception:
                    logger.warning(
                        "Tier 2 LLM summarization failed, using a local "
                        "(non-LLM) fallback summary",
                        exc_info=True,
                    )
                    # A rejected fallback returns the pre-Tier-2 messages, so the
                    # attempt is recorded with zero savings (feeds anti-thrashing).
                    messages = self._local_fallback_summary(messages, system_prompt)
                    total = self._estimate_total(messages, system_prompt)
                    self._record_tier2_attempt(tokens_before_tier2, total)
                    if total <= threshold:
                        return messages, system_prompt

        # Tier 3: emergency truncation — drop oldest until under budget
        if self._config.tier_3_enabled:
            self.last_tier = "truncate"
            messages = self._emergency_truncate(messages, system_prompt, threshold)

        return messages, system_prompt

    def _tier2_thrashing(self, current_tokens: int) -> bool:
        """True when the last ANTI_THRASHING_WINDOW Tier-2 attempts each
        saved less than MIN_SAVINGS_RATIO — cooldown, skip the LLM call —
        until the context grows by COOLDOWN_REGROWTH_RATIO past the last
        attempt (new material may now be worth summarizing)."""
        recent = [
            savings_ratio(r["tokens_before"], r["tokens_after"])
            for r in self._compression_history
        ][-ANTI_THRASHING_WINDOW:]
        if len(recent) < ANTI_THRASHING_WINDOW or any(
            r >= MIN_SAVINGS_RATIO for r in recent
        ):
            return False
        last_before = self._compression_history[-1]["tokens_before"]
        return current_tokens < last_before * (1 + COOLDOWN_REGROWTH_RATIO)

    def _record_tier2_attempt(self, tokens_before: int, tokens_after: int) -> None:
        self._compression_history.append(
            {"tokens_before": tokens_before, "tokens_after": tokens_after}
        )
        self._compression_history = self._compression_history[-ANTI_THRASHING_WINDOW:]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _estimate_total(self, messages: list[Message], system_prompt: str) -> int:
        """Estimate total tokens for system prompt + all messages."""
        total = estimate_tokens(system_prompt)
        for m in messages:
            total += estimate_message_tokens(m)
        return total

    def _find_tool_groups(self, messages: list[Message]) -> list[tuple[int, list[int]]]:
        """Find (assistant_index, [tool_result_indices]) groups.

        Recognizes BOTH shapes (codex R1 [1 CRITICAL] fix):
        - legacy text-ReAct: assistant with ``metadata["tool_call"]`` (single
          tool name) immediately followed by exactly 1 tool-role result.
        - native tool-calling: assistant with ``tool_calls`` (a list of N
          entries) immediately followed by exactly N tool-role results, one
          per call, in order.

        A native assistant message only counts as a group when ALL N
        expected result slots are actually present and tool-role —
        otherwise (truncated/malformed) it is treated as UNGROUPED
        (fail-safe: claiming no pairing beats claiming a wrong one).
        """
        groups: list[tuple[int, list[int]]] = []
        i = 0
        n = len(messages)
        while i < n:
            msg = messages[i]
            if msg.role != "assistant":
                i += 1
                continue
            if msg.tool_calls:
                k = len(msg.tool_calls)
                result_indices = list(range(i + 1, i + 1 + k))
                if result_indices[-1] < n and all(
                    messages[idx].role == "tool" for idx in result_indices
                ):
                    groups.append((i, result_indices))
                    i += 1 + k
                    continue
                i += 1
                continue
            if (
                msg.metadata
                and "tool_call" in msg.metadata
                and i + 1 < n
                and messages[i + 1].role == "tool"
            ):
                groups.append((i, [i + 1]))
                i += 2
                continue
            i += 1
        return groups

    def _find_contiguous_tool_units(self, messages: list[Message]) -> list[list[int]]:
        """Broader than ``_find_tool_groups`` (codex R2 [1]): ANY assistant
        message that looks like a tool-call initiator (non-empty
        ``tool_calls`` OR ``metadata["tool_call"]``) plus ALL CONTIGUOUS
        tool-role messages immediately following it — REGARDLESS of whether
        the count matches the declared number of calls exactly.

        ``_find_tool_groups``'s strict N-match is still what dedup/
        templating uses (correct per-call tool-name attribution needs an
        exact match). But for cut/drop ATOMICITY (Tier 3 truncation,
        ``_protected_indices``, the preserve-boundary) a partial/malformed
        native group must still never orphan whatever tool-role messages
        DID survive: even when ``_find_tool_groups`` fail-safes into
        "ungrouped" because the call count doesn't match, the assistant and
        its actual (possibly incomplete) run of tool-role followers must
        move/drop TOGETHER. For any WELL-FORMED group this produces the
        exact same unit as ``_find_tool_groups`` — purely additive safety.
        """
        units: list[list[int]] = []
        i = 0
        n = len(messages)
        while i < n:
            msg = messages[i]
            is_tool_initiator = msg.role == "assistant" and (
                bool(msg.tool_calls)
                or (msg.metadata is not None and "tool_call" in msg.metadata)
            )
            if is_tool_initiator:
                j = i + 1
                # codex R3 [1] note: this run absorbs EVERY contiguous
                # tool-role message after the initiator, with no attempt to
                # disambiguate which ones "really" belong to a malformed/
                # partial call count -- on well-formed input this is exactly
                # the initiator's own N results (identical to
                # ``_find_tool_groups``). On malformed input it is
                # intentionally CONSERVATIVE (over-grouping, never
                # under-grouping): the goal here is orphan-prevention for
                # cut/drop atomicity, not precise per-call attribution (that
                # precision lives in ``_find_tool_groups`` and is used only
                # by dedup/templating, never by this method's callers).
                while j < n and messages[j].role == "tool":
                    j += 1
                if j > i + 1:
                    units.append(list(range(i, j)))
                    i = j
                    continue
            i += 1
        return units

    def _protected_indices(self, messages: list[Message]) -> set[int]:
        """Indices that must never be dropped/collapsed/rewritten away.

        A message tagged ``metadata.non_compactable=True`` is protected
        directly. A tool call/result unit is an ATOMIC unit for this
        purpose: tagging ANY member protects the WHOLE unit, so the
        cut-point invariant (never split a tool_use/tool_result unit) holds
        even under inconsistent caller tagging AND under a partial/
        malformed native group (codex R2 [1] — uses the broader contiguous-
        run concept, not the strict N-match).
        """
        protected: set[int] = {
            i
            for i, msg in enumerate(messages)
            if msg.metadata and msg.metadata.get("non_compactable")
        }
        latest = latest_human_request_index(messages)
        # Текстовая сводка не может заменить изображение текущего запроса.
        if latest is not None and estimate_image_tokens(
            messages[latest].content_blocks
        ):
            protected.add(latest)
        for unit in self._find_contiguous_tool_units(messages):
            if any(idx in protected for idx in unit):
                protected.update(unit)
        return protected

    def _pair_safe_preserve_boundary(
        self, messages: list[Message], preserve_count: int
    ) -> int:
        """Extend ``preserve_count`` when the region/preserved cut would
        otherwise fall INSIDE a tool call/result(s) unit (part of the unit
        dropped into the region, part kept in preserved) — cut-point
        invariant holds at tier boundaries too, not just for explicitly-
        tagged messages. Uses the broader contiguous-run concept (codex R2
        [1]), so a partial/malformed native group is protected too, not
        just a strictly-matched one."""
        if preserve_count >= len(messages):
            return preserve_count
        cut_index = len(messages) - preserve_count
        best = preserve_count
        for unit in self._find_contiguous_tool_units(messages):
            lo, hi = unit[0], unit[-1]
            if lo < cut_index <= hi:
                best = max(best, len(messages) - lo)
        return best

    def _split_for_summarization(
        self, messages: list[Message]
    ) -> (
        tuple[list[Message], list[tuple[int, Message]], int, list[Message], str | None]
        | None
    ):
        """Shared Tier-2 split: (compactable, non_compactable_with_pos,
        summary_insert_pos, preserved, previous_summary), or ``None`` when
        there is nothing new to compact.

        ``non_compactable_with_pos`` keeps each protected message's ORIGINAL
        position in ``region`` (codex R1 [5 MAJOR]: reassembly must preserve
        relative order, never cluster every non_compactable message right
        after the summary regardless of where it actually sat).
        ``summary_insert_pos`` is the position of the FIRST compactable
        message — where the single summary message replaces the whole
        compactable run once reassembled (see ``_reassemble_region``).
        ``previous_summary`` is the text of an earlier ``[Conversation
        summary]`` message that has aged back into the compaction region
        (Ступень C iterative UPDATE) — extracted and excluded from
        ``compactable`` so it is never re-quoted as raw dialog.
        """
        preserve_count = max(1, self._config.preserve_recent_pairs * 2 + 1)
        preserve_count = self._pair_safe_preserve_boundary(messages, preserve_count)
        if len(messages) <= preserve_count:
            return None

        # region is a prefix of messages, so its indices equal absolute
        # indices in `messages` — protected_indices computed on the full
        # list lines up directly with region's own positions.
        protected_indices = self._protected_indices(messages)
        region = messages[:-preserve_count]
        preserved = list(messages[-preserve_count:])

        compactable: list[Message] = []
        non_compactable_with_pos: list[tuple[int, Message]] = []
        previous_summary: str | None = None
        summary_insert_pos: int | None = None
        for idx, msg in enumerate(region):
            if idx in protected_indices:
                # codex R6b: symmetric to the tail-guard below -- a
                # protected message that is ITSELF a prior summary
                # (pathological externally-protected case; a summary this
                # filter builds itself is never non_compactable) must stay
                # the SOLE/authoritative one. `non_compactable_with_pos`
                # already keeps it from being removed/rewritten, but that
                # alone isn't enough: a FRESH summary would still get built
                # from the rest of the region and land right next to it
                # after reassembly (both exempt from
                # `_merge_adjacent_system_messages`), violating "at most
                # one summary". So bail out of compacting THIS pass
                # entirely, same as the tail-guard does.
                if is_summary_message(msg):
                    return None
                non_compactable_with_pos.append((idx, msg))
            elif previous_summary is None and is_summary_message(msg):
                previous_summary = previous_llm_part(msg)
            else:
                compactable.append(msg)
                if summary_insert_pos is None:
                    summary_insert_pos = idx

        # codex R5: the prior summary can just as easily have aged into the
        # PRESERVED TAIL instead of the compactable region (the cut
        # boundary doesn't know or care where a summary message sits). If
        # it's not in the region, look for it in the tail too -- and, once
        # found, DROP it from `preserved` so the result never carries BOTH
        # the stale prior summary AND the freshly-UPDATEd one side by side
        # (exactly one summary must survive per pass, regardless of WHERE
        # the prior one physically sat).
        #
        # codex R6: a summary found in the tail that is ITSELF tagged
        # ``metadata.non_compactable=True`` must NEVER be removed --
        # protected messages are never removed/rewritten, full stop. In
        # normal flow a summary message is never non_compactable (neither
        # ``_summarize_oldest`` nor ``_local_fallback_summary`` ever sets
        # metadata on the ones they build); this only covers the
        # pathological case of an externally-protected summary. Skipping
        # the deletion alone isn't enough, though: building a FRESH summary
        # for the region would still land it right next to this protected
        # one, violating "at most one summary" from the other direction.
        # So this pass compacts NOTHING at all here -- the protected
        # summary is treated as the sole/authoritative one, and no
        # competing summary is created (matches the ``None`` "nothing new
        # to compact" contract used elsewhere in this method).
        if previous_summary is None:
            for tail_idx, msg in enumerate(preserved):
                if is_summary_message(msg):
                    if msg.metadata and msg.metadata.get("non_compactable"):
                        return None
                    previous_summary = previous_llm_part(msg)
                    del preserved[tail_idx]
                    break

        if not compactable or summary_insert_pos is None:
            return None
        return (
            compactable,
            non_compactable_with_pos,
            summary_insert_pos,
            preserved,
            previous_summary,
        )

    @staticmethod
    def _reassemble_region(
        non_compactable_with_pos: list[tuple[int, Message]],
        summary_insert_pos: int,
        summary_msg: Message,
    ) -> list[Message]:
        """Rebuild the compacted region: non_compactable messages stay at
        their ORIGINAL relative position, the summary is inserted exactly
        where the compactable run started (codex R1 [5 MAJOR] — positions
        and interleaving are preserved, never clustered)."""
        items = [*non_compactable_with_pos, (summary_insert_pos, summary_msg)]
        items.sort(key=lambda pair: pair[0])
        return [msg for _pos, msg in items]

    @staticmethod
    def _merge_adjacent_system_messages(messages: list[Message]) -> list[Message]:
        """Post-reassembly safety net (codex R2 [5]): position-preserving
        reassembly can legitimately place a protected (non_compactable)
        system-role message directly next to the newly-inserted summary
        (also system-role). Merges any RUN of adjacent NON-SUMMARY
        system-role messages into ONE (content joined by newline, metadata
        unioned, nothing lost) -- non-system messages are never touched,
        reordered, or considered.

        codex R4: the summary message itself (content starting with
        ``_SUMMARY_PREFIX``) is NEVER merged into a neighbor, on either
        side. Fix-cycle 3's [4] merged protected+summary together (forcing
        ``non_compactable=True`` on the result) to satisfy R2 [5] -- but
        that made ``_split_for_summarization`` classify the WHOLE merged
        message as protected on the NEXT pass, so the summary text was
        never extracted as ``previous_summary`` for the Stage C iterative
        UPDATE (two summaries would silently stack instead of merging).
        The DoD invariant is narrowed here to "no two collapsed-
        placeholder/summary messages stacked back to back", NOT "a
        protected system message can never sit next to the summary" --
        those are semantically DIFFERENT kinds of system content, and the
        Anthropic API auto-merges consecutive same-role messages
        server-side with no information loss (as it already does for
        consecutive user-role messages), so leaving them as two adjacent,
        SEPARATE messages is safe and keeps the summary independently
        extractable.

        codex R3 [4] (still valid for non-summary runs): metadata dicts
        are unioned (later message's keys win on conflict); ``non_
        compactable`` is forced ``True`` on the merged result if ANY
        member of the run had it set.
        """
        result: list[Message] = []
        i = 0
        n = len(messages)
        while i < n:
            msg = messages[i]
            is_mergeable_system = msg.role == "system" and not msg.content.startswith(
                _SUMMARY_PREFIX
            )
            if is_mergeable_system:
                run = [msg]
                j = i + 1
                # A compaction artifact never merges with a non-artifact
                # system message: protected system text must not be
                # re-rendered as quoted data (and vice versa).
                is_artifact = bool((msg.metadata or {}).get(ARTIFACT_KEY))
                while (
                    j < n
                    and messages[j].role == "system"
                    and not messages[j].content.startswith(_SUMMARY_PREFIX)
                    and bool((messages[j].metadata or {}).get(ARTIFACT_KEY))
                    == is_artifact
                ):
                    run.append(messages[j])
                    j += 1
                if j > i + 1:
                    merged_metadata: dict[str, Any] | None = None
                    for m in run:
                        if m.metadata:
                            merged_metadata = {**(merged_metadata or {}), **m.metadata}
                    if any(
                        m.metadata and m.metadata.get("non_compactable") for m in run
                    ):
                        merged_metadata = {
                            **(merged_metadata or {}),
                            "non_compactable": True,
                        }
                    result.append(
                        Message(
                            role="system",
                            content="\n".join(m.content for m in run),
                            metadata=merged_metadata,
                        )
                    )
                else:
                    result.append(msg)
                i = j
            else:
                result.append(msg)
                i += 1
        return result

    async def _summarize_oldest(
        self, messages: list[Message], system_prompt: str = ""
    ) -> list[Message]:
        """Tier 2: Summarize oldest messages via LLM call.

        Replaces oldest messages with a single structured-summary system
        message (Ступень C — fixed sections, iterative UPDATE against any
        prior summary aged back into the region). Preserves the last
        ``preserve_recent_pairs * 2 + 1`` messages (recent tool pairs + at
        least 1 trailing message). Messages with ``metadata.non_compactable=
        True`` skip summarization and are preserved in their original
        position. Raises on LLM failure OR gate rejection (caller catches /
        applies safe-fail).
        """
        split = self._split_for_summarization(messages)
        if split is None:
            return messages
        prompt = _build_structured_summary_prompt(split[4])
        summary = await self._llm_call(prompt, render_transcript(split[0]))  # ty: ignore[call-non-callable]  # Optional Callable gated by caller config
        # codex R1 [3 MAJOR] / R2 [3b]: an empty, non-string, OR structurally
        # degenerate response ("Summary.") is a FAILURE (-> local fallback).
        if (
            not isinstance(summary, str)
            or not summary.strip()
            or not _looks_like_valid_summary(summary)
        ):
            raise ValueError(
                f"Summarizer returned empty/invalid/degenerate output: {summary!r}"
            )
        accepted = self._gated_summary(messages, system_prompt, split, summary)
        if accepted is None:
            raise ValueError("Summarizer output rejected by the acceptance gate")
        return accepted

    def _local_fallback_summary(
        self, messages: list[Message], system_prompt: str = ""
    ) -> list[Message]:
        """Safe-fail: deterministic, non-LLM structured summary.

        Used when the summarizer raises anything OTHER than an auth/network
        failure (those ABORT instead — see ``_ABORT_EXCEPTIONS``) or its
        output is rejected. A fallback the gate rejects too is dropped:
        ``messages`` come back unchanged for Tier 3.
        """
        split = self._split_for_summarization(messages)
        if split is None:
            return messages
        text = _build_local_fallback_summary_text(split[0], split[4])
        return self._gated_summary(messages, system_prompt, split, text) or messages

    def _gated_summary(
        self, messages: list[Message], system_prompt: str, split: Any, llm_part: str
    ) -> list[Message] | None:
        """Build the summary message (verbatim request + LLM part + anchors),
        reassemble, and return it only if the acceptance gate passes."""
        compactable, non_compactable_with_pos, insert_pos, preserved, _ = split
        prior = next((m for m in messages if is_summary_message(m)), None)
        body, metadata, verbatim = build_summary_body(
            llm_part,
            compactable=compactable,
            prior=prior,
            recovery_hint=self._config.recovery_hint,
            verbatim_max_chars=verbatim_budget_chars(
                self._config.effective_threshold_tokens
            ),
        )
        summary_msg = Message(
            role="system", content=f"{_SUMMARY_PREFIX}{body}", metadata=metadata
        )
        region_result = self._reassemble_region(
            non_compactable_with_pos, insert_pos, summary_msg
        )
        # codex R2 [5]: same-role-adjacency safety net (the summary itself is never merged).
        result = self._merge_adjacent_system_messages([*region_result, *preserved])
        verdict = SummaryAcceptanceGate().check(
            body,
            llm_part=llm_part,
            region=[*compactable, *([prior] if prior else [])],
            tokens_before=self._estimate_total(messages, system_prompt),
            tokens_after=self._estimate_total(result, system_prompt),
            verbatim=verbatim,
        )
        if not verdict.accepted:
            logger.warning(
                "Tier 2 summary rejected by the acceptance gate: %s", verdict.reason
            )
            return None
        return result

    def _emergency_truncate(
        self,
        messages: list[Message],
        system_prompt: str,
        threshold_tokens: int,
    ) -> list[Message]:
        """Tier 3: Drop oldest messages until under budget.

        Always preserves the last message. Messages with
        ``metadata.non_compactable=True`` are never dropped. Tool call/result
        units are dropped or kept TOGETHER (never split — cut-point
        invariant), including when the unit straddles the guaranteed-last-
        message boundary, and including a partial/malformed native group
        (codex R2 [1] — uses the broader contiguous-run concept). System
        prompt tokens are counted against the budget but never truncated.
        O(n) performance.
        """
        protected = self._protected_indices(messages) | tier3_protected_indices(
            messages
        )
        last_idx = len(messages) - 1
        # index -> the full unit's index list it belongs to (covers native
        # multi-result groups AND partial/malformed ones, not just single
        # legacy pairs).
        group_of: dict[int, list[int]] = {}
        for unit in self._find_contiguous_tool_units(messages):
            for idx in unit:
                group_of[idx] = unit
        if last_idx in group_of:
            # The last message is always preserved; protect its WHOLE group
            # too so none of it gets orphaned.
            protected.update(group_of[last_idx])

        budget = threshold_tokens - estimate_tokens(system_prompt)
        if budget <= 0:
            forced_keep = [m for i, m in enumerate(messages[:-1]) if i in protected]
            return [*forced_keep, messages[-1]]

        # Group indices into drop UNITS: a lone message, or a whole tool
        # group (dropped together, never split apart).
        units: list[list[int]] = []
        grouped: set[int] = set()
        for i in range(len(messages) - 1):  # last message is never a drop candidate
            if i in grouped:
                continue
            unit = group_of.get(i)
            if unit is None or last_idx in unit:
                unit = [i]
            units.append(unit)
            grouped.update(unit)

        total = sum(estimate_message_tokens(m) for m in messages)
        dropped: set[int] = set()
        for unit in units:
            if total <= budget:
                break
            if any(idx in protected for idx in unit):
                continue
            for idx in unit:
                total -= estimate_message_tokens(messages[idx])
                dropped.add(idx)
        if total > budget:
            logger.warning(
                "Tier 3 left the context over budget: protected messages exceed it"
            )
        return [m for i, m in enumerate(messages) if i not in dropped]

    def _dedup_and_templatize(self, messages: list[Message]) -> list[Message]:
        """Ступень A (Stage 6, Tier 0) — no-LLM, cheapest pass.

        For each eligible (non-recent) tool call/result pair:
        - if the tool is declared ``compactable_tool_names`` (reproducible —
          the model can always re-call it), the result is ALWAYS replaced by a
          deterministic one-liner naming the tool + original size;
        - otherwise, if the result is >= ``DEDUP_MIN_CHARS`` and byte-identical
          to an earlier eligible result's content, it is replaced by
          ``DUPLICATE_TOOL_OUTPUT_MARKER`` (the first occurrence stays intact —
          it is the canonical copy the duplicate refers back to).

        Recent pairs (``preserve_recent_pairs``) and ``non_compactable``-tagged
        messages are never touched, mirroring Tier 1's own boundary so the
        whole cascade shares one "protected recent window" concept.
        """
        groups = self._find_tool_groups(messages)
        if not groups:
            return messages

        preserve = self._config.preserve_recent_pairs
        if preserve >= len(groups):
            return messages

        eligible = groups[: len(groups) - preserve]
        protected = self._protected_indices(messages)
        seen_hashes: set[str] = set()
        result = list(messages)
        changed = False

        for a_idx, t_indices in eligible:
            a_msg = result[a_idx]
            for t_idx in t_indices:
                if t_idx in protected:
                    continue
                t_msg = result[t_idx]
                content = t_msg.content
                tool_name = (a_msg.metadata or {}).get(
                    "tool_call", t_msg.name or "unknown"
                )

                if tool_name in self._config.compactable_tool_names:
                    templated = f"[{tool_name} result collapsed — {len(content)} chars, re-call to view]"
                    if templated != content:
                        result[t_idx] = Message(
                            role="tool",
                            content=templated,
                            name=t_msg.name,
                            metadata=t_msg.metadata,
                        )
                        changed = True
                    continue

                if len(content) >= DEDUP_MIN_CHARS:
                    content_hash = hashlib.sha256(content.encode()).hexdigest()
                    if content_hash in seen_hashes:
                        result[t_idx] = Message(
                            role="tool",
                            content=DUPLICATE_TOOL_OUTPUT_MARKER,
                            name=t_msg.name,
                            metadata=t_msg.metadata,
                        )
                        changed = True
                    else:
                        seen_hashes.add(content_hash)

        return result if changed else messages

    def _collapse_tool_results(self, messages: list[Message]) -> list[Message]:
        """Collapse old tool call/result groups into compact summary messages.

        Preserves the most recent ``preserve_recent_pairs`` groups intact.
        Consecutive collapsible groups are merged into ONE system message
        (codex R1 [2 MAJOR]: several adjacent system-role collapse markers
        is a defect, not accepted cascade behaviour) — one line per
        underlying tool result, never multiple separate system messages
        back to back. Error-bearing results keep a longer snippet than
        ordinary ones (Manus rule 6: keep errors in context).
        """
        groups = self._find_tool_groups(messages)
        if not groups:
            return messages

        preserve = self._config.preserve_recent_pairs
        if preserve >= len(groups):
            return messages

        protected = self._protected_indices(messages)
        eligible_groups: dict[int, list[int]] = {
            a_idx: t_indices
            for a_idx, t_indices in groups[: len(groups) - preserve]
            if not any(idx in protected for idx in (a_idx, *t_indices))
        }

        result: list[Message] = []
        i = 0
        n = len(messages)
        while i < n:
            if i in eligible_groups:
                run_lines: list[str] = []
                while i in eligible_groups:
                    t_indices = eligible_groups[i]
                    a_msg = messages[i]
                    tool_name = (a_msg.metadata or {}).get("tool_call")
                    for t_idx in t_indices:
                        t_msg = messages[t_idx]
                        name = tool_name or t_msg.name or "unknown"
                        run_lines.append(
                            f"[Collapsed tool call: {name}] {self._collapse_snippet(t_msg.content)}"
                        )
                    i = t_indices[-1] + 1
                result.append(
                    Message(
                        role="system",
                        content="\n".join(run_lines),
                        metadata={ARTIFACT_KEY: "collapsed"},
                    )
                )
            else:
                result.append(messages[i])
                i += 1

        return result

    @staticmethod
    def _collapse_snippet(content: str) -> str:
        """Tier-1 collapse snippet: error-bearing content is kept FULLY
        verbatim (codex R2 [2] — Tier 2 reads Tier 1's OUTPUT, not the
        original raw messages, so ANY cap here — even a generous one —
        would mean Tier 2's own "Errors: verbatim" section could only ever
        be verbatim relative to whatever survived Tier 1, never the true
        original). Ordinary (non-error) content keeps the tight cap so
        Tier 1 still actually shrinks normal content."""
        if _ERROR_LINE_PATTERN.search(content):
            return content
        return content[:_SNIPPET_MAX_CHARS]
