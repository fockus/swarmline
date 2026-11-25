"""Edge-case tests for react_strategy evolution wiring.

Additional coverage beyond dev-domain tests.
Covers: history cleared after recovery, re-stuck after recovery,
recovery prompt injection, mixed tool calls, evolution + max_tool_calls,
evolution + max_iterations, no recovery cascade provided.
"""

from __future__ import annotations

import json

import pytest
from swarmline.evolution.recovery import RecoveryCascade, RecoveryStrategy
from swarmline.evolution.stuck_detector import StuckDetector
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec


class _MockLLM:
    """Mock LLM that returns canned responses in order."""

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


def _grep_tool(**kwargs: object) -> str:
    return json.dumps({"result": "no match"})


def _write_tool(**kwargs: object) -> str:
    return json.dumps({"ok": True})


async def _collect(runtime: ThinRuntime) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in runtime.run(
        messages=[Message(role="user", content="find the bug")],
        system_prompt="You are a helper.",
        active_tools=[
            ToolSpec(name="grep", description="search", parameters={}),
            ToolSpec(name="write_file", description="write", parameters={}),
        ],
        mode_hint="react",
    ):
        events.append(ev)
    return events


def _status_texts(events: list[RuntimeEvent]) -> list[str]:
    return [e.data.get("text", "") for e in events if e.type == "status"]


def _make_runtime(
    responses: list[str],
    *,
    evolution_enabled: bool = True,
    max_iterations: int = 20,
    max_tool_calls: int = 20,
    stuck_detector: StuckDetector | None = None,
    recovery_cascade: RecoveryCascade | None = None,
) -> ThinRuntime:
    return ThinRuntime(
        llm_call=_MockLLM(responses),
        local_tools={"grep": _grep_tool, "write_file": _write_tool},
        config=RuntimeConfig(
            runtime_name="thin",
            max_iterations=max_iterations,
            max_tool_calls=max_tool_calls,
            evolution_enabled=evolution_enabled,
            stuck_detector=stuck_detector or StuckDetector(),
            recovery_cascade=recovery_cascade or RecoveryCascade(),
        ),
    )


# ---------------------------------------------------------------------------
# History cleared after recovery — re-stuck needs fresh 3 calls
# ---------------------------------------------------------------------------


class TestHistoryClearedAfterRecovery:
    """After recovery, tool history is cleared so stuck needs 3 fresh repeats."""

    @pytest.mark.asyncio
    async def test_single_repeat_after_recovery_no_stuck(self) -> None:
        """1 repeat of same tool after recovery should NOT trigger stuck again."""
        responses = (
            [_tool_call("grep", {"pattern": "x"})] * 3  # stuck #1 → REPHRASE
            + [_tool_call("grep", {"pattern": "x"})]  # 1 repeat post-recovery
            + [_final("ok")]
        )
        runtime = _make_runtime(responses)
        events = await _collect(runtime)
        stuck_events = [t for t in _status_texts(events) if "stuck_detected" in t]
        assert len(stuck_events) == 1  # Only the first stuck

    @pytest.mark.asyncio
    async def test_re_stuck_after_recovery_needs_3_fresh(self) -> None:
        """Need 3 fresh repeats after recovery to re-trigger stuck."""
        responses = (
            [_tool_call("grep", {"pattern": "x"})] * 3  # stuck #1 → REPHRASE
            + [_tool_call("grep", {"pattern": "x"})] * 3  # stuck #2 → SIMPLIFY
            + [_final("ok")]
        )
        runtime = _make_runtime(responses)
        events = await _collect(runtime)
        stuck_events = [t for t in _status_texts(events) if "stuck_detected" in t]
        assert len(stuck_events) == 2


# ---------------------------------------------------------------------------
# Recovery prompt injected into lm_messages
# ---------------------------------------------------------------------------


class TestRecoveryPromptInjection:
    """Recovery prompt should appear in LLM conversation context."""

    @pytest.mark.asyncio
    async def test_recovery_emits_strategy_name(self) -> None:
        """After stuck, recovery_applied event contains strategy name."""
        responses = [_tool_call("grep", {"pattern": "x"})] * 3 + [_final("recovered")]
        runtime = _make_runtime(responses)
        events = await _collect(runtime)
        recovery_events = [t for t in _status_texts(events) if "recovery_applied" in t]
        assert len(recovery_events) >= 1
        assert "rephrase" in recovery_events[0]


# ---------------------------------------------------------------------------
# Mixed tool calls — only one tool repeats
# ---------------------------------------------------------------------------


class TestMixedToolCallsEvolution:
    """Only specific tool repeat patterns should trigger stuck."""

    @pytest.mark.asyncio
    async def test_different_tools_no_stuck(self) -> None:
        """Alternating between grep and write_file with different args — no stuck."""
        responses = [
            _tool_call("grep", {"pattern": "a"}),
            _tool_call("write_file", {"path": "/x"}),
            _tool_call("grep", {"pattern": "b"}),
            _tool_call("write_file", {"path": "/y"}),
            _final("done"),
        ]
        runtime = _make_runtime(responses)
        events = await _collect(runtime)
        stuck_events = [t for t in _status_texts(events) if "stuck_detected" in t]
        assert len(stuck_events) == 0

    @pytest.mark.asyncio
    async def test_one_tool_repeats_among_variety(self) -> None:
        """grep repeats 3x with same args among other calls — triggers stuck."""
        responses = [
            _tool_call("grep", {"pattern": "x"}),
            _tool_call("write_file", {"path": "/a"}),
            _tool_call("grep", {"pattern": "x"}),
            _tool_call("write_file", {"path": "/b"}),
            _tool_call("grep", {"pattern": "x"}),
            _final("ok"),
        ]
        runtime = _make_runtime(responses)
        events = await _collect(runtime)
        # In window of 5-6 calls, grep with same args appears 3 times
        stuck_events = [t for t in _status_texts(events) if "stuck_detected" in t]
        # Depending on window, may or may not trigger — grep 3x but with non-grep in between
        # The window has all 5 calls: grep, write, grep, write, grep — 3 exact repeats
        assert len(stuck_events) >= 1


# ---------------------------------------------------------------------------
# Evolution + budget exceeded interaction
# ---------------------------------------------------------------------------


class TestEvolutionBudgetInteraction:
    """Stuck detection interacts with max_tool_calls budget."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_before_stuck(self) -> None:
        """If tool budget runs out before 3 repeats, no stuck detected."""
        responses = [_tool_call("grep", {"pattern": "x"})] * 5
        runtime = _make_runtime(
            responses,
            max_tool_calls=2,  # Budget runs out after 2 calls
        )
        events = await _collect(runtime)
        stuck_events = [t for t in _status_texts(events) if "stuck_detected" in t]
        assert len(stuck_events) == 0
        # Should have budget_exceeded error
        errors = [e for e in events if e.type == "error"]
        assert len(errors) >= 1

    @pytest.mark.asyncio
    async def test_stuck_detected_within_budget(self) -> None:
        """Stuck detected before budget runs out."""
        responses = [_tool_call("grep", {"pattern": "x"})] * 5 + [_final("ok")]
        runtime = _make_runtime(
            responses,
            max_tool_calls=10,  # Plenty of budget
        )
        events = await _collect(runtime)
        stuck_events = [t for t in _status_texts(events) if "stuck_detected" in t]
        assert len(stuck_events) >= 1


# ---------------------------------------------------------------------------
# Evolution + max_iterations
# ---------------------------------------------------------------------------


class TestEvolutionMaxIterations:
    """Stuck detection interacts with iteration limit."""

    @pytest.mark.asyncio
    async def test_iterations_limit_stops_before_escalation(self) -> None:
        """If max_iterations is very low, loop stops before full cascade."""
        responses = [_tool_call("grep", {"pattern": "x"})] * 20
        runtime = _make_runtime(
            responses,
            max_iterations=4,  # Only 4 iterations total
            max_tool_calls=20,
        )
        events = await _collect(runtime)
        # Either error (loop_limit or budget_exceeded) or stuck_escalated
        has_end = any(e.type == "error" for e in events) or any(
            "stuck_escalated" in t for t in _status_texts(events)
        )
        assert has_end


# ---------------------------------------------------------------------------
# Evolution enabled but no detector — graceful no-op
# ---------------------------------------------------------------------------


class TestEvolutionPartialConfig:
    """evolution_enabled=True but missing detector or cascade."""

    @pytest.mark.asyncio
    async def test_detector_only_no_cascade(self) -> None:
        """stuck_detector provided but no recovery_cascade — should not crash."""
        responses = [_tool_call("grep", {"pattern": "x"})] * 3 + [_final("ok")]
        runtime = ThinRuntime(
            llm_call=_MockLLM(responses),
            local_tools={"grep": _grep_tool},
            config=RuntimeConfig(
                runtime_name="thin",
                max_iterations=8,
                max_tool_calls=8,
                evolution_enabled=True,
                stuck_detector=StuckDetector(),
                # No recovery_cascade
            ),
        )
        events = await _collect(runtime)
        assert any(e.type == "final" for e in events)

    @pytest.mark.asyncio
    async def test_cascade_only_no_detector(self) -> None:
        """recovery_cascade provided but no stuck_detector — should not crash."""
        responses = [_tool_call("grep", {"pattern": "x"})] * 3 + [_final("ok")]
        runtime = ThinRuntime(
            llm_call=_MockLLM(responses),
            local_tools={"grep": _grep_tool},
            config=RuntimeConfig(
                runtime_name="thin",
                max_iterations=8,
                max_tool_calls=8,
                evolution_enabled=True,
                recovery_cascade=RecoveryCascade(),
                # No stuck_detector
            ),
        )
        events = await _collect(runtime)
        assert any(e.type == "final" for e in events)


# ---------------------------------------------------------------------------
# Escalation — ESCALATE with default cascade
# ---------------------------------------------------------------------------


class TestEscalationDetails:
    """Verify escalation behavior details."""

    @pytest.mark.asyncio
    async def test_escalation_emits_recovery_prompt(self) -> None:
        """stuck_escalated event should contain meaningful text."""
        responses = [_tool_call("grep", {"pattern": "x"})] * 20
        immediate_escalate = RecoveryCascade(strategies=[RecoveryStrategy.ESCALATE])
        runtime = _make_runtime(
            responses,
            recovery_cascade=immediate_escalate,
        )
        events = await _collect(runtime)
        escalated = [t for t in _status_texts(events) if "stuck_escalated" in t]
        assert len(escalated) >= 1
        # Should contain meaningful text about being stuck
        assert len(escalated[0]) > len("stuck_escalated: ")

    @pytest.mark.asyncio
    async def test_escalation_prevents_final_event(self) -> None:
        """After ESCALATE, no final event should be emitted."""
        responses = [_tool_call("grep", {"pattern": "x"})] * 20
        immediate_escalate = RecoveryCascade(strategies=[RecoveryStrategy.ESCALATE])
        runtime = _make_runtime(
            responses,
            recovery_cascade=immediate_escalate,
        )
        events = await _collect(runtime)
        # Should NOT have a final event (loop was aborted)
        final_events = [e for e in events if e.type == "final"]
        assert len(final_events) == 0


# ---------------------------------------------------------------------------
# Evolution disabled — regression guard
# ---------------------------------------------------------------------------


class TestEvolutionDisabledRegression:
    """Verify evolution_enabled=False is a complete no-op."""

    @pytest.mark.asyncio
    async def test_many_repeats_no_stuck_when_disabled(self) -> None:
        """Even 6 identical calls should not trigger stuck when disabled."""
        responses = [_tool_call("grep", {"pattern": "x"})] * 6 + [_final("ok")]
        runtime = _make_runtime(
            responses,
            evolution_enabled=False,
            max_tool_calls=10,
        )
        events = await _collect(runtime)
        stuck_events = [t for t in _status_texts(events) if "stuck_detected" in t]
        assert len(stuck_events) == 0
        assert any(e.type == "final" for e in events)
