"""Unit: register_supervisor_composition() -- wires the H6 supervisor block
into the harness composition registry seam from OUTSIDE swarmline.harness
(I-052).

This module only CALLS the public ``swarmline.harness.registries`` API
(``get_composition_registry().register(...)`` / ``.get()`` / ``.names()``)
-- it never imports or edits any other harness module (see
``harness_composition``'s own docstring backlog note, which explicitly
sanctions exactly this kind of outside-caller registration -- mirrors
``tests/unit/test_observability_harness_infra.py``'s pattern for the infra
seam).

Isolation: the composition registry (``get_composition_registry()``) is a
process-wide singleton shared with ``test_harness_presets.py`` and
``test_harness_taskloom_example.py``, both of which fail loudly if they find
ANY leaked registration (the former's
``test_composition_preset_expands_valid_but_build_raises_composition_not_found``
explicitly ``pytest.fail``s on any pre-existing name in the registry).
``monkeypatch.setattr`` records the ORIGINAL ``_resolvers`` dict object and
restores it verbatim on teardown, so registrations made here can never leak
into other test modules regardless of run order.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from swarmline.harness.registries import (
    CompositionBlockNotFound,
    get_composition_registry,
)
from swarmline.orchestration.supervisor import harness_composition
from swarmline.orchestration.supervisor.harness_composition import (
    register_supervisor_composition,
)
from swarmline.orchestration.supervisor.kernel import build_supervisor

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def clean_composition_registry(monkeypatch: pytest.MonkeyPatch):
    """Swap in a throwaway copy of the process-wide composition registry's
    resolver dict for the duration of the test.

    See module docstring: this prevents any registration made inside a test
    from leaking into ``test_harness_presets.py`` /
    ``test_harness_taskloom_example.py``, which assert the registry stays
    empty by default.
    """
    registry = get_composition_registry()
    monkeypatch.setattr(registry, "_resolvers", dict(registry._resolvers))
    return registry


class TestRegisterSupervisorComposition:
    """I-052: explicit (non-import-side-effect) registration of the H6
    supervisor composition block into the harness registry seam."""

    def test_supervisor_not_found_before_registration(
        self, clean_composition_registry
    ) -> None:
        """Before calling register_supervisor_composition(), the block is
        unknown -- proves the isolation fixture actually starts clean."""
        with pytest.raises(CompositionBlockNotFound) as exc_info:
            clean_composition_registry.get("supervisor")

        assert "supervisor" in str(exc_info.value)

    def test_register_makes_supervisor_composition_resolvable(
        self, clean_composition_registry
    ) -> None:
        """After registration, 'supervisor' resolves to the documented
        factory: build_supervisor itself."""
        register_supervisor_composition()

        assert "supervisor" in clean_composition_registry.names()
        assert clean_composition_registry.get("supervisor") is build_supervisor

    def test_register_is_idempotent(self, clean_composition_registry) -> None:
        """Calling register_supervisor_composition() twice still resolves
        cleanly: a single resolver per name (register() overwrites by name
        -- no duplicate/leaked registrations accumulate), and re-registering
        does not swap in a different factory."""
        register_supervisor_composition()
        first = clean_composition_registry.get("supervisor")

        register_supervisor_composition()
        second = clean_composition_registry.get("supervisor")

        assert first is build_supervisor
        assert second is build_supervisor
        assert clean_composition_registry.names() == frozenset({"supervisor"})

    def test_register_has_no_import_side_effect(
        self, clean_composition_registry
    ) -> None:
        """Merely importing harness_composition (done at module scope,
        above, before this fixture ever ran) never registers 'supervisor'
        -- only calling register_supervisor_composition() does."""
        assert "supervisor" not in clean_composition_registry.names()

    def test_supervisor_team_spec_builds_after_registration(
        self, clean_composition_registry
    ) -> None:
        """Once registered, a supervisor-composition HarnessSpec's .build()
        succeeds and returns a real Agent (no CompositionBlockNotFound) --
        closing I-052's literal ask. Consumed read-only through the public
        swarmline.harness API (spec + builder), never edited."""
        from swarmline.agent import Agent
        from swarmline.harness.builder import HarnessBuilder
        from swarmline.harness.spec import CompositionSpec, HarnessSpec, WorkerSpec

        register_supervisor_composition()

        spec = HarnessSpec(
            kernel="react",
            composition=CompositionSpec(
                mode="supervisor", workers=(WorkerSpec("researcher"),)
            ),
        )

        agent = HarnessBuilder.from_spec(spec).build()

        assert isinstance(agent, Agent)

    def test_registration_uses_only_public_registry_api(self) -> None:
        """Guard: the module source never reaches into ``_BlockRegistry``
        internals (``_resolvers``/``_lock``) -- only the public
        ``register``/``get``/``names`` surface of
        ``swarmline.harness.registries`` is used."""
        source = inspect.getsource(harness_composition)

        assert "_resolvers" not in source
        assert "_lock" not in source

    def test_module_does_not_import_harness_at_module_level(self) -> None:
        """The lazy-import discipline (I-052): the ``from swarmline.harness``
        import must live INSIDE ``register_supervisor_composition()``'s
        body, not at module scope -- so merely importing
        ``swarmline.orchestration.supervisor.harness_composition`` never
        touches the harness package; only actually CALLING the function
        does."""
        module_source = inspect.getsource(harness_composition)
        function_source = inspect.getsource(register_supervisor_composition)
        module_scope_source = module_source.split(
            "def register_supervisor_composition"
        )[0]

        assert "from swarmline.harness" in function_source
        assert "from swarmline.harness" not in module_scope_source

    def test_resolver_lazily_imports_build_supervisor_not_at_registration_time(
        self,
    ) -> None:
        """Belt-and-suspenders: the ``swarmline.orchestration.supervisor.kernel``
        import (which pulls ThinRuntime when actually called) must live
        inside the resolver closure returned by
        ``register_supervisor_composition``, not directly inside that
        function's own body -- i.e. it must not fire merely from calling
        register_supervisor_composition(), only from resolving the block.
        Only actual ``import``-statement lines are checked (not docstring
        prose, which also mentions the module path)."""
        function_source = inspect.getsource(register_supervisor_composition)
        lines = function_source.splitlines()
        kernel_import_lines = [
            line
            for line in lines
            if line.strip().startswith(
                "from swarmline.orchestration.supervisor.kernel import"
            )
        ]
        assert kernel_import_lines, "expected a lazy import of the kernel module"
        for line in kernel_import_lines:
            # 8+ spaces of indent == nested inside the inner resolver
            # function, not the outer register_supervisor_composition body
            # (which is indented 4 spaces).
            assert line.startswith(" " * 8), (
                f"kernel import must be nested inside the resolver closure: {line!r}"
            )


class TestWorkflowPatternsTask1WorkerKernelResolution:
    """workflow-patterns spec, Task 1 (REQ-005/006/016/017/018): delta tests
    on top of I-052's registration, closing the reconciliation with
    ``tasks.md``'s planned (but not built -- see the module docstring's
    reconciliation note) ``orchestration/harness_compositions.py``.

    ANALYSIS: REQ-005/006 ask that every declared ``WorkerSpec.kernel``
    resolve through the SAME kernel registry as the root kernel, with an
    unregistered one raising the registry's not-found error naming the
    available kernels. ``HarnessBuilder.build()`` (harness/builder.py --
    already shipped, H3 Task 5) already does exactly this, generically, for
    ANY composition mode -- iterating ``spec.composition.workers`` and
    checking each ``worker.kernel`` against
    ``get_default_kernel_registry().modes()``. The resolver this module
    registers returns ``build_supervisor`` UNINVOKED (``build()`` only
    proves the block exists and discards the result -- see
    ``harness_composition``'s module docstring), and ``build_supervisor``
    itself takes ``state``/``orchestrator`` keyword deps, not a
    ``WorkerSpec`` list -- so there is, today, no call site that would ever
    invoke a standalone worker-kernel-resolution helper added to
    ``harness_composition.py``. Adding one now would be unreachable code
    (YAGNI); these tests instead lock REQ-005/006/016/017/018 against the
    real, already-enforcing ``HarnessBuilder.build()`` path end-to-end.
    """

    def test_worker_kernels_resolved_via_shared_registry(
        self, clean_composition_registry
    ) -> None:
        """REQ-005 / scenario 2: workers declaring "react" and "adapt" both
        resolve through the same get_default_kernel_registry() the root
        kernel uses -- proven end-to-end via a real supervisor-mode build."""
        from swarmline.agent import Agent
        from swarmline.harness.builder import HarnessBuilder
        from swarmline.harness.spec import CompositionSpec, HarnessSpec, WorkerSpec
        from swarmline.runtime.thin.kernels import get_default_kernel_registry

        registry = get_default_kernel_registry()
        assert {"react", "adapt"} <= registry.modes()

        register_supervisor_composition()

        spec = HarnessSpec(
            kernel="react",
            composition=CompositionSpec(
                mode="supervisor",
                workers=(
                    WorkerSpec("researcher", kernel="react"),
                    WorkerSpec("fixer", kernel="adapt"),
                ),
            ),
        )

        agent = HarnessBuilder.from_spec(spec).build()

        assert isinstance(agent, Agent)

    def test_unregistered_worker_kernel_raises_kernel_not_found(
        self, clean_composition_registry
    ) -> None:
        """REQ-006 / scenario 2: a worker naming an unregistered kernel
        raises KernelNotFound listing the available kernel modes, resolved
        through HarnessBuilder.build()'s existing worker-kernel check."""
        from swarmline.harness.builder import HarnessBuilder
        from swarmline.harness.spec import CompositionSpec, HarnessSpec, WorkerSpec
        from swarmline.runtime.thin.kernels.errors import KernelNotFound

        register_supervisor_composition()

        spec = HarnessSpec(
            kernel="react",
            composition=CompositionSpec(
                mode="supervisor",
                workers=(WorkerSpec("ghost", kernel="not-a-real-kernel"),),
            ),
        )

        with pytest.raises(KernelNotFound) as exc_info:
            HarnessBuilder.from_spec(spec).build()

        assert exc_info.value.mode == "not-a-real-kernel"
        assert "react" in exc_info.value.available

    def test_unregistered_mode_still_raises_composition_not_found(
        self, clean_composition_registry
    ) -> None:
        """REQ-017 / scenario 1: registering "supervisor" does not make
        every mode resolvable -- an unrelated, still-unregistered mode
        keeps raising CompositionBlockNotFound, naming "supervisor" among
        the now-available modes and NOT naming the bogus one requested."""
        register_supervisor_composition()

        with pytest.raises(CompositionBlockNotFound) as exc_info:
            clean_composition_registry.get("nope-not-registered")

        assert "supervisor" in exc_info.value.available
        assert "nope-not-registered" not in exc_info.value.available

    def test_composition_none_path_never_consults_registry(self) -> None:
        """REQ-016/018: a composition=None build never even calls
        get_composition_registry() -- the byte-identical, zero-overhead
        minimal path, regardless of whether "supervisor" has been
        registered elsewhere in the process. Deliberately does NOT use the
        clean_composition_registry fixture: the assertion is that the
        registry getter is never CALLED at all, so no registry state (real
        or swapped) is ever touched either way. Re-locks, from this
        module's own test surface (task ask), the same contract
        test_harness_builder.py's TestHarnessBuilderMinimalSpecNoOverhead
        already proves against harness/builder.py directly."""
        from unittest.mock import patch

        from swarmline.harness.builder import HarnessBuilder

        with patch(
            "swarmline.harness.builder.get_composition_registry"
        ) as composition_mock:
            HarnessBuilder().build()

        composition_mock.assert_not_called()


class TestSupervisorCompositionModuleImportLight:
    """Importing the module in a fresh subprocess must not eagerly pull
    swarmline.harness or swarmline.multi_agent.graph_orchestrator into
    sys.modules -- the two edges this module's docstring promises to defer.

    NOTE on ThinRuntime: it is deliberately NOT asserted absent here.
    ``swarmline.orchestration.supervisor`` necessarily first imports its
    parent package ``swarmline.orchestration``, whose PRE-EXISTING,
    H6-unrelated ``__init__.py`` already eagerly imports ThinRuntime (see
    ``tests/unit/test_supervisor_import_light.py``'s own docstring/baseline
    test for the same, already-accepted fact) -- so a ThinRuntime-absence
    assertion here would fail regardless of anything this module does. What
    THIS module controls, and what it must not regress, is the additional
    ``swarmline.harness`` / ``graph_orchestrator`` edges checked below.
    """

    def test_importing_module_does_not_pull_harness_or_graph_orchestrator(
        self,
    ) -> None:
        code = (
            "import sys\n"
            "import swarmline.orchestration.supervisor.harness_composition\n"
            "mods = sys.modules\n"
            "assert not any(m.startswith('swarmline.harness') for m in mods), ("
            "'importing harness_composition eagerly pulled swarmline.harness')\n"
            "assert 'swarmline.multi_agent.graph_orchestrator' not in mods, ("
            "'importing harness_composition eagerly pulled graph_orchestrator')\n"
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

    def test_calling_register_without_resolving_does_not_pull_harness_builder(
        self,
    ) -> None:
        """Calling register_supervisor_composition() itself (which DOES
        import swarmline.harness.registries -- the sanctioned seam, per
        module docstring) must not pull the wider harness.builder/
        harness.presets modules.

        NOTE: ``swarmline.orchestration.supervisor.kernel`` is deliberately
        NOT asserted absent here -- the ``supervisor`` package's own
        (pre-existing, H6-unrelated) ``__init__.py`` already imports
        ``build_supervisor`` from it at module level, so it is already in
        ``sys.modules`` merely from importing
        ``swarmline.orchestration.supervisor.harness_composition`` (which
        necessarily imports its parent package first), regardless of this
        module's own lazy-import discipline. What matters, and what this
        test isolates, is that resolving the block does not ALSO drag in
        the harness builder/presets machinery.
        """
        code = (
            "import sys\n"
            "from swarmline.orchestration.supervisor.harness_composition import ("
            " register_supervisor_composition,\n"
            ")\n"
            "register_supervisor_composition()\n"
            "mods = sys.modules\n"
            "assert 'swarmline.harness.registries' in mods, ("
            "'expected the sanctioned registries seam to be imported')\n"
            "assert 'swarmline.harness.builder' not in mods, ("
            "'register_supervisor_composition() eagerly pulled harness.builder')\n"
            "assert 'swarmline.harness.presets' not in mods, ("
            "'register_supervisor_composition() eagerly pulled harness.presets')\n"
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
