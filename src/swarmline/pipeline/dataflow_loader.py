"""YAML data-flow pipeline loader — structure validation + imperative name resolution.

``load_pipeline_from_yaml`` parses the YAML, validates its STRUCTURE through :class:`PipelineSpec`
(pydantic — bounds, per-kind required fields, Literal enums), then imperatively resolves every
handler / validator / selector / predicate / joiner / dedup / payload NAME against the injected
registries and constructs the runtime stage dataclasses. Resolution is fail-fast: an unknown name
raises :class:`StageConfigError` at LOAD time. This split (yaml → typed model → imperative resolve)
keeps callables out of the pydantic model.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from swarmline.pipeline.dataflow_core import StageConfigError
from swarmline.pipeline.dataflow_spec import PipelineSpec, StageConfig
from swarmline.pipeline.stages.conditional_stage import ConditionalStage
from swarmline.pipeline.stages.fanout_stage import FanOutStage
from swarmline.pipeline.stages.guard_stage import GuardStage
from swarmline.pipeline.stages.typed_stage import TypedStage


@dataclasses.dataclass(frozen=True)
class PipelineRegistries:
    """Name → object registries the loader resolves the declared spec against (fail-fast).

    ``payloads`` holds plain values (e.g. a graceful-notice string for a guard's ``on_trip``); the
    rest hold callables. ``selectors``, ``dedups`` and ``overs`` are registry-OR-literal: a name
    absent from the registry is kept as a literal (a dotted path for a selector / fanout ``over``,
    an attr/key for a dedup_key).
    """

    handlers: Mapping[str, Callable[..., Any]] = dataclasses.field(default_factory=dict)
    validators: Mapping[str, Callable[..., Any]] = dataclasses.field(
        default_factory=dict
    )
    selectors: Mapping[str, Callable[..., Any]] = dataclasses.field(
        default_factory=dict
    )
    predicates: Mapping[str, Callable[..., Any]] = dataclasses.field(
        default_factory=dict
    )
    joiners: Mapping[str, Callable[..., Any]] = dataclasses.field(default_factory=dict)
    dedups: Mapping[str, Callable[..., Any]] = dataclasses.field(default_factory=dict)
    overs: Mapping[str, Callable[..., Any]] = dataclasses.field(default_factory=dict)
    payloads: Mapping[str, Any] = dataclasses.field(default_factory=dict)


def _require(registry: Mapping[str, Any], name: str | None, kind: str) -> Any:
    """Resolve a REQUIRED name; raise fail-fast if it is missing or absent from the registry."""
    if name is None:
        raise StageConfigError(f"{kind} name is required but missing")
    try:
        return registry[name]
    except KeyError as exc:
        raise StageConfigError(f"unknown {kind} {name!r} (not in registry)") from exc


def _optional(registry: Mapping[str, Any], name: str | None, kind: str) -> Any | None:
    """Resolve an OPTIONAL name (None passes through; a named-but-absent entry still fails)."""
    return None if name is None else _require(registry, name, kind)


def _registry_or_literal(registry: Mapping[str, Any], name: str) -> Any:
    """Return the registry entry for ``name`` if present, else ``name`` itself (literal)."""
    return registry[name] if name in registry else name


def load_pipeline_from_yaml(
    path: str | Path,
    *,
    registries: PipelineRegistries,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Any]:
    """Load + validate a YAML pipeline and build its runtime stages (fail-fast on unknown names).

    ``overrides`` (keyed by stage name) injects runtime numbers into a deliberately number-free YAML
    BEFORE validation — the declare-only pattern: the YAML declares STRUCTURE, the caller supplies
    the cost/size numbers from its config (config = SSOT). Each override may set scalar fields
    (e.g. a fanout's ``concurrency`` / ``max_n``) and deep-merges a nested ``params`` map. Overrides
    apply recursively into conditional ``cases`` sub-stages.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if overrides:
        _apply_overrides(raw, overrides)
    spec = PipelineSpec.model_validate(raw)
    return build_pipeline(spec, registries=registries)


def _apply_overrides(raw: Any, overrides: Mapping[str, Mapping[str, Any]]) -> None:
    """Merge per-stage ``overrides`` into the raw spec dict in place (recursing into cases)."""
    if not isinstance(raw, Mapping):
        return
    for stage in raw.get("stages", []):
        _override_stage(stage, overrides)


def _override_stage(stage: Any, overrides: Mapping[str, Mapping[str, Any]]) -> None:
    """Apply an override (scalars set, ``params`` deep-merged) to one stage dict, then its cases."""
    if not isinstance(stage, dict):
        return
    override = overrides.get(stage.get("name"))
    if override:
        for field, value in override.items():
            if field == "params":
                stage.setdefault("params", {}).update(value)
            else:
                stage[field] = value
    for branch in (stage.get("cases") or {}).values():
        for sub in branch:
            _override_stage(sub, overrides)
    for sub in stage.get("default") or []:
        _override_stage(sub, overrides)


def build_pipeline(spec: PipelineSpec, *, registries: PipelineRegistries) -> list[Any]:
    """Build runtime stages from an already-validated spec."""
    return [_build_stage(stage, registries) for stage in spec.stages]


def _build_stage(cfg: StageConfig, reg: PipelineRegistries) -> Any:
    """Construct one runtime stage from its config, resolving names against the registries."""
    if cfg.kind in ("llm", "io", "pure"):
        return TypedStage(
            name=cfg.name,
            handler=_require(reg.handlers, cfg.handler, "handler"),
            dependency=cfg.kind,
            validator=_optional(reg.validators, cfg.validator, "validator"),
            max_attempts=cfg.max_attempts,
            params=cfg.params,
            status_label=cfg.status_label,
        )
    if cfg.kind == "fanout":
        # spec validation guarantees these; the explicit check narrows the type for the type checker.
        if cfg.concurrency is None or cfg.max_n is None:
            raise StageConfigError(
                f"fanout stage {cfg.name!r} missing concurrency/max_n"
            )
        return FanOutStage(
            name=cfg.name,
            item_handler=_require(reg.handlers, cfg.item_handler, "handler"),
            over=_registry_or_literal(reg.overs, cfg.over) if cfg.over else "",
            concurrency=cfg.concurrency,
            max_n=cfg.max_n,
            dedup_key=_registry_or_literal(reg.dedups, cfg.dedup_key)
            if cfg.dedup_key
            else None,
            on_item_error=cfg.on_item_error,
            joiner=_optional(reg.joiners, cfg.joiner, "joiner"),
            status_label=cfg.status_label,
            params=cfg.params,
        )
    if cfg.kind == "conditional":
        # spec validation guarantees these; the explicit check narrows the type for the type checker.
        if cfg.selector is None or cfg.cases is None:
            raise StageConfigError(
                f"conditional stage {cfg.name!r} missing selector/cases"
            )
        cases = {
            key: [_build_stage(sub, reg) for sub in branch]
            for key, branch in cfg.cases.items()
        }
        default = (
            [_build_stage(sub, reg) for sub in cfg.default] if cfg.default else None
        )
        return ConditionalStage(
            name=cfg.name,
            selector=_registry_or_literal(reg.selectors, cfg.selector),
            cases=cases,
            default=default,
            status_label=cfg.status_label,
            params=cfg.params,
        )
    return GuardStage(
        name=cfg.name,
        predicate=_require(reg.predicates, cfg.predicate, "predicate"),
        on_trip=_require(reg.payloads, cfg.on_trip, "payload"),
        status_label=cfg.status_label,
        params=cfg.params,
    )
