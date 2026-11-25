"""Live plan recitation turns in the ReAct loop (Sprint 1ce CE-9, taskloom Stage 6).

Two modes of placing a ``<plan-recitation>`` turn in the LM projection:

* ``append`` (default): on the cadence, from round 2 on, the fresh turn is
  appended; older copies stay in the history (the pre-Stage-6 behaviour).
* ``replace_tail``: before EVERY round, round 1 included, the previous turn is
  removed by object identity and the fresh one becomes the last message. The
  prefix before the tail never changes between rounds (prompt cache); no marker
  keys are added to the message dict, so the provider payload stays clean.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from swarmline.context.recitation_input_filter import render_plan_recitation

logger = logging.getLogger(__name__)

RECITATION_TIMEOUT_SECONDS = 2.0
PlanProvider = Callable[[], Awaitable[str]]
RecitationMode = Literal["append", "replace_tail"]
RECITATION_MODES: tuple[RecitationMode, ...] = ("append", "replace_tail")
_FAILED = object()


class RecitationTail:
    """Fetches the live plan and places its recitation turn in the projection."""

    def __init__(
        self,
        provider: PlanProvider | None,
        *,
        mode: RecitationMode = "append",
        cadence: int = 0,
        timeout: float = RECITATION_TIMEOUT_SECONDS,
    ) -> None:
        self.mode: RecitationMode = mode if mode in RECITATION_MODES else "append"
        every_round = self.mode == "replace_tail"
        # Append mode with a non-positive cadence means no recitation at all.
        self._provider = provider if every_round or cadence > 0 else None
        self._cadence = cadence
        self._timeout = timeout
        self._last: dict[str, Any] | None = None  # append: re-placed after compaction
        self._placed: dict[str, Any] | None = (
            None  # replace_tail: the turn in the projection
        )
        self._blank = False  # replace_tail: the last read returned an empty list

    @property
    def every_round(self) -> bool:
        """True when round 1 is recited too (``replace_tail``)."""
        return self._provider is not None and self.mode == "replace_tail"

    async def fetch(self, round_index: int) -> dict[str, Any] | None:
        """The fresh turn when the round is due; None when not due or blank."""
        if self._provider is None:
            return None
        if self.mode == "append" and (round_index - 1) % self._cadence:
            return None
        text = await self._read()
        if text is _FAILED:
            return None
        if not isinstance(text, str) or not text.strip():
            self._blank = True
            return None
        self._blank = False
        fresh = {"role": "user", "content": render_plan_recitation(text)}
        if self.mode == "append":
            self._last = fresh
        return fresh

    def place(
        self,
        lm_messages: list[dict[str, Any]],
        fresh: dict[str, Any] | None,
        *,
        compacted: bool,
    ) -> list[dict[str, Any]]:
        """The projection the model gets with this round's recitation in place."""
        if self.mode == "append":
            if compacted:
                tail = self._last
                return [*lm_messages, *([tail] if tail is not None else [])]
            return [*lm_messages, fresh] if fresh is not None else lm_messages
        stale = self._placed
        kept = (
            [m for m in lm_messages if m is not stale]
            if stale is not None
            else list(lm_messages)
        )
        # A blank list clears the recitation; a failed read keeps the last known one.
        turn = fresh if fresh is not None else (None if self._blank else stale)
        self._placed = turn
        return [*kept, turn] if turn is not None else kept

    async def _read(self) -> object:
        assert self._provider is not None
        try:
            return await asyncio.wait_for(self._provider(), self._timeout)
        except Exception as exc:  # noqa: BLE001 - a plan store failure must not fail the run
            logger.warning("plan recitation skipped: %s", type(exc).__name__)
            return _FAILED
