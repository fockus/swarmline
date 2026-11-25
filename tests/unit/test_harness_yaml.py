"""Unit: YAML front-end loading a HarnessSpec — parity with the SDK builder.

harness-composition spec, Task 3 (REQ-005, REQ-006).

REQ-005: ``load_harness_yaml(path)`` reads a YAML pipeline file into the same
frozen ``HarnessSpec`` the SDK ``HarnessBuilder`` produces — single source of
truth, no duplicated resolution logic.
REQ-006: an SDK-described composition and a YAML-described composition of
the SAME shape produce an EQUIVALENT agent. "Equivalent" is defined
concretely here as: (1) the two ``HarnessSpec``s compare equal (frozen
dataclasses are structurally ``==``-comparable, so equal specs are the
single source of truth guarantee), AND (2) both specs build successfully
through ``HarnessBuilder.from_spec(spec).build()`` into an ``Agent`` whose
resolved kernel (``agent.config.native_config["harness_kernel"]``) matches.

Written BEFORE the implementation (TDD, RED first).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.spec import CompositionSpec, HarnessSpec, InfraSpec, WorkerSpec
from swarmline.harness.yaml_loader import load_harness_yaml


class TestYamlLoadsIntoHarnessSpec:
    """REQ-005: YAML pipeline file -> correct, fully-reconstructed HarnessSpec."""

    def test_yaml_loads_into_harness_spec(self, tmp_path: Any) -> None:
        """A YAML file with kernel/composition/infra maps field-for-field
        into HarnessSpec, with nested CompositionSpec/InfraSpec/WorkerSpec
        reconstructed and lists turned into tuples."""
        yaml_path = tmp_path / "pipeline.yaml"
        yaml_path.write_text(
            """
kernel: react
middleware:
  - logging
  - retry
tools:
  - web_search
memory: sqlite
composition:
  mode: supervisor
  blackboard: false
  workers:
    - role: researcher
      kernel: react
      tools:
        - web_search
    - role: writer
      kernel: planner
infra:
  checkpoint: true
  event_record: true
  replay: false
"""
        )

        spec = load_harness_yaml(str(yaml_path))

        assert spec == HarnessSpec(
            kernel="react",
            composition=CompositionSpec(
                mode="supervisor",
                workers=(
                    WorkerSpec(
                        role="researcher", kernel="react", tools=("web_search",)
                    ),
                    WorkerSpec(role="writer", kernel="planner", tools=()),
                ),
                blackboard=False,
            ),
            infra=InfraSpec(checkpoint=True, event_record=True, replay=False),
            middleware=("logging", "retry"),
            tools=("web_search",),
            memory="sqlite",
        )
        # Explicit list->tuple proof (design.md: frozen specs need tuple fields).
        assert isinstance(spec.middleware, tuple)
        assert isinstance(spec.tools, tuple)
        assert isinstance(spec.composition.workers, tuple)
        assert isinstance(spec.composition.workers[0].tools, tuple)

    def test_minimal_yaml_loads_into_solo_react_spec(self, tmp_path: Any) -> None:
        """REQ-010 parity: an empty/minimal YAML file loads into the same
        all-defaults solo-react HarnessSpec as HarnessSpec()."""
        yaml_path = tmp_path / "minimal.yaml"
        yaml_path.write_text("kernel: react\n")

        spec = load_harness_yaml(str(yaml_path))

        assert spec == HarnessSpec()

    def test_empty_yaml_file_loads_into_default_spec(self, tmp_path: Any) -> None:
        """An entirely empty YAML document (safe_load -> None) still yields
        the all-defaults HarnessSpec rather than raising."""
        yaml_path = tmp_path / "empty.yaml"
        yaml_path.write_text("")

        spec = load_harness_yaml(str(yaml_path))

        assert spec == HarnessSpec()

    def test_yaml_without_infra_block_leaves_infra_none(self, tmp_path: Any) -> None:
        """No 'infra:' key in the YAML -> HarnessSpec.infra stays None (not
        an InfraSpec with all-False fields) -- matches the SDK's minimal path."""
        yaml_path = tmp_path / "no_infra.yaml"
        yaml_path.write_text("kernel: react\ncomposition:\n  mode: supervisor\n")

        spec = load_harness_yaml(str(yaml_path))

        assert spec.infra is None
        assert spec.composition == CompositionSpec(mode="supervisor")

    def test_unknown_top_level_key_raises_error_naming_the_key(
        self, tmp_path: Any
    ) -> None:
        """Fail-loud (foundation for REQ-003/Task 5 validation): an unknown
        top-level YAML key raises a clear error that names the offending key."""
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text("kernel: react\nnonexistent_field: true\n")

        with pytest.raises(ValueError, match="nonexistent_field"):
            load_harness_yaml(str(yaml_path))

    def test_composition_block_without_mode_raises_naming_composition_mode(
        self, tmp_path: Any
    ) -> None:
        """A 'composition:' block missing the required 'mode' field raises a
        clear ValueError naming composition.mode, not a bare KeyError/TypeError
        (CompositionSpec.mode has no default)."""
        yaml_path = tmp_path / "no_mode.yaml"
        yaml_path.write_text("kernel: react\ncomposition:\n  blackboard: false\n")

        with pytest.raises(ValueError, match="mode"):
            load_harness_yaml(str(yaml_path))

    def test_missing_pyyaml_raises_clear_import_error_with_install_hint(
        self, tmp_path: Any
    ) -> None:
        """If PyYAML is not importable, load_harness_yaml surfaces a clear,
        actionable ImportError rather than a bare ModuleNotFoundError."""
        yaml_path = tmp_path / "pipeline.yaml"
        yaml_path.write_text("kernel: react\n")

        import builtins

        real_import = builtins.__import__

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "yaml":
                raise ModuleNotFoundError("No module named 'yaml'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_fake_import):
            with pytest.raises(ImportError, match="(?i)pyyaml"):
                load_harness_yaml(str(yaml_path))


class TestYamlModuleImportIsLight:
    """The loader module must not eagerly import PyYAML (lazy-import convention).

    NOTE on how this is proven: a plain ``'yaml' in sys.modules`` probe
    after ``import swarmline.harness.yaml_loader`` is NOT a valid signal in
    this repo, because ``import swarmline.harness.yaml_loader`` necessarily
    runs the top-level ``swarmline/__init__.py`` first (Python import
    semantics always import parent packages) — and that chain
    (``swarmline`` -> ``swarmline.agent`` -> ``swarmline.agent.config``)
    already pulls PyYAML in eagerly today, entirely unrelated to this
    module and out of Task 3's additive/import-light scope (touching
    ``swarmline/__init__.py`` or ``swarmline.agent`` is explicitly
    forbidden). So instead this is proven with an AST check of
    ``yaml_loader.py``'s own source: no top-level ``import yaml`` /
    ``from yaml import ...`` statement exists outside a function body —
    exactly the lazy-import convention used by
    ``swarmline.multi_agent.graph_builder.GraphBuilder.from_yaml``.
    """

    def test_yaml_loader_source_has_no_module_level_yaml_import(self) -> None:
        import ast
        import inspect

        from swarmline.harness import yaml_loader

        source = inspect.getsource(yaml_loader)
        tree = ast.parse(source)

        for node in tree.body:  # module-level statements only, not nested
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
                assert "yaml" not in names, "yaml imported at module top-level"
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "yaml", "yaml imported at module top-level"

    def test_yaml_loader_module_has_no_yaml_attribute_bound_at_import_time(
        self,
    ) -> None:
        """Importing the module in isolation must not bind a ``yaml`` name
        into its namespace — the import only happens inside the function."""
        from swarmline.harness import yaml_loader

        assert not hasattr(yaml_loader, "yaml")


class TestSdkAndYamlProduceEquivalentAgent:
    """REQ-006 (scenario 1): SDK-built spec and YAML-built spec of the same
    composition are equal specs and build equivalent agents."""

    def test_sdk_and_yaml_produce_equivalent_agent(self, tmp_path: Any) -> None:
        yaml_path = tmp_path / "supervisor_team.yaml"
        yaml_path.write_text(
            """
kernel: react
composition:
  mode: supervisor
  blackboard: true
  workers:
    - role: researcher
      kernel: react
infra:
  checkpoint: true
"""
        )

        sdk_spec = (
            HarnessBuilder()
            .kernel("react")
            .supervisor(workers=(WorkerSpec(role="researcher", kernel="react"),))
            .with_checkpointing()
            .spec
        )
        yaml_spec = load_harness_yaml(str(yaml_path))

        # Single source of truth: equal specs, the strongest parity proof.
        assert sdk_spec == yaml_spec

        # Both specs resolve through the SAME builder into a real Agent with
        # the same resolved kernel; composition/infra registries are stubbed
        # (Task 2 boundary — no concrete supervisor/checkpoint block yet).
        with (
            patch("swarmline.harness.builder.get_composition_registry"),
            patch("swarmline.harness.builder.get_infra_registry"),
        ):
            sdk_agent = HarnessBuilder.from_spec(sdk_spec).build()
            yaml_agent = HarnessBuilder.from_spec(yaml_spec).build()

        from swarmline.agent import Agent

        assert isinstance(sdk_agent, Agent)
        assert isinstance(yaml_agent, Agent)
        assert (
            sdk_agent.config.native_config["harness_kernel"]
            == yaml_agent.config.native_config["harness_kernel"]
            == "react"
        )

    def test_load_then_build_pipeline_returns_agent(self, tmp_path: Any) -> None:
        """The documented full pipeline: load_harness_yaml(path) ->
        HarnessBuilder.from_spec(spec).build() -> Agent."""
        yaml_path = tmp_path / "solo.yaml"
        yaml_path.write_text("kernel: react\n")

        spec = load_harness_yaml(str(yaml_path))
        agent = HarnessBuilder.from_spec(spec).build()

        from swarmline.agent import Agent

        assert isinstance(agent, Agent)
        assert agent.config.native_config["harness_kernel"] == "react"
