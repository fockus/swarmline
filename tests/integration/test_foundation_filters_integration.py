"""Integration tests for Foundation Filters (Phase 11).

Validates that ProjectInstructionFilter and SystemReminderFilter work
correctly when wired into ThinRuntime via RuntimeConfig.input_filters.

Tests real component interaction — no mocks for internal components.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swarmline.input_filters import InputFilter, MaxTokensFilter
from swarmline.project_instruction_filter import ProjectInstructionFilter
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent
from swarmline.system_reminder_filter import SystemReminder, SystemReminderFilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


def _make_llm_call(capture: dict[str, Any]):
    """Create a fake llm_call that captures what it receives and returns valid JSON."""

    async def llm_call(
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        capture["messages"] = messages
        capture["system_prompt"] = system_prompt
        return '{"type": "final", "final_message": "ok"}'

    return llm_call


async def _collect_events(runtime: ThinRuntime, **kwargs: Any) -> list[RuntimeEvent]:
    events = []
    async for event in runtime.run(**kwargs):
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# 1. ProjectInstructionFilter in ThinRuntime pipeline
# ---------------------------------------------------------------------------


class TestProjectInstructionFilterPipeline:
    @pytest.mark.asyncio
    async def test_project_instructions_in_thin_runtime_pipeline(
        self, tmp_path: Path
    ) -> None:
        """ProjectInstructionFilter injects discovered content via RuntimeConfig."""
        (tmp_path / "CLAUDE.md").write_text("PROJECT_LEVEL_INSTRUCTIONS")
        captured: dict[str, Any] = {}

        instruction_filter = ProjectInstructionFilter(
            cwd=tmp_path, home=tmp_path / "fakehome"
        )
        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[instruction_filter],
        )
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        events = await _collect_events(
            runtime,
            messages=[_msg("user", "hello")],
            system_prompt="base prompt",
            active_tools=[],
        )

        assert "PROJECT_LEVEL_INSTRUCTIONS" in captured["system_prompt"]
        assert "base prompt" in captured["system_prompt"]
        assert any(e.is_final for e in events)

    @pytest.mark.asyncio
    async def test_project_instructions_prepended_before_base_prompt(
        self, tmp_path: Path
    ) -> None:
        """Instruction content is prepended — appears before base system prompt."""
        (tmp_path / "RULES.md").write_text("RULES_FIRST")
        captured: dict[str, Any] = {}

        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[
                ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "nohome")
            ],
        )
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        await _collect_events(
            runtime,
            messages=[_msg("user", "hi")],
            system_prompt="SYSTEM_BASE",
            active_tools=[],
        )

        prompt = captured["system_prompt"]
        rules_pos = prompt.index("RULES_FIRST")
        base_pos = prompt.index("SYSTEM_BASE")
        assert rules_pos < base_pos

    @pytest.mark.asyncio
    async def test_project_instructions_merge_all_same_level_in_repo_order(
        self, tmp_path: Path
    ) -> None:
        """All instruction files on one level are merged in AGENTS->RULES->CLAUDE order."""
        (tmp_path / "AGENTS.md").write_text("A")
        (tmp_path / "RULES.md").write_text("R")
        (tmp_path / "CLAUDE.md").write_text("C")
        captured: dict[str, Any] = {}

        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "nohome")],
        )
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        await _collect_events(
            runtime,
            messages=[_msg("user", "hi")],
            system_prompt="BASE",
            active_tools=[],
        )

        prompt = captured["system_prompt"]
        assert prompt.index("A") < prompt.index("R") < prompt.index("C") < prompt.index("BASE")


# ---------------------------------------------------------------------------
# 2. SystemReminderFilter in ThinRuntime pipeline
# ---------------------------------------------------------------------------


class TestSystemReminderFilterPipeline:
    @pytest.mark.asyncio
    async def test_system_reminders_in_thin_runtime_pipeline(self) -> None:
        """SystemReminderFilter injects <system-reminder> blocks via RuntimeConfig."""
        captured: dict[str, Any] = {}

        reminder = SystemReminder(
            id="ctx1", content="important context", token_estimate=10
        )
        reminder_filter = SystemReminderFilter(reminders=[reminder])

        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[reminder_filter],
        )
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        events = await _collect_events(
            runtime,
            messages=[_msg("user", "hello")],
            system_prompt="base prompt",
            active_tools=[],
        )

        assert '<system-reminder id="ctx1">' in captured["system_prompt"]
        assert "important context" in captured["system_prompt"]
        assert any(e.is_final for e in events)

    @pytest.mark.asyncio
    async def test_conditional_reminder_only_active_when_triggered(self) -> None:
        """Reminder with trigger=False is NOT injected into ThinRuntime pipeline."""
        captured: dict[str, Any] = {}

        inactive = SystemReminder(
            id="gated",
            content="should not appear",
            trigger=lambda msgs, sp: False,
            token_estimate=10,
        )
        reminder_filter = SystemReminderFilter(reminders=[inactive])

        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[reminder_filter],
        )
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        await _collect_events(
            runtime,
            messages=[_msg("user", "hello")],
            system_prompt="base prompt",
            active_tools=[],
        )

        assert "should not appear" not in captured["system_prompt"]
        assert captured["system_prompt"].startswith("base prompt")


# ---------------------------------------------------------------------------
# 3. Both filters combined in pipeline
# ---------------------------------------------------------------------------


class TestCombinedFiltersPipeline:
    @pytest.mark.asyncio
    async def test_both_filters_combined_pipeline(self, tmp_path: Path) -> None:
        """ProjectInstructionFilter + SystemReminderFilter work together.

        Instructions are prepended, reminders are appended — both present
        and in correct order relative to the base prompt.
        """
        (tmp_path / "CLAUDE.md").write_text("INSTRUCTION_BLOCK")
        captured: dict[str, Any] = {}

        instruction_filter = ProjectInstructionFilter(
            cwd=tmp_path, home=tmp_path / "fakehome"
        )
        reminder = SystemReminder(
            id="combined", content="REMINDER_BLOCK", token_estimate=10
        )
        reminder_filter = SystemReminderFilter(reminders=[reminder])

        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[instruction_filter, reminder_filter],
        )
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        events = await _collect_events(
            runtime,
            messages=[_msg("user", "hello")],
            system_prompt="BASE_PROMPT",
            active_tools=[],
        )

        prompt = captured["system_prompt"]

        # Both effects are present
        assert "INSTRUCTION_BLOCK" in prompt
        assert "REMINDER_BLOCK" in prompt
        assert "BASE_PROMPT" in prompt

        # Order: instructions (prepended) < base < reminders (appended)
        instr_pos = prompt.index("INSTRUCTION_BLOCK")
        base_pos = prompt.index("BASE_PROMPT")
        reminder_pos = prompt.index("REMINDER_BLOCK")
        assert instr_pos < base_pos < reminder_pos

        assert any(e.is_final for e in events)

    @pytest.mark.asyncio
    async def test_combined_filters_messages_unchanged(self, tmp_path: Path) -> None:
        """Neither filter modifies the messages list — only system_prompt."""
        (tmp_path / "AGENTS.md").write_text("agent stuff")
        captured: dict[str, Any] = {}

        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[
                ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "nohome"),
                SystemReminderFilter(
                    reminders=[
                        SystemReminder(id="r1", content="ctx", token_estimate=5)
                    ]
                ),
            ],
        )
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        msgs = [_msg("user", "hello"), _msg("assistant", "world")]
        await _collect_events(
            runtime,
            messages=msgs,
            system_prompt="sys",
            active_tools=[],
        )

        assert len(captured["messages"]) == 2
        assert captured["messages"][0]["content"] == "hello"
        assert captured["messages"][1]["content"] == "world"


# ---------------------------------------------------------------------------
# 4. Compatibility with MaxTokensFilter
# ---------------------------------------------------------------------------


class TestMaxTokensFilterCompatibility:
    @pytest.mark.asyncio
    async def test_instruction_filter_with_max_tokens_filter(
        self, tmp_path: Path
    ) -> None:
        """ProjectInstructionFilter + MaxTokensFilter coexist without conflicts."""
        (tmp_path / "RULES.md").write_text("RULE_CONTENT")
        captured: dict[str, Any] = {}

        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[
                ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "nohome"),
                MaxTokensFilter(max_tokens=100_000),
            ],
        )
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        events = await _collect_events(
            runtime,
            messages=[_msg("user", "hello")],
            system_prompt="base",
            active_tools=[],
        )

        assert "RULE_CONTENT" in captured["system_prompt"]
        assert any(e.is_final for e in events)

    @pytest.mark.asyncio
    async def test_all_three_filters_combined(self, tmp_path: Path) -> None:
        """ProjectInstructionFilter + SystemReminderFilter + MaxTokensFilter together."""
        (tmp_path / "CLAUDE.md").write_text("INSTRUCTIONS")
        captured: dict[str, Any] = {}

        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[
                ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "nohome"),
                SystemReminderFilter(
                    reminders=[
                        SystemReminder(id="r1", content="REMINDER", token_estimate=5)
                    ]
                ),
                MaxTokensFilter(max_tokens=100_000),
            ],
        )
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        events = await _collect_events(
            runtime,
            messages=[_msg("user", "msg")],
            system_prompt="BASE",
            active_tools=[],
        )

        prompt = captured["system_prompt"]
        assert "INSTRUCTIONS" in prompt
        assert "REMINDER" in prompt
        assert "BASE" in prompt
        assert any(e.is_final for e in events)


# ---------------------------------------------------------------------------
# 5. Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_backward_compat_no_filters_configured(self) -> None:
        """Without input_filters, ThinRuntime works identically — no side effects."""
        captured: dict[str, Any] = {}
        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        msgs = [_msg("user", "hello")]
        events = await _collect_events(
            runtime,
            messages=msgs,
            system_prompt="original",
            active_tools=[],
        )

        assert len(captured["messages"]) == 1
        assert captured["system_prompt"].startswith("original")
        assert any(e.is_final for e in events)

    @pytest.mark.asyncio
    async def test_backward_compat_empty_filter_list(self) -> None:
        """Explicitly empty input_filters=[] behaves like no filters."""
        captured: dict[str, Any] = {}
        config = RuntimeConfig(runtime_name="thin", input_filters=[])
        runtime = ThinRuntime(config=config, llm_call=_make_llm_call(captured))

        msgs = [_msg("user", "hi")]
        events = await _collect_events(
            runtime,
            messages=msgs,
            system_prompt="sys",
            active_tools=[],
        )

        assert len(captured["messages"]) == 1
        assert captured["system_prompt"].startswith("sys")
        assert any(e.is_final for e in events)


# ---------------------------------------------------------------------------
# 6. Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_project_instruction_filter_implements_input_filter(
        self, tmp_path: Path
    ) -> None:
        """ProjectInstructionFilter satisfies InputFilter protocol."""
        f = ProjectInstructionFilter(cwd=tmp_path)
        assert isinstance(f, InputFilter)

    def test_system_reminder_filter_implements_input_filter(self) -> None:
        """SystemReminderFilter satisfies InputFilter protocol."""
        f = SystemReminderFilter(reminders=[])
        assert isinstance(f, InputFilter)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "filter_factory",
        [
            pytest.param(
                lambda tmp: ProjectInstructionFilter(cwd=tmp),
                id="project_instruction_filter",
            ),
            pytest.param(
                lambda tmp: SystemReminderFilter(
                    reminders=[
                        SystemReminder(id="t", content="test", token_estimate=1)
                    ]
                ),
                id="system_reminder_filter",
            ),
        ],
    )
    async def test_filter_contract_returns_tuple(
        self, tmp_path: Path, filter_factory: Any
    ) -> None:
        """Both filters return (list[Message], str) tuple from filter()."""
        f = filter_factory(tmp_path)
        msgs = [_msg("user", "hello")]
        result = await f.filter(msgs, "prompt")

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], str)
