"""Tests for the pydantic spec models — the declarative YAML config layer.

The runtime stages stay frozen dataclasses (hot path, dependency-light); the DECLARATION surface is
pydantic v2 so a YAML pipeline gets real validation (field bounds, per-kind required fields, Literal
enums), informative ``ValidationError`` paths, and a JSON Schema (for editor autocompletion / docs).
Registry-name resolution is NOT here — that needs the injected registries and lives in the loader;
these models validate STRUCTURE only.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from swarmline.pipeline.dataflow_spec import (
    BudgetConfig,
    PipelineSpec,
    StageConfig,
)


def test_llm_stage_parses_with_handler() -> None:
    """A minimal llm/io/pure stage needs only a name, kind and handler."""
    stage = StageConfig(name="decide", kind="llm", handler="decide", params={"max_queries": 4})

    assert stage.handler == "decide"
    assert stage.params == {"max_queries": 4}
    assert stage.max_attempts == 1


def test_work_stage_without_handler_is_rejected() -> None:
    """A work stage (llm/io/pure) without a handler fails validation."""
    with pytest.raises(ValidationError):
        StageConfig(name="decide", kind="llm")


def test_fanout_stage_requires_its_fields() -> None:
    """A fanout stage needs item_handler / over / concurrency / max_n."""
    ok = StageConfig(
        name="gather",
        kind="fanout",
        item_handler="gather",
        over="queries",
        concurrency=4,
        max_n=4,
    )
    assert ok.concurrency == 4

    with pytest.raises(ValidationError):
        StageConfig(name="gather", kind="fanout", item_handler="gather", over="queries")


def test_conditional_requires_selector_and_cases() -> None:
    """A conditional stage needs a selector and a non-empty cases map (recursive sub-stages)."""
    ok = StageConfig(
        name="route",
        kind="conditional",
        selector="kind",
        cases={"search": [StageConfig(name="g", kind="pure", handler="gather_all")]},
    )
    assert "search" in ok.cases

    with pytest.raises(ValidationError):
        StageConfig(name="route", kind="conditional", selector="kind")


def test_guard_requires_predicate_and_on_trip() -> None:
    """A guard stage needs a predicate and an on_trip payload key."""
    ok = StageConfig(name="empty", kind="guard", predicate="pool_empty", on_trip="empty_notice")
    assert ok.predicate == "pool_empty"

    with pytest.raises(ValidationError):
        StageConfig(name="empty", kind="guard", predicate="pool_empty")


def test_numeric_bounds_enforced() -> None:
    """max_attempts>=1, concurrency>=1, max_n>=1, timeout_s>0 are enforced."""
    with pytest.raises(ValidationError):
        StageConfig(name="s", kind="pure", handler="h", max_attempts=0)
    with pytest.raises(ValidationError):
        StageConfig(name="s", kind="pure", handler="h", timeout_s=0)
    with pytest.raises(ValidationError):
        StageConfig(
            name="f", kind="fanout", item_handler="h", over="o", concurrency=0, max_n=4
        )


def test_on_item_error_literal_enforced() -> None:
    """An unknown on_item_error value is rejected by the Literal type."""
    with pytest.raises(ValidationError):
        StageConfig(
            name="f",
            kind="fanout",
            item_handler="h",
            over="o",
            concurrency=4,
            max_n=4,
            on_item_error="oops",
        )


def test_pipeline_spec_rejects_empty_and_duplicate_stages() -> None:
    """A spec needs at least one stage and unique top-level stage names."""
    with pytest.raises(ValidationError):
        PipelineSpec(name="p", stages=[])
    with pytest.raises(ValidationError):
        PipelineSpec(
            name="p",
            stages=[
                StageConfig(name="dup", kind="pure", handler="h"),
                StageConfig(name="dup", kind="pure", handler="h"),
            ],
        )


def test_budget_defaults_to_calls_unit_and_optional_numbers() -> None:
    """Budget is declare-only: unit defaults to 'calls'; numbers are optional (from config)."""
    budget = BudgetConfig()

    assert budget.unit == "calls"
    assert budget.max_calls is None
    assert budget.timeout_s is None


def test_pipeline_spec_emits_json_schema() -> None:
    """The spec produces a JSON Schema (the community win — editor autocompletion / docs)."""
    schema = PipelineSpec.model_json_schema()

    assert schema["title"] == "PipelineSpec"
    assert "stages" in schema["properties"]
