"""Deterministic stop signals and the run time budget for the ReAct loop.

Opt-in (``native_config["loop_guards_enabled"] is True``); otherwise every hook is a
no-op. The model is warned before it is stopped: a repeated (tool, args, result) call
or a re-run of the pre-compaction tail warns once; the same kind of signal again
soft-lands with ``exit_reason="no_progress"``. An empty reply is nudged once, a second fails the run
with ``empty_model_response``. ``run_budget_seconds`` (from the start of THIS
execution) appends a wrap-up notice at 80%, soft-lands with ``exit_reason=
"time_budget"`` at 100% and caps each model call by what is left.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from swarmline.evolution.stuck_detector import (
    WINDOW_SIZE,
    StuckDetector,
    ToolCallRecord,
)
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.types import RuntimeConfig, RuntimeErrorData, RuntimeEvent

NO_PROGRESS_NOTICE = (
    "You are repeating the same call with the same result; change approach or finish."
)
EMPTY_REPLY_NOTICE = "Your previous reply was empty; answer or call a tool."
TIME_BUDGET_NOTICE = (
    "Time budget nearly exhausted: stop exploring and produce the final deliverable."
)
EMPTY_MODEL_RESPONSE = "empty_model_response"
_SUMMARY_ASK = (
    "Reply with a final summary: what you accomplished, what remains, and the next "
    "concrete step. Do not call any tools."
)
_LANDING_INSTRUCTIONS = {
    "no_progress": "You kept repeating the same tool call with the same result, "
    f"so tool calling has stopped. {_SUMMARY_ASK}",
    "time_budget": "The time budget for this run is exhausted, so tool calling has "
    f"stopped. {_SUMMARY_ASK}",
}
WRAP_UP_FRACTION = 0.8
POST_COMPACTION_REPEATS = 3

# Monotonic clock; tests patch this module attribute with a fake clock.
_monotonic: Callable[[], float] = time.monotonic


class RunTimeBudgetExceeded(ThinLlmError):
    """A model call was cut because the run's time budget ran out."""

    def __init__(self) -> None:
        message = "time_budget: run time budget exhausted"
        super().__init__(RuntimeErrorData(kind="budget_exceeded", message=message))


class LoopGuards:
    """Per-``run_react`` state of the stop signals. Inert unless enabled."""

    def __init__(self, *, enabled: bool = False, budget_seconds: float = 0.0) -> None:
        self.enabled = enabled
        self.stop_reason: str | None = None
        self._budget = budget_seconds if enabled else 0.0
        self._started = _monotonic()
        self._detector = StuckDetector()
        self._history: list[ToolCallRecord] = []
        self._warned: set[str] = set()  # signal kinds the model was already warned of
        self._pending: tuple[str, str] | None = None  # this round's (tool, kind)
        self._empty_streak = 0
        self._time_noticed = False
        self._landing = False
        self._pre_compaction_tail: frozenset[tuple[str, str, str | None]] = frozenset()
        self._post_compaction_hits = 0

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> LoopGuards:
        native = config.native_config
        if native.get("loop_guards_enabled") is not True:
            return cls()
        raw = native.get("run_budget_seconds")
        if isinstance(raw, bool) or not isinstance(raw, int | float) or raw <= 0:
            raw = 0.0  # 0 / invalid: no time budget, the other guards stay on
        return cls(enabled=True, budget_seconds=float(raw))

    def _expire(self) -> RunTimeBudgetExceeded:
        self.stop_reason = self.stop_reason or "time_budget"
        return RunTimeBudgetExceeded()

    def bound(self, llm_call: Callable[..., Any]) -> Callable[..., Any]:
        """Cap every model call by the remaining budget (the wrap-up call is exempt)."""
        if self._budget <= 0:
            return llm_call

        async def bounded(*args: Any, **kwargs: Any) -> Any:
            if self._landing:
                return await llm_call(*args, **kwargs)
            result = await self._within_budget(llm_call(*args, **kwargs))
            return self._stream(result) if hasattr(result, "__aiter__") else result

        return bounded

    async def _within_budget(self, awaitable: Any) -> Any:
        remaining = self._budget - (_monotonic() - self._started)
        if remaining <= 0:
            if (close := getattr(awaitable, "close", None)) is not None:
                close()  # never started: no "was never awaited" warning
            raise self._expire()
        try:
            async with asyncio.timeout(remaining) as scope:
                return await awaitable
        except TimeoutError:
            if not scope.expired():
                raise  # the call's own, shorter timeout: not the budget's
            raise self._expire() from None

    async def _stream(self, stream: Any) -> AsyncIterator[Any]:
        iterator = stream.__aiter__()
        while True:
            try:
                chunk = await self._within_budget(iterator.__anext__())
            except StopAsyncIteration:
                return
            yield chunk

    def before_call(self, lm_messages: list[dict[str, str]]) -> bool:
        """True when the loop must stop now; appends the 80% wrap-up notice once."""
        if not self.enabled:
            return False
        if self.stop_reason is None and self._budget > 0:
            elapsed = _monotonic() - self._started
            if elapsed >= self._budget:
                self.stop_reason = "time_budget"
            elif elapsed >= WRAP_UP_FRACTION * self._budget and not self._time_noticed:
                self._time_noticed = True
                lm_messages.append({"role": "user", "content": TIME_BUDGET_NOTICE})
        return self.stop_reason is not None

    def empty_reply(self, text: str, lm_messages: list[dict[str, str]]) -> bool:
        """True when the reply was empty: nudged once, a second one stops the run."""
        if not self.enabled or text.strip():
            self._empty_streak = 0
            return False
        self._empty_streak += 1
        if self._empty_streak >= 2:
            self.stop_reason = EMPTY_MODEL_RESPONSE
        else:
            lm_messages.append({"role": "user", "content": EMPTY_REPLY_NOTICE})
        return True

    def observe(self, tool_name: str, args: dict[str, Any], result: str) -> None:
        """Fingerprint one executed tool call (every call of a parallel batch)."""
        if not self.enabled:
            return
        record = ToolCallRecord(
            tool_name=tool_name,
            args_hash=ToolCallRecord.compute_args_hash(args),
            result_summary=str(result)[:100],
            result_hash=ToolCallRecord.compute_result_hash(result),
        )
        self._history.append(record)
        kind = "repeat" if self._detector.detect_latest_repeat(self._history) else None
        if self._pre_compaction_tail:
            known = record.repeat_key in self._pre_compaction_tail
            self._post_compaction_hits = self._post_compaction_hits + 1 if known else 0
            if self._post_compaction_hits >= POST_COMPACTION_REPEATS:
                self._pre_compaction_tail = frozenset()
                kind = kind or "compaction"
        if kind is not None and self._pending is None:  # one signal per round
            self._pending = (tool_name, kind)

    def flush(self, lm_messages: list[dict[str, str]]) -> RuntimeEvent | None:
        """End of a tool round: warn on the first signal of a kind, stop on its repeat.

        Kinds are counted apart: re-reading the pre-compaction tail after an earlier
        repeat warning is recovering lost context, so it only warns the first time."""
        pending, self._pending = self._pending, None
        if pending is None:
            return None
        tool_name, kind = pending
        if kind in self._warned:
            self.stop_reason = "no_progress"
            return None
        self._warned.add(kind)
        lm_messages.append({"role": "user", "content": NO_PROGRESS_NOTICE})
        return RuntimeEvent.status(f"loop_guard.warned: {tool_name}")

    def mark_compaction(self, lm_messages: list[dict[str, str]]) -> None:
        """A compaction rebuilt the projection: remember the tail before it (a re-run
        of it is a loop) and restore the lm-only wrap-up notice the rebuild dropped."""
        if not self.enabled:
            return
        tail = self._history[-WINDOW_SIZE:]
        self._pre_compaction_tail = frozenset(r.repeat_key for r in tail)
        self._post_compaction_hits = 0
        if self._time_noticed:
            lm_messages.append({"role": "user", "content": TIME_BUDGET_NOTICE})

    def landing(self, config: RuntimeConfig) -> dict[str, str] | None:
        """``_soft_landing_call`` kwargs, or None when the loop ends with an error."""
        reason = self.stop_reason
        if reason in _LANDING_INSTRUCTIONS:
            self._landing = True
            return {"exit_reason": reason, "instruction": _LANDING_INSTRUCTIONS[reason]}
        if (
            reason is None
            and config.native_config.get("loop_limit_soft_landing") is True
        ):
            self._landing = True  # the wrap-up call is never cut by the time budget
            return {}
        return None

    def stop_error(self) -> RuntimeErrorData | None:
        if self.stop_reason == EMPTY_MODEL_RESPONSE:
            return RuntimeErrorData(kind="bad_model_output", message=self.stop_reason)
        if self.stop_reason is not None:
            message = f"Run stopped by the loop guard: {self.stop_reason}"
            return RuntimeErrorData(kind="loop_limit", message=message)
        return None
