"""Unit: HarnessBuilder — SDK front-end resolving HarnessSpec -> Agent.

harness-composition spec, Task 2 (REQ-002, REQ-004, REQ-008, REQ-009,
REQ-012).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.registries import (
    CompositionBlockNotFound,
    InfraBlockNotFound,
    get_composition_registry,
    get_infra_registry,
)
from swarmline.harness.spec import HarnessSpec, WorkerSpec


class TestHarnessBuilderMinimalSpecNoOverhead:
    """REQ-008/009: kernel-only spec builds a simple agent, zero overhead."""

    def test_builder_minimal_kernel_only_no_overhead(self) -> None:
        """HarnessBuilder().build() -> plain react Agent; no composition/infra touched."""
        from swarmline.agent import Agent

        with (
            patch(
                "swarmline.harness.builder.get_composition_registry"
            ) as composition_mock,
            patch("swarmline.harness.builder.get_infra_registry") as infra_mock,
        ):
            agent = HarnessBuilder().build()

        assert isinstance(agent, Agent)
        assert agent.config.native_config.get("harness_kernel") == "react"
        composition_mock.assert_not_called()
        infra_mock.assert_not_called()

    def test_builder_minimal_spec_has_no_composition_or_infra(self) -> None:
        """The accumulated spec for a bare builder carries no composition/infra."""
        builder = HarnessBuilder()

        assert builder.spec.composition is None
        assert builder.spec.infra is None
        assert builder.spec.kernel == "react"


class TestHarnessBuilderResolvesKernelViaRegistry:
    """REQ-002: kernel resolution goes through the H1 KernelRegistry, not if/elif."""

    def teardown_method(self) -> None:
        # Test isolation: never leak a custom mode into the process-wide
        # default registry used by other tests / test files.
        from swarmline.runtime.thin.kernels import reset_default_kernel_registry

        reset_default_kernel_registry()

    def test_builder_resolves_kernel_via_registry_for_builtin_mode(self) -> None:
        """.kernel("react").build() succeeds and the resolved mode == 'react'."""
        agent = HarnessBuilder().kernel("react").build()

        assert agent.config.native_config["harness_kernel"] == "react"

    def test_builder_resolves_arbitrary_runtime_registered_kernel_not_hardcoded(
        self,
    ) -> None:
        """A kernel registered at RUNTIME (not one of the fixed built-ins) also
        resolves — proving build() consults the live registry rather than a
        hardcoded if/elif over a fixed set of known mode names.
        """
        from swarmline.runtime.thin.kernels import get_default_kernel_registry

        class _NoopKernel:
            def run(self, ctx: Any) -> Any:
                async def _gen():
                    return
                    yield  # pragma: no cover - never reached

                return _gen()

        mode_name = "harness_builder_test_custom_mode"
        get_default_kernel_registry().register(mode_name, lambda: _NoopKernel())

        assert mode_name in get_default_kernel_registry().modes()

        agent = HarnessBuilder().kernel(mode_name).build()

        assert agent.config.native_config["harness_kernel"] == mode_name

    def test_builder_rejects_unregistered_kernel_with_named_error(self) -> None:
        """An unknown kernel name is rejected — proves real validation, not
        blind acceptance of any string.
        """
        from swarmline.runtime.thin.kernels import KernelNotFound

        with pytest.raises(KernelNotFound) as exc_info:
            HarnessBuilder().kernel("definitely-not-a-registered-kernel").build()

        assert "definitely-not-a-registered-kernel" in str(exc_info.value)

    async def test_builder_custom_kernel_drives_agent_query_end_to_end(self) -> None:
        """The registry-resolved kernel actually drives the built Agent's
        query loop — not react/conversational — proven without touching the
        network (only the LLM call boundary is faked).
        """
        from swarmline.runtime.thin.kernels import get_default_kernel_registry
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeEvent

        sentinel_text = "harness-custom-kernel-ran"
        mode_name = "harness_builder_e2e_custom_mode"

        class _SentinelKernel:
            def run(self, ctx: Any) -> Any:
                async def _gen():
                    yield RuntimeEvent.final(text=sentinel_text)

                return _gen()

        get_default_kernel_registry().register(mode_name, lambda: _SentinelKernel())

        agent = HarnessBuilder().kernel(mode_name).build()

        async def unreachable_llm(
            messages: Any, system_prompt: Any, **kwargs: Any
        ) -> str:
            raise AssertionError(
                "llm_call must not be invoked; the custom, registry-resolved "
                "kernel must drive the loop directly instead of falling back "
                "to react/conversational."
            )

        fake_factory = MagicMock()
        fake_factory.create.side_effect = lambda **kwargs: ThinRuntime(
            config=kwargs["config"], llm_call=unreachable_llm
        )

        with patch(
            "swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory
        ):
            result = await agent.query("hello")

        assert result.ok is True
        assert result.text == sentinel_text


class TestHarnessBuilderReturnsExistingAgentInterface:
    """REQ-012: the assembled agent is the EXISTING Agent interface."""

    def test_builder_returns_existing_agent_interface(self) -> None:
        from swarmline.agent import Agent

        agent = HarnessBuilder().kernel("react").build()

        assert isinstance(agent, Agent)


class TestHarnessBuilderFluentChaining:
    """Fluent methods mutate-and-return self so calls chain naturally."""

    def test_fluent_methods_return_the_same_builder_instance(self) -> None:
        builder = HarnessBuilder()

        chained = builder.kernel("react").with_checkpointing().with_events()

        assert chained is builder
        assert builder.spec.kernel == "react"
        assert builder.spec.infra is not None
        assert builder.spec.infra.checkpoint is True
        assert builder.spec.infra.event_record is True

    def test_supervisor_sets_composition_spec_with_given_workers(self) -> None:
        builder = HarnessBuilder().supervisor(workers=(WorkerSpec(role="researcher"),))

        assert builder.spec.composition is not None
        assert builder.spec.composition.mode == "supervisor"
        assert builder.spec.composition.workers == (WorkerSpec(role="researcher"),)


class TestHarnessBuilderGraphFluent:
    """graph-composition spec, Task 1 (REQ-002): fluent .graph(workers, ...)
    mirrors .supervisor() but sets mode="graph" plus declarative topology."""

    def test_graph_sets_composition_mode_workers_and_edges(self) -> None:
        builder = HarnessBuilder().graph(
            (WorkerSpec(role="a"), WorkerSpec(role="b")),
            edges=[("a", "b"), ("b", "END")],
        )

        assert builder.spec.composition is not None
        assert builder.spec.composition.mode == "graph"
        assert builder.spec.composition.workers == (
            WorkerSpec(role="a"),
            WorkerSpec(role="b"),
        )
        assert builder.spec.composition.edges == (("a", "b"), ("b", "END"))
        assert all(isinstance(edge, tuple) for edge in builder.spec.composition.edges)

    def test_graph_returns_self_for_chaining(self) -> None:
        builder = HarnessBuilder()

        chained = builder.graph((WorkerSpec(role="a"),))

        assert chained is builder

    def test_graph_without_topology_leaves_all_topology_fields_empty(self) -> None:
        builder = HarnessBuilder().graph((WorkerSpec(role="a"),))

        assert builder.spec.composition.edges == ()
        assert builder.spec.composition.parallel == ()
        assert builder.spec.composition.routes == ()

    def test_graph_passes_through_parallel_and_routes(self) -> None:
        from swarmline.harness.spec import ParallelSpec, RouteSpec

        parallel_group = ParallelSpec(members=("r1", "r2"), then="synth")
        route = RouteSpec(
            source="reviewer", key="verdict", mapping=(("approve", "publisher"),)
        )

        builder = HarnessBuilder().graph(
            (WorkerSpec(role="r1"), WorkerSpec(role="r2"), WorkerSpec(role="synth")),
            parallel=(parallel_group,),
            routes=(route,),
        )

        assert builder.spec.composition.parallel == (parallel_group,)
        assert builder.spec.composition.routes == (route,)

    def test_graph_has_no_blackboard_parameter(self) -> None:
        """Design decision: unlike .supervisor(), .graph() takes no
        ``blackboard`` kwarg."""
        import inspect

        signature = inspect.signature(HarnessBuilder.graph)

        assert "blackboard" not in signature.parameters


class TestHarnessBuilderFromSpec:
    """from_spec() wraps an existing HarnessSpec (YAML/preset front-ends, Tasks 3-4)."""

    def test_from_spec_wraps_existing_spec_and_builds(self) -> None:
        from swarmline.agent import Agent

        agent = HarnessBuilder.from_spec(HarnessSpec()).build()

        assert isinstance(agent, Agent)
        assert agent.config.native_config["harness_kernel"] == "react"


class TestHarnessBuilderUnavailableCompositionInfraBlocks:
    """Requesting a composition/infra block not (yet) in the registry seam
    raises a clear, named error — the seam Task 5 (REQ-003) builds on.
    """

    def teardown_method(self) -> None:
        # These tests never register anything into the shared composition/
        # infra singletons, but guard against future test additions that do.
        for registry in (get_composition_registry(), get_infra_registry()):
            for name in registry.names():
                pytest.fail(
                    f"Unexpected leaked registration {name!r} in a "
                    "composition/infra registry singleton."
                )

    def test_supervisor_composition_not_yet_available_raises_named_error(self) -> None:
        with pytest.raises(CompositionBlockNotFound) as exc_info:
            HarnessBuilder().supervisor(workers=(WorkerSpec(role="worker"),)).build()

        assert "supervisor" in str(exc_info.value)

    def test_checkpoint_infra_not_yet_available_raises_named_error(self) -> None:
        with pytest.raises(InfraBlockNotFound) as exc_info:
            HarnessBuilder().with_checkpointing().build()

        assert "checkpoint" in str(exc_info.value)
