"""Unit: register_graph_composition() -- wires the "graph" composition block
into the harness composition registry seam from OUTSIDE swarmline.harness
(workflow-patterns spec, Task 3 -- the FINAL task, closing REQ-012/013/014/
015/017/018).

This module only CALLS the public ``swarmline.harness.registries`` API
(``get_composition_registry().register(...)`` / ``.get()`` / ``.names()``)
-- it never imports or edits any other harness module. Mirrors
``tests/unit/test_supervisor_harness_composition.py``'s pattern (I-052) for
the sibling "supervisor" composition block, including its registry-isolation
fixture shape.

Isolation: the composition registry (``get_composition_registry()``) is a
process-wide singleton shared with ``test_harness_presets.py``,
``test_harness_taskloom_example.py`` and
``test_supervisor_harness_composition.py``, all of which fail loudly if they
find ANY leaked registration. ``monkeypatch.setattr`` records the ORIGINAL
``_resolvers`` dict object and restores it verbatim on teardown, so
registrations made here can never leak into other test modules regardless
of run order.
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
from swarmline.orchestration import graph_harness_composition
from swarmline.orchestration.graph_harness_composition import (
    register_graph_composition,
)
from swarmline.orchestration.workflow_graph import WorkflowGraph

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def clean_composition_registry(monkeypatch: pytest.MonkeyPatch):
    """Swap in a throwaway copy of the process-wide composition registry's
    resolver dict for the duration of the test.

    See module docstring: this prevents any registration made inside a test
    from leaking into other composition-registry tests, which assert the
    registry stays as they expect by default.
    """
    registry = get_composition_registry()
    monkeypatch.setattr(registry, "_resolvers", dict(registry._resolvers))
    return registry


class TestRegisterGraphComposition:
    """REQ-012/013/017: explicit (non-import-side-effect) registration of
    the "graph" composition block into the harness registry seam."""

    def test_graph_not_found_before_registration(
        self, clean_composition_registry
    ) -> None:
        """Before calling register_graph_composition(), the block is
        unknown -- proves the isolation fixture actually starts clean."""
        with pytest.raises(CompositionBlockNotFound) as exc_info:
            clean_composition_registry.get("graph")

        assert "graph" in str(exc_info.value)

    def test_register_graph_makes_mode_resolvable(
        self, clean_composition_registry
    ) -> None:
        """REQ-012/013: after registration, 'graph' resolves to a handle on
        the EXISTING graph substrate -- the WorkflowGraph class itself, not
        a newly-defined class in this module (identity check)."""
        register_graph_composition()

        assert "graph" in clean_composition_registry.names()
        assert clean_composition_registry.get("graph") is WorkflowGraph

    def test_register_graph_is_idempotent(self, clean_composition_registry) -> None:
        """Calling register_graph_composition() twice still resolves
        cleanly: re-registering does not swap in a different handle."""
        register_graph_composition()
        first = clean_composition_registry.get("graph")

        register_graph_composition()
        second = clean_composition_registry.get("graph")

        assert first is WorkflowGraph
        assert second is WorkflowGraph
        assert clean_composition_registry.names() == frozenset({"graph"})

    def test_register_graph_has_no_import_side_effect(
        self, clean_composition_registry
    ) -> None:
        """Merely importing graph_harness_composition (done at module
        scope, above, before this fixture ever ran) never registers
        'graph' -- only calling register_graph_composition() does."""
        assert "graph" not in clean_composition_registry.names()

    def test_graph_factory_uses_existing_substrate_no_new_engine(
        self, clean_composition_registry
    ) -> None:
        """REQ-012: the resolved handle lives in an EXISTING substrate
        module (workflow_graph / supervisor.handoff / graph_orchestrator),
        never in this new registration module -- proving no new engine
        class was introduced here."""
        register_graph_composition()

        handle = clean_composition_registry.get("graph")

        existing_substrate_modules = {
            "swarmline.orchestration.workflow_graph",
            "swarmline.orchestration.supervisor.handoff",
            "swarmline.multi_agent.graph_orchestrator",
        }
        assert handle.__module__ in existing_substrate_modules
        assert handle.__module__ != graph_harness_composition.__name__

    def test_unregistered_mode_still_raises_after_graph_registered(
        self, clean_composition_registry
    ) -> None:
        """REQ-017: registering "graph" does not make every mode
        resolvable -- an unrelated, still-unregistered mode keeps raising
        CompositionBlockNotFound, naming "graph" among the now-available
        modes and NOT naming the bogus one requested."""
        register_graph_composition()

        with pytest.raises(CompositionBlockNotFound) as exc_info:
            clean_composition_registry.get("nope-not-registered")

        assert "graph" in exc_info.value.available
        assert "nope-not-registered" not in exc_info.value.available

    def test_registration_uses_only_public_registry_api(self) -> None:
        """Guard: the module source never reaches into ``_BlockRegistry``
        internals (``_resolvers``/``_lock``) -- only the public
        ``register``/``get``/``names`` surface of
        ``swarmline.harness.registries`` is used."""
        source = inspect.getsource(graph_harness_composition)

        assert "_resolvers" not in source
        assert "_lock" not in source

    def test_module_does_not_import_harness_at_module_level(self) -> None:
        """The lazy-import discipline: the ``from swarmline.harness``
        import must live INSIDE ``register_graph_composition()``'s body,
        not at module scope -- so merely importing
        ``swarmline.orchestration.graph_harness_composition`` never
        touches the harness package; only actually CALLING the function
        does."""
        module_source = inspect.getsource(graph_harness_composition)
        function_source = inspect.getsource(register_graph_composition)
        module_scope_source = module_source.split("def register_graph_composition")[0]

        assert "from swarmline.harness" in function_source
        assert "from swarmline.harness" not in module_scope_source

    def test_resolver_lazily_imports_workflow_graph_not_at_registration_time(
        self,
    ) -> None:
        """Belt-and-suspenders: the ``swarmline.orchestration.workflow_graph``
        import must live inside the resolver closure returned by
        ``register_graph_composition``, not directly inside that function's
        own body -- i.e. it must not fire merely from calling
        register_graph_composition(), only from resolving the block. Only
        actual ``import``-statement lines are checked (not docstring prose,
        which also mentions the module path)."""
        function_source = inspect.getsource(register_graph_composition)
        lines = function_source.splitlines()
        substrate_import_lines = [
            line
            for line in lines
            if line.strip().startswith(
                "from swarmline.orchestration.workflow_graph import"
            )
        ]
        assert substrate_import_lines, "expected a lazy import of the substrate module"
        for line in substrate_import_lines:
            # 8+ spaces of indent == nested inside the inner resolver
            # function, not the outer register_graph_composition body
            # (which is indented 4 spaces).
            assert line.startswith(" " * 8), (
                f"substrate import must be nested inside the resolver closure: {line!r}"
            )


class TestGraphCompositionModuleImportLight:
    """Importing the module in a fresh subprocess must not eagerly pull
    swarmline.multi_agent.graph_orchestrator into sys.modules (I-020) --
    the edge this module's docstring promises to defer, mirroring
    ``test_supervisor_harness_composition.py``'s
    ``TestSupervisorCompositionModuleImportLight``.

    NOTE on ThinRuntime: it is deliberately NOT asserted absent here.
    ``swarmline.orchestration.graph_harness_composition`` necessarily first
    imports its parent package ``swarmline.orchestration``, whose
    PRE-EXISTING, workflow-patterns-unrelated ``__init__.py`` already eagerly
    imports ThinRuntime (the same already-accepted fact documented in the
    supervisor module's own import-light test) -- so a ThinRuntime-absence
    assertion would fail regardless of anything THIS module does. What this
    module controls, and what the tests below pin, is the ADDITIONAL
    ``swarmline.multi_agent.graph_orchestrator`` edge: the resolver hands back
    ``WorkflowGraph`` (stdlib-only import chain), so neither importing the
    module, nor calling ``register_graph_composition()``, nor RESOLVING the
    ``"graph"`` block ever pulls the graph-orchestrator/ThinRuntime-via-
    multi_agent surface. The first test explicitly asserts BOTH facts (the
    real invariant `graph_orchestrator` absent AND the pre-existing
    `runtime.thin.runtime` presence) so the ThinRuntime distinction is
    covered, not silently ignored.
    """

    def test_importing_module_does_not_pull_graph_orchestrator(self) -> None:
        code = (
            "import sys\n"
            "import swarmline.orchestration.graph_harness_composition\n"
            "mods = sys.modules\n"
            # The real invariant THIS module controls: the multi_agent graph
            # runtime is never dragged in.
            "assert 'swarmline.multi_agent.graph_orchestrator' not in mods, ("
            "'importing graph_harness_composition eagerly pulled graph_orchestrator')\n"
            # Documented reality (not this module's doing): the parent package
            # swarmline.orchestration.__init__ eagerly imports ThinRuntime, so
            # it IS present -- asserted here so the ThinRuntime invariant is
            # covered explicitly rather than missed.
            "assert 'swarmline.runtime.thin.runtime' in mods, ("
            "'expected the pre-existing orchestration.__init__ ThinRuntime pull')\n"
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

    def test_calling_register_without_resolving_does_not_pull_graph_orchestrator(
        self,
    ) -> None:
        code = (
            "import sys\n"
            "from swarmline.orchestration.graph_harness_composition import ("
            " register_graph_composition,\n"
            ")\n"
            "register_graph_composition()\n"
            "mods = sys.modules\n"
            "assert 'swarmline.harness.registries' in mods, ("
            "'expected the sanctioned registries seam to be imported')\n"
            "assert 'swarmline.multi_agent.graph_orchestrator' not in mods, ("
            "'register_graph_composition() eagerly pulled graph_orchestrator')\n"
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
