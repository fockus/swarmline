"""TDD tests for Task 1 of the harness-composition spec (Epic H3).

Covers REQ-001, REQ-010: the domain foundation for harness composition —
four frozen dataclasses that are the single source of truth for building an
agent's kernel/composition/infra/middleware/tools/memory. Pure data, no
builder, no YAML, no registry resolution (those are Tasks 2-5).

Also covers graph-composition spec, Task 1 (REQ-001): ``CompositionSpec``'s
optional declarative graph topology (``edges``/``parallel``/``routes``) and
its two new sub-specs, ``RouteSpec``/``ParallelSpec`` — all defaulting to
empty so every existing spec stays byte-identical in behavior.

Written BEFORE the implementation (TDD, RED first).
"""

from __future__ import annotations

import dataclasses

import pytest

from swarmline.harness import (
    CompositionSpec,
    HarnessSpec,
    InfraSpec,
    ParallelSpec,
    RouteSpec,
    WorkerSpec,
)


class TestHarnessSpecDefaults:
    def test_harness_spec_defaults_to_react_kernel_solo(self) -> None:
        """REQ-010: minimal spec (no args) is a solo ReAct kernel — no
        composition, no infra, no preset, empty middleware/tools tuples."""
        spec = HarnessSpec()

        assert spec.kernel == "react"
        assert spec.composition is None
        assert spec.infra is None
        assert spec.preset is None
        assert spec.middleware == ()
        assert spec.tools == ()
        assert spec.memory is None


class TestFrozenImmutability:
    @pytest.mark.parametrize(
        ("instance_factory", "attr", "value"),
        [
            (lambda: HarnessSpec(), "kernel", "planner"),
            (lambda: CompositionSpec(mode="supervisor"), "mode", "graph"),
            (lambda: InfraSpec(), "checkpoint", True),
            (lambda: WorkerSpec(role="researcher"), "role", "writer"),
            (
                lambda: RouteSpec(
                    source="reviewer",
                    key="verdict",
                    mapping=(("approve", "publisher"),),
                ),
                "source",
                "other",
            ),
            (
                lambda: ParallelSpec(members=("r1", "r2"), then="synth"),
                "then",
                "other",
            ),
        ],
        ids=[
            "HarnessSpec",
            "CompositionSpec",
            "InfraSpec",
            "WorkerSpec",
            "RouteSpec",
            "ParallelSpec",
        ],
    )
    def test_specs_frozen(self, instance_factory, attr, value) -> None:
        instance = instance_factory()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, attr, value)


class TestSubSpecDefaults:
    def test_composition_spec_requires_mode_positionally(self) -> None:
        """CompositionSpec.mode has no default — must be supplied."""
        spec = CompositionSpec(mode="supervisor")

        assert spec.mode == "supervisor"
        assert spec.workers == ()
        assert spec.blackboard is True

    def test_composition_spec_missing_mode_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            CompositionSpec()  # type: ignore[call-arg]

    def test_infra_spec_defaults_all_false(self) -> None:
        infra = InfraSpec()

        assert infra.checkpoint is False
        assert infra.event_record is False
        assert infra.replay is False

    def test_worker_spec_defaults_kernel_to_react(self) -> None:
        worker = WorkerSpec(role="researcher")

        assert worker.role == "researcher"
        assert worker.kernel == "react"
        assert worker.tools == ()


class TestGraphTopologyDefaults:
    """graph-composition spec, Task 1 (REQ-001): edges/parallel/routes
    default to empty tuples — every spec written before this extension
    stays byte-identical in behavior."""

    def test_composition_spec_topology_fields_default_empty(self) -> None:
        spec = CompositionSpec(mode="supervisor", workers=(WorkerSpec(role="a"),))

        assert spec.edges == ()
        assert spec.parallel == ()
        assert spec.routes == ()

    def test_pre_extension_style_construction_still_equal(self) -> None:
        """A CompositionSpec built exactly the way it was before this
        extension (no topology kwargs at all) equals one built the same way
        today — proves the extension is purely additive (byte-identical)."""
        pre_extension_style = CompositionSpec(
            mode="supervisor", workers=(), blackboard=True
        )
        post_extension_default = CompositionSpec(mode="supervisor")

        assert pre_extension_style == post_extension_default

    def test_route_spec_defaults_default_field_to_none(self) -> None:
        route = RouteSpec(
            source="reviewer", key="verdict", mapping=(("approve", "publisher"),)
        )

        assert route.source == "reviewer"
        assert route.key == "verdict"
        assert route.mapping == (("approve", "publisher"),)
        assert route.default is None

    def test_route_spec_missing_required_fields_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            RouteSpec(source="reviewer")  # type: ignore[call-arg]

    def test_parallel_spec_holds_members_and_join_target(self) -> None:
        group = ParallelSpec(members=("r1", "r2"), then="synth")

        assert group.members == ("r1", "r2")
        assert group.then == "synth"

    def test_parallel_spec_missing_then_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            ParallelSpec(members=("r1", "r2"))  # type: ignore[call-arg]
