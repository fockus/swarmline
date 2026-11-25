"""Supervisor-orchestrator sub-package (H6).

Kept import-light on purpose — do NOT re-export from `orchestration/__init__.py`,
which eager-imports ThinRuntime (I-020).

NOTE: `build_supervisor` (kernel.py) imports `ThinRuntime` lazily inside the
function body, so importing this package (this module) does NOT pull in
ThinRuntime — only *calling* `build_supervisor(...)` does.
"""

from __future__ import annotations

from swarmline.orchestration.supervisor.blackboard import (
    Blackboard,
    ContextSlice,
    PlanPatch,
)
from swarmline.orchestration.supervisor.finalize import FINALIZE_TOOL_SPEC
from swarmline.orchestration.supervisor.handoff import GraphHandoffRunner, handoff
from swarmline.orchestration.supervisor.kernel import SupervisorKernel, build_supervisor
from swarmline.orchestration.supervisor.mailbox import Mailbox, OutboxMessage
from swarmline.orchestration.supervisor.replan import (
    Decomposer,
    is_blocker,
    plan_via_subagent,
)
from swarmline.orchestration.supervisor.state import SupervisorState
from swarmline.orchestration.supervisor.tools import (
    READ_REPORTS_TOOL_SPEC,
    SEND_MESSAGE_TOOL_SPEC,
    SPAWN_SUBAGENT_TOOL_SPEC,
    UPDATE_PLAN_TOOL_SPEC,
)
from swarmline.orchestration.supervisor.types import Report

__all__ = [
    "Blackboard",
    "ContextSlice",
    "PlanPatch",
    "Report",
    "SupervisorState",
    "Mailbox",
    "OutboxMessage",
    "Decomposer",
    "is_blocker",
    "plan_via_subagent",
    "GraphHandoffRunner",
    "handoff",
    "SupervisorKernel",
    "build_supervisor",
    "SPAWN_SUBAGENT_TOOL_SPEC",
    "UPDATE_PLAN_TOOL_SPEC",
    "SEND_MESSAGE_TOOL_SPEC",
    "READ_REPORTS_TOOL_SPEC",
    "FINALIZE_TOOL_SPEC",
]
