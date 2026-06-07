"""Declarative data-flow pipeline spec — the pydantic v2 YAML config layer.

Hybrid design: the runtime stages (``stages/*.py``) stay frozen dataclasses (hot path, no pydantic
dependency on construction), while THIS declaration layer is pydantic v2 so a YAML pipeline gets
real validation — field bounds (``ge`` / ``gt``), per-kind required fields, Literal enums —
informative ``ValidationError`` paths, and a JSON Schema (editor autocompletion / docs). These
models validate STRUCTURE only; resolving the ``handler`` / ``validator`` / ``selector`` names
against the injected registries is the loader's job (:mod:`swarmline.pipeline.dataflow_loader`).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

#: The declarable stage kinds (mirror the runtime stage types + the dependency taxonomy).
StageKind = Literal["llm", "io", "pure", "fanout", "conditional", "guard"]
#: Per-item failure policy of a fanout stage.
ItemErrorPolicy = Literal["skip", "fail"]
#: Pipeline-level fallback mode.
FallbackModeName = Literal["none", "last_valid"]
#: Budget accounting unit — ``calls`` (a call count, the default) or ``usd``.
BudgetUnit = Literal["usd", "calls"]


class StageConfig(BaseModel):
    """A single declared stage. Kind-specific fields are validated by ``_check_kind_fields``.

    ``llm`` / ``io`` / ``pure`` are work stages (``dependency`` carried by ``kind``); ``fanout`` /
    ``conditional`` / ``guard`` map to the matching runtime stage kinds. ``handler`` and friends are
    registry NAMES (resolved by the loader), never callables — YAML cannot carry a function.
    """

    name: str
    kind: StageKind
    status_label: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    # Work stages (llm / io / pure):
    handler: str | None = None
    validator: str | None = None
    max_attempts: int = Field(default=1, ge=1)
    timeout_s: float | None = Field(default=None, gt=0)

    # Conditional (router):
    selector: str | None = None
    cases: dict[str, list[StageConfig]] | None = None
    default: list[StageConfig] | None = None

    # Guard (graceful early-exit):
    predicate: str | None = None
    on_trip: str | None = None

    # Fan-out (dynamic bounded fan-out):
    item_handler: str | None = None
    over: str | None = None
    concurrency: int | None = Field(default=None, ge=1)
    max_n: int | None = Field(default=None, ge=1)
    dedup_key: str | None = None
    on_item_error: ItemErrorPolicy = "skip"
    joiner: str | None = None

    @model_validator(mode="after")
    def _check_kind_fields(self) -> StageConfig:
        """Enforce the fields each stage kind structurally requires."""
        if self.kind in ("llm", "io", "pure"):
            if not self.handler:
                raise ValueError(f"stage {self.name!r} of kind {self.kind!r} requires 'handler'")
        elif self.kind == "fanout":
            missing = [
                field
                for field in ("item_handler", "over", "concurrency", "max_n")
                if getattr(self, field) is None
            ]
            if missing:
                raise ValueError(f"fanout stage {self.name!r} requires {missing}")
        elif self.kind == "conditional":
            if not self.selector or not self.cases:
                raise ValueError(
                    f"conditional stage {self.name!r} requires 'selector' and 'cases'"
                )
        elif self.kind == "guard":
            if not self.predicate or not self.on_trip:
                raise ValueError(
                    f"guard stage {self.name!r} requires 'predicate' and 'on_trip'"
                )
        return self


class FallbackConfig(BaseModel):
    """Pipeline fallback policy (default: fail on a stage error)."""

    mode: FallbackModeName = "none"


class BudgetConfig(BaseModel):
    """Declare-only budget. Numbers are optional — the caller injects them from its config (SSOT)."""

    unit: BudgetUnit = "calls"
    max_total: float | None = Field(default=None, gt=0)
    max_calls: int | None = Field(default=None, ge=1)
    timeout_s: float | None = Field(default=None, gt=0)


class PipelineSpec(BaseModel):
    """A full declarative pipeline: ordered stages + fallback + budget + ordered event labels."""

    name: str
    stages: list[StageConfig]
    fallback: FallbackConfig = Field(default_factory=FallbackConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    events: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_stages(self) -> PipelineSpec:
        """Require at least one stage and unique top-level stage names."""
        if not self.stages:
            raise ValueError("PipelineSpec.stages must be non-empty")
        names = [stage.name for stage in self.stages]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate stage names: {duplicates}")
        return self


StageConfig.model_rebuild()
