"""Integration tests -- stuck detection wiring (code-agent-facade plan,
Stage 4).

`StuckDetector`/`RecoveryCascade` are pure, pre-existing domain logic
(`evolution/`) already exercised by `runtime/thin/react_strategy.py`. Stage
4 only wires them into `RuntimeConfig` when `evolution=True`.
`TestStuckDetectionThroughRealRuntime` drives the actual wired path end to
end (a real `ThinRuntime`, built via `CodeAgent`'s own
`RuntimeFactoryPort` + the augmented plan, with a scripted `FunctionModel`
LLM double standing in for the live model); `TestStuckDetectorConfigWiring`
covers the narrower config-shape assertions directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarmline.code_agent import CodeAgent
from swarmline.evolution.recovery import RecoveryCascade
from swarmline.evolution.stuck_detector import ToolCallRecord

pytestmark = pytest.mark.asyncio


def _build_plan(agent: CodeAgent):
    from swarmline.agent.runtime_wiring import build_portable_runtime_plan

    plan = build_portable_runtime_plan(
        agent._config, "thin", runtime_factory=agent._factory
    )
    return agent._augment_plan(plan)


class TestStuckDetectionThroughRealRuntime:
    async def test_repeated_tool_calls_trigger_stuck_signal(
        self, tmp_path: Path
    ) -> None:
        """Drives a REAL `ThinRuntime` (via `CodeAgent`'s own
        `RuntimeFactoryPort` + augmented plan -- the actual wired path, not
        just the config shape) with a scripted LLM double that repeats the
        same tool call 3 times, then asserts the runtime itself emits the
        `stuck_detected` status event `react_strategy.py` yields when
        `config.stuck_detector.detect(...)` fires. Fully offline: no live
        LLM call, `swarmline.testing.FunctionModel` stands in for the model.
        """
        from swarmline.runtime.types import Message
        from swarmline.testing import FunctionModel

        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))  # evolution=True default
        plan = _build_plan(agent)

        repeated_call = json.dumps(
            {"type": "tool_call", "tool": {"name": "bash", "args": {"command": "ls"}}}
        )
        final_call = json.dumps({"type": "final", "final_message": "done"})
        responses = iter([repeated_call, repeated_call, repeated_call, final_call])
        model = FunctionModel(fn=lambda _messages: next(responses))

        create_kwargs = dict(plan.create_kwargs)
        create_kwargs["llm_call"] = model.as_llm_call()
        runtime = agent._factory.create(config=plan.config, **create_kwargs)
        try:
            events = [
                event
                async for event in runtime.run(
                    messages=[Message(role="user", content="loop please")],
                    system_prompt="test",
                    active_tools=plan.active_tools,
                )
            ]
        finally:
            await runtime.cleanup()

        stuck_events = [
            event
            for event in events
            if event.type == "status" and "stuck_detected" in event.data.get("text", "")
        ]
        assert stuck_events, (
            "expected a 'stuck_detected' status event from the wired "
            f"stuck_detector; got event types: {[e.type for e in events]}"
        )


class TestStuckDetectorConfigWiring:
    async def test_fewer_than_three_calls_do_not_trigger_stuck_signal(
        self, tmp_path: Path
    ) -> None:
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))

        plan = _build_plan(agent)

        history = [ToolCallRecord.from_call("bash", {"command": "ls"}, "ok")] * 2
        signal = plan.config.stuck_detector.detect(history)

        assert signal is None

    async def test_recovery_cascade_wired_when_evolution_enabled(
        self, tmp_path: Path
    ) -> None:
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))

        plan = _build_plan(agent)

        assert isinstance(plan.config.recovery_cascade, RecoveryCascade)
        assert plan.config.recovery_cascade.next_strategy(0).value == "rephrase"
