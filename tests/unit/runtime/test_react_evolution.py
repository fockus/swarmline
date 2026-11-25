"""Tests for stuck detection + recovery cascade wired into react_strategy.

TDD Red phase: tests before implementation.
Covers: opt-in flag, stuck triggers recovery, cascade escalates, backward compat.
"""

from __future__ import annotations

import json

import pytest
from swarmline.evolution.recovery import RecoveryCascade, RecoveryStrategy
from swarmline.evolution.stuck_detector import StuckDetector
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec


class MockLLM:
    """Mock LLM that returns canned responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def __call__(self, messages: list[dict], system_prompt: str) -> str:  # type: ignore[type-arg]
        if self._idx < len(self._responses):
            r = self._responses[self._idx]
            self._idx += 1
            return r
        return json.dumps({"type": "final", "final_message": "fallback"})


def _tool_call(name: str = "grep", args: dict | None = None) -> str:  # type: ignore[type-arg]
    return json.dumps({"type": "tool_call", "tool": {"name": name, "args": args or {}}})


def _final(text: str = "done") -> str:
    return json.dumps({"type": "final", "final_message": text})


async def _collect(
    runtime: ThinRuntime,
    mode_hint: str = "react",
) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content="find the bug")],
        system_prompt="You are a helper.",
        active_tools=[ToolSpec(name="grep", description="search", parameters={})],
        mode_hint=mode_hint,
    ):
        events.append(ev)
    return events


def _grep_tool(**kwargs: object) -> str:
    return json.dumps({"result": "no match"})


# ---------------------------------------------------------------------------
# Backward compatibility: evolution_enabled=False (default)
# ---------------------------------------------------------------------------


class TestReactEvolutionDisabled:
    """Default: evolution_enabled=False — no stuck detection."""

    @pytest.mark.asyncio
    async def test_default_config_no_evolution(self) -> None:
        config = RuntimeConfig(runtime_name="thin")
        assert config.evolution_enabled is False

    @pytest.mark.asyncio
    async def test_repeated_calls_no_stuck_events_when_disabled(self) -> None:
        # 4 identical tool calls then final — should NOT emit stuck events
        llm = MockLLM(
            [_tool_call("grep", {"pattern": "x"})] * 4 + [_final()],
        )
        config = RuntimeConfig(runtime_name="thin", max_iterations=8, max_tool_calls=8)
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"grep": _grep_tool}, config=config
        )

        events = await _collect(runtime)
        assert "stuck_detected" not in [
            e.data.get("text", "") for e in events if e.type == "status"
        ]

    @pytest.mark.asyncio
    async def test_evolution_enabled_attr_exists(self) -> None:
        config = RuntimeConfig(runtime_name="thin", evolution_enabled=True)
        assert config.evolution_enabled is True


# ---------------------------------------------------------------------------
# Stuck detection triggers
# ---------------------------------------------------------------------------


class TestReactStuckDetection:
    """evolution_enabled=True — stuck detection fires."""

    @pytest.mark.asyncio
    async def test_exact_repeat_3x_emits_stuck_detected(self) -> None:
        # 3 identical tool calls → stuck → recovery → then final
        llm = MockLLM(
            [_tool_call("grep", {"pattern": "x"})] * 3 + [_final("recovered")],
        )
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=8,
            max_tool_calls=8,
            evolution_enabled=True,
            stuck_detector=StuckDetector(),
            recovery_cascade=RecoveryCascade(),
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"grep": _grep_tool}, config=config
        )

        events = await _collect(runtime)
        status_texts = [e.data.get("text", "") for e in events if e.type == "status"]
        assert any("stuck_detected" in t for t in status_texts)

    @pytest.mark.asyncio
    async def test_recovery_applied_event_emitted(self) -> None:
        # 3 identical → stuck → recovery applied → then final
        llm = MockLLM(
            [_tool_call("grep", {"pattern": "x"})] * 3 + [_final("ok")],
        )
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=8,
            max_tool_calls=8,
            evolution_enabled=True,
            stuck_detector=StuckDetector(),
            recovery_cascade=RecoveryCascade(),
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"grep": _grep_tool}, config=config
        )

        events = await _collect(runtime)
        status_texts = [e.data.get("text", "") for e in events if e.type == "status"]
        assert any("recovery_applied" in t for t in status_texts)


# ---------------------------------------------------------------------------
# Cascade escalation
# ---------------------------------------------------------------------------


class TestReactCascadeEscalation:
    """4 stuck detections → ESCALATE → break."""

    @pytest.mark.asyncio
    async def test_escalation_after_4_stuck_events(self) -> None:
        # Need 4 rounds of 3 identical calls = 12 + recoveries
        # Simpler: after each recovery the agent repeats the same call pattern
        # For efficiency, use a cascade with ESCALATE at attempt 0
        immediate_escalate = RecoveryCascade(strategies=[RecoveryStrategy.ESCALATE])
        llm = MockLLM(
            [_tool_call("grep", {"pattern": "x"})] * 3 + [_final("should not reach")],
        )
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=8,
            max_tool_calls=8,
            evolution_enabled=True,
            stuck_detector=StuckDetector(),
            recovery_cascade=immediate_escalate,
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"grep": _grep_tool}, config=config
        )

        events = await _collect(runtime)
        status_texts = [e.data.get("text", "") for e in events if e.type == "status"]
        assert any("stuck_escalated" in t for t in status_texts)

    @pytest.mark.asyncio
    async def test_escalation_stops_loop(self) -> None:
        # ESCALATE should stop the loop — no final event with user text
        immediate_escalate = RecoveryCascade(strategies=[RecoveryStrategy.ESCALATE])
        # 20 tool calls, but should stop after 3 (stuck) + escalation
        llm = MockLLM([_tool_call("grep", {"pattern": "x"})] * 20)
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=20,
            max_tool_calls=20,
            evolution_enabled=True,
            stuck_detector=StuckDetector(),
            recovery_cascade=immediate_escalate,
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"grep": _grep_tool}, config=config
        )

        events = await _collect(runtime)
        # Should have far fewer tool calls than 20
        tool_calls = [e for e in events if e.type == "tool_call_finished"]
        assert len(tool_calls) <= 5  # 3 for stuck + maybe 1-2 buffer

    @pytest.mark.asyncio
    async def test_progressive_escalation(self) -> None:
        # First 3 repeats → REPHRASE, next 3 → SIMPLIFY, etc.
        # Need enough identical calls to trigger stuck 3+ times
        # Use max recovery attempts = 4
        responses = [_tool_call("grep", {"pattern": "x"})] * 15 + [_final("done")]
        llm = MockLLM(responses)
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=20,
            max_tool_calls=20,
            evolution_enabled=True,
            stuck_detector=StuckDetector(),
            recovery_cascade=RecoveryCascade(),
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"grep": _grep_tool}, config=config
        )

        events = await _collect(runtime)
        status_texts = [e.data.get("text", "") for e in events if e.type == "status"]
        # Should see at least one stuck_detected
        assert any("stuck_detected" in t for t in status_texts)


# ---------------------------------------------------------------------------
# No stuck_detector provided (evolution_enabled but no detector)
# ---------------------------------------------------------------------------


class TestReactEvolutionWithoutDetector:
    """evolution_enabled=True but no stuck_detector — graceful no-op."""

    @pytest.mark.asyncio
    async def test_no_detector_no_crash(self) -> None:
        llm = MockLLM(
            [_tool_call("grep", {"pattern": "x"})] * 3 + [_final()],
        )
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=8,
            max_tool_calls=8,
            evolution_enabled=True,
            # No stuck_detector or recovery_cascade
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"grep": _grep_tool}, config=config
        )

        events = await _collect(runtime)
        # Should complete normally without crash
        assert any(e.type == "final" for e in events)


# ---------------------------------------------------------------------------
# Recovery counter respects max 4
# ---------------------------------------------------------------------------


class TestReactRecoveryLimit:
    """Max 4 recovery attempts (one per strategy)."""

    @pytest.mark.asyncio
    async def test_max_recovery_attempts(self) -> None:
        # After 4 recovery attempts, should escalate and stop
        responses = [_tool_call("grep", {"pattern": "x"})] * 30
        llm = MockLLM(responses)
        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=40,
            max_tool_calls=40,
            evolution_enabled=True,
            stuck_detector=StuckDetector(),
            recovery_cascade=RecoveryCascade(),
        )
        runtime = ThinRuntime(
            llm_call=llm, local_tools={"grep": _grep_tool}, config=config
        )

        events = await _collect(runtime)
        status_texts = [e.data.get("text", "") for e in events if e.type == "status"]
        stuck_events = [t for t in status_texts if "stuck_detected" in t]
        # Should not exceed 4 stuck detections before escalation stops loop
        assert len(stuck_events) <= 4
        # Should have an escalation event
        assert any("stuck_escalated" in t for t in status_texts)
