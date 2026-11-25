"""Unit: fail-loud graph topology validation (REQ-010..014/018..020).

RED-first: ``swarmline.harness.graph_validation`` did not exist before this
task. Covers all 9 fail-loud modes, valid topologies, build<->validate
parity, wiring/mock-guard, import-lightness. REQ-018 stays covered by the
EXISTING ``test_harness_builder.py`` suite.
"""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from swarmline.harness import graph_validation
from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.graph_validation import (
    GraphTopologyError,
    validate_graph_topology,
)
from swarmline.harness.registries import CompositionBlockNotFound
from swarmline.harness.spec import (
    CompositionSpec,
    HarnessSpec,
    ParallelSpec,
    RouteSpec,
    WorkerSpec,
)
from swarmline.harness.validation import validate_harness_spec

REPO_ROOT = Path(__file__).resolve().parents[2]


def _workers(*roles: str) -> tuple[WorkerSpec, ...]:
    return tuple(WorkerSpec(role=role) for role in roles)


class TestValidateGraphTopologyRejectsEachFailureMode:
    """One case per fail-loud mode (REQ-010..014/019/020) — names the culprit."""

    @pytest.mark.parametrize(
        ("composition", "match"),
        [
            pytest.param(
                CompositionSpec(mode="graph", workers=()),
                "zero workers",
                id="zero-workers",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph", workers=_workers("researcher", "researcher")
                ),
                "researcher",
                id="dup-role",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=(WorkerSpec(role="researcher", tools=("search",)),),
                ),
                "researcher",
                id="tools-declared",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("researcher"),
                    edges=(("researcher", "writer"),),
                ),
                "writer",
                id="unknown-ref-edge-target",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("researcher"),
                    edges=(("END", "researcher"),),
                ),
                "END",
                id="unknown-ref-end-as-edge-source",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("reviewer", "publisher", "archiver"),
                    routes=(
                        RouteSpec(
                            source="reviewer",
                            key="verdict",
                            mapping=(("approve", "publisher"),),
                        ),
                        RouteSpec(
                            source="reviewer",
                            key="other",
                            mapping=(("x", "archiver"),),
                        ),
                    ),
                ),
                "reviewer",
                id="dup-route-source",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("m1", "m2", "m3", "synth", "synth2"),
                    parallel=(
                        ParallelSpec(members=("m1", "m2"), then="synth"),
                        ParallelSpec(members=("m1", "m3"), then="synth2"),
                    ),
                ),
                "m1",
                id="member-integrity-ambiguous-membership",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("m1", "m2", "synth", "extra"),
                    parallel=(ParallelSpec(members=("m1", "m2"), then="synth"),),
                    edges=(("m1", "extra"),),
                ),
                "m1",
                id="member-integrity-edge-from-member",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("a", "b", "c"),
                    edges=(("a", "b"), ("a", "c")),
                ),
                "a",
                id="multi-successor-two-unconditional-edges",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("a", "b", "c"),
                    edges=(("a", "b"),),
                    routes=(RouteSpec(source="a", key="k", mapping=(("x", "c"),)),),
                ),
                "a",
                id="multi-successor-edge-and-route",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("a", "b"),
                    edges=(("a", "b"), ("b", "a")),
                ),
                "cycle",
                id="cycle",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("a", "b", "orphan"),
                    edges=(("a", "b"),),
                ),
                "orphan",
                id="unreachable",
            ),
        ],
    )
    def test_invalid_topology_raises_graph_topology_error_naming_culprit(
        self, composition: CompositionSpec, match: str
    ) -> None:
        with pytest.raises(GraphTopologyError, match=match):
            validate_graph_topology(composition)


class TestValidateGraphTopologyAcceptsValidTopologies:
    """Non-regression: every legitimate topology shape passes (returns None)."""

    @pytest.mark.parametrize(
        "composition",
        [
            pytest.param(
                CompositionSpec(mode="graph", workers=_workers("researcher", "writer")),
                id="linear-default-no-topology",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("researcher", "writer"),
                    edges=(("researcher", "writer"), ("writer", "END")),
                ),
                id="explicit-edges-chain-to-end",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("r1", "r2", "synth"),
                    parallel=(ParallelSpec(members=("r1", "r2"), then="synth"),),
                ),
                id="fanout-entry-in-group",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("reviewer", "publisher", "archiver"),
                    routes=(
                        RouteSpec(
                            source="reviewer",
                            key="verdict",
                            mapping=(("approve", "publisher"),),
                            default="archiver",
                        ),
                    ),
                ),
                id="route-with-default",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("reviewer", "publisher"),
                    routes=(
                        RouteSpec(
                            source="reviewer",
                            key="verdict",
                            mapping=(("approve", "publisher"), ("reject", "END")),
                        ),
                    ),
                ),
                id="route-to-end",
            ),
            pytest.param(
                CompositionSpec(
                    mode="graph",
                    workers=_workers("intake", "r1", "r2", "synth"),
                    edges=(("intake", "r1"),),
                    parallel=(ParallelSpec(members=("r1", "r2"), then="synth"),),
                ),
                id="edge-into-group-member-is-whole-group-entry",
            ),
        ],
    )
    def test_valid_topology_returns_none(self, composition: CompositionSpec) -> None:
        assert validate_graph_topology(composition) is None


_VALID_GRAPH_SPEC = HarnessSpec(
    composition=CompositionSpec(
        mode="graph",
        workers=_workers("researcher", "writer"),
        edges=(("researcher", "writer"), ("writer", "END")),
    )
)
_INVALID_GRAPH_SPEC = HarnessSpec(
    composition=CompositionSpec(
        mode="graph",
        workers=_workers("researcher"),
        edges=(("researcher", "ghost"),),
    )
)


@contextmanager
def _stub_registry(module_path: str):
    """Patch *module_path* so a "graph" mode clears the existence check."""
    with patch(module_path) as reg_mock:
        reg_mock.return_value.get.return_value = MagicMock()
        yield reg_mock


class TestBuildAndValidateHarnessSpecParity:
    """``build()`` and ``validate_harness_spec`` reach an IDENTICAL verdict
    for graph-mode specs (I-061 parity pattern)."""

    @pytest.mark.parametrize(
        ("spec", "expect_error"),
        [
            pytest.param(_VALID_GRAPH_SPEC, None, id="valid-graph-spec"),
            pytest.param(
                _INVALID_GRAPH_SPEC, GraphTopologyError, id="invalid-graph-spec"
            ),
        ],
    )
    def test_build_and_validate_harness_spec_agree(
        self, spec: HarnessSpec, expect_error: type[Exception] | None
    ) -> None:
        from swarmline.agent import Agent

        with _stub_registry("swarmline.harness.builder.get_composition_registry"):
            if expect_error is not None:
                with pytest.raises(expect_error):
                    HarnessBuilder.from_spec(spec).build()
            else:
                assert isinstance(HarnessBuilder.from_spec(spec).build(), Agent)

        with _stub_registry("swarmline.harness.registries.get_composition_registry"):
            if expect_error is not None:
                with pytest.raises(expect_error):
                    validate_harness_spec(spec)
            else:
                assert validate_harness_spec(spec) is None


class TestValidateGraphTopologyWiring:
    """Graph mode reaches ``validate_graph_topology`` on ``build()``/
    ``validate_harness_spec``; supervisor/``composition=None`` never do."""

    def test_build_graph_mode_calls_validate_graph_topology(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = MagicMock(wraps=graph_validation.validate_graph_topology)
        monkeypatch.setattr(graph_validation, "validate_graph_topology", spy)

        with _stub_registry("swarmline.harness.builder.get_composition_registry"):
            HarnessBuilder.from_spec(_VALID_GRAPH_SPEC).build()

        spy.assert_called_once_with(_VALID_GRAPH_SPEC.composition)

    def test_validate_harness_spec_graph_mode_calls_validate_graph_topology(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = MagicMock(wraps=graph_validation.validate_graph_topology)
        monkeypatch.setattr(graph_validation, "validate_graph_topology", spy)

        with _stub_registry("swarmline.harness.registries.get_composition_registry"):
            validate_harness_spec(_VALID_GRAPH_SPEC)

        spy.assert_called_once_with(_VALID_GRAPH_SPEC.composition)

    def test_build_supervisor_mode_never_calls_validate_graph_topology(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = MagicMock()
        monkeypatch.setattr(graph_validation, "validate_graph_topology", spy)

        with pytest.raises(CompositionBlockNotFound):
            HarnessBuilder().supervisor(workers=(WorkerSpec(role="w1"),)).build()

        spy.assert_not_called()

    def test_build_composition_none_never_calls_validate_graph_topology(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = MagicMock()
        monkeypatch.setattr(graph_validation, "validate_graph_topology", spy)

        HarnessBuilder().build()

        spy.assert_not_called()

    def test_validate_harness_spec_supervisor_mode_never_calls_validate_graph_topology(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = MagicMock()
        monkeypatch.setattr(graph_validation, "validate_graph_topology", spy)

        spec = HarnessSpec(
            composition=CompositionSpec(
                mode="supervisor", workers=(WorkerSpec(role="w1"),)
            )
        )
        with pytest.raises(CompositionBlockNotFound):
            validate_harness_spec(spec)

        spy.assert_not_called()

    def test_validate_harness_spec_composition_none_never_calls_validate_graph_topology(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = MagicMock()
        monkeypatch.setattr(graph_validation, "validate_graph_topology", spy)

        validate_harness_spec(HarnessSpec())

        spy.assert_not_called()


class TestGraphValidationModuleImportLight:
    """NFR-001 mirror: importing ``graph_validation`` never pulls the
    orchestration substrate (``ThinRuntime`` is already eagerly loaded by
    the top-level ``swarmline`` package itself, unrelated to this module)."""

    def test_importing_graph_validation_does_not_pull_workflow_graph_substrate(
        self,
    ) -> None:
        code = (
            "import sys\n"
            "import swarmline.harness.graph_validation\n"
            "mods = sys.modules\n"
            "assert 'swarmline.orchestration.workflow_graph' not in mods, ("
            "'importing graph_validation eagerly pulled workflow_graph')\n"
            "assert 'swarmline.orchestration.workflow_executor' not in mods, ("
            "'importing graph_validation eagerly pulled workflow_executor')\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout
