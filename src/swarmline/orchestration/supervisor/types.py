"""Report — result-only artifact a worker hands back to the supervisor.

H6 supervisor-orchestrator, Task 2 (REQ-006). Deliberately NOT a reuse of
`orchestration.subagent_types.SubagentResult` — different bounded context.
`Report` never carries a transcript field, so there is nothing for
`read_reports` to leak by construction. Adapted at the tool boundary
(`tools.py::create_spawn_subagent_tool`) via::

    Report(
        worker=role, worker_id=handle.id,
        summary=result.output, status=result.status.state,
    )

Task 4 adds `worker_id` (REQ-008 fix): `worker` is the human-readable ROLE
(display only — `read_reports`/`finalize`), while `worker_id` is the STABLE
IDENTITY that matches `Blackboard.assignments`' key space (`AgentHandle.id`).
`replan_on_blocker` (state.py) MUST join on `worker_id`, never on `worker` —
a role string and an assignment key live in different spaces and are not
guaranteed to ever be equal (they never are in practice: `assign_steps` is
called with `handle.id`, a fresh `uuid4()`, not the role). `worker_id`
defaults to `""` so existing display-only `Report(...)` construction sites
that are never joined back against `assignments` keep working unchanged.

Zero external dependencies beyond stdlib — Domain-adjacent, kept import-light
like the rest of `orchestration/supervisor/` (I-020).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Report:
    """Result-only report from a worker: summary + status, never a transcript.

    `worker` is the display-facing ROLE name. `worker_id` is the assignments-
    key identity (`AgentHandle.id`) — see module docstring for why the two
    must never be conflated.
    """

    worker: str
    summary: str
    status: str
    worker_id: str = ""
