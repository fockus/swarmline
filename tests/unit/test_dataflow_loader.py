"""Tests for the YAML loader — structure (pydantic) + name resolution (imperative).

``load_pipeline_from_yaml`` parses YAML, validates STRUCTURE via PipelineSpec (pydantic), then
imperatively resolves every handler / validator / selector / predicate / joiner / dedup / payload
NAME against the injected registries and builds the runtime stages — fail-fast on an unknown name
(the load-time safety the feature is for). This split (yaml → typed model → imperative resolve)
keeps callables out of the pydantic model.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from swarmline.pipeline.dataflow_core import StageConfigError
from swarmline.pipeline.dataflow_loader import (
    PipelineRegistries,
    load_pipeline_from_yaml,
)
from swarmline.pipeline.stages.conditional_stage import ConditionalStage
from swarmline.pipeline.stages.fanout_stage import FanOutStage
from swarmline.pipeline.stages.guard_stage import GuardStage
from swarmline.pipeline.stages.typed_stage import TypedStage

_YAML = """
name: demo
events: [searching, composing]
stages:
  - {name: decide, kind: llm, handler: decide, params: {max_queries: 4}, status_label: searching}
  - name: route
    kind: conditional
    selector: kind
    cases:
      search:
        - name: gather
          kind: fanout
          item_handler: gather
          over: queries
          concurrency: 4
          max_n: 4
          dedup_key: by_url
        - {name: guard_empty, kind: guard, predicate: pool_empty, on_trip: empty_notice}
        - {name: finalize, kind: llm, handler: finalize, status_label: composing}
"""


def _dedup(element: object) -> object:
    return element


def _registries() -> PipelineRegistries:
    return PipelineRegistries(
        handlers={
            "decide": lambda v: v,
            "gather": lambda v: [v],
            "finalize": lambda v: v,
        },  # noqa: ARG005
        predicates={"pool_empty": lambda v: not v},
        payloads={"empty_notice": "Nothing found"},
        dedups={"by_url": _dedup},
    )


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "pipeline.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_builds_stage_types_and_order(tmp_path: Path) -> None:
    """The YAML builds the right stage TYPES, order and nesting under conditional cases."""
    stages = load_pipeline_from_yaml(_write(tmp_path, _YAML), registries=_registries())

    assert isinstance(stages[0], TypedStage)
    assert stages[0].name == "decide"
    assert stages[0].params == {"max_queries": 4}
    assert stages[0].status_label == "searching"

    route = stages[1]
    assert isinstance(route, ConditionalStage)
    branch = route.cases["search"]
    assert [type(stage) for stage in branch] == [FanOutStage, GuardStage, TypedStage]


def test_resolves_registry_names_to_callables_and_payloads(tmp_path: Path) -> None:
    """Handler/dedup/predicate/payload NAMES resolve to the injected registry objects."""
    stages = load_pipeline_from_yaml(_write(tmp_path, _YAML), registries=_registries())
    branch = stages[1].cases["search"]
    fanout, guard, _finalize = branch

    assert callable(fanout.item_handler)
    assert fanout.dedup_key is _dedup  # registry callable, not the literal "by_url"
    assert callable(guard.predicate)
    assert guard.on_trip == "Nothing found"  # payload registry value


def test_selector_falls_back_to_literal_dotted_path(tmp_path: Path) -> None:
    """A selector name not in the selector registry is kept as a literal dotted path."""
    stages = load_pipeline_from_yaml(_write(tmp_path, _YAML), registries=_registries())

    assert stages[1].selector == "kind"  # no 'kind' selector registered → literal path


def test_unknown_handler_name_fails_fast(tmp_path: Path) -> None:
    """A handler name absent from the registry raises at load time (not at run time)."""
    bad = _YAML.replace("handler: decide", "handler: nonexistent")
    with pytest.raises(StageConfigError):
        load_pipeline_from_yaml(_write(tmp_path, bad), registries=_registries())


def test_invalid_structure_raises_validation_error(tmp_path: Path) -> None:
    """A structurally invalid spec (llm stage with no handler) fails pydantic validation."""
    bad = "name: x\nstages:\n  - {name: decide, kind: llm}\n"
    with pytest.raises(ValidationError):
        load_pipeline_from_yaml(_write(tmp_path, bad), registries=_registries())


def _identity(value: object) -> object:
    return value


_NUMBERLESS_YAML = """
name: numberless
stages:
  - {name: decide, kind: llm, handler: decide}
  - name: route
    kind: conditional
    selector: kind
    cases:
      search:
        - name: gather
          kind: fanout
          item_handler: gather
          over: queries
          dedup_key: by_url
        - name: reviews
          kind: fanout
          item_handler: gather
          over: self
"""


def test_over_resolves_against_overs_registry_else_literal(tmp_path: Path) -> None:
    """A fanout ``over`` in the ``overs`` registry resolves to a callable; else stays literal."""
    registries = PipelineRegistries(
        handlers={"decide": _identity, "gather": lambda v: [v]},  # noqa: ARG005
        dedups={"by_url": _dedup},
        overs={"self": _identity},
    )
    overrides = {
        "gather": {"concurrency": 4, "max_n": 4},
        "reviews": {"concurrency": 2, "max_n": 2},
    }
    stages = load_pipeline_from_yaml(
        _write(tmp_path, _NUMBERLESS_YAML), registries=registries, overrides=overrides
    )
    gather, reviews = stages[1].cases["search"]

    assert gather.over == "queries"  # not in overs registry → literal dotted path
    assert (
        reviews.over is _identity
    )  # 'self' resolved to the registered identity callable


def test_overrides_inject_numbers_into_a_numberless_yaml(tmp_path: Path) -> None:
    """Declare-only: the YAML carries NO numbers; the caller injects them per stage (SSOT)."""
    registries = PipelineRegistries(
        handlers={"decide": _identity, "gather": lambda v: [v]},  # noqa: ARG005
        dedups={"by_url": _dedup},
        overs={"self": _identity},
    )
    overrides = {
        "decide": {"params": {"max_queries": 4}},
        "gather": {"concurrency": 4, "max_n": 8},
        "reviews": {"concurrency": 2, "max_n": 2},
    }

    stages = load_pipeline_from_yaml(
        _write(tmp_path, _NUMBERLESS_YAML), registries=registries, overrides=overrides
    )
    gather, reviews = stages[1].cases["search"]

    assert stages[0].params == {
        "max_queries": 4
    }  # injected into the decide stage params
    assert (gather.concurrency, gather.max_n) == (4, 8)  # injected fanout numbers
    assert (reviews.concurrency, reviews.max_n) == (2, 2)


def test_numberless_fanout_without_overrides_fails_validation(tmp_path: Path) -> None:
    """Without the injected numbers a fanout stage is structurally invalid (fail-fast at load)."""
    registries = PipelineRegistries(
        handlers={"decide": _identity, "gather": lambda v: [v]},  # noqa: ARG005
        dedups={"by_url": _dedup},
        overs={"self": _identity},
    )
    with pytest.raises(ValidationError):
        load_pipeline_from_yaml(
            _write(tmp_path, _NUMBERLESS_YAML), registries=registries
        )
