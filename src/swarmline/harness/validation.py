"""Standalone spec validation — REQ-003, comprehensive named-error rejection.

harness-composition spec, Task 5 (REQ-003, scenario 4). :func:`HarnessBuilder.build`
(Task 2) already rejects an unknown top-level ``kernel``, ``composition.mode``,
or ``infra`` block with a clear, named error (``KernelNotFound`` /
``CompositionBlockNotFound`` / ``InfraBlockNotFound``) — see
``swarmline.harness.builder``'s own inline checks, extended by Task 5 with
two additional checks it did not previously cover (both closed directly in
``build()``, not here — see that module's docstring):

- ``HarnessSpec.preset`` — when a spec carries a preset NAME (e.g. loaded
  from YAML ``{preset: "typo-name"}``) rather than an already-expanded
  composition, ``build()`` used to never look at that field at all, so an
  unknown preset name silently built a plain default agent instead of being
  rejected. Closed: ``build()`` now resolves it through
  ``swarmline.harness.presets.PresetRegistry`` and lets ``PresetNotFound``
  propagate.
- ``CompositionSpec.workers[*].kernel`` — each worker declares its OWN
  kernel (design.md's ``WorkerSpec`` ADR), which is a second, independent
  "kernel" reference a composition spec can carry besides the top-level one
  — REQ-003's literal wording ("a composition spec references an unknown
  kernel...") names this case directly. Closed: ``build()`` now checks every
  worker's kernel against the live ``KernelRegistry`` too.

This module exists for a DIFFERENT, complementary reason: :func:`validate_harness_spec`
is a **validate-only** entry point — it performs the exact same four checks
``build()`` now performs (same order, same named-error classes, zero new
error types), but WITHOUT the side effect of constructing a real ``Agent``.
That is useful wherever a caller wants a pre-flight check on a spec — e.g. a
downstream app (taskloom) validating a loaded YAML pipeline at deploy time,
or a CI step — without paying for (or being able to trigger) actual agent
construction. It intentionally duplicates ``build()``'s small (~15-line)
check sequence rather than having ``build()`` delegate to it: two of
``build()``'s existing tests (``test_harness_builder.py``,
``test_harness_yaml.py``) patch ``swarmline.harness.builder.get_composition_registry``/
``get_infra_registry`` directly (one of them functionally, to stub the
not-yet-wired composition/infra blocks so a parity build can proceed) —
refactoring ``build()`` to call into this module would silently break that
patch target. Keeping the two entry points textually separate (both reusing
the same named-error classes and the same registries) avoids that coupling
at the cost of ~15 duplicated lines — judged the safer trade-off for the
final task of this epic.

Import-light: only :mod:`swarmline.harness.spec` at module scope; every
``swarmline``-internal registry lookup is a lazy, in-function import (kernel
registry, preset registry, composition/infra registries), matching the rest
of the ``harness`` package's import-light contract.
"""

from __future__ import annotations

from swarmline.harness.spec import HarnessSpec


def validate_harness_spec(spec: HarnessSpec) -> None:
    """Validate every named reference in *spec* resolves — no ``Agent`` built.

    Checks, in order: top-level ``kernel``, ``preset`` (if set), the
    composition ``mode`` and every worker's ``kernel`` (if ``composition``
    is set), the declared graph topology when ``mode == "graph"``
    (graph-composition Task 2, REQ-010..014/019/020 — see
    :func:`~swarmline.harness.graph_validation.validate_graph_topology`),
    and every enabled ``infra`` flag (if ``infra`` is set). Raises the SAME
    named-error classes :meth:`~swarmline.harness.builder.HarnessBuilder.build`
    raises for the same conditions — this function introduces no new error
    type, it is purely a validate-without-building convenience.

    Raises:
        KernelNotFound: ``spec.kernel`` (or any worker's ``kernel``) is not
            registered in the live kernel registry.
        PresetNotFound: ``spec.preset`` is set but not a registered preset.
        CompositionBlockNotFound: ``spec.composition.mode`` is set but has
            no registered resolver.
        GraphTopologyError: ``spec.composition.mode == "graph"`` and the
            declared topology is invalid (unknown ref, cycle, etc.).
        InfraBlockNotFound: an enabled ``spec.infra`` flag has no registered
            resolver.
    """
    from swarmline.runtime.thin.kernels import get_default_kernel_registry
    from swarmline.runtime.thin.kernels.errors import KernelNotFound

    kernel_registry = get_default_kernel_registry()
    if spec.kernel not in kernel_registry.modes():
        raise KernelNotFound(spec.kernel, kernel_registry.modes())

    if spec.preset is not None:
        from swarmline.harness.presets import get_preset_registry

        get_preset_registry().expand(spec.preset)

    if spec.composition is not None:
        from swarmline.harness.registries import get_composition_registry

        get_composition_registry().get(spec.composition.mode)
        for worker in spec.composition.workers:
            if worker.kernel not in kernel_registry.modes():
                raise KernelNotFound(worker.kernel, kernel_registry.modes())
        if spec.composition.mode == "graph":
            from swarmline.harness.graph_validation import validate_graph_topology

            validate_graph_topology(spec.composition)

    if spec.infra is not None:
        from swarmline.harness.registries import get_infra_registry

        infra_registry = get_infra_registry()
        for block_name, enabled in (
            ("checkpoint", spec.infra.checkpoint),
            ("event_record", spec.infra.event_record),
            ("replay", spec.infra.replay),
        ):
            if enabled:
                infra_registry.get(block_name)
