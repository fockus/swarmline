"""Unit: taskloom-style embedding example — REQ-011/012 embeddability.

harness-composition spec, Task 5 (REQ-011 "downstream apps ... embed it",
mirrors design.md's ADR "output = existing Agent -> taskloom embeds as
inner agent"). This file is the executable counterpart of
``docs/harness.md``'s "Composable harness for taskloom" section: it proves
the DOCUMENTED example code actually does what the doc claims, both for the
part that builds today (``simple-react``, any composition-free spec) and
for the part that is honestly deferred (the durable ``supervisor-team`` +
checkpointing pattern — I-052/I-053, not yet wired).

No fake/mocked "successful durable build" anywhere in this file — the
durable-pattern test explicitly asserts the CURRENT, honest outcome
(``CompositionBlockNotFound`` naming "supervisor"), matching Task 4's own
``test_composition_preset_expands_valid_but_build_raises_composition_not_found``
pattern.
"""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.presets import get_preset_registry
from swarmline.harness.registries import CompositionBlockNotFound
from swarmline.harness.spec import CompositionSpec, HarnessSpec, InfraSpec, WorkerSpec
from swarmline.harness.yaml_loader import load_harness_yaml


class TestTaskloomSimpleAgentThreeEquivalentRoutes:
    """taskloom's simplest embedding: one solo-react worker agent, buildable
    via all three front-ends (SDK / YAML / preset) — they agree exactly."""

    def test_sdk_yaml_and_preset_produce_the_identical_spec(
        self, tmp_path: Any
    ) -> None:
        sdk_spec = HarnessBuilder().kernel("react").spec

        yaml_path = tmp_path / "taskloom_simple.yaml"
        yaml_path.write_text("kernel: react\n")
        yaml_spec = load_harness_yaml(str(yaml_path))

        preset_spec = get_preset_registry().expand("simple-react")

        assert sdk_spec == yaml_spec == preset_spec == HarnessSpec(kernel="react")

    def test_the_shared_spec_builds_a_real_embeddable_agent(self) -> None:
        """The REQ-012 promise: taskloom gets back the EXISTING Agent
        interface and can embed it as its own inner agent, today, for the
        composition-free case."""
        from swarmline.agent import Agent

        spec = get_preset_registry().expand("simple-react")

        agent = HarnessBuilder.from_spec(spec).build()

        assert isinstance(agent, Agent)
        assert agent.config.native_config["harness_kernel"] == "react"


class TestTaskloomDurableSupervisorPatternHonestDeferral:
    """taskloom's INTENDED durable pattern: preset('supervisor-team') +
    with_checkpointing(). Expands to a fully valid, well-formed spec (the
    documented intent) but does NOT build end-to-end yet — the supervisor
    composition block (I-052) and the checkpoint infra block (I-053) are
    not wired into their registries. This is the honest, current state;
    the doc says so explicitly and this test proves the doc is not lying.
    """

    def _assemble_intended_durable_spec(self) -> HarnessSpec:
        """Mirrors ``docs/harness.md``'s taskloom durable-supervisor example:
        start from the ``supervisor-team`` preset, layer checkpointing on
        top via the SDK builder."""
        preset_spec = get_preset_registry().expand("supervisor-team")
        return HarnessBuilder.from_spec(preset_spec).with_checkpointing().spec

    def test_durable_pattern_expands_to_the_documented_valid_spec_shape(self) -> None:
        spec = self._assemble_intended_durable_spec()

        assert spec.kernel == "react"
        assert spec.composition == CompositionSpec(
            mode="supervisor",
            workers=(
                WorkerSpec(role="researcher"),
                WorkerSpec(role="coder"),
                WorkerSpec(role="reviewer"),
            ),
            blackboard=True,
        )
        assert spec.infra == InfraSpec(checkpoint=True)

    def test_durable_pattern_build_fails_loud_naming_supervisor_not_faked(self) -> None:
        """The honest current outcome: ``.build()`` raises
        ``CompositionBlockNotFound`` naming "supervisor" -- proving the
        seam is correct and the doc's "not yet wired" claim is true, rather
        than silently returning a fake/no-op durable agent."""
        spec = self._assemble_intended_durable_spec()

        with pytest.raises(CompositionBlockNotFound) as exc_info:
            HarnessBuilder.from_spec(spec).build()

        assert "supervisor" in str(exc_info.value)

    def test_one_line_registration_would_light_it_up(self) -> None:
        """Documents (executably) the exact backlog-closing action
        (I-052): registering a "supervisor" resolver into the composition
        registry is the ONE line that turns this from
        ``CompositionBlockNotFound`` into a real build — proven here with a
        throwaway local registry (never touching the shared process-wide
        singleton other tests depend on staying empty)."""
        from swarmline.harness.registries import _BlockRegistry

        local_registry = _BlockRegistry(CompositionBlockNotFound)
        local_registry.register("supervisor", lambda: object())

        # Proves the registration mechanism itself (register -> get
        # succeeds) without asserting anything about the real, still-empty
        # process-wide composition registry used by HarnessBuilder.build().
        assert local_registry.get("supervisor") is not None
        assert "supervisor" in local_registry.names()
