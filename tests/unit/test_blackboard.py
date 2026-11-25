"""Tests for the Blackboard shared-plan artifact (H6 supervisor-orchestrator, Task 1).

Covers REQ-004 (shared plan as a blackboard artifact) and REQ-005 (each worker gets
a scoped context slice). TDD: written before the implementation exists.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from swarmline.domain_types import LifecycleMode
from swarmline.orchestration.supervisor.blackboard import (
    Blackboard,
    ContextSlice,
    PlanPatch,
)
from swarmline.orchestration.types import Plan, PlanStep
from swarmline.protocols.host_adapter import AgentHandle


def _make_plan(*, goal: str = "Ship feature X") -> Plan:
    return Plan(
        id="plan-1",
        goal=goal,
        steps=[
            PlanStep(id="step-1", description="Research"),
            PlanStep(id="step-2", description="Implement"),
            PlanStep(id="step-3", description="Verify"),
        ],
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


def _make_handle(worker_id: str) -> AgentHandle:
    return AgentHandle(id=worker_id, role="worker", lifecycle=LifecycleMode.EPHEMERAL)


class TestBlackboardWithPatch:
    def test_blackboard_with_patch_returns_new_immutable(self) -> None:
        plan = _make_plan()
        bb = Blackboard(plan=plan)
        patch = PlanPatch(
            step=PlanStep(
                id="step-2", description="Implement", status="completed", result="done"
            )
        )

        bb2 = bb.with_patch(patch)

        assert bb2 is not bb
        # Original blackboard/plan/step are untouched.
        original_step = next(s for s in bb.plan.steps if s.id == "step-2")
        assert original_step.status == "pending"
        assert original_step.result is None
        # New blackboard reflects the patch.
        patched_step = next(s for s in bb2.plan.steps if s.id == "step-2")
        assert patched_step.status == "completed"
        assert patched_step.result == "done"

    def test_with_patch_on_unknown_step_id_propagates_value_error(self) -> None:
        bb = Blackboard(plan=_make_plan())
        patch = PlanPatch(step=PlanStep(id="no-such-step", description="ghost"))

        with pytest.raises(ValueError, match="no-such-step"):
            bb.with_patch(patch)

    def test_with_patch_carries_over_assignments(self) -> None:
        plan = _make_plan()
        worker = _make_handle("worker-a")
        bb = Blackboard(plan=plan, assignments={worker.id: ("step-1",)})
        patch = PlanPatch(
            step=PlanStep(
                id="step-1", description="Research", status="completed", result="ok"
            )
        )

        bb2 = bb.with_patch(patch)

        assert bb2.assignments == {"worker-a": ("step-1",)}

    def test_with_patch_caller_mutation_of_patch_step_does_not_leak(self) -> None:
        plan = _make_plan()
        bb = Blackboard(plan=plan)
        step = PlanStep(
            id="step-2",
            description="Implement",
            substeps=[PlanStep(id="sub-1", description="Draft")],
        )
        patch = PlanPatch(step=step)

        bb2 = bb.with_patch(patch)
        # Mutate the caller's original step (and its substeps list) after the call.
        step.substeps.append(PlanStep(id="sub-2", description="Injected"))

        patched_step = next(s for s in bb2.plan.steps if s.id == "step-2")
        assert [s.id for s in patched_step.substeps] == ["sub-1"]


class TestBlackboardSliceFor:
    def test_blackboard_slice_for_worker_returns_scoped_subset(self) -> None:
        plan = _make_plan()
        worker_a = _make_handle("worker-a")
        worker_b = _make_handle("worker-b")
        bb = Blackboard(
            plan=plan,
            assignments={
                worker_a.id: ("step-1", "step-3"),
                worker_b.id: ("step-2",),
            },
        )

        slice_a = bb.slice_for(worker_a)

        assert slice_a.goal == "Ship feature X"
        assert [s.id for s in slice_a.steps] == ["step-1", "step-3"]
        assert "step-2" not in [s.id for s in slice_a.steps]

    def test_slice_for_unassigned_worker_returns_empty_steps_no_leak(self) -> None:
        bb = Blackboard(plan=_make_plan())
        stranger = _make_handle("stranger")

        result = bb.slice_for(stranger)

        assert result.steps == ()
        assert result.goal == "Ship feature X"

    def test_slice_for_preserves_plan_order_when_assignments_out_of_order(self) -> None:
        plan = _make_plan()
        worker = _make_handle("worker-a")
        # Assignment tuple lists step-3 before step-1 — plan order must still win.
        bb = Blackboard(plan=plan, assignments={worker.id: ("step-3", "step-1")})

        result = bb.slice_for(worker)

        assert [s.id for s in result.steps] == ["step-1", "step-3"]

    def test_slice_for_step_substeps_mutation_does_not_leak_to_plan(self) -> None:
        plan = Plan(
            id="plan-1",
            goal="Ship feature X",
            steps=[
                PlanStep(
                    id="step-1",
                    description="Research",
                    substeps=[PlanStep(id="sub-1", description="Draft")],
                ),
            ],
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        worker = _make_handle("worker-a")
        bb = Blackboard(plan=plan, assignments={worker.id: ("step-1",)})

        slice_ = bb.slice_for(worker)
        slice_.steps[0].substeps.append(PlanStep(id="sub-2", description="Injected"))

        original_step = next(s for s in bb.plan.steps if s.id == "step-1")
        assert [s.id for s in original_step.substeps] == ["sub-1"]


class TestBlackboardWithAssignment:
    def test_blackboard_with_assignment_returns_new_immutable(self) -> None:
        bb = Blackboard(plan=_make_plan())

        bb2 = bb.with_assignment("w1", ["step-1"])

        assert bb2 is not bb
        # Original blackboard is untouched — no "w1" key leaked into it.
        assert "w1" not in bb.assignments
        assert bb2.assignments["w1"] == ("step-1",)
        sliced = bb2.slice_for(AgentHandle(id="w1", role="r"))
        assert [s.id for s in sliced.steps] == ["step-1"]
        # New assignments mapping is still read-only.
        with pytest.raises(TypeError):
            bb2.assignments["w1"] = ("step-2",)  # type: ignore[index]


class TestBlackboardAssignmentsImmutability:
    def test_assignments_external_dict_mutation_does_not_change_slice(self) -> None:
        plan = _make_plan()
        worker = _make_handle("worker-a")
        stranger = _make_handle("stranger")
        d: dict[str, tuple[str, ...]] = {worker.id: ("step-1",)}
        bb = Blackboard(plan=plan, assignments=d)

        # Mutate the caller's dict after construction — broaden and add a new key.
        d[worker.id] = ("step-1", "step-2", "step-3")
        d[stranger.id] = ("step-1", "step-2", "step-3")

        result = bb.slice_for(worker)
        assert [s.id for s in result.steps] == ["step-1"]
        stranger_result = bb.slice_for(stranger)
        assert stranger_result.steps == ()

    def test_assignments_is_read_only_mapping(self) -> None:
        bb = Blackboard(plan=_make_plan())
        with pytest.raises(TypeError):
            bb.assignments["x"] = ("step-1",)  # type: ignore[index]


class TestFrozenInvariants:
    def test_blackboard_is_frozen(self) -> None:
        bb = Blackboard(plan=_make_plan())
        with pytest.raises(FrozenInstanceError):
            bb.plan = _make_plan()  # type: ignore[misc]

    def test_context_slice_is_frozen(self) -> None:
        slice_ = ContextSlice(goal="g", steps=())
        with pytest.raises(FrozenInstanceError):
            slice_.goal = "other"  # type: ignore[misc]

    def test_plan_patch_is_frozen(self) -> None:
        patch = PlanPatch(step=PlanStep(id="step-1", description="Research"))
        with pytest.raises(FrozenInstanceError):
            patch.step = PlanStep(id="step-2", description="Implement")  # type: ignore[misc]
