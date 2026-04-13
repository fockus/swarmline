"""Unit tests for SystemReminderFilter — conditional context injection.

Covers RMND-01..04:
- RMND-01: Conditional context blocks injected by trigger conditions
- RMND-02: Reminder budget capped (default 500 tokens)
- RMND-03: Priority ordering under budget pressure
- RMND-04: Implemented via InputFilter, no ThinRuntime.run() changes
"""

from __future__ import annotations

from typing import Callable

import pytest

from swarmline.input_filters import InputFilter
from swarmline.runtime.types import Message
from swarmline.system_reminder_filter import SystemReminder, SystemReminderFilter


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


def _reminder(
    id: str,
    content: str,
    priority: int = 0,
    trigger: Callable[[list[Message], str], bool] | None = None,
    token_estimate: int | None = None,
) -> SystemReminder:
    return SystemReminder(
        id=id,
        content=content,
        priority=priority,
        trigger=trigger,
        token_estimate=token_estimate,
    )


# ---------------------------------------------------------------------------
# Protocol compliance (RMND-04)
# ---------------------------------------------------------------------------


class TestSystemReminderFilterProtocol:
    def test_implements_input_filter_protocol(self) -> None:
        f = SystemReminderFilter(reminders=[])
        assert isinstance(f, InputFilter)


# ---------------------------------------------------------------------------
# Trigger evaluation (RMND-01)
# ---------------------------------------------------------------------------


class TestReminderTriggers:
    @pytest.mark.asyncio
    async def test_reminder_always_active_when_no_trigger(self) -> None:
        """Reminder with trigger=None is always included."""
        r = _reminder("r1", "always on")
        f = SystemReminderFilter(reminders=[r])

        _, prompt = await f.filter([_msg("user", "hi")], "base")

        assert "always on" in prompt

    @pytest.mark.asyncio
    async def test_reminder_trigger_true_included(self) -> None:
        """Reminder with trigger returning True is included."""
        r = _reminder("r1", "conditional on", trigger=lambda msgs, sp: True)
        f = SystemReminderFilter(reminders=[r])

        _, prompt = await f.filter([_msg("user", "hi")], "base")

        assert "conditional on" in prompt

    @pytest.mark.asyncio
    async def test_reminder_trigger_false_excluded(self) -> None:
        """Reminder with trigger returning False is excluded."""
        r = _reminder("r1", "conditional off", trigger=lambda msgs, sp: False)
        f = SystemReminderFilter(reminders=[r])

        _, prompt = await f.filter([_msg("user", "hi")], "base")

        assert "conditional off" not in prompt

    @pytest.mark.asyncio
    async def test_reminder_no_match_passthrough(self) -> None:
        """When no reminders are active, system_prompt is unchanged."""
        r = _reminder("r1", "nope", trigger=lambda msgs, sp: False)
        f = SystemReminderFilter(reminders=[r])

        _, prompt = await f.filter([_msg("user", "hi")], "base prompt")

        assert prompt == "base prompt"


# ---------------------------------------------------------------------------
# Budget enforcement (RMND-02)
# ---------------------------------------------------------------------------


class TestReminderBudget:
    @pytest.mark.asyncio
    async def test_reminder_budget_cap_500_tokens(self) -> None:
        """Total injected tokens must not exceed default 500-token budget."""
        # Each reminder ~250 tokens (1000 chars / 4.0 chars_per_token)
        # 3 reminders = 750 tokens, budget = 500 → at most 2 fit
        reminders = [
            _reminder("r1", "A" * 1000, priority=1),
            _reminder("r2", "B" * 1000, priority=2),
            _reminder("r3", "C" * 1000, priority=3),
        ]
        f = SystemReminderFilter(reminders=reminders)

        _, prompt = await f.filter([], "base")

        # Count how many reminder blocks were injected
        block_count = prompt.count("<system-reminder")
        assert block_count == 2

    @pytest.mark.asyncio
    async def test_reminder_custom_budget(self) -> None:
        """Custom budget_tokens is respected."""
        # 100 chars = 25 tokens. Budget = 30 → only 1 fits
        reminders = [
            _reminder("r1", "X" * 100, priority=1),
            _reminder("r2", "Y" * 100, priority=2),
        ]
        f = SystemReminderFilter(reminders=reminders, budget_tokens=30)

        _, prompt = await f.filter([], "base")

        block_count = prompt.count("<system-reminder")
        assert block_count == 1

    @pytest.mark.asyncio
    async def test_reminder_all_exceed_budget_keeps_highest_priority(self) -> None:
        """If even one reminder exceeds budget, the highest-priority one is still included."""
        # Single reminder = 500 tokens but budget = 10
        r = _reminder("r1", "Z" * 2000, priority=5)
        f = SystemReminderFilter(reminders=[r], budget_tokens=10)

        _, prompt = await f.filter([], "base")

        # Must include at least the highest priority reminder
        assert '<system-reminder id="r1">' in prompt

    @pytest.mark.asyncio
    async def test_reminder_token_estimate_auto_calculated(self) -> None:
        """When token_estimate is None, it is auto-calculated from content length."""
        # 200 chars / 4.0 = 50 tokens. Budget = 40 → exceeds, but highest-prio rule keeps it
        r = _reminder("r1", "W" * 200)
        f = SystemReminderFilter(reminders=[r], budget_tokens=40)

        _, prompt = await f.filter([], "base")

        # Auto-estimated at 50 tokens, but guaranteed at least one
        assert '<system-reminder id="r1">' in prompt


# ---------------------------------------------------------------------------
# Priority ordering (RMND-03)
# ---------------------------------------------------------------------------


class TestReminderPriority:
    @pytest.mark.asyncio
    async def test_reminder_priority_ordering_under_pressure(self) -> None:
        """Under budget pressure, highest-priority reminders are kept."""
        # Each ~50 tokens. Budget = 60 → only 1 fits
        reminders = [
            _reminder("low", "L" * 200, priority=1),
            _reminder("high", "H" * 200, priority=10),
            _reminder("mid", "M" * 200, priority=5),
        ]
        f = SystemReminderFilter(reminders=reminders, budget_tokens=60)

        _, prompt = await f.filter([], "base")

        assert '<system-reminder id="high">' in prompt
        assert '<system-reminder id="low">' not in prompt

    @pytest.mark.asyncio
    async def test_priority_order_in_output(self) -> None:
        """Reminders appear in priority order (highest first) in the prompt."""
        reminders = [
            _reminder("low", "lo", priority=1, token_estimate=1),
            _reminder("high", "hi", priority=10, token_estimate=1),
            _reminder("mid", "md", priority=5, token_estimate=1),
        ]
        f = SystemReminderFilter(reminders=reminders, budget_tokens=500)

        _, prompt = await f.filter([], "base")

        pos_high = prompt.index('id="high"')
        pos_mid = prompt.index('id="mid"')
        pos_low = prompt.index('id="low"')
        assert pos_high < pos_mid < pos_low


# ---------------------------------------------------------------------------
# Output format (RMND-01 / RMND-04)
# ---------------------------------------------------------------------------


class TestReminderOutputFormat:
    @pytest.mark.asyncio
    async def test_reminder_injected_as_system_reminder_block(self) -> None:
        """Each reminder is wrapped in <system-reminder id="X">...</system-reminder>."""
        r = _reminder("ctx1", "important context")
        f = SystemReminderFilter(reminders=[r])

        _, prompt = await f.filter([], "base")

        assert '<system-reminder id="ctx1">\nimportant context\n</system-reminder>' in prompt

    @pytest.mark.asyncio
    async def test_reminder_appended_to_system_prompt(self) -> None:
        """Reminder blocks are appended after the original system prompt."""
        r = _reminder("r1", "extra", token_estimate=1)
        f = SystemReminderFilter(reminders=[r])

        _, prompt = await f.filter([], "original prompt")

        assert prompt.startswith("original prompt")
        assert "extra" in prompt

    @pytest.mark.asyncio
    async def test_reminder_messages_not_modified(self) -> None:
        """Messages list is returned unchanged — filter only modifies system_prompt."""
        r = _reminder("r1", "ctx")
        f = SystemReminderFilter(reminders=[r])
        msgs = [_msg("user", "hello"), _msg("assistant", "world")]

        result_msgs, _ = await f.filter(msgs, "base")

        assert result_msgs is msgs  # identity check — not just equality


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestReminderEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_reminders_passthrough(self) -> None:
        """No reminders → system_prompt unchanged."""
        f = SystemReminderFilter(reminders=[])

        _, prompt = await f.filter([_msg("user", "hi")], "base")

        assert prompt == "base"

    @pytest.mark.asyncio
    async def test_explicit_token_estimate_used(self) -> None:
        """When token_estimate is set, it overrides auto-calculation."""
        # Content is 1000 chars (auto = 250 tokens), but estimate says 10
        # Budget = 20 → fits with explicit estimate, wouldn't fit with auto
        r = _reminder("r1", "X" * 1000, priority=1, token_estimate=10)
        f = SystemReminderFilter(reminders=[r], budget_tokens=20)

        _, prompt = await f.filter([], "base")

        assert '<system-reminder id="r1">' in prompt

    @pytest.mark.asyncio
    async def test_empty_system_prompt_with_reminders(self) -> None:
        """Works correctly when base system_prompt is empty."""
        r = _reminder("r1", "injected", token_estimate=1)
        f = SystemReminderFilter(reminders=[r])

        _, prompt = await f.filter([], "")

        assert '<system-reminder id="r1">' in prompt
        assert "injected" in prompt
