"""RCA-SEC-01 — spawn_agent allowlist gate for LLM-initiated runtime selection.

TDD: tests written BEFORE implementation (RED → GREEN).

The vulnerability: an LLM-controlled `runtime_name` in spawn_agent args could
select ANY registered runtime, bypassing sandbox isolation.

Fix: `create_subagent_executor` accepts `allowed_runtimes: frozenset[str] | None`
(default None = DEFAULT-DENY). The gate is enforced at the LLM boundary in
`_execute`, BEFORE building SubagentSpec. The trusted programmatic path
(SubagentSpec.runtime_name set by host code) is untouched.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentStatus,
    SubagentSpec,
)
from swarmline.runtime.thin.subagent_tool import (
    SubagentToolConfig,
    create_subagent_executor,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_mock_orchestrator() -> AsyncMock:
    mock = AsyncMock()
    mock.spawn.return_value = "agent-id"
    mock.wait.return_value = SubagentResult(
        agent_id="agent-id",
        status=SubagentStatus(state="completed"),
        output="ok",
    )
    return mock


# ---------------------------------------------------------------------------
# 1. Allowed runtime → honored (plumbed into SubagentSpec)
# ---------------------------------------------------------------------------


class TestAllowedRuntimeIsHonored:
    """When runtime_name is in the allowlist, it is plumbed into SubagentSpec."""

    async def test_allowed_runtime_name_plumbed_into_spec(self) -> None:
        """runtime_name in allowed_runtimes → SubagentSpec.runtime_name set."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            [],
            current_depth=0,
            allowed_runtimes=frozenset({"thin", "codex"}),
        )

        await executor({"task": "do X", "runtime_name": "thin"})

        orch.spawn.assert_called_once()
        spec: SubagentSpec = orch.spawn.call_args.args[0]
        assert spec.runtime_name == "thin"

    async def test_second_allowed_runtime_also_honored(self) -> None:
        """All names in the allowlist are each individually permitted."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            [],
            current_depth=0,
            allowed_runtimes=frozenset({"codex", "claude_sdk"}),
        )

        await executor({"task": "t", "runtime_name": "codex"})

        spec: SubagentSpec = orch.spawn.call_args.args[0]
        assert spec.runtime_name == "codex"


# ---------------------------------------------------------------------------
# 2. Runtime NOT in allowlist → fail-closed rejection
# ---------------------------------------------------------------------------


class TestDisallowedRuntimeIsRejected:
    """runtime_name not in allowed_runtimes → fail-closed JSON error, no spawn."""

    async def test_disallowed_runtime_returns_error_json(self) -> None:
        """A runtime outside the allowlist returns a JSON error response."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            [],
            current_depth=0,
            allowed_runtimes=frozenset({"thin"}),
        )

        result = await executor({"task": "t", "runtime_name": "claude_sdk"})

        payload = json.loads(result)
        assert payload["status"] == "error"

    async def test_disallowed_runtime_error_names_the_runtime(self) -> None:
        """Rejection error message contains the denied runtime name."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            [],
            current_depth=0,
            allowed_runtimes=frozenset({"thin"}),
        )

        result = await executor({"task": "t", "runtime_name": "privileged_runtime"})

        payload = json.loads(result)
        assert "privileged_runtime" in payload["error"]

    async def test_disallowed_runtime_spawn_is_never_called(self) -> None:
        """Orchestrator.spawn must NOT be called when runtime is rejected."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            [],
            current_depth=0,
            allowed_runtimes=frozenset({"thin"}),
        )

        await executor({"task": "t", "runtime_name": "claude_sdk"})

        orch.spawn.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Default-deny: no allowlist → any LLM-provided runtime_name is denied
# ---------------------------------------------------------------------------


class TestDefaultDenyWithNoAllowlist:
    """Default-deny: allowed_runtimes=None means agent-initiated runtime selection is off."""

    async def test_no_allowlist_rejects_any_runtime_name(self) -> None:
        """With no allowlist, any LLM-provided runtime_name is rejected."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            [],
            current_depth=0,
            # allowed_runtimes not provided → default None → default-deny
        )

        result = await executor({"task": "t", "runtime_name": "thin"})

        payload = json.loads(result)
        assert payload["status"] == "error"
        orch.spawn.assert_not_called()

    async def test_empty_allowlist_rejects_all_runtimes(self) -> None:
        """An empty frozenset also denies all agent-initiated runtime selection."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            [],
            current_depth=0,
            allowed_runtimes=frozenset(),  # empty = deny all
        )

        result = await executor({"task": "t", "runtime_name": "thin"})

        payload = json.loads(result)
        assert payload["status"] == "error"
        orch.spawn.assert_not_called()

    async def test_no_allowlist_rejection_names_the_runtime(self) -> None:
        """Default-deny error message names the rejected runtime."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            [],
            current_depth=0,
        )

        result = await executor({"task": "t", "runtime_name": "any_runtime"})

        payload = json.loads(result)
        assert "any_runtime" in payload["error"]


# ---------------------------------------------------------------------------
# 4. Omitting runtime_name → unchanged default-thin behaviour
# ---------------------------------------------------------------------------


class TestOmittedRuntimeNameIsUnchanged:
    """When runtime_name is absent, behaviour is byte-identical to pre-SEC-01."""

    async def test_omitted_runtime_name_no_error(self) -> None:
        """No runtime_name in args → no rejection, agent spawns normally."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            [],
            current_depth=0,
            # no allowed_runtimes — default-deny only applies when runtime_name IS provided
        )

        result = await executor({"task": "do X"})

        payload = json.loads(result)
        assert payload["status"] == "completed"
        orch.spawn.assert_called_once()

    async def test_omitted_runtime_name_spec_has_none(self) -> None:
        """Omitted runtime_name → SubagentSpec.runtime_name is None."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch, SubagentToolConfig(), [], current_depth=0
        )

        await executor({"task": "do X"})

        spec: SubagentSpec = orch.spawn.call_args.args[0]
        assert spec.runtime_name is None


# ---------------------------------------------------------------------------
# 5. Trusted programmatic path is unaffected
# ---------------------------------------------------------------------------


class TestTrustedProgrammaticPathUnaffected:
    """SubagentSpec.runtime_name set by host code bypasses the spawn_agent gate."""

    async def test_subagent_spec_runtime_name_bypasses_allowlist(self) -> None:
        """Host code setting SubagentSpec.runtime_name directly is NOT gated."""
        from swarmline.runtime.registry import RuntimeRegistry
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
        from swarmline.domain_types import RuntimeEvent

        async def _fake_events(**kwargs: Any):  # type: ignore[return]
            yield RuntimeEvent.final("trusted output")

        class FakeRuntime:
            def run(self, **kwargs: Any):
                return _fake_events(**kwargs)

        registry = RuntimeRegistry()
        registry.register("privileged", lambda config, **kw: FakeRuntime())

        orch = ThinSubagentOrchestrator(registry=registry, max_concurrent=2)
        # Host code sets runtime_name directly — this is the trusted path
        spec = SubagentSpec(
            name="trusted-worker", system_prompt="p", runtime_name="privileged"
        )
        agent_id = await orch.spawn(spec, "task")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert "trusted output" in result.output

    async def test_unknown_runtime_in_trusted_path_still_fails_fast(self) -> None:
        """Trusted path fail-fast (REQ-RCA-052) is unchanged by SEC-01."""
        from swarmline.runtime.registry import RuntimeRegistry
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

        registry = RuntimeRegistry()  # "unknown" not registered
        orch = ThinSubagentOrchestrator(registry=registry, max_concurrent=2)
        spec = SubagentSpec(name="w", system_prompt="p", runtime_name="unknown")

        with pytest.raises(ValueError, match="unknown"):
            await orch.spawn(spec, "task")
