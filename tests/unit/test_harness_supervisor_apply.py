"""Unit: HarnessBuilder.build() APPLIES the supervisor composition (I-066).

Before this task, ``build()`` resolved ``get_composition_registry().get(mode)``
for EXISTENCE-VALIDATION ONLY and DISCARDED the returned factory (see
``swarmline.orchestration.supervisor.harness_composition``'s "Honest scope"
docstring section) -- so ``.supervisor(...).build()`` returned a kernel-only
``Agent``, never a live supervisor-backed one. This module locks the fix: for
``composition.mode == "supervisor"`` specifically, ``build()`` now constructs
a ``SupervisorState``/``ThinSubagentOrchestrator`` pair, calls the resolved
factory (``build_supervisor``) with them, and returns an ``Agent`` whose
runtime is driven by the assembled 5-tool supervisor surface. Every OTHER
composition mode keeps the pre-existing discard-the-factory behavior
unchanged (scope boundary, see the module's own tests below).

Isolation: mirrors ``tests/unit/test_supervisor_harness_composition.py``'s
``clean_composition_registry`` fixture -- ``monkeypatch.setattr`` swaps in a
throwaway copy of the process-wide composition registry's resolver dict for
the duration of each test, so a ``register_supervisor_composition()`` call
here can never leak into ``test_harness_builder.py`` /
``test_harness_presets.py`` / ``test_harness_validation.py``, all of which
assert (directly or indirectly) that "supervisor" is NOT registered by
default.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.registries import (
    InfraBlockNotFound,
    get_composition_registry,
    get_infra_registry,
)
from swarmline.harness.spec import CompositionSpec, HarnessSpec, WorkerSpec
from swarmline.orchestration.supervisor.harness_composition import (
    register_supervisor_composition,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

SUPERVISOR_TOOL_NAMES = frozenset(
    {"spawn_subagent", "update_plan", "send_message", "read_reports", "finalize"}
)


@pytest.fixture
def clean_composition_registry(monkeypatch: pytest.MonkeyPatch):
    """Swap in a throwaway copy of the process-wide composition registry's
    resolver dict for the duration of the test (mirrors
    ``test_supervisor_harness_composition.py``'s isolation fixture)."""
    registry = get_composition_registry()
    monkeypatch.setattr(registry, "_resolvers", dict(registry._resolvers))
    return registry


@pytest.fixture
def clean_infra_registry(monkeypatch: pytest.MonkeyPatch):
    """Swap in a throwaway copy of the process-wide infra registry's
    resolver dict for the duration of the test (mirrors
    ``clean_composition_registry`` above) so a test-local ``register()``
    call here can never leak into other modules' infra-registry
    assertions."""
    registry = get_infra_registry()
    monkeypatch.setattr(registry, "_resolvers", dict(registry._resolvers))
    return registry


class _RecordingRuntime:
    """Fake ``AgentRuntime``: records the kwargs ``run()`` is invoked with and
    yields a single ``final`` event so ``Agent.query()`` completes cleanly
    without touching the network."""

    def __init__(self) -> None:
        self.run_kwargs: dict[str, Any] | None = None

    def run(self, **kwargs: Any) -> Any:
        self.run_kwargs = kwargs
        from swarmline.runtime.types import RuntimeEvent

        async def _gen():
            yield RuntimeEvent.final(text="supervisor-ok")

        return _gen()

    async def cleanup(self) -> None:
        pass

    def cancel(self) -> None:
        pass


def _patched_fake_factory() -> tuple[
    MagicMock, list[dict[str, Any]], _RecordingRuntime
]:
    """Build a MagicMock ``RuntimeFactory`` replacement recording ``create()``
    kwargs, mirroring the ``fake_factory``/``side_effect`` idiom in
    ``test_harness_builder.py::test_builder_custom_kernel_drives_agent_query_end_to_end``
    (~line 106)."""
    create_calls: list[dict[str, Any]] = []
    runtime = _RecordingRuntime()

    def _fake_create(**kwargs: Any) -> _RecordingRuntime:
        create_calls.append(kwargs)
        return runtime

    fake_factory = MagicMock()
    fake_factory.create.side_effect = _fake_create
    return fake_factory, create_calls, runtime


class TestHarnessBuilderAppliesSupervisorComposition:
    """DoD 1/2/3: ``build()`` returns a LIVE supervisor-backed Agent."""

    async def test_build_wires_local_tools_and_active_tools_end_to_end(
        self, clean_composition_registry
    ) -> None:
        """create(local_tools=...) carries all 5 supervisor executors AND
        run(active_tools=...) carries all 5 supervisor ToolSpecs (DoD 1)."""
        register_supervisor_composition()

        agent = (
            HarnessBuilder()
            .supervisor(workers=(WorkerSpec(role="researcher"),))
            .build()
        )

        fake_factory, create_calls, runtime = _patched_fake_factory()
        with patch(
            "swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory
        ):
            result = await agent.query("hello")

        assert result.ok is True
        assert len(create_calls) == 1
        local_tools = create_calls[0]["local_tools"]
        assert SUPERVISOR_TOOL_NAMES <= set(local_tools)

        assert runtime.run_kwargs is not None
        active_tool_names = {tool.name for tool in runtime.run_kwargs["active_tools"]}
        assert SUPERVISOR_TOOL_NAMES <= active_tool_names

    async def test_supervisor_executors_are_live_closures_bound_to_shared_state(
        self, clean_composition_registry
    ) -> None:
        """DoD 2: an executor obtained from the built factory is REAL, not a
        stub -- read_reports({}) proves it is live and bound to a fresh,
        shared SupervisorState (no reports yet -> the documented sentinel)."""
        register_supervisor_composition()

        agent = (
            HarnessBuilder()
            .supervisor(workers=(WorkerSpec(role="researcher"),))
            .build()
        )

        fake_factory, create_calls, _runtime = _patched_fake_factory()
        with patch(
            "swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory
        ):
            await agent.query("hello")

        local_tools = create_calls[0]["local_tools"]
        read_reports = local_tools["read_reports"]
        assert await read_reports({}) == "No worker reports yet."

        # A second, distinct executor -- send_message -- proves state is
        # actually mutated (not just read), still bound to the SAME shared
        # SupervisorState the built factory assembled.
        send_message = local_tools["send_message"]
        outcome = await send_message({"to": "worker-1", "content": "keep going"})
        assert outcome == "Message queued for 'worker-1'."

    async def test_mode_hint_still_pinned_to_spec_kernel(
        self, clean_composition_registry
    ) -> None:
        """DoD 3: the supervisor proxy keeps the parent's mode_hint pin."""
        register_supervisor_composition()

        agent = (
            HarnessBuilder()
            .kernel("adapt")
            .supervisor(workers=(WorkerSpec(role="researcher"),))
            .build()
        )

        fake_factory, _create_calls, runtime = _patched_fake_factory()
        with patch(
            "swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory
        ):
            await agent.query("hello")

        assert runtime.run_kwargs is not None
        assert runtime.run_kwargs["mode_hint"] == "adapt"


class TestHarnessBuilderSupervisorToolsSurviveTheRealRuntimeFactory:
    """Regression: production ``RuntimeFactory``/registry ``_create_thin``
    silently dropped ``local_tools`` whenever ``tool_executors`` was
    empty/falsy -- exactly the shape the facade passes for a supervisor
    build (``AgentConfig.tools`` is always empty, so ``create_kwargs``
    always carries ``tool_executors={}``). Every other test in this module
    patches ``swarmline.runtime.factory.RuntimeFactory`` with a
    ``fake_factory`` MagicMock, so none of them exercised the real
    ``_create_thin`` merge logic. This test drives
    ``HarnessBuilder().supervisor(...).build()``'s
    ``_SupervisorRuntimeFactory`` through the REAL, unpatched
    ``RuntimeFactory`` and asserts the constructed ``ThinRuntime`` actually
    carries all 5 supervisor executor names bound as local tools -- proving
    the supervisor tools are LIVE on the production path, not merely
    visible to a fake."""

    async def test_supervisor_local_tools_bound_through_the_real_runtime_factory(
        self, clean_composition_registry
    ) -> None:
        register_supervisor_composition()

        agent = (
            HarnessBuilder()
            .supervisor(workers=(WorkerSpec(role="researcher"),))
            .build()
        )

        from swarmline.runtime.types import RuntimeConfig

        # Same kwargs shape the facade passes for a supervisor build
        # (build_portable_runtime_plan always sets tool_executors from
        # AgentConfig.tools, which is empty here) -- no mock in the chain.
        # create() returns a _SupervisorRuntimeProxy wrapping the real
        # ThinRuntime -- unwrap it (._runtime) to inspect the bound tools.
        proxy = agent.runtime_factory.create(
            config=RuntimeConfig(runtime_name="thin"), tool_executors={}
        )
        runtime = proxy._runtime

        assert SUPERVISOR_TOOL_NAMES <= set(runtime._executor._local_tools)


class TestHarnessBuilderNonSupervisorModeStaysDiscardOnly:
    """DoD 4: only "supervisor" is applied -- every other registered mode
    keeps the pre-existing existence-validation-only (discard the factory)
    behavior, and ``composition=None`` never touches the registries.

    graph-composition spec, Task 3 reconciliation: this class originally
    used a hypothetical future ``"graph"`` mode as its stand-in example for
    "some OTHER registered mode" -- Task 3 made ``"graph"`` a SECOND
    applied mode (mirroring supervisor, see
    ``test_harness_graph_apply.py``), so it is no longer a valid example of
    the discard-only invariant this class actually protects. Renamed the
    stand-in to ``"future-block"`` -- still an arbitrary, registered-but-
    unrecognized mode name, which is what DoD 4 is about.
    """

    def test_registered_non_supervisor_mode_never_invokes_the_discarded_factory(
        self, clean_composition_registry
    ) -> None:
        """A registered mode OTHER than "supervisor"/"graph" (e.g. a
        hypothetical "future-block") still only proves existence -- the
        resolved factory is DISCARDED, never called, unlike the
        supervisor/graph paths."""
        from swarmline.agent import Agent

        def _never_call() -> str:
            raise AssertionError(
                "a non-supervisor composition factory must stay discarded, "
                "never invoked"
            )

        clean_composition_registry.register("future-block", lambda: _never_call)

        spec = HarnessSpec(
            kernel="react",
            composition=CompositionSpec(
                mode="future-block", workers=(WorkerSpec(role="w1"),)
            ),
        )

        agent = HarnessBuilder.from_spec(spec).build()

        assert isinstance(agent, Agent)
        assert agent.config.native_config["harness_kernel"] == "react"

    async def test_registered_non_supervisor_mode_leaks_no_supervisor_tools(
        self, clean_composition_registry
    ) -> None:
        """Behavioral proof of "no supervisor tools leak" (DoD 4): running
        the built Agent end-to-end shows an EMPTY active_tools/local_tools
        surface -- not the 5 supervisor tools."""

        def _never_call() -> str:
            raise AssertionError("discarded factory must never be invoked")

        clean_composition_registry.register("future-block", lambda: _never_call)

        spec = HarnessSpec(
            kernel="react",
            composition=CompositionSpec(
                mode="future-block", workers=(WorkerSpec(role="w1"),)
            ),
        )
        agent = HarnessBuilder.from_spec(spec).build()

        fake_factory, create_calls, runtime = _patched_fake_factory()
        with patch(
            "swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory
        ):
            await agent.query("hello")

        local_tools = create_calls[0].get("local_tools") or {}
        assert not (SUPERVISOR_TOOL_NAMES & set(local_tools))
        active_tool_names = {
            tool.name for tool in (runtime.run_kwargs or {}).get("active_tools", [])
        }
        assert not (SUPERVISOR_TOOL_NAMES & active_tool_names)

    def test_composition_none_path_never_consults_registry(self) -> None:
        """REQ-008/009 non-regression: composition=None never even calls
        get_composition_registry() -- zero overhead, regardless of the
        supervisor-apply change."""
        with patch(
            "swarmline.harness.builder.get_composition_registry"
        ) as composition_mock:
            HarnessBuilder().build()

        composition_mock.assert_not_called()

    def test_unregistered_mode_still_raises_composition_block_not_found(
        self, clean_composition_registry
    ) -> None:
        """An unregistered mode keeps raising CompositionBlockNotFound,
        exactly like before the supervisor-apply change."""
        from swarmline.harness.registries import CompositionBlockNotFound

        spec = HarnessSpec(
            composition=CompositionSpec(mode="definitely-not-registered")
        )

        with pytest.raises(CompositionBlockNotFound) as exc_info:
            HarnessBuilder.from_spec(spec).build()

        assert "definitely-not-registered" in str(exc_info.value)


class TestHarnessBuilderSupervisorApplyImportLight:
    """DoD 5: merely importing ``swarmline.harness.builder`` never eagerly
    pulls the supervisor substrate -- only actually building a
    supervisor-mode spec does. Mirrors
    ``test_supervisor_harness_composition.py``'s
    ``TestSupervisorCompositionModuleImportLight`` subprocess idiom."""

    def test_importing_builder_does_not_pull_supervisor_kernel_or_thin_subagent(
        self,
    ) -> None:
        code = (
            "import sys\n"
            "import swarmline.harness.builder\n"
            "mods = sys.modules\n"
            "assert 'swarmline.orchestration.supervisor.kernel' not in mods, ("
            "'importing harness.builder eagerly pulled supervisor.kernel')\n"
            "assert 'swarmline.orchestration.thin_subagent' not in mods, ("
            "'importing harness.builder eagerly pulled thin_subagent')\n"
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

    def test_importing_agent_assembly_does_not_pull_supervisor_kernel_or_thin_subagent(
        self,
    ) -> None:
        """I-076 mirror: ``harness/agent_assembly.py`` now holds the
        supervisor-apply construction logic (moved out of ``builder.py``) --
        importing it alone must stay just as import-light as importing
        ``harness.builder`` itself."""
        code = (
            "import sys\n"
            "import swarmline.harness.agent_assembly\n"
            "mods = sys.modules\n"
            "assert 'swarmline.orchestration.supervisor.kernel' not in mods, ("
            "'importing harness.agent_assembly eagerly pulled supervisor.kernel')\n"
            "assert 'swarmline.orchestration.thin_subagent' not in mods, ("
            "'importing harness.agent_assembly eagerly pulled thin_subagent')\n"
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


class TestHarnessBuilderSupervisorInfraValidationConsistency:
    """VERIFY-stage gap (I-066 follow-up): the supervisor branch used to
    ``return`` BEFORE infra existence-validation ran, so an unregistered
    infra block was silently skipped for a supervisor build -- inconsistent
    with the non-supervisor path, which DOES validate infra (see
    ``TestHarnessBuilderUnavailableCompositionInfraBlocks`` in
    ``test_harness_builder.py``). Locks the fix: infra validation now runs
    BEFORE composition in ``build()``, so both the supervisor early-return
    and the non-supervisor return are reached only after infra is proven
    available.
    """

    def test_supervisor_build_validates_unregistered_infra_block_raises(
        self, clean_composition_registry, clean_infra_registry
    ) -> None:
        """checkpoint infra requested but unregistered -> InfraBlockNotFound,
        even though composition.mode == "supervisor" (which used to return
        early, before infra was ever validated)."""
        register_supervisor_composition()

        with pytest.raises(InfraBlockNotFound) as exc_info:
            (
                HarnessBuilder()
                .supervisor(workers=(WorkerSpec(role="researcher"),))
                .with_checkpointing()
                .build()
            )

        assert "checkpoint" in str(exc_info.value)

    async def test_supervisor_build_succeeds_when_requested_infra_block_is_registered(
        self, clean_composition_registry, clean_infra_registry
    ) -> None:
        """A registered infra resolver doesn't block the supervisor apply --
        the built Agent is still a live supervisor-backed one exposing all
        5 tools (proves the reordering didn't break the happy path)."""
        register_supervisor_composition()
        clean_infra_registry.register("checkpoint", lambda: object())

        agent = (
            HarnessBuilder()
            .supervisor(workers=(WorkerSpec(role="researcher"),))
            .with_checkpointing()
            .build()
        )

        fake_factory, create_calls, runtime = _patched_fake_factory()
        with patch(
            "swarmline.runtime.factory.RuntimeFactory", return_value=fake_factory
        ):
            await agent.query("hello")

        local_tools = create_calls[0]["local_tools"]
        assert SUPERVISOR_TOOL_NAMES <= set(local_tools)

        assert runtime.run_kwargs is not None
        active_tool_names = {tool.name for tool in runtime.run_kwargs["active_tools"]}
        assert SUPERVISOR_TOOL_NAMES <= active_tool_names
