"""Stage 29, fix-cycle 2 — SecretBoundary must cover ALL child-return paths.

GPT-5.5 review (CHANGES_REQUESTED): fix-cycle 1 wired `secret_boundary` only
into `create_subagent_executor`'s foreground JSON return — three OTHER exit
paths for an untrusted spawned child's content still bypassed the scan:

- MAJOR-1: `ThinRuntime` never threaded `secret_boundary` into either
  `create_subagent_executor` call site at all (covered separately in
  `test_stage29_thin_runtime_subagent_wiring.py`).
- MAJOR-2: `create_monitor_executor` had no `secret_boundary` parameter
  (covered separately, ThinRuntime-level, in
  `test_stage29_thin_runtime_subagent_wiring.py`); the orchestrator's
  background-complete EVENT and `on_result_callback` had no scanning point
  at all — covered HERE, at the `ThinSubagentOrchestrator` level.
- MINOR-3: `SubagentSpec.depth`/`ThinRuntime.current_depth` accepted
  negative values, silently resetting/bypassing the depth guard — covered
  HERE.
"""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock

from swarmline.domain_types import RuntimeEvent
from swarmline.governance.secret_boundary import SecretBoundaryManager
from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
)
from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import RuntimeConfig

_LEAKING_OUTPUT = "here is the key: sk-abcdefghijklmnopqrstuvwxyz0123456789"
_LEAKING_ERROR = "crashed while using key sk-abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.fixture()
def mock_runtime() -> AsyncMock:
    rt = AsyncMock()
    rt.run = AsyncMock(return_value=_LEAKING_OUTPUT)
    rt._cwd = None
    return rt


def _make_orchestrator(
    mock_runtime: AsyncMock, **kwargs: object
) -> ThinSubagentOrchestrator:
    orch = ThinSubagentOrchestrator(max_concurrent=10, **kwargs)  # type: ignore[arg-type]
    orch._create_runtime = lambda spec: mock_runtime  # type: ignore[assignment,method-assign]
    return orch


# ---------------------------------------------------------------------------
# MAJOR-2b: background-complete event scanned
# ---------------------------------------------------------------------------


class TestBackgroundCompleteEventIsSecretBoundaryScanned:
    async def test_success_result_in_background_event_is_redacted(
        self, mock_runtime: AsyncMock
    ) -> None:
        events: list[RuntimeEvent] = []

        async def capture(event: RuntimeEvent) -> None:
            events.append(event)

        orch = _make_orchestrator(
            mock_runtime,
            on_background_complete=capture,
            secret_boundary=SecretBoundaryManager(),
        )
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in events[0].data["result"]
        assert "[REDACTED:api_key]" in events[0].data["result"]

    async def test_error_in_background_event_is_redacted(
        self, mock_runtime: AsyncMock
    ) -> None:
        mock_runtime.run = AsyncMock(side_effect=RuntimeError(_LEAKING_ERROR))
        events: list[RuntimeEvent] = []

        async def capture(event: RuntimeEvent) -> None:
            events.append(event)

        orch = _make_orchestrator(
            mock_runtime,
            on_background_complete=capture,
            secret_boundary=SecretBoundaryManager(),
        )
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in events[0].data["error"]
        assert "[REDACTED:api_key]" in events[0].data["error"]

    async def test_no_secret_boundary_preserves_legacy_event_passthrough(
        self, mock_runtime: AsyncMock
    ) -> None:
        """Regression: default None does not scan — byte-identical legacy."""
        events: list[RuntimeEvent] = []

        async def capture(event: RuntimeEvent) -> None:
            events.append(event)

        orch = _make_orchestrator(mock_runtime, on_background_complete=capture)
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)
        await asyncio.sleep(0.05)

        assert events[0].data["result"] == _LEAKING_OUTPUT


# ---------------------------------------------------------------------------
# MAJOR-2c: on_result_callback scanned
# ---------------------------------------------------------------------------


class TestOnResultCallbackIsSecretBoundaryScanned:
    async def test_success_output_passed_to_callback_is_redacted(
        self, mock_runtime: AsyncMock
    ) -> None:
        captured: list[tuple[str, SubagentResult]] = []

        def capture(agent_id: str, result: SubagentResult) -> None:
            captured.append((agent_id, result))

        orch = _make_orchestrator(
            mock_runtime,
            on_result_callback=capture,
            secret_boundary=SecretBoundaryManager(),
        )
        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)

        assert len(captured) == 1
        _, result = captured[0]
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in result.output
        assert "[REDACTED:api_key]" in result.output

    async def test_failed_error_passed_to_callback_is_redacted(
        self, mock_runtime: AsyncMock
    ) -> None:
        mock_runtime.run = AsyncMock(side_effect=RuntimeError(_LEAKING_ERROR))
        captured: list[tuple[str, SubagentResult]] = []

        def capture(agent_id: str, result: SubagentResult) -> None:
            captured.append((agent_id, result))

        orch = _make_orchestrator(
            mock_runtime,
            on_result_callback=capture,
            secret_boundary=SecretBoundaryManager(),
        )
        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)

        assert len(captured) == 1
        _, result = captured[0]
        assert result.status.error is not None
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in result.status.error
        assert "[REDACTED:api_key]" in result.status.error

    async def test_no_secret_boundary_preserves_legacy_callback_passthrough(
        self, mock_runtime: AsyncMock
    ) -> None:
        """Regression: default None does not scan — byte-identical legacy."""
        captured: list[tuple[str, SubagentResult]] = []

        def capture(agent_id: str, result: SubagentResult) -> None:
            captured.append((agent_id, result))

        orch = _make_orchestrator(mock_runtime, on_result_callback=capture)
        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)

        assert captured[0][1].output == _LEAKING_OUTPUT


# ---------------------------------------------------------------------------
# Fix-cycle 3: `wait()` itself was the last raw-passthrough exit point.
# `orchestrator.wait(agent_id)` is called DIRECTLY (no re-scanning wrapper)
# by `supervisor/tools.py::_spawn_and_wait` (-> `Report.summary` ->
# `read_reports` -> supervisor LLM), `supervisor/replan.py::plan_via_subagent`,
# and `tools/research.py::spawn_research` — all three re-enter an LLM context
# with the raw child output.
# ---------------------------------------------------------------------------


class TestWaitIsSecretBoundaryScanned:
    """`ThinSubagentOrchestrator.wait()` returns a redacted COPY when a
    boundary is configured — the LAST bypass GPT-5.5 review round 2 found."""

    async def test_success_output_returned_by_wait_is_redacted(
        self, mock_runtime: AsyncMock
    ) -> None:
        orch = _make_orchestrator(mock_runtime, secret_boundary=SecretBoundaryManager())
        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")

        result = await orch.wait(agent_id)

        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in result.output
        assert "[REDACTED:api_key]" in result.output

    async def test_success_status_result_returned_by_wait_is_also_redacted(
        self, mock_runtime: AsyncMock
    ) -> None:
        """Round-3 review finding: `_run_agent`'s success branch sets
        `status=SubagentStatus(result=output)` alongside the top-level
        `.output` — `.status.result` carries the SAME raw text and must be
        scanned too, not just `.output`."""
        orch = _make_orchestrator(mock_runtime, secret_boundary=SecretBoundaryManager())
        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")

        result = await orch.wait(agent_id)

        assert result.status.result is not None
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in result.status.result
        assert "[REDACTED:api_key]" in result.status.result

    async def test_failed_error_returned_by_wait_is_redacted(
        self, mock_runtime: AsyncMock
    ) -> None:
        mock_runtime.run = AsyncMock(side_effect=RuntimeError(_LEAKING_ERROR))
        orch = _make_orchestrator(mock_runtime, secret_boundary=SecretBoundaryManager())
        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")

        result = await orch.wait(agent_id)

        assert result.status.error is not None
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in result.status.error
        assert "[REDACTED:api_key]" in result.status.error

    async def test_no_secret_boundary_preserves_legacy_wait_passthrough(
        self, mock_runtime: AsyncMock
    ) -> None:
        """Regression: default None does not scan — byte-identical legacy."""
        orch = _make_orchestrator(mock_runtime)
        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")

        result = await orch.wait(agent_id)

        assert result.output == _LEAKING_OUTPUT
        assert result.status.result == _LEAKING_OUTPUT

    async def test_internal_results_storage_stays_raw_for_lessons_extraction(
        self, mock_runtime: AsyncMock
    ) -> None:
        """`self._results` (read by `get_status()`/lessons-extraction) is NOT
        mutated by `wait()`'s scan — only the value handed back to the
        CALLER of `wait()` is a redacted copy."""
        orch = _make_orchestrator(mock_runtime, secret_boundary=SecretBoundaryManager())
        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)

        assert orch._results[agent_id].output == _LEAKING_OUTPUT


class TestSupervisorReportPathIsSecretBoundaryScanned:
    """End-to-end through the REAL supervisor consumer:
    `_spawn_and_wait` -> `_build_report` -> `Report.summary` — the exact
    path `read_reports` hands back to the supervisor LLM (REQ-ORC-044)."""

    async def test_report_summary_from_spawned_worker_is_redacted(
        self, mock_runtime: AsyncMock
    ) -> None:
        from uuid import uuid4

        from swarmline.orchestration.supervisor.tools import (
            _build_report,
            _spawn_and_wait,
        )
        from swarmline.protocols.host_adapter import AgentHandle

        orch = _make_orchestrator(mock_runtime, secret_boundary=SecretBoundaryManager())
        spec = SubagentSpec(name="researcher", system_prompt="p")

        agent_id, result = await _spawn_and_wait(orch, spec, "investigate")
        handle = AgentHandle(id=str(uuid4()), role="researcher")
        report = _build_report(handle, "researcher", result)

        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in report.summary
        assert "[REDACTED:api_key]" in report.summary
        del agent_id

    async def test_no_secret_boundary_preserves_legacy_report_passthrough(
        self, mock_runtime: AsyncMock
    ) -> None:
        """Regression: default None does not scan — byte-identical legacy."""
        from uuid import uuid4

        from swarmline.orchestration.supervisor.tools import (
            _build_report,
            _spawn_and_wait,
        )
        from swarmline.protocols.host_adapter import AgentHandle

        orch = _make_orchestrator(mock_runtime)
        spec = SubagentSpec(name="researcher", system_prompt="p")

        _agent_id, result = await _spawn_and_wait(orch, spec, "investigate")
        handle = AgentHandle(id=str(uuid4()), role="researcher")
        report = _build_report(handle, "researcher", result)

        assert report.summary == _LEAKING_OUTPUT


# ---------------------------------------------------------------------------
# MINOR-3: negative depth is rejected (fail fast), not silently accepted
# ---------------------------------------------------------------------------


class TestNegativeDepthIsRejected:
    def test_subagent_spec_negative_depth_raises(self) -> None:
        with pytest.raises(ValueError, match="depth"):
            SubagentSpec(name="w", system_prompt="p", depth=-1)

    def test_subagent_spec_zero_depth_is_accepted(self) -> None:
        spec = SubagentSpec(name="w", system_prompt="p", depth=0)
        assert spec.depth == 0

    def test_thin_runtime_negative_current_depth_raises(self) -> None:
        with pytest.raises(ValueError, match="current_depth"):
            ThinRuntime(config=RuntimeConfig(runtime_name="thin"), current_depth=-1)

    def test_thin_runtime_zero_current_depth_is_accepted(self) -> None:
        rt = ThinRuntime(config=RuntimeConfig(runtime_name="thin"), current_depth=0)
        assert rt._current_depth == 0
