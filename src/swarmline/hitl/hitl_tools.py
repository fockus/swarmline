"""HITL tool factory — agent-callable tools for human-in-the-loop operations.

Creates 5 tools: view_timeline, review_diff, collect_evidence, retry_step, resume_run.
All return JSON-serialized results. Follows code_intel/tools.py pattern.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from swarmline.domain_types import ToolSpec
from swarmline.hitl.hitl_protocols import (
    DiffReviewPort,
    EvidenceSurfacePort,
    RetryManagerPort,
    RunTimelinePort,
)
from swarmline.hitl.timeline_types import DiffDecision

# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

_VIEW_TIMELINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "Run ID to view timeline for"},
    },
    "required": ["run_id"],
}

_REVIEW_DIFF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "diff_id": {"type": "string", "description": "Diff ID to review"},
        "decision": {
            "type": "string",
            "enum": ["approved", "rejected", "changes_requested"],
            "description": "Review decision",
        },
        "reason": {"type": "string", "description": "Optional reason for decision"},
    },
    "required": ["diff_id", "decision"],
}

_COLLECT_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "Run ID to collect evidence for"},
        "test_results": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Test result strings",
        },
        "logs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Log lines",
        },
        "artifacts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Artifact paths",
        },
        "changed_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Changed file paths",
        },
    },
    "required": ["run_id"],
}

_RETRY_STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "Run ID"},
        "step_name": {"type": "string", "description": "Step name to retry"},
    },
    "required": ["run_id", "step_name"],
}

_RESUME_RUN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "Run ID to resume"},
    },
    "required": ["run_id"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DECISION_MAP: dict[str, DiffDecision] = {
    "approved": DiffDecision.APPROVED,
    "rejected": DiffDecision.REJECTED,
    "changes_requested": DiffDecision.CHANGES_REQUESTED,
}


def _error_json(error_type: str, message: str) -> str:
    return json.dumps({"status": "error", "error_type": error_type, "message": message})


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_hitl_tools(
    *,
    diff_review_manager: DiffReviewPort,
    evidence_collector: EvidenceSurfacePort,
    retry_manager: RetryManagerPort,
    timeline_port: RunTimelinePort,
) -> tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]]:
    """Create 5 HITL tools for agent use.

    Returns (specs dict, executors dict) matching the workspace tools pattern.
    """
    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable[..., Any]] = {}

    # 1. view_timeline
    def _view_timeline(args: dict[str, Any]) -> str:
        run_id = args.get("run_id", "")
        if not run_id:
            return _error_json("validation", "run_id is required")

        timeline = timeline_port.get_timeline(run_id)
        if timeline is None:
            return _error_json("not_found", f"No timeline found for run_id={run_id}")

        return json.dumps(
            {
                "run_id": timeline.run_id,
                "current_phase": timeline.current_phase,
                "start_time": timeline.start_time.isoformat(),
                "end_time": timeline.end_time.isoformat()
                if timeline.end_time
                else None,
                "events": [
                    {
                        "event_id": e.event_id,
                        "step_name": e.step_name,
                        "status": e.status.value,
                        "timestamp": e.timestamp.isoformat(),
                        "tool_name": e.tool_name,
                        "output": e.output,
                        "error": e.error,
                        "duration_ms": e.duration_ms,
                    }
                    for e in timeline.events
                ],
            }
        )

    specs["view_timeline"] = ToolSpec(
        name="view_timeline",
        description="View the timeline of events for an agent run",
        parameters=_VIEW_TIMELINE_SCHEMA,
    )
    executors["view_timeline"] = _view_timeline

    # 2. review_diff
    def _review_diff(args: dict[str, Any]) -> str:
        diff_id = args.get("diff_id", "")
        decision_str = args.get("decision", "")
        reason = args.get("reason", "")

        if not diff_id or not decision_str:
            return _error_json("validation", "diff_id and decision are required")

        decision = _DECISION_MAP.get(decision_str)
        if decision is None:
            return _error_json(
                "validation",
                f"Invalid decision: {decision_str}. Must be one of: approved, rejected, changes_requested",
            )

        try:
            result = diff_review_manager.decide(diff_id, decision, reason)
        except KeyError:
            return _error_json("not_found", f"No diff found for diff_id={diff_id}")
        except ValueError as e:
            return _error_json("already_decided", str(e))

        return json.dumps(
            {
                "diff_id": result.diff_id,
                "run_id": result.run_id,
                "file_path": result.file_path,
                "decision": result.decision.value,
                "reason": result.reason,
            }
        )

    specs["review_diff"] = ToolSpec(
        name="review_diff",
        description="Review a code diff — approve, reject, or request changes",
        parameters=_REVIEW_DIFF_SCHEMA,
    )
    executors["review_diff"] = _review_diff

    # 3. collect_evidence
    def _collect_evidence(args: dict[str, Any]) -> str:
        run_id = args.get("run_id", "")
        if not run_id:
            return _error_json("validation", "run_id is required")

        ev = evidence_collector.collect_evidence(
            run_id,
            test_results=tuple(args.get("test_results", [])),
            logs=tuple(args.get("logs", [])),
            artifacts=tuple(args.get("artifacts", [])),
            changed_files=tuple(args.get("changed_files", [])),
            plan_state=args.get("plan_state"),
        )

        return json.dumps(
            {
                "run_id": ev.run_id,
                "test_results": list(ev.test_results),
                "logs": list(ev.logs),
                "artifacts": list(ev.artifacts),
                "changed_files": list(ev.changed_files),
                "plan_state": ev.plan_state,
            }
        )

    specs["collect_evidence"] = ToolSpec(
        name="collect_evidence",
        description="Collect test results, logs, and artifacts from an agent run",
        parameters=_COLLECT_EVIDENCE_SCHEMA,
    )
    executors["collect_evidence"] = _collect_evidence

    # 4. retry_step
    def _retry_step(args: dict[str, Any]) -> str:
        run_id = args.get("run_id", "")
        step_name = args.get("step_name", "")
        if not run_id or not step_name:
            return _error_json("validation", "run_id and step_name are required")

        if not retry_manager.can_retry(run_id, step_name):
            return _error_json(
                "max_retries_exhausted",
                f"Max retry attempts exhausted for run_id={run_id}, step={step_name}",
            )

        ctx = retry_manager.retry_step(run_id, step_name)

        return json.dumps(
            {
                "original_event_id": ctx.original_event_id,
                "run_id": ctx.run_id,
                "step_name": ctx.step_name,
                "attempt_number": ctx.attempt_number,
                "max_attempts": ctx.max_attempts,
                "preserved_state": ctx.preserved_state,
            }
        )

    specs["retry_step"] = ToolSpec(
        name="retry_step",
        description="Retry a failed step in an agent run",
        parameters=_RETRY_STEP_SCHEMA,
    )
    executors["retry_step"] = _retry_step

    # 5. resume_run
    def _resume_run(args: dict[str, Any]) -> str:
        run_id = args.get("run_id", "")
        if not run_id:
            return _error_json("validation", "run_id is required")

        timeline = retry_manager.resume_run(run_id)

        return json.dumps(
            {
                "run_id": timeline.run_id,
                "current_phase": timeline.current_phase,
                "start_time": timeline.start_time.isoformat(),
                "end_time": timeline.end_time.isoformat()
                if timeline.end_time
                else None,
                "events": [
                    {
                        "event_id": e.event_id,
                        "step_name": e.step_name,
                        "status": e.status.value,
                        "timestamp": e.timestamp.isoformat(),
                    }
                    for e in timeline.events
                ],
            }
        )

    specs["resume_run"] = ToolSpec(
        name="resume_run",
        description="Resume an agent run from the last completed step",
        parameters=_RESUME_RUN_SCHEMA,
    )
    executors["resume_run"] = _resume_run

    return specs, executors
