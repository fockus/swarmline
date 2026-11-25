"""Per-round context refresh for the ReAct loop (Sprint 1ce CE-9).

``ThinRuntime.run()`` compacts and recites once, before the loop; a long run
outgrows the window mid-way. Before model rounds 2..N this module:

* compacts the STRUCTURED view (``messages`` + ``new_messages``: tool units stay
  atomic) with the SAME filter the startup step used (shared anti-thrashing
  history) down to ``threshold - round_hysteresis_tokens`` and rebuilds the LM
  projection — between compactions the projection is append-only (prompt cache);
* places the LIVE plan as a ``<plan-recitation>`` turn (``round_recitation``:
  appended on its cadence, or replacing the tail before every round);
* budgets on the provider's ``prompt_tokens`` of the last call plus an estimate
  of what was appended since (ref: hermes 2026-09-27), else the plain estimate.

``new_messages`` is never modified. Compaction is off for the run when the
projection holds entries the structured view lacks (lm-only resume/producers).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from swarmline.context.budget import (
    estimate_image_tokens,
    estimate_message_tokens,
    estimate_tokens,
)
from swarmline.domain_types import Message
from swarmline.runtime.thin.helpers import _messages_to_lm
from swarmline.runtime.thin.round_recitation import (
    RECITATION_TIMEOUT_SECONDS,
    PlanProvider,
    RecitationMode,
    RecitationTail,
)
from swarmline.runtime.thin.tool_result_render import ToolResultRendering
from swarmline.runtime.thin.usage import add_call_usage

if TYPE_CHECKING:
    from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
    from swarmline.runtime.types import RuntimeConfig

logger = logging.getLogger(__name__)

__all__ = ["RECITATION_TIMEOUT_SECONDS", "PlanProvider", "RoundContextRefresher"]
# RuntimeConfig hooks whose output lands ONLY in the LM projection; a rebuild
# from the structured view would silently drop it.
_LM_ONLY_PRODUCERS = (
    "get_steering_messages",
    "get_followup_messages",
    "transform_context",
    "recovery_cascade",
)


@dataclass(frozen=True)
class RoundRefreshOutcome:
    """What ``before_round`` did; ``lm_messages`` is what the model gets next."""

    lm_messages: list[dict[str, Any]]
    compacted: bool = False
    recited: bool = False
    tokens_before: int = 0
    tokens_after: int = 0


def _estimate_lm(lm_messages: list[dict[str, Any]]) -> int:
    return sum(
        estimate_tokens(str(m.get("content", "")))
        + estimate_image_tokens(m.get("content_blocks"))
        for m in lm_messages
    )


class RoundContextRefresher:
    """Refreshes the LM projection before model rounds 2..N of ONE run."""

    def __init__(
        self,
        *,
        compaction_filter: ConversationCompactionFilter | None = None,
        compaction_config: CompactionConfig | None = None,
        plan_provider: PlanProvider | None = None,
        recitation_cadence: int = 0,
        recitation_timeout_seconds: float = RECITATION_TIMEOUT_SECONDS,
        recitation_mode: RecitationMode = "append",
    ) -> None:
        both = compaction_filter is not None and compaction_config is not None
        self._filter = compaction_filter if both else None
        self._config = compaction_config if both else None
        self._recitation = RecitationTail(
            plan_provider,
            mode=recitation_mode,
            cadence=recitation_cadence,
            timeout=recitation_timeout_seconds,
        )
        self._compaction_disabled: str | None = None
        # Structured view after the last round compaction (None: the run's input).
        self._base: list[Message] | None = None
        self._consumed = 0
        self._anchor: tuple[int, int] | None = None
        self._rendering = ToolResultRendering()  # CE-24: how a rebuild renders results

    @property
    def compression_history(self) -> list[dict[str, int]]:
        """The shared filter's anti-thrashing history (for the run checkpoint)."""
        return self._filter.compression_history if self._filter is not None else []

    def start_run(
        self, config: RuntimeConfig, *, resumed: bool, auto_verify: bool
    ) -> str | None:
        """Turn round compaction off if a rebuild would be lossy; the status text."""
        self._rendering = ToolResultRendering.from_config(config)
        if self._filter is None:
            return None
        producers = [n for n in _LM_ONLY_PRODUCERS if getattr(config, n) is not None]
        if auto_verify:
            producers.append("auto_verify_loop")
        if resumed:
            reason = "run resumed from an lm-only checkpoint"
        elif producers:
            reason = "lm-only producers configured: " + ", ".join(producers)
        else:
            return None
        self._compaction_disabled = reason
        logger.warning("round_compaction.disabled: %s", reason)
        return f"round compaction disabled: {reason}"

    def observe_call(self, usage: Mapping[str, Any] | None, request_len: int) -> None:
        """Anchor the budget on the provider's count of the request just sent."""
        prompt_tokens = usage.get("prompt_tokens") if usage else None
        if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool):
            self._anchor = (prompt_tokens, request_len)
        else:
            self._anchor = None

    def estimate_budget(
        self, lm_messages: list[dict[str, Any]], system_prompt: str
    ) -> int:
        """Anchor + estimate of what was appended since, else the full estimate."""
        if self._anchor is not None and self._anchor[1] <= len(lm_messages):
            prompt_tokens, request_len = self._anchor
            return prompt_tokens + _estimate_lm(lm_messages[request_len:])
        return estimate_tokens(system_prompt) + _estimate_lm(lm_messages)

    async def before_round(
        self,
        *,
        round_index: int,
        lm_messages: list[dict[str, Any]],
        messages: list[Message],
        new_messages: list[Message],
        system_prompt: str,
    ) -> RoundRefreshOutcome:
        """Refresh before 1-based ``round_index`` (round 1: startup compacted
        already; only a ``replace_tail`` recitation acts on it)."""
        first = round_index < 2
        if first and not self._recitation.every_round:
            return RoundRefreshOutcome(lm_messages)
        fresh = await self._recitation.fetch(round_index)
        result, before, after, compacted = lm_messages, 0, 0, False
        if not first and self._config is not None and self._compaction_disabled is None:
            before = self.estimate_budget(lm_messages, system_prompt)
            if before > self._config.effective_threshold_tokens:
                rebuilt = await self._compact(
                    messages, new_messages, system_prompt, before
                )
                if rebuilt is not None:
                    result, compacted = rebuilt, True
        result = self._recitation.place(result, fresh, compacted=compacted)
        if compacted:
            after = estimate_tokens(system_prompt) + _estimate_lm(result)
            self._log_compaction(round_index, before, after)
        return RoundRefreshOutcome(
            lm_messages=result,
            compacted=compacted,
            recited=fresh is not None,
            tokens_before=before,
            tokens_after=after,
        )

    async def _compact(
        self,
        messages: list[Message],
        new_messages: list[Message],
        system_prompt: str,
        budget: int,
    ) -> list[dict[str, Any]] | None:
        assert self._filter is not None and self._config is not None
        base = self._base if self._base is not None else messages
        structured = [*base, *new_messages[self._consumed :]]
        threshold = self._config.effective_threshold_tokens
        # Never below half the threshold; minus what the structured estimate misses
        # (tool-call rendering, tool schemas when anchored on provider usage).
        target = max(threshold - self._config.round_hysteresis_tokens, threshold // 2)
        structured_tokens = estimate_tokens(system_prompt) + sum(
            estimate_message_tokens(m) for m in structured
        )
        overhead = max(budget - structured_tokens, 0)
        compacted, _ = await self._filter.filter(
            structured, system_prompt, target_tokens=max(target - overhead, 1)
        )
        if compacted == structured:
            return None
        self._base = compacted
        self._consumed = len(new_messages)
        self._anchor = None
        return _messages_to_lm(compacted, rendering=self._rendering)

    def _log_compaction(self, round_index: int, before: int, after: int) -> None:
        tier = self._filter.last_tier if self._filter is not None else None
        fields = {"compaction_round": round_index, "tier": tier}
        fields.update(tokens_before=before, tokens_after=after)
        logger.info("compaction.round %s", fields, extra=fields)


def build_round_context_refresher(
    config: RuntimeConfig,
    compaction_filter: ConversationCompactionFilter | None,
) -> RoundContextRefresher | None:
    """A refresher for one run, or None when neither mechanism is opted into:
    ``CompactionConfig.per_round`` (with the run's filter), or a callable
    ``native_config["recitation_plan_provider"]`` with a positive
    ``recitation_round_cadence`` or ``recitation_mode="replace_tail"`` (every
    round, cadence ignored). A static plan text never opts in (stale mid-run).
    """
    compaction = config.compaction
    per_round = bool(compaction and compaction.per_round and compaction_filter)
    provider = config.native_config.get("recitation_plan_provider")
    cadence_raw = config.native_config.get("recitation_round_cadence")
    cadence = cadence_raw if type(cadence_raw) is int else 0  # bool excluded
    mode = config.native_config.get("recitation_mode")
    replace_tail = mode == "replace_tail"
    recite = callable(provider) and (cadence > 0 or replace_tail)
    if not per_round and not recite:
        return None
    return RoundContextRefresher(
        compaction_filter=compaction_filter if per_round else None,
        compaction_config=compaction if per_round else None,
        plan_provider=provider if recite else None,
        recitation_cadence=cadence if recite else 0,
        recitation_mode="replace_tail" if replace_tail else "append",
    )


def track_call_usage(
    refresher: RoundContextRefresher | None,
    run_usage: dict[str, int] | None,
    usage: Mapping[str, Any] | None,
    request_len: int,
) -> dict[str, int] | None:
    """Record one model call: re-anchor the refresher's budget, add to run usage."""
    if refresher is not None:
        refresher.observe_call(usage, request_len)
    return add_call_usage(run_usage, usage)
