"""PresetRegistry — named bundles that expand into a full ``HarnessSpec``.

harness-composition spec, Task 4 (REQ-007, scenario 2). A preset is a
documented, named shortcut for a common composition: ``preset: <name>``
(or, in code, ``PresetRegistry.expand(name)``) resolves to the exact same
frozen :class:`~swarmline.harness.spec.HarnessSpec` a caller would otherwise
have to write out field-by-field. Presets do not introduce a fourth way of
describing composition — they are just named factories over the single
source of truth established in Task 1 (:mod:`swarmline.harness.spec`); the
expanded spec is resolved exactly like any hand-written one, through
:class:`~swarmline.harness.builder.HarnessBuilder` (Task 2) or the YAML
loader (Task 3).

Three built-ins are registered on the process-wide default instance
(:func:`get_preset_registry`), mirroring the registration/error-naming shape
already used by ``swarmline.harness.registries`` (``CompositionBlockNotFound``/
``InfraBlockNotFound``) and ``swarmline.runtime.thin.kernels.errors.KernelNotFound``:

- ``simple-react`` -- ``HarnessSpec(kernel="react")``. Solo ReAct kernel, no
  composition, no infra: the minimal happy path (REQ-008/009/010), one line
  instead of an empty-args constructor call.
- ``supervisor-team`` -- a supervisor coordinating a small, general-purpose
  team: ``researcher`` (gathers information), ``coder`` (implements),
  ``reviewer`` (checks the coder's output) -- the smallest team that covers
  "investigate, build, verify" end to end. ``blackboard=True`` (shared
  scratch state between workers, the ``CompositionSpec`` default).
- ``research-fanout`` -- a supervisor fanning a research question out across
  three parallel ``react`` researcher workers (``researcher-1``/``-2``/
  ``-3``) that each explore independently before the supervisor synthesizes
  their findings; also ``blackboard=True`` so they can see each other's
  partial results rather than working in silos.

Composition-build tension (documented, not hidden): ``supervisor-team`` and
``research-fanout`` both expand to a spec with ``composition.mode ==
"supervisor"``. The real supervisor composition block
(``swarmline.orchestration.supervisor``, H6) is NOT wired into the harness
registry seam yet -- that wiring is deferred to backlog item I-052 (it needs
H6's ``build_supervisor(orchestrator, state, config, llm_call)``, which is
too heavy to pull into a preset default today, and pulling it here would
break this module's import-light contract below). So today:

- ``PresetRegistry.expand("supervisor-team" | "research-fanout")`` returns a
  perfectly valid, well-formed ``HarnessSpec`` (REQ-007 is fully satisfied --
  it is about *expansion*, not building).
- ``HarnessBuilder.from_spec(that_spec).build()`` raises
  ``swarmline.harness.registries.CompositionBlockNotFound`` naming
  ``"supervisor"`` -- proving the seam is correct, not faking a build. Once
  I-052 registers a ``"supervisor"`` resolver into
  ``get_composition_registry()``, these two presets start building real
  agents with zero changes to this module.
- ``simple-react`` has no composition layer, so it builds a real ``Agent``
  today, unaffected by the I-052 deferral.

Import-light: this module imports only :mod:`swarmline.harness.spec`
(stdlib-only dataclasses) at module scope. It does not import
``swarmline.harness.builder``, ``swarmline.harness.registries``,
``swarmline.agent``, or any orchestration/runtime code, so importing it
never pulls ``swarmline.orchestration.supervisor`` into ``sys.modules``.
"""

from __future__ import annotations

import threading

from swarmline.harness.spec import CompositionSpec, HarnessSpec, WorkerSpec


class PresetNotFound(LookupError):
    """Raised by :meth:`PresetRegistry.expand` for an unregistered preset name."""

    def __init__(self, name: str, available: frozenset[str]) -> None:
        self.name = name
        self.available = available
        listed = ", ".join(sorted(available)) or "(none registered)"
        super().__init__(
            f"Unknown harness preset {name!r}. Available presets: {listed}."
        )


class PresetRegistry:
    """Thread-safe name -> ``HarnessSpec`` registry.

    Presets are stored as already-built, frozen ``HarnessSpec`` instances
    (not factories): a ``HarnessSpec`` is immutable, so there is nothing to
    protect by re-constructing it on every :meth:`expand` call, and storing
    the spec directly keeps the extensibility contract trivial -- a caller
    registers a spec and gets that exact spec back.

    Each instance is independent (no shared state): the module-level
    :func:`get_preset_registry` singleton carries the 3 built-ins; a
    caller-constructed ``PresetRegistry()`` starts empty and can register
    its own presets without touching the shared default.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._presets: dict[str, HarnessSpec] = {}

    def register(self, name: str, spec: HarnessSpec) -> None:
        """Register *spec* under *name*. Overwrites any existing registration."""
        with self._lock:
            self._presets[name] = spec

    def expand(self, name: str) -> HarnessSpec:
        """Return the full ``HarnessSpec`` registered under *name*.

        Raises:
            PresetNotFound: *name* has no registered preset. The error names
                *name* and lists every currently-registered preset name.
        """
        with self._lock:
            spec = self._presets.get(name)
        if spec is None:
            raise PresetNotFound(name, self.names())
        return spec

    def names(self) -> frozenset[str]:
        """Return a snapshot of all registered preset names."""
        with self._lock:
            return frozenset(self._presets.keys())


_SIMPLE_REACT = HarnessSpec(kernel="react")

_SUPERVISOR_TEAM = HarnessSpec(
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

_RESEARCH_FANOUT = HarnessSpec(
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


def _build_default_registry() -> PresetRegistry:
    """Construct the process-wide default registry with the 3 built-ins."""
    registry = PresetRegistry()
    registry.register("simple-react", _SIMPLE_REACT)
    registry.register("supervisor-team", _SUPERVISOR_TEAM)
    registry.register("research-fanout", _RESEARCH_FANOUT)
    return registry


_default_preset_registry = _build_default_registry()


def get_preset_registry() -> PresetRegistry:
    """Return the process-wide default preset registry (3 built-ins pre-registered)."""
    return _default_preset_registry
