"""Tests for HITL tool factory — create_hitl_tools.

TDD: these tests were written BEFORE the implementation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from swarmline.domain_types import ToolSpec
from swarmline.hitl.diff_review import InMemoryDiffReviewManager
from swarmline.hitl.evidence_collector import InMemoryEvidenceCollector
from swarmline.hitl.retry_manager import InMemoryRetryManager
from swarmline.hitl.timeline_types import (
    DiffReview,
    RunTimeline,
    StepStatus,
    TimelineEvent,
)


class _StubRunTimeline:
    """Minimal RunTimelinePort stub for testing."""

    def __init__(self) -> None:
        self._events: dict[str, list[TimelineEvent]] = {}

    def record_event(self, event: TimelineEvent) -> None:
        self._events.setdefault(event.run_id, []).append(event)

    def get_timeline(self, run_id: str) -> RunTimeline | None:
        events = self._events.get(run_id)
        if events is None:
            return None
        return RunTimeline(
            run_id=run_id,
            events=tuple(events),
            current_phase=None,
            start_time=events[0].timestamp,
        )

    def get_current_status(self, run_id: str) -> StepStatus | None:
        events = self._events.get(run_id)
        if not events:
            return None
        return events[-1].status


@pytest.fixture()
def timeline_port() -> _StubRunTimeline:
    return _StubRunTimeline()


@pytest.fixture()
def tools(
    timeline_port: _StubRunTimeline,
) -> tuple[dict[str, ToolSpec], dict[str, object]]:
    from swarmline.hitl.hitl_tools import create_hitl_tools

    diff_mgr = InMemoryDiffReviewManager()
    evidence_mgr = InMemoryEvidenceCollector()
    retry_mgr = InMemoryRetryManager(timeline_port=timeline_port, max_attempts=3)

    return create_hitl_tools(
        diff_review_manager=diff_mgr,
        evidence_collector=evidence_mgr,
        retry_manager=retry_mgr,
        timeline_port=timeline_port,
    )


class TestCreateHitlTools:
    """Tests for create_hitl_tools factory."""

    def test_returns_five_tool_specs(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        specs, executors = tools
        assert len(specs) == 5
        assert len(executors) == 5

    def test_all_specs_are_tool_spec(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        specs, _ = tools
        for spec in specs.values():
            assert isinstance(spec, ToolSpec)

    def test_tool_names(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        specs, _ = tools
        expected = {
            "view_timeline",
            "review_diff",
            "collect_evidence",
            "retry_step",
            "resume_run",
        }
        assert set(specs.keys()) == expected

    def test_executor_names_match_specs(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        specs, executors = tools
        assert set(specs.keys()) == set(executors.keys())


class TestViewTimelineTool:
    """Tests for view_timeline tool."""

    def test_returns_valid_json(
        self,
        tools: tuple[dict[str, ToolSpec], dict[str, object]],
        timeline_port: _StubRunTimeline,
    ) -> None:
        _, executors = tools
        event = TimelineEvent(
            event_id="e1",
            run_id="run-1",
            step_name="step-a",
            status=StepStatus.COMPLETED,
            timestamp=datetime.now(UTC),
        )
        timeline_port.record_event(event)
        result = executors["view_timeline"]({"run_id": "run-1"})
        parsed = json.loads(result)
        assert parsed["run_id"] == "run-1"

    def test_missing_run_id_returns_error(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        _, executors = tools
        result = executors["view_timeline"]({"run_id": "nonexistent"})
        parsed = json.loads(result)
        assert parsed["status"] == "error"


class TestReviewDiffTool:
    """Tests for review_diff tool."""

    def test_returns_valid_json(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        specs, executors = tools
        # First submit a diff via the underlying manager (setup)
        from swarmline.hitl.hitl_tools import create_hitl_tools

        diff_mgr = InMemoryDiffReviewManager()
        evidence_mgr = InMemoryEvidenceCollector()
        timeline_port = _StubRunTimeline()
        retry_mgr = InMemoryRetryManager(timeline_port=timeline_port, max_attempts=3)
        specs, executors = create_hitl_tools(
            diff_review_manager=diff_mgr,
            evidence_collector=evidence_mgr,
            retry_manager=retry_mgr,
            timeline_port=timeline_port,
        )
        diff_mgr.submit_diff(
            DiffReview(
                diff_id="d-1",
                run_id="run-1",
                file_path="f.py",
                diff_content="diff",
            )
        )
        result = executors["review_diff"](
            {"diff_id": "d-1", "decision": "approved", "reason": "OK"}
        )
        parsed = json.loads(result)
        assert parsed["decision"] == "approved"
        assert parsed["diff_id"] == "d-1"

    def test_missing_diff_returns_error(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        _, executors = tools
        result = executors["review_diff"](
            {"diff_id": "nonexistent", "decision": "approved"}
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"


class TestCollectEvidenceTool:
    """Tests for collect_evidence tool."""

    def test_returns_valid_json(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        _, executors = tools
        result = executors["collect_evidence"](
            {"run_id": "run-1", "test_results": ["PASS"]}
        )
        parsed = json.loads(result)
        assert parsed["run_id"] == "run-1"
        assert parsed["test_results"] == ["PASS"]

    def test_missing_run_id_returns_error(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        _, executors = tools
        result = executors["collect_evidence"]({})
        parsed = json.loads(result)
        assert parsed["status"] == "error"


class TestRetryStepTool:
    """Tests for retry_step tool."""

    def test_returns_valid_json(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        _, executors = tools
        result = executors["retry_step"]({"run_id": "run-1", "step_name": "step-a"})
        parsed = json.loads(result)
        assert parsed["run_id"] == "run-1"
        assert parsed["step_name"] == "step-a"
        assert parsed["attempt_number"] == 1

    def test_missing_params_returns_error(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        _, executors = tools
        result = executors["retry_step"]({})
        parsed = json.loads(result)
        assert parsed["status"] == "error"


class TestResumeRunTool:
    """Tests for resume_run tool."""

    def test_returns_valid_json(
        self,
        tools: tuple[dict[str, ToolSpec], dict[str, object]],
        timeline_port: _StubRunTimeline,
    ) -> None:
        _, executors = tools
        event = TimelineEvent(
            event_id="e1",
            run_id="run-1",
            step_name="step-a",
            status=StepStatus.COMPLETED,
            timestamp=datetime.now(UTC),
        )
        timeline_port.record_event(event)
        result = executors["resume_run"]({"run_id": "run-1"})
        parsed = json.loads(result)
        assert parsed["run_id"] == "run-1"

    def test_missing_run_id_returns_error(
        self, tools: tuple[dict[str, ToolSpec], dict[str, object]]
    ) -> None:
        _, executors = tools
        result = executors["resume_run"]({})
        parsed = json.loads(result)
        assert parsed["status"] == "error"
