"""Tests SubagentOrchestrator types and Protocol - TDD."""

from __future__ import annotations

from datetime import UTC, datetime


def _now() -> datetime:
    return datetime.now(tz=UTC)


class TestSubagentSpec:
    def test_create(self) -> None:
        from cognitia.orchestration.subagent_types import SubagentSpec

        spec = SubagentSpec(name="researcher", system_prompt="Ты исследователь")
        assert spec.name == "researcher"
        assert spec.tools == []
        assert spec.sandbox_config is None

    def test_with_tools(self) -> None:
        from cognitia.orchestration.subagent_types import SubagentSpec
        from cognitia.runtime.types import ToolSpec

        ts = ToolSpec(name="search", description="search", parameters={})
        spec = SubagentSpec(name="s", system_prompt="p", tools=[ts])
        assert len(spec.tools) == 1


class TestSubagentStatus:
    def test_pending(self) -> None:
        from cognitia.orchestration.subagent_types import SubagentStatus

        s = SubagentStatus()
        assert s.state == "pending"
        assert s.result is None

    def test_running(self) -> None:
        from cognitia.orchestration.subagent_types import SubagentStatus

        s = SubagentStatus(state="running", progress="50%", started_at=_now())
        assert s.state == "running"

    def test_completed(self) -> None:
        from cognitia.orchestration.subagent_types import SubagentStatus

        s = SubagentStatus(state="completed", result="done", started_at=_now(), finished_at=_now())
        assert s.result == "done"

    def test_failed(self) -> None:
        from cognitia.orchestration.subagent_types import SubagentStatus

        s = SubagentStatus(state="failed", error="crash")
        assert s.error == "crash"


class TestSubagentResult:
    def test_create(self) -> None:
        from cognitia.orchestration.subagent_types import SubagentResult, SubagentStatus

        r = SubagentResult(
            agent_id="a1", status=SubagentStatus(state="completed"), output="result text"
        )
        assert r.agent_id == "a1"
        assert r.output == "result text"
        assert r.messages == []


class TestSubagentOrchestratorProtocol:
    def test_runtime_checkable(self) -> None:
        from cognitia.orchestration.subagent_protocol import SubagentOrchestrator

        class FakeOrch:
            async def spawn(self, spec, task):
                return "id"

            async def get_status(self, agent_id):
                return None

            async def cancel(self, agent_id):
                pass

            async def wait(self, agent_id):
                return None

            async def list_active(self):
                return []

        assert isinstance(FakeOrch(), SubagentOrchestrator)

    def test_incomplete_not_instance(self) -> None:
        from cognitia.orchestration.subagent_protocol import SubagentOrchestrator

        class Incomplete:
            async def spawn(self, spec, task):
                return "id"

        assert not isinstance(Incomplete(), SubagentOrchestrator)

    def test_isp_max_5(self) -> None:
        from cognitia.orchestration.subagent_protocol import SubagentOrchestrator

        methods = [
            n
            for n in dir(SubagentOrchestrator)
            if not n.startswith("_") and callable(getattr(SubagentOrchestrator, n, None))
        ]
        assert len(methods) <= 5
