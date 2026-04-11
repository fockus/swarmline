"""Shared test stubs for swarmline orchestration tests.

StubPlannerMode: satisfies CodePlannerPort Protocol with deterministic output.
Replaces PlannerMode placeholder that was in code_workflow_engine.py (Y5).
"""

from __future__ import annotations


class StubPlannerMode:
    """Test-only stub satisfying CodePlannerPort Protocol.

    Produces deterministic output for assertions.
    """

    async def create_plan(self, goal: str) -> str:
        return f"Plan for: {goal}"

    async def execute_plan(self, plan: str) -> str:
        return f"Executed: {plan}"
