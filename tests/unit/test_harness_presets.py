"""Unit: PresetRegistry — named presets expand into a full HarnessSpec.

harness-composition spec, Task 4 (REQ-007, scenario 2). Written BEFORE the
implementation (TDD, RED first): ``swarmline.harness.presets`` does not
exist yet at the time this file is authored.

Covers:
- ``test_preset_expands_to_full_spec`` — each of the 3 built-in presets
  expands to the exact, documented, field-by-field ``HarnessSpec``.
- ``test_each_builtin_preset_builds_valid_agent`` — ``simple-react`` builds
  a real ``Agent``; ``supervisor-team``/``research-fanout`` expand to a
  valid spec whose composition block is not yet wired (I-052 backlog), so
  ``.build()`` raises ``CompositionBlockNotFound`` naming "supervisor".
- Extras: unknown preset name -> clear, named error; registry is
  extensible (register a custom preset -> expand it).
"""

from __future__ import annotations

import pytest

from swarmline.harness.presets import (
    PresetNotFound,
    PresetRegistry,
    get_preset_registry,
)
from swarmline.harness.registries import CompositionBlockNotFound
from swarmline.harness.spec import CompositionSpec, HarnessSpec, WorkerSpec

_SIMPLE_REACT_SPEC = HarnessSpec(kernel="react")

_SUPERVISOR_TEAM_SPEC = HarnessSpec(
    kernel="react",
    composition=CompositionSpec(
        mode="supervisor",
        workers=(
            WorkerSpec(role="researcher"),
            WorkerSpec(role="coder"),
            WorkerSpec(role="reviewer"),
        ),
        blackboard=True,
    ),
)

_RESEARCH_FANOUT_SPEC = HarnessSpec(
    kernel="react",
    composition=CompositionSpec(
        mode="supervisor",
        workers=(
            WorkerSpec(role="researcher-1"),
            WorkerSpec(role="researcher-2"),
            WorkerSpec(role="researcher-3"),
        ),
        blackboard=True,
    ),
)


class TestPresetExpandsToFullSpec:
    """REQ-007, scenario 2: a named preset expands into a full HarnessSpec."""

    @pytest.mark.parametrize(
        ("preset_name", "expected_spec"),
        [
            ("simple-react", _SIMPLE_REACT_SPEC),
            ("supervisor-team", _SUPERVISOR_TEAM_SPEC),
            ("research-fanout", _RESEARCH_FANOUT_SPEC),
        ],
    )
    def test_preset_expands_to_full_spec(
        self, preset_name: str, expected_spec: HarnessSpec
    ) -> None:
        registry = get_preset_registry()

        expanded = registry.expand(preset_name)

        assert expanded == expected_spec


class TestEachBuiltinPresetBuildsValidAgent:
    """simple-react builds a real Agent; composition presets expand-correctly
    but fail loud on build (supervisor block not yet wired -> I-052)."""

    def test_simple_react_preset_builds_real_agent(self) -> None:
        from swarmline.agent import Agent
        from swarmline.harness.builder import HarnessBuilder

        registry = get_preset_registry()
        spec = registry.expand("simple-react")

        agent = HarnessBuilder.from_spec(spec).build()

        assert isinstance(agent, Agent)
        assert agent.config.native_config["harness_kernel"] == "react"

    @pytest.mark.parametrize("preset_name", ["supervisor-team", "research-fanout"])
    def test_composition_preset_expands_valid_but_build_raises_composition_not_found(
        self, preset_name: str
    ) -> None:
        from swarmline.harness.builder import HarnessBuilder
        from swarmline.harness.registries import (
            get_composition_registry,
            get_infra_registry,
        )

        registry = get_preset_registry()
        spec = registry.expand(preset_name)

        # The expanded spec is a genuinely valid, well-formed composition spec.
        assert spec.composition is not None
        assert spec.composition.mode == "supervisor"
        assert len(spec.composition.workers) >= 1

        for block_registry in (get_composition_registry(), get_infra_registry()):
            for name in block_registry.names():
                pytest.fail(
                    f"Unexpected leaked registration {name!r} in a "
                    "composition/infra registry singleton."
                )

        with pytest.raises(CompositionBlockNotFound) as exc_info:
            HarnessBuilder.from_spec(spec).build()

        assert "supervisor" in str(exc_info.value)


class TestPresetRegistryUnknownName:
    """Unknown preset name -> clear error naming it + listing known presets."""

    def test_expand_unknown_preset_raises_named_error_listing_known(self) -> None:
        registry = get_preset_registry()

        with pytest.raises(PresetNotFound) as exc_info:
            registry.expand("definitely-not-a-registered-preset")

        message = str(exc_info.value)
        assert "definitely-not-a-registered-preset" in message
        assert "simple-react" in message
        assert "supervisor-team" in message
        assert "research-fanout" in message


class TestPresetRegistryExtensible:
    """A caller can register a custom preset and expand it back out."""

    def test_register_custom_preset_then_expand_returns_it(self) -> None:
        registry = PresetRegistry()
        custom_spec = HarnessSpec(kernel="planner", memory="sqlite")

        registry.register("my-custom-preset", custom_spec)

        assert registry.expand("my-custom-preset") == custom_spec

    def test_custom_registry_instance_is_independent_of_default_singleton(self) -> None:
        registry = PresetRegistry()

        with pytest.raises(PresetNotFound):
            registry.expand("simple-react")

    def test_default_singleton_returns_same_instance_across_calls(self) -> None:
        assert get_preset_registry() is get_preset_registry()

    def test_names_lists_all_three_builtin_presets(self) -> None:
        registry = get_preset_registry()

        names = registry.names()

        assert {"simple-react", "supervisor-team", "research-fanout"} <= names


class TestPresetsModuleImportLight:
    """Importing presets.py must not eagerly pull the H6 supervisor module."""

    def test_import_does_not_pull_orchestration_supervisor(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import swarmline.harness.presets; import sys; "
                "print('swarmline.orchestration.supervisor' in sys.modules)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        assert result.stdout.strip() == "False"
