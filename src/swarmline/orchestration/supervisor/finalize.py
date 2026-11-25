"""finalize — REQ-011 verify-before-done contract gate on the finalize tool.

H6 supervisor-orchestrator, Task 5. Moved out of `tools.py` (SRP + that
file's 400-line ceiling): `FINALIZE_TOOL_SPEC`/`create_finalize_tool` now
live here. Design decision (per dispatch spec): gate the finalize TOOL
itself, not the ThinRuntime finalization machinery — `create_finalize_tool`
gains OPT-IN `verifier`/`ledger` keyword args.

- Both omitted (the default): finalize returns the SAME plain summary it
  always has — unchanged for every caller that predates Task 5 (REQ-012
  back-compat).
- Both supplied: finalize runs `verifier.verify(ledger, ctx)` (the EXISTING
  `verify-before-done` `Verifier` contract) before reporting completion, then
  applies the SAME coverage-aware rule the runtime finalize gate applies
  (`swarmline.verification.coverage`, I-024) — NOT the ledger's own
  `.gate_passed`, which is intentionally vacuous for zero results,
  advisory-only results, or a criterion with no non-advisory result at all
  (fix-cycle 2, GPT-5.5 external review r1, REQ-011 gate incomplete). If any
  criterion is unmet, finalize returns a BLOCKED result naming every unmet
  criterion id and its reason (`failed` vs `not_verified`) and does NOT
  declare done. Only when every criterion is satisfied does it return the
  done summary.

Idempotent by construction: `ledger` is the caller's ORIGINAL, criteria-only
snapshot (e.g. from `verification.capture.capture_ledger`), captured ONCE
and closed over by the returned executor. Every call re-verifies that SAME
immutable `ledger` — it is never reassigned to the ledger `verify()`
returns — so a block -> (external fix) -> re-call sequence produces a
fresh, non-accumulating set of outcomes each time; nothing is ever mutated.

Kept import-light on purpose (I-020): `swarmline.protocols.verification` is
only needed for a type hint here (behind `TYPE_CHECKING`) —
`create_finalize_tool` never imports it at runtime, it only calls methods on
the caller-supplied `verifier`/`ledger` objects (duck-typed via the
`Verifier` Protocol's single `verify` method). `swarmline.verification.coverage`
IS imported at module level: it is pure-domain (imports only
`swarmline.types` + stdlib, no `RuntimeEvent`/`RuntimeConfig`/runtime pull),
so importing it here does not compromise import-lightness — verified by a
`sys.modules` subprocess check (see test suite / report).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from swarmline.orchestration.supervisor.state import SupervisorState
from swarmline.runtime.types import ToolSpec
from swarmline.verification.coverage import unmet_criteria, unmet_report

if TYPE_CHECKING:
    from swarmline.protocols.verification import Verifier
    from swarmline.types import VerificationLedger

ToolExecutorFn = Callable[[dict[str, Any]], Awaitable[str]]

__all__ = ["FINALIZE_TOOL_SPEC", "create_finalize_tool"]

FINALIZE_TOOL_SPEC = ToolSpec(
    name="finalize",
    description=(
        "Summarize the run: collected worker reports and plan completion "
        "status. WHERE a verification contract is configured, completion is "
        "reported only if every criterion has >=1 non-advisory (deterministic) "
        "result that passed (REQ-011) — otherwise this returns BLOCKED and "
        "names each unmet criterion with its reason (failed/not_verified) "
        "instead of declaring done."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    is_local=True,
)


def _summary_lines(state: SupervisorState) -> list[str]:
    """Build the plain run summary — unchanged from the pre-Task-5 version."""
    plan = state.blackboard.plan
    reports = state.reports
    completed = sum(1 for s in plan.steps if s.status == "completed")
    lines = [
        f"Plan '{plan.id}' ({plan.status}): {completed}/{len(plan.steps)} "
        f"steps completed; {len(reports)} report(s) collected."
    ]
    lines.extend(f"- {r.worker}: {r.status} — {r.summary}" for r in reports)
    return lines


def create_finalize_tool(
    state: SupervisorState,
    *,
    verifier: Verifier | None = None,
    ledger: VerificationLedger | None = None,
) -> ToolExecutorFn:
    """Create the finalize executor bound to `state`, optionally gated on a
    verify-before-done contract (REQ-011).

    `ctx` passed to `verifier.verify(ledger, ctx)` is `state` itself — the
    same `SupervisorState` threaded through every other supervisor tool, so
    a predicate can inspect the plan/reports for evidence if it needs to.
    """

    async def _execute(_args: dict[str, Any]) -> str:
        lines = _summary_lines(state)
        if verifier is None or ledger is None:
            return "\n".join(lines)

        result_ledger = await verifier.verify(ledger, state)
        unmet = unmet_criteria(result_ledger)
        if unmet:
            reports = [unmet_report(c, result_ledger.results) for c in unmet]
            unmet_summary = ", ".join(
                f"{r['criterion_id']} ({r['reason']})" for r in reports
            )
            return (
                f"BLOCKED: verification contract not satisfied — unmet "
                f"criteria: {unmet_summary}.\n" + "\n".join(lines)
            )

        return "\n".join(lines)

    return _execute
