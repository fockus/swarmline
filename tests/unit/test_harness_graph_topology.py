"""Unit: YAML front-end mapping declarative graph topology onto CompositionSpec.

graph-composition spec, Task 1 (REQ-001, REQ-002, REQ-003, NFR-003). Split
out from ``test_harness_yaml.py`` (SRP/file-size ceiling — see design.md's
Decision 6) so it stays under the 400-line cap; covers ONLY the new
``edges``/``parallel``/``routes`` topology keys under ``composition:``. The
pre-existing composition keys (``mode``/``workers``/``blackboard``) stay
covered by ``test_harness_yaml.py``.

REQ-003: the YAML loader maps graph topology keys under ``composition:``
onto the exact same ``CompositionSpec`` fields an equivalent fluent
``.graph()`` call produces — no parallel resolution logic. NFR-003 (fail
loud): every malformed topology shape raises a ``ValueError`` naming the
offending key/block.

Written BEFORE the implementation (TDD, RED first).
"""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.spec import ParallelSpec, RouteSpec, WorkerSpec
from swarmline.harness.yaml_loader import load_harness_yaml


class TestYamlGraphTopologyRoundTrip:
    """REQ-003/REQ-006 parity: a full graph YAML pipeline maps onto the
    exact same CompositionSpec an equivalent fluent .graph() call produces."""

    def test_full_graph_topology_yaml_equals_fluent_spec(self, tmp_path: Any) -> None:
        yaml_path = tmp_path / "graph_pipeline.yaml"
        yaml_path.write_text(
            """
kernel: react
composition:
  mode: graph
  workers:
    - role: researcher
    - role: writer
    - role: r1
    - role: r2
    - role: synth
    - role: reviewer
    - role: publisher
  edges:
    - [researcher, writer]
    - [writer, END]
  parallel:
    - members: [r1, r2]
      then: synth
  routes:
    - source: reviewer
      key: verdict
      mapping:
        approve: publisher
        reject: END
      default: publisher
"""
        )

        spec = load_harness_yaml(str(yaml_path))

        fluent_spec = (
            HarnessBuilder()
            .kernel("react")
            .graph(
                (
                    WorkerSpec(role="researcher"),
                    WorkerSpec(role="writer"),
                    WorkerSpec(role="r1"),
                    WorkerSpec(role="r2"),
                    WorkerSpec(role="synth"),
                    WorkerSpec(role="reviewer"),
                    WorkerSpec(role="publisher"),
                ),
                edges=[("researcher", "writer"), ("writer", "END")],
                parallel=(ParallelSpec(members=("r1", "r2"), then="synth"),),
                routes=(
                    RouteSpec(
                        source="reviewer",
                        key="verdict",
                        mapping=(("approve", "publisher"), ("reject", "END")),
                        default="publisher",
                    ),
                ),
            )
            .spec
        )

        assert spec == fluent_spec
        assert isinstance(spec.composition.edges, tuple)
        assert isinstance(spec.composition.edges[0], tuple)
        assert isinstance(spec.composition.parallel, tuple)
        assert isinstance(spec.composition.parallel[0], ParallelSpec)
        assert isinstance(spec.composition.routes, tuple)
        assert isinstance(spec.composition.routes[0], RouteSpec)

    def test_graph_topology_route_without_default_field(self, tmp_path: Any) -> None:
        yaml_path = tmp_path / "graph_no_default.yaml"
        yaml_path.write_text(
            """
composition:
  mode: graph
  workers:
    - role: reviewer
    - role: publisher
  routes:
    - source: reviewer
      key: verdict
      mapping:
        approve: publisher
"""
        )

        spec = load_harness_yaml(str(yaml_path))

        assert spec.composition.routes == (
            RouteSpec(
                source="reviewer", key="verdict", mapping=(("approve", "publisher"),)
            ),
        )
        assert spec.composition.routes[0].default is None

    def test_graph_topology_absent_keys_default_to_empty(self, tmp_path: Any) -> None:
        """REQ-001 parity through the YAML front-end: a graph composition
        with no edges/parallel/routes keys loads with all three empty."""
        yaml_path = tmp_path / "graph_no_topology.yaml"
        yaml_path.write_text(
            "composition:\n  mode: graph\n  workers:\n    - role: solo\n"
        )

        spec = load_harness_yaml(str(yaml_path))

        assert spec.composition.edges == ()
        assert spec.composition.parallel == ()
        assert spec.composition.routes == ()


class TestYamlGraphTopologyMalformed:
    """REQ-003/NFR-003: malformed topology shapes fail loud, naming the key."""

    @pytest.mark.parametrize(
        ("yaml_body", "match"),
        [
            pytest.param(
                "composition:\n  mode: graph\n  edges: not-a-list\n",
                "edges",
                id="edges-scalar-instead-of-list",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  edges:\n    - [only_one]\n",
                "edges",
                id="edge-with-one-element",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  edges:\n    - [a, b, c]\n",
                "edges",
                id="edge-with-three-elements",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  parallel: not-a-list\n",
                "parallel",
                id="parallel-scalar-instead-of-list",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  parallel:\n    - members: [a, b]\n",
                "then",
                id="parallel-entry-missing-then",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  parallel:\n    - then: synth\n",
                "members",
                id="parallel-entry-missing-members",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  parallel:\n"
                "    - members: [a]\n      then: synth\n      extra: 1\n",
                "extra",
                id="parallel-entry-unknown-key",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes: not-a-list\n",
                "routes",
                id="routes-scalar-instead-of-list",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes:\n"
                "    - key: verdict\n      mapping: {a: b}\n",
                "source",
                id="route-entry-missing-source",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes:\n"
                "    - source: reviewer\n      mapping: {a: b}\n",
                "key",
                id="route-entry-missing-key",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes:\n"
                "    - source: reviewer\n      key: verdict\n",
                "mapping",
                id="route-entry-missing-mapping",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes:\n"
                "    - source: reviewer\n      key: verdict\n"
                "      mapping: not-a-mapping\n",
                "mapping",
                id="route-entry-mapping-scalar",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes:\n"
                "    - source: reviewer\n      key: verdict\n"
                "      mapping: {a: b}\n      extra: 1\n",
                "extra",
                id="route-entry-unknown-key",
            ),
            # Review r2, Major 1: edges member type-checked, not just arity.
            pytest.param(
                "composition:\n  mode: graph\n  edges:\n    - [1, writer]\n",
                "edges",
                id="edge-member-numeric",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  edges:\n    - [true, writer]\n",
                "edges",
                id="edge-member-bool",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  edges:\n    - [null, writer]\n",
                "edges",
                id="edge-member-null",
            ),
            # Review r2, Major 2: no silent coercion in parallel/routes.
            pytest.param(
                "composition:\n  mode: graph\n  parallel:\n"
                "    - members: ab\n      then: synth\n",
                "members",
                id="parallel-members-scalar-string",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  parallel:\n"
                "    - members: 5\n      then: synth\n",
                "members",
                id="parallel-members-int",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  parallel:\n"
                "    - members: [1, 2]\n      then: synth\n",
                "members",
                id="parallel-member-int-in-list",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  parallel:\n"
                "    - members: [a, b]\n      then: 5\n",
                "then",
                id="parallel-then-int",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes:\n"
                "    - source: 5\n      key: verdict\n      mapping: {a: b}\n",
                "source",
                id="route-source-int",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes:\n"
                "    - source: reviewer\n      key: 5\n      mapping: {a: b}\n",
                "key",
                id="route-key-int",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes:\n"
                "    - source: reviewer\n      key: verdict\n"
                "      mapping: {a: b}\n      default: 5\n",
                "default",
                id="route-default-int",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes:\n"
                "    - source: reviewer\n      key: verdict\n"
                "      mapping: {1: b}\n",
                "mapping",
                id="route-mapping-key-int",
            ),
            pytest.param(
                "composition:\n  mode: graph\n  routes:\n"
                "    - source: reviewer\n      key: verdict\n"
                "      mapping: {a: 2}\n",
                "mapping",
                id="route-mapping-value-int",
            ),
        ],
    )
    def test_malformed_topology_raises_value_error_naming_key(
        self, tmp_path: Any, yaml_body: str, match: str
    ) -> None:
        yaml_path = tmp_path / "malformed.yaml"
        yaml_path.write_text(yaml_body)

        with pytest.raises(ValueError, match=match):
            load_harness_yaml(str(yaml_path))
