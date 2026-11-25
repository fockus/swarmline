"""YAML front-end — loads a pipeline file into the same ``HarnessSpec``.

harness-composition spec, Task 3 (REQ-005, REQ-006). ``load_harness_yaml``
is the second front-end onto the single source of truth established in
Task 1 (:mod:`swarmline.harness.spec`): where :class:`~swarmline.harness.builder.HarnessBuilder`
compiles a fluent SDK call chain into a frozen ``HarnessSpec``, this module
compiles a YAML mapping into the exact same dataclass. No parallel
resolution logic exists anywhere else — a YAML pipeline and an equivalent
SDK call produce ``==``-equal specs (REQ-006), which is what guarantees
they build into equivalent agents once resolved through
``HarnessBuilder.from_spec(spec).build()``.

graph-composition spec, Task 1 (REQ-003): the ``composition:`` block also
accepts the declarative graph topology keys — ``edges`` (2-element
``[source, target]`` pairs), ``parallel`` (fan-out groups, each a
``{members, then}`` mapping), and ``routes`` (state-key routing rules, each
a ``{source, key, mapping, default?}`` mapping) — reconstructed into
:class:`~swarmline.harness.spec.ParallelSpec`/
:class:`~swarmline.harness.spec.RouteSpec` tuples on the same
``CompositionSpec``. Every malformed shape (scalar instead of list, wrong
edge arity, missing required field, non-mapping ``mapping``, unknown key)
raises a ``ValueError`` naming the offending key/block (fail-loud, I-057
convention).

Full pipeline (loader returns the spec; callers build)::

    spec = load_harness_yaml("pipeline.yaml")
    agent = HarnessBuilder.from_spec(spec).build()

PyYAML is imported lazily, inside :func:`load_harness_yaml`'s body — not at
module top — matching this repo's optional/lazy-dependency convention (see
``swarmline.multi_agent.graph_builder.GraphBuilder.from_yaml``). PyYAML is
in fact declared as a hard runtime dependency in ``pyproject.toml`` already,
but the lazy import keeps this module's own body import-light: ``yaml`` is
bound only inside :func:`load_harness_yaml`, never at module top, so
importing this module adds no eager ``yaml`` import of its own. (The
package-import chain may already have loaded ``yaml`` elsewhere — e.g. via
``swarmline.agent.config`` — which is unrelated to this module.) If PyYAML
were absent from the environment the failure surfaces as a clear,
actionable ``ImportError`` rather than a bare ``ModuleNotFoundError``
(matching ``swarmline.multi_agent.graph_communication_redis`` /
``graph_communication_nats``'s missing-optional-dependency pattern).
"""

from __future__ import annotations

from typing import Any

from swarmline.harness.spec import (
    CompositionSpec,
    HarnessSpec,
    InfraSpec,
    ParallelSpec,
    RouteSpec,
    WorkerSpec,
)

#: Top-level HarnessSpec fields the YAML document is allowed to set,
#: excluding the two that require nested reconstruction (``composition``,
#: ``infra`` — handled explicitly below) and ``preset`` (Task 4 territory,
#: still a flat scalar so it is included here).
_SCALAR_FIELDS = ("kernel", "middleware", "tools", "memory", "preset")
_NESTED_FIELDS = ("composition", "infra")
_KNOWN_TOP_LEVEL_KEYS = frozenset(_SCALAR_FIELDS) | frozenset(_NESTED_FIELDS)

#: Task 5 (REQ-003/I-057, partial): known keys inside each nested mapping,
#: mirroring design.md's Interfaces section field-for-field. Cheap,
#: shallow (one level deep) unknown-key rejection — NOT full deep
#: type/shape validation (deferred, see ``_build_*`` docstrings below).
_KNOWN_COMPOSITION_KEYS = frozenset(
    {"mode", "workers", "blackboard", "edges", "parallel", "routes"}
)
_KNOWN_WORKER_KEYS = frozenset({"role", "kernel", "tools"})
_KNOWN_INFRA_KEYS = frozenset({"checkpoint", "event_record", "replay"})
#: graph-composition spec, Task 1 (REQ-001): known keys inside each
#: ``parallel``/``routes`` entry mapping, mirroring design.md's
#: Interfaces section (``ParallelSpec``/``RouteSpec``) field-for-field.
_KNOWN_PARALLEL_KEYS = frozenset({"members", "then"})
_KNOWN_ROUTE_KEYS = frozenset({"source", "key", "mapping", "default"})


def _reject_unknown_keys(
    raw: dict[str, Any], known: frozenset[str], where: str
) -> None:
    """Raise ``ValueError`` naming any key in *raw* outside *known*, tagged *where*."""
    unknown = set(raw) - known
    if unknown:
        raise ValueError(
            f"Unknown key(s) in harness YAML {where}: {sorted(unknown)}. "
            f"Known keys: {sorted(known)}"
        )


def _require_str(value: Any, where: str) -> str:
    """Raise ``ValueError`` naming *where* unless *value* is a ``str``.

    Review r2 (2 majors) fix: closes the silent-coercion / raw-TypeError
    holes in the graph topology loaders — every leaf value that
    ``CompositionSpec``'s topology sub-specs contractually type as ``str``
    (edge endpoints, ``ParallelSpec.members``/``then``,
    ``RouteSpec.source``/``key``/``default``, and every ``mapping``
    key/value) is checked here BEFORE it reaches a bare ``tuple(...)``/
    direct assignment, instead of trusting YAML's scalar type (int/bool/
    ``None`` all parse fine and used to pass straight through).
    """
    if not isinstance(value, str):
        raise ValueError(
            f"Harness YAML {where} must be a string, got "
            f"{type(value).__name__}: {value!r}"
        )
    return value


def load_harness_yaml(path: str) -> HarnessSpec:
    """Load a YAML pipeline file into a frozen :class:`HarnessSpec`.

    Absent optional keys fall back to ``HarnessSpec``'s own defaults, so a
    minimal ``{kernel: react}`` (or even an empty ``{}``/blank document)
    loads into the same solo-react spec as ``HarnessSpec()`` (REQ-010
    parity). An unknown top-level key raises ``ValueError`` naming the key
    (fail-loud; foundation for the REQ-003/Task 5 validation layer) rather
    than silently ignoring a typo'd field.

    Raises:
        ImportError: PyYAML is not installed.
        ValueError: the YAML document contains an unknown top-level key, or
            does not parse into a mapping.
    """
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required to load a harness YAML pipeline file. "
            "Install: pip install pyyaml"
        ) from exc

    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if raw is None:
        raw = {}

    if not isinstance(raw, dict):
        raise ValueError(
            f"Harness YAML file {path!r} must parse into a mapping at the "
            f"top level, got {type(raw).__name__}"
        )

    unknown_keys = set(raw) - _KNOWN_TOP_LEVEL_KEYS
    if unknown_keys:
        raise ValueError(
            f"Unknown harness YAML key(s) in {path!r}: {sorted(unknown_keys)}. "
            f"Known keys: {sorted(_KNOWN_TOP_LEVEL_KEYS)}"
        )

    kwargs: dict[str, Any] = {}

    if "kernel" in raw:
        kwargs["kernel"] = raw["kernel"]
    if "middleware" in raw:
        kwargs["middleware"] = tuple(raw["middleware"])
    if "tools" in raw:
        kwargs["tools"] = tuple(raw["tools"])
    if "memory" in raw:
        kwargs["memory"] = raw["memory"]
    if "preset" in raw:
        kwargs["preset"] = raw["preset"]

    if "composition" in raw:
        kwargs["composition"] = _build_composition_spec(raw["composition"])
    if "infra" in raw:
        kwargs["infra"] = _build_infra_spec(raw["infra"])

    return HarnessSpec(**kwargs)


def _build_composition_spec(raw: dict[str, Any]) -> CompositionSpec:
    """Reconstruct a nested ``CompositionSpec`` (with its ``WorkerSpec`` tuple).

    Task 5 (I-057, partial): rejects an unknown key inside the mapping
    (shallow, one level) in addition to the pre-existing required-``mode``
    check. Does NOT validate ``mode``'s VALUE against the composition
    registry (that is REQ-003/``HarnessBuilder.build()``'s job, resolved
    lazily against the LIVE registry — this loader has no registry access
    and must stay import-light) nor deep-type-check ``workers``/``blackboard``
    beyond what ``CompositionSpec.__init__`` itself enforces.
    """
    if not isinstance(raw, dict) or "mode" not in raw:
        raise ValueError(
            "Harness YAML 'composition' block requires a 'mode' field "
            '("supervisor" | "graph").'
        )
    _reject_unknown_keys(raw, _KNOWN_COMPOSITION_KEYS, "'composition' block")
    kwargs: dict[str, Any] = {"mode": raw["mode"]}
    if "workers" in raw:
        kwargs["workers"] = tuple(_build_worker_spec(w) for w in raw["workers"])
    if "blackboard" in raw:
        kwargs["blackboard"] = raw["blackboard"]
    if "edges" in raw:
        kwargs["edges"] = _build_edges(raw["edges"])
    if "parallel" in raw:
        if not isinstance(raw["parallel"], list):
            raise ValueError(
                "Harness YAML composition 'parallel' must be a list, got "
                f"{type(raw['parallel']).__name__}"
            )
        kwargs["parallel"] = tuple(_build_parallel_spec(p) for p in raw["parallel"])
    if "routes" in raw:
        if not isinstance(raw["routes"], list):
            raise ValueError(
                "Harness YAML composition 'routes' must be a list, got "
                f"{type(raw['routes']).__name__}"
            )
        kwargs["routes"] = tuple(_build_route_spec(r) for r in raw["routes"])
    return CompositionSpec(**kwargs)


def _build_edges(raw: Any) -> tuple[tuple[str, str], ...]:
    """Reconstruct the ``edges`` tuple: a list of 2-element ``[source, target]`` pairs.

    graph-composition spec, Task 1 (REQ-001, REQ-003). A scalar (non-list)
    value, any entry that isn't exactly a 2-element pair, or a pair member
    that isn't a ``str`` (review r2 Major 1 — e.g. ``[1, writer]``) raises a
    ``ValueError`` naming ``'edges'`` (fail-loud, NFR-003).
    """
    if not isinstance(raw, list):
        raise ValueError(
            "Harness YAML composition 'edges' must be a list of 2-element "
            f"pairs, got {type(raw).__name__}"
        )
    edges: list[tuple[str, str]] = []
    for edge in raw:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            raise ValueError(
                "Harness YAML composition 'edges' entry must be a "
                f"2-element [source, target] pair, got {edge!r}"
            )
        source, target = edge
        edges.append(
            (
                _require_str(source, "composition 'edges' entry source"),
                _require_str(target, "composition 'edges' entry target"),
            )
        )
    return tuple(edges)


def _build_parallel_spec(raw: Any) -> ParallelSpec:
    """Reconstruct one ``ParallelSpec`` fan-out group entry.

    graph-composition spec, Task 1 (REQ-001, REQ-003). Requires both
    ``members`` (a list of role names) and ``then`` (the join node); a
    missing field raises a ``ValueError`` naming that field and the
    ``'parallel'`` block (fail-loud, NFR-003); an unknown key is rejected
    via ``_reject_unknown_keys`` (same shallow, one-level convention as
    ``_build_worker_spec``).

    Review r2 Major 2: ``members`` must be a ``list`` (a scalar string like
    ``"ab"`` used to silently coerce via ``tuple("ab") == ("a", "b")``; a
    non-iterable scalar like an int used to raise a raw, unhelpful
    ``TypeError`` from that same ``tuple(...)`` call) — both now raise a
    named ``ValueError`` instead. Every member, and ``then``, must be a
    ``str``.
    """
    if not isinstance(raw, dict) or "members" not in raw:
        raise ValueError(
            "Harness YAML composition 'parallel' entry is missing the "
            "required field 'members'."
        )
    if "then" not in raw:
        raise ValueError(
            "Harness YAML composition 'parallel' entry is missing the "
            "required field 'then'."
        )
    _reject_unknown_keys(raw, _KNOWN_PARALLEL_KEYS, "composition 'parallel' entry")
    members = raw["members"]
    if not isinstance(members, list):
        raise ValueError(
            "Harness YAML composition 'parallel' entry 'members' must be a "
            f"list, got {type(members).__name__}"
        )
    validated_members = tuple(
        _require_str(member, "composition 'parallel' entry 'members' item")
        for member in members
    )
    then = _require_str(raw["then"], "composition 'parallel' entry 'then'")
    return ParallelSpec(members=validated_members, then=then)


def _build_route_spec(raw: Any) -> RouteSpec:
    """Reconstruct one ``RouteSpec`` state-key routing rule entry.

    graph-composition spec, Task 1 (REQ-001, REQ-003). Requires ``source``,
    ``key``, and ``mapping`` (a YAML mapping, turned into an
    insertion-order-preserving ``tuple[tuple[str, str], ...]``); ``default``
    is optional. A missing required field, a non-mapping ``mapping``, or an
    unknown key each raise a ``ValueError`` naming the offender and the
    ``'routes'`` block (fail-loud, NFR-003).

    Review r2 Major 2: ``source``/``key``/``default`` (when present) and
    every key/value inside ``mapping`` must be ``str`` — a non-string value
    used to pass straight through into ``RouteSpec`` unchecked; each now
    raises a named ``ValueError`` instead.
    """
    if not isinstance(raw, dict) or "source" not in raw:
        raise ValueError(
            "Harness YAML composition 'routes' entry is missing the "
            "required field 'source'."
        )
    if "key" not in raw:
        raise ValueError(
            "Harness YAML composition 'routes' entry is missing the "
            "required field 'key'."
        )
    if "mapping" not in raw:
        raise ValueError(
            "Harness YAML composition 'routes' entry is missing the "
            "required field 'mapping'."
        )
    _reject_unknown_keys(raw, _KNOWN_ROUTE_KEYS, "composition 'routes' entry")
    if not isinstance(raw["mapping"], dict):
        raise ValueError(
            "Harness YAML composition 'routes' entry 'mapping' must be a "
            f"mapping, got {type(raw['mapping']).__name__}"
        )
    source = _require_str(raw["source"], "composition 'routes' entry 'source'")
    key = _require_str(raw["key"], "composition 'routes' entry 'key'")
    mapping = tuple(
        (
            _require_str(k, "composition 'routes' entry 'mapping' key"),
            _require_str(v, "composition 'routes' entry 'mapping' value"),
        )
        for k, v in raw["mapping"].items()
    )
    kwargs: dict[str, Any] = {"source": source, "key": key, "mapping": mapping}
    if "default" in raw:
        kwargs["default"] = _require_str(
            raw["default"], "composition 'routes' entry 'default'"
        )
    return RouteSpec(**kwargs)


def _build_worker_spec(raw: dict[str, Any]) -> WorkerSpec:
    """Reconstruct one ``WorkerSpec`` slot, turning its ``tools`` list into a tuple.

    Closes I-056: a worker mapping missing the required ``role`` field used
    to raise a raw, unhelpful ``KeyError`` from the ``raw["role"]`` lookup
    below — now a clear ``ValueError`` naming ``worker.role`` (same
    fail-loud pattern ``_build_composition_spec`` already uses for its own
    required ``mode`` field).
    """
    if not isinstance(raw, dict) or "role" not in raw:
        raise ValueError(
            "Harness YAML composition 'workers' entry is missing the "
            "required field 'worker.role'."
        )
    _reject_unknown_keys(raw, _KNOWN_WORKER_KEYS, "composition worker entry")
    kwargs: dict[str, Any] = {"role": raw["role"]}
    if "kernel" in raw:
        kwargs["kernel"] = raw["kernel"]
    if "tools" in raw:
        kwargs["tools"] = tuple(raw["tools"])
    return WorkerSpec(**kwargs)


def _build_infra_spec(raw: dict[str, Any]) -> InfraSpec:
    """Reconstruct a nested ``InfraSpec``.

    Task 5 (I-057, partial): rejects an unknown key inside the mapping
    (shallow, one level).
    """
    _reject_unknown_keys(raw, _KNOWN_INFRA_KEYS, "'infra' block")
    kwargs: dict[str, Any] = {}
    for field_name in ("checkpoint", "event_record", "replay"):
        if field_name in raw:
            kwargs[field_name] = raw[field_name]
    return InfraSpec(**kwargs)
