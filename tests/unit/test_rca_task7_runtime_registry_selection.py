"""RCA Task 7 — Subagent runtime selection via RuntimeRegistry.

TDD — tests written BEFORE implementation (RED → GREEN).

Covers:
  REQ-RCA-050: SubagentSpec.runtime_name resolves via RuntimeRegistry
  REQ-RCA-051: code-runtime adapters registered and resolved through registry
  REQ-RCA-052: unknown runtime_name fails fast naming the missing runtime
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest

from swarmline.domain_types import RuntimeEvent
from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.runtime.registry import RuntimeRegistry
from swarmline.runtime.types import RuntimeConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_call(response_text: str):
    """Mock LLM returning a final JSON envelope."""

    async def _llm(messages: list, system_prompt: str, **kwargs: Any) -> str:
        return json.dumps({"type": "final", "final_message": response_text})

    return _llm


async def _fake_event_stream(
    output_text: str, **kwargs: Any
) -> AsyncIterator[RuntimeEvent]:
    """Async generator yielding a single 'final' RuntimeEvent."""
    yield RuntimeEvent.final(output_text)


def _make_fake_runtime_factory(
    output_text: str,
    calls: list | None = None,
) -> Any:
    """Return a factory that creates a fake AgentRuntime.

    The fake runtime's run() is an async generator that yields one final event.
    calls is an optional list that accumulates each (config, kwargs) pair when
    the factory is invoked — useful for spy assertions.
    """

    class _FakeRuntime:
        def run(self, **kwargs: Any) -> AsyncIterator[RuntimeEvent]:
            return _fake_event_stream(output_text, **kwargs)

    def factory(config: RuntimeConfig, **kwargs: Any) -> _FakeRuntime:
        if calls is not None:
            calls.append({"config": config, "kwargs": kwargs})
        return _FakeRuntime()

    return factory


# ---------------------------------------------------------------------------
# 1. SubagentSpec.runtime_name field
# ---------------------------------------------------------------------------


class TestSubagentSpecRuntimeName:
    """SubagentSpec gains runtime_name — backward compatible."""

    def test_subagent_spec_default_runtime_name_is_none(self) -> None:
        """Existing code creating SubagentSpec without runtime_name still works."""
        spec = SubagentSpec(name="w", system_prompt="p")
        assert spec.runtime_name is None

    def test_subagent_spec_runtime_name_stored_correctly(self) -> None:
        """runtime_name is stored and retrievable from the frozen dataclass."""
        spec = SubagentSpec(name="w", system_prompt="p", runtime_name="thin")
        assert spec.runtime_name == "thin"

    def test_subagent_spec_frozen_with_runtime_name(self) -> None:
        """SubagentSpec remains frozen (immutable) with the new field."""
        spec = SubagentSpec(name="w", system_prompt="p", runtime_name="codex")
        with pytest.raises(Exception):  # FrozenInstanceError
            spec.runtime_name = "other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]


# ---------------------------------------------------------------------------
# 2. Registry resolution (REQ-RCA-050, REQ-RCA-051)
# ---------------------------------------------------------------------------


class TestRegistryRuntimeResolution:
    """runtime_name resolves through RuntimeRegistry only."""

    async def test_fake_registered_runtime_resolves_and_runs(self) -> None:
        """Registered runtime factory is called when runtime_name matches."""
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

        factory_invocations: list[dict] = []
        registry = RuntimeRegistry()
        registry.register(
            "fake_code", _make_fake_runtime_factory("fake result", factory_invocations)
        )

        orch = ThinSubagentOrchestrator(registry=registry, max_concurrent=2)
        spec = SubagentSpec(name="worker", system_prompt="p", runtime_name="fake_code")
        agent_id = await orch.spawn(spec, "do task")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert "fake result" in result.output
        assert len(factory_invocations) == 1, "Factory must be invoked exactly once"

    async def test_thin_runtime_name_resolves_via_registry(self) -> None:
        """runtime_name='thin' resolves via the injected registry."""
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

        thin_calls: list[dict] = []
        registry = RuntimeRegistry()
        registry.register("thin", _make_fake_runtime_factory("thin output", thin_calls))

        orch = ThinSubagentOrchestrator(registry=registry, max_concurrent=2)
        spec = SubagentSpec(name="worker", system_prompt="p", runtime_name="thin")
        agent_id = await orch.spawn(spec, "task")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert "thin output" in result.output
        assert len(thin_calls) == 1

    async def test_codex_stub_registered_resolves_via_registry(self) -> None:
        """CodeRuntimePort stub registered as 'codex' is resolved and used."""
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

        codex_calls: list[dict] = []
        registry = RuntimeRegistry()
        registry.register(
            "codex", _make_fake_runtime_factory("codex result", codex_calls)
        )

        orch = ThinSubagentOrchestrator(registry=registry, max_concurrent=2)
        spec = SubagentSpec(name="coder", system_prompt="Code it", runtime_name="codex")
        agent_id = await orch.spawn(spec, "build X")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert "codex result" in result.output
        assert len(codex_calls) == 1, "Registered codex factory must be called"

    async def test_registry_resolution_passes_config_to_factory(self) -> None:
        """Factory receives a RuntimeConfig when resolved."""
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

        calls: list[dict] = []
        registry = RuntimeRegistry()
        registry.register("pianobar", _make_fake_runtime_factory("pong", calls))

        orch = ThinSubagentOrchestrator(registry=registry, max_concurrent=2)
        spec = SubagentSpec(name="w", system_prompt="p", runtime_name="pianobar")
        agent_id = await orch.spawn(spec, "ping")
        await orch.wait(agent_id)

        assert calls, "Factory must have been called"
        assert isinstance(calls[0]["config"], RuntimeConfig)


# ---------------------------------------------------------------------------
# 3. Fail-fast invariant (REQ-RCA-052)
# ---------------------------------------------------------------------------


class TestFailFastOnUnknownRuntime:
    """Unknown runtime_name raises a ValueError naming the missing runtime."""

    async def test_unknown_runtime_name_raises_value_error(self) -> None:
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

        registry = RuntimeRegistry()  # empty — no "ghost" registered
        orch = ThinSubagentOrchestrator(registry=registry, max_concurrent=2)
        spec = SubagentSpec(name="w", system_prompt="p", runtime_name="ghost")

        with pytest.raises(ValueError) as exc_info:
            await orch.spawn(spec, "task")

        assert "ghost" in str(exc_info.value), (
            "Error message must name the missing runtime"
        )

    async def test_unknown_runtime_error_message_contains_name(self) -> None:
        """Fail-fast message names the exact unknown runtime_name."""
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

        registry = RuntimeRegistry()
        registry.register("known_one", _make_fake_runtime_factory("x"))
        orch = ThinSubagentOrchestrator(registry=registry, max_concurrent=2)
        spec = SubagentSpec(name="w", system_prompt="p", runtime_name="not_registered")

        with pytest.raises(ValueError, match="not_registered"):
            await orch.spawn(spec, "task")

    async def test_fail_fast_never_silently_falls_back_to_default(self) -> None:
        """No fallback to default when runtime_name is set but not registered."""
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

        registry = RuntimeRegistry()  # "missing" not registered
        orch = ThinSubagentOrchestrator(registry=registry, max_concurrent=2)
        spec = SubagentSpec(name="w", system_prompt="p", runtime_name="missing")

        # Must raise — never silently bypass
        with pytest.raises(ValueError):
            await orch.spawn(spec, "task")

        # Double-check: _create_runtime is not reached with the old default path
        # (the error should happen inside spawn before any LLM work)
        assert orch._tasks == {} or all(t.done() for t in orch._tasks.values()), (
            "No tasks should have been created or all should have failed immediately"
        )


# ---------------------------------------------------------------------------
# 4. Default None is byte-identical (no registry lookup)
# ---------------------------------------------------------------------------


class TestDefaultNoneIsIdentical:
    """runtime_name=None preserves current behaviour — registry is NOT consulted."""

    async def test_none_runtime_name_does_not_call_registry_get(self) -> None:
        """Registry.get must not be invoked when runtime_name is None."""
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

        registry = RuntimeRegistry()
        get_calls: list[str] = []
        original_get = registry.get

        def spy_get(name: str) -> Any:
            get_calls.append(name)
            return original_get(name)

        registry.get = spy_get  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]

        orch = ThinSubagentOrchestrator(
            registry=registry,
            max_concurrent=2,
            llm_call=_make_llm_call("done"),
        )
        spec = SubagentSpec(name="w", system_prompt="p")  # runtime_name=None (default)
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)

        assert get_calls == [], (
            "Registry must NOT be consulted when runtime_name is None"
        )

    async def test_none_runtime_name_creates_thin_worker_runtime(self) -> None:
        """Default (None) still creates _ThinWorkerRuntime, not registry path."""
        from swarmline.orchestration.thin_subagent import (
            ThinSubagentOrchestrator,
        )

        runtime_types: list[str] = []
        original_create = ThinSubagentOrchestrator._create_runtime

        def patched_create(spec: SubagentSpec) -> Any:
            rt = original_create(orch, spec)
            runtime_types.append(type(rt).__name__)
            return rt

        orch = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call("done"),
        )
        orch._create_runtime = patched_create  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]

        spec = SubagentSpec(name="w", system_prompt="p")  # runtime_name=None
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)

        assert runtime_types == ["_ThinWorkerRuntime"]


# ---------------------------------------------------------------------------
# 5. spawn_agent tool exposes runtime_name (schema + plumbing)
# ---------------------------------------------------------------------------


class TestSpawnAgentToolRuntimeName:
    """spawn_agent tool exposes runtime_name and plumbs it into SubagentSpec."""

    def test_spawn_agent_tool_spec_declares_runtime_name(self) -> None:
        """SUBAGENT_TOOL_SPEC.parameters must include 'runtime_name' property."""
        from swarmline.runtime.thin.subagent_tool import SUBAGENT_TOOL_SPEC

        props = SUBAGENT_TOOL_SPEC.parameters.get("properties", {})
        assert "runtime_name" in props, "spawn_agent schema must declare 'runtime_name'"

    async def test_spawn_agent_executor_plumbs_runtime_name_into_spec(self) -> None:
        """Executor builds SubagentSpec with runtime_name from tool call args."""
        from swarmline.orchestration.subagent_types import (
            SubagentResult,
            SubagentStatus,
        )
        from swarmline.runtime.thin.subagent_tool import (
            SubagentToolConfig,
            create_subagent_executor,
        )

        mock_orch = AsyncMock()
        mock_orch.spawn.return_value = "agent-id"
        mock_orch.wait.return_value = SubagentResult(
            agent_id="agent-id",
            status=SubagentStatus(state="completed"),
            output="done",
        )

        executor = create_subagent_executor(
            mock_orch,
            SubagentToolConfig(),
            [],
            current_depth=0,
            allowed_runtimes=frozenset({"codex"}),  # RCA-SEC-01: must be in allowlist
        )
        await executor({"task": "do X", "runtime_name": "codex"})

        mock_orch.spawn.assert_called_once()
        spec_arg: SubagentSpec = mock_orch.spawn.call_args.args[0]
        assert spec_arg.runtime_name == "codex"

    async def test_spawn_agent_executor_omitted_runtime_name_is_none(self) -> None:
        """When runtime_name is absent from tool args, SubagentSpec.runtime_name is None."""
        from swarmline.orchestration.subagent_types import (
            SubagentResult,
            SubagentStatus,
        )
        from swarmline.runtime.thin.subagent_tool import (
            SubagentToolConfig,
            create_subagent_executor,
        )

        mock_orch = AsyncMock()
        mock_orch.spawn.return_value = "agent-id"
        mock_orch.wait.return_value = SubagentResult(
            agent_id="agent-id",
            status=SubagentStatus(state="completed"),
            output="done",
        )

        executor = create_subagent_executor(
            mock_orch, SubagentToolConfig(), [], current_depth=0
        )
        await executor({"task": "do X"})  # no runtime_name key

        spec_arg: SubagentSpec = mock_orch.spawn.call_args.args[0]
        assert spec_arg.runtime_name is None
