"""RecitationInputFilter -- Stage 5 (context-engineering-manus-parity): plan
re-injection by cadence of MEANINGFUL (human) turns.

Manus/Claude-Code canon: re-inject the run's plan/todo at the END of the
conversation periodically, so it stays salient once the middle of a long
context fills up with tool exchanges -- WITHOUT ever touching the STATIC
system prompt, which must stay byte-stable (Stage 1's stable-prefix
invariant; PlanningPromptModule on the host side stays guidance-text only).

Cadence is a PURE DERIVATIVE of the message history (count of ``role="user"``
``Message`` objects) -- never a separately persisted counter. A caller's own
conversation history already distinguishes genuine human turns from
tool-round bookkeeping (``Message.role`` is ``"tool"``/``"assistant"`` for
that, never ``"user"``), so this is deterministically recoverable after a
crash/restart for free: there is no separate state to restore at all.

Wired the same way as ``CodingContextInputFilter`` (Stage 3):
``RuntimeConfig.input_filters``, applied ONCE per ``ThinRuntime.run()``
invocation (before the internal ReAct loop starts), never per internal
tool-round iteration. Rounds 2..N of a ReAct run are covered separately, from
a LIVE plan provider, by ``swarmline.runtime.thin.round_context`` (Sprint 1ce
CE-9) — a static ``plan_text`` is never recited mid-run (it would be stale).
"""

from __future__ import annotations

from swarmline.domain_types import Message

#: Claude-Code-style cadence: recite on the FIRST human turn (full text), then
#: every Nth human turn thereafter (sparse text).
RECITATION_CADENCE: int = 5

_RECITATION_OPEN_TAG = "<plan-recitation>"
_RECITATION_CLOSE_TAG = "</plan-recitation>"


def render_plan_recitation(text: str) -> str:
    """The ``<plan-recitation>`` meta-turn body — one rendering shared by the
    per-run filter below and the per-round refresher (runtime/thin/round_context.py)."""
    return f"{_RECITATION_OPEN_TAG}\n{text}\n{_RECITATION_CLOSE_TAG}"


def count_human_turns(messages: list[Message]) -> int:
    """Count genuine user-authored turns in the conversation history.

    A pure derivative of ``messages`` -- never persisted separately, always
    recomputable from the caller's own conversation history, so it is
    automatically recoverable after a crash/restart.
    """
    return sum(1 for m in messages if m.role == "user")


def should_recite(human_turn_count: int, *, cadence: int = RECITATION_CADENCE) -> bool:
    """Whether THIS turn should carry a plan recitation.

    True on the FIRST human turn (``count == 1``) and every ``cadence``-th
    human turn thereafter (``count % cadence == 0``). False for zero/negative
    counts and every turn in between.
    """
    if human_turn_count <= 0:
        return False
    return human_turn_count == 1 or human_turn_count % cadence == 0


class RecitationInputFilter:
    """Append a plan/todo recitation as a meta user-turn at the END of
    ``messages``, on cadence, without ever mutating the STATIC system prompt.

    Byte-identical-when-off: if ``plan_text`` is blank/whitespace-only,
    ``filter()`` returns ``(messages, system_prompt)`` completely unchanged.

    Args:
        plan_text: Full plan/todo text, injected verbatim on the FIRST human
            turn.
        plan_summary_text: Sparser plan/todo text, injected on every
            subsequent cadence turn. Falls back to ``plan_text`` (full text
            every time) when ``None`` -- correct but not sparse; callers that
            want a smaller recitation on later turns must supply this.
        cadence: Human-turn cadence (default ``RECITATION_CADENCE``).
    """

    def __init__(
        self,
        *,
        plan_text: str,
        plan_summary_text: str | None = None,
        cadence: int = RECITATION_CADENCE,
    ) -> None:
        self._plan_text = plan_text
        self._plan_summary_text = (
            plan_summary_text if plan_summary_text is not None else plan_text
        )
        self._cadence = cadence

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        """Return ``(messages, system_prompt)``, appending a recitation
        message to ``messages`` on cadence turns; ``system_prompt`` is always
        returned UNCHANGED (Stage 1 stable-prefix invariant)."""
        if not self._plan_text.strip():
            return messages, system_prompt

        human_turns = count_human_turns(messages)
        if not should_recite(human_turns, cadence=self._cadence):
            return messages, system_prompt

        text = self._plan_text if human_turns == 1 else self._plan_summary_text
        recitation_message = Message(
            role="user",
            content=render_plan_recitation(text),
            metadata={"recitation": True},
        )
        return [*messages, recitation_message], system_prompt


__all__ = [
    "RECITATION_CADENCE",
    "RecitationInputFilter",
    "count_human_turns",
    "render_plan_recitation",
    "should_recite",
]
