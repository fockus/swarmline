"""ToolsetPolicy scoped spawn — default-deny full inheritance for spawn_agent.

TDD: tests written BEFORE the `create_subagent_executor` wiring (RED → GREEN).

The vulnerability: an LLM-initiated `spawn_agent` call with no `tools=`
argument inherited the parent's FULL toolset
(`child_tools = list(parent_tools)`, subagent_tool.py:161). REQ-ORC-040/041/042:

- REQ-ORC-040/041: when a `ToolsetPolicy` is wired in and no `tools=` is
  named, the child is scoped to the role's policy set (intersected with
  what the parent actually has), NOT the full parent toolset.
- REQ-ORC-042: a `researcher` role is scoped to research/discovery tools.
- Explicit `tools=` requests are intersected with the policy when one is
  wired in.
- `toolset_policy=None` (the default) DENIES: an absent policy is an empty
  allowlist, not "inherit everything" (Sprint D stage 1 — see section 6; this
  reverses the original backward-compat carve-out).
- The trusted programmatic `SubagentSpec.tools` path (set by host code via
  `orchestrator.spawn(spec, ...)` directly) is never routed through this
  executor and is therefore unaffected.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from swarmline.domain_types import ToolSpec
from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from swarmline.policy.toolset_policy import RESEARCHER_TOOLS, ToolsetPolicy
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


def _make_parent_tools() -> list[ToolSpec]:
    """Parent toolset mixing research tools with non-research tools."""
    names = ["read", "grep", "web_search", "bash", "edit"]
    return [
        ToolSpec(name=n, description=f"{n} tool", parameters={"type": "object"})
        for n in names
    ]


# ---------------------------------------------------------------------------
# 1. ToolsetPolicy.allowed_tools — researcher vs unknown role
# ---------------------------------------------------------------------------


class TestToolsetPolicyAllowedTools:
    """`allowed_tools` resolves per-role; unknown roles default-deny."""

    def test_allowed_tools_for_researcher_returns_research_set(self) -> None:
        """`researcher` role resolves to the research/discovery toolset."""
        policy = ToolsetPolicy.researcher()

        assert policy.allowed_tools("researcher") == RESEARCHER_TOOLS

    def test_allowed_tools_for_unknown_role_returns_empty_frozenset(self) -> None:
        """An unrecognized role gets an empty frozenset (default-deny)."""
        policy = ToolsetPolicy.researcher()

        result = policy.allowed_tools("unregistered-role")

        assert result == frozenset()


# ---------------------------------------------------------------------------
# 2. Policy wired + no tools= → default-deny full inheritance (REQ-ORC-041)
# ---------------------------------------------------------------------------


class TestPolicyWiredWithNoToolsArgDefaultDenies:
    """No `tools=` + a policy wired in → scoped to policy set, not full parent."""

    async def test_no_tools_arg_scopes_to_policy_intersection_not_full_parent(
        self,
    ) -> None:
        """Child gets parent ∩ policy set; full parent set is NOT granted."""
        orch = _make_mock_orchestrator()
        policy = ToolsetPolicy.researcher()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            _make_parent_tools(),
            current_depth=0,
            toolset_policy=policy,
            spawn_role="researcher",
        )

        await executor({"task": "investigate X"})

        spec: SubagentSpec = orch.spawn.call_args.args[0]
        child_names = {t.name for t in spec.tools}
        parent_names = {t.name for t in _make_parent_tools()}
        assert child_names == {"read", "grep", "web_search"}
        assert child_names != parent_names

    async def test_no_tools_arg_drops_non_research_tools(self) -> None:
        """bash/edit are dropped; they are not in the researcher policy set."""
        orch = _make_mock_orchestrator()
        policy = ToolsetPolicy.researcher()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            _make_parent_tools(),
            current_depth=0,
            toolset_policy=policy,
            spawn_role="researcher",
        )

        await executor({"task": "investigate X"})

        spec: SubagentSpec = orch.spawn.call_args.args[0]
        child_names = {t.name for t in spec.tools}
        assert "bash" not in child_names
        assert "edit" not in child_names


# ---------------------------------------------------------------------------
# 3. researcher role scopes to research/discovery tools only (REQ-ORC-042)
# ---------------------------------------------------------------------------


class TestResearcherRoleScopesToResearchTools:
    """A `researcher` spawn is scoped to research/discovery tools only."""

    async def test_researcher_role_child_tools_subset_of_researcher_tools(self) -> None:
        """Every granted child tool name is a member of RESEARCHER_TOOLS."""
        orch = _make_mock_orchestrator()
        policy = ToolsetPolicy.researcher()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            _make_parent_tools(),
            current_depth=0,
            toolset_policy=policy,
            spawn_role="researcher",
        )

        await executor({"task": "investigate X"})

        spec: SubagentSpec = orch.spawn.call_args.args[0]
        child_names = {t.name for t in spec.tools}
        assert child_names <= RESEARCHER_TOOLS
        assert child_names  # non-empty: parent actually has research tools


# ---------------------------------------------------------------------------
# 4. Explicit tools= intersected with policy
# ---------------------------------------------------------------------------


class TestExplicitToolsIntersectedWithPolicy:
    """Explicit `tools=` names are intersected with the wired policy set."""

    async def test_explicit_tools_intersected_with_policy_keeps_only_allowed(
        self,
    ) -> None:
        """tools=["read","bash"] + researcher policy → only 'read' survives."""
        orch = _make_mock_orchestrator()
        policy = ToolsetPolicy.researcher()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            _make_parent_tools(),
            current_depth=0,
            toolset_policy=policy,
            spawn_role="researcher",
        )

        await executor({"task": "investigate X", "tools": ["read", "bash"]})

        spec: SubagentSpec = orch.spawn.call_args.args[0]
        child_names = {t.name for t in spec.tools}
        assert child_names == {"read"}


# ---------------------------------------------------------------------------
# 5. Explicit tool absent from policy is dropped
# ---------------------------------------------------------------------------


class TestExplicitToolAbsentFromPolicyIsDropped:
    """A tool named in `tools=` but absent from the policy set is dropped."""

    async def test_tool_absent_from_policy_dropped_even_if_parent_has_it(self) -> None:
        """'edit' is a real parent tool but not in the researcher policy."""
        orch = _make_mock_orchestrator()
        policy = ToolsetPolicy.researcher()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            _make_parent_tools(),
            current_depth=0,
            toolset_policy=policy,
            spawn_role="researcher",
        )

        await executor({"task": "investigate X", "tools": ["edit", "grep"]})

        spec: SubagentSpec = orch.spawn.call_args.args[0]
        child_names = {t.name for t in spec.tools}
        assert child_names == {"grep"}
        assert "edit" not in child_names


# ---------------------------------------------------------------------------
# 6. BREAKING (Sprint D stage 1): toolset_policy=None now DENIES
#
# The original wiring kept legacy full inheritance when no policy was wired, as
# a backward-compat carve-out. That makes the security property opt-IN: a host
# that forgets to wire a policy hands every spawned child the parent's entire
# toolset, which is the exact failure mode ToolsetPolicy exists to prevent.
# An absent policy is now an EMPTY allowlist. Hosts that want a child to have
# tools must say which ones.
# ---------------------------------------------------------------------------


class TestAbsentPolicyDenies:
    """`toolset_policy=None` (the default) → child gets NO tools."""

    async def test_no_policy_no_tools_arg_denies_the_whole_parent_toolset(self) -> None:
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            _make_parent_tools(),
            current_depth=0,
            # toolset_policy not provided -> default None -> DENY
        )

        await executor({"task": "do X"})

        spec: SubagentSpec = orch.spawn.call_args.args[0]
        assert list(spec.tools) == []

    async def test_no_policy_explicit_tools_arg_is_denied_too(self) -> None:
        """The hole that would make the default meaningless: if the model can
        name tools and get them, deny-by-default is bypassed by typing names.
        Both branches must resolve against the same empty allowlist."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            _make_parent_tools(),
            current_depth=0,
        )

        await executor({"task": "do X", "tools": ["bash", "read"]})

        spec: SubagentSpec = orch.spawn.call_args.args[0]
        assert list(spec.tools) == []

    async def test_wired_policy_still_grants_its_role_set(self) -> None:
        """The deny is about the ABSENT policy, not about policies in general —
        a wired policy must keep working exactly as before."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            _make_parent_tools(),
            current_depth=0,
            toolset_policy=ToolsetPolicy.researcher(),
            spawn_role="researcher",
        )

        await executor({"task": "do X"})

        spec: SubagentSpec = orch.spawn.call_args.args[0]
        child_names = {t.name for t in spec.tools}
        assert child_names
        assert child_names <= RESEARCHER_TOOLS


# ---------------------------------------------------------------------------
# 6b. Host-controlled arguments cannot be set by the model
# ---------------------------------------------------------------------------


class TestHostControlledArgsRejected:
    """`timeout`/`routing`/`depth` are host limits, not model parameters.

    None of them is in `SUBAGENT_TOOL_SPEC` today, so a well-behaved model never
    sends one — but a schema that grows later, or a model that guesses, must not
    be able to widen its own timeout or reset its own recursion depth. Rejecting
    loudly beats silently ignoring: a silently dropped `timeout` looks to the
    model like a limit it successfully raised.
    """

    async def test_model_passed_timeout_is_rejected(self) -> None:
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch, SubagentToolConfig(), _make_parent_tools(), current_depth=0
        )

        raw = await executor({"task": "do X", "timeout": 9999})

        assert json.loads(raw)["status"] == "error"
        orch.spawn.assert_not_called()

    async def test_model_passed_depth_is_rejected(self) -> None:
        """Depth is derived from run state; a model-supplied value would let a
        child reset its own recursion budget and defeat the depth guard."""
        # Depth well BELOW max on purpose: at the leaf the depth guard would
        # reject first and this test would pass without the arg check existing.
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch, SubagentToolConfig(max_depth=3), _make_parent_tools(), current_depth=0
        )

        raw = await executor({"task": "do X", "depth": 0})

        assert json.loads(raw)["status"] == "error"
        orch.spawn.assert_not_called()

    async def test_model_passed_routing_is_rejected(self) -> None:
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch, SubagentToolConfig(), _make_parent_tools(), current_depth=0
        )

        raw = await executor({"task": "do X", "routing": "cheap-model"})

        assert json.loads(raw)["status"] == "error"
        orch.spawn.assert_not_called()

    async def test_ordinary_spawn_is_unaffected(self) -> None:
        """The guard must not reject a normal call — the arg list is a denylist
        of host-controlled names, not a whitelist of the schema."""
        orch = _make_mock_orchestrator()
        executor = create_subagent_executor(
            orch,
            SubagentToolConfig(),
            _make_parent_tools(),
            current_depth=0,
            toolset_policy=ToolsetPolicy.researcher(),
            spawn_role="researcher",
        )

        raw = await executor({"task": "do X", "system_prompt": "be brief"})

        assert json.loads(raw)["status"] == "completed"
        orch.spawn.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Trusted programmatic path is unaffected
# ---------------------------------------------------------------------------


class TestTrustedProgrammaticPathUnaffected:
    """SubagentSpec.tools set directly by host code bypasses the spawn_agent gate."""

    async def test_direct_spawn_with_explicit_spec_tools_is_not_gated(self) -> None:
        """Host code building a SubagentSpec directly never touches this executor
        or ToolsetPolicy — orchestrator.spawn receives exactly what was set."""
        orch = _make_mock_orchestrator()
        trusted_tools = [
            ToolSpec(name="bash", description="bash", parameters={"type": "object"})
        ]
        spec = SubagentSpec(
            name="trusted-worker", system_prompt="p", tools=trusted_tools
        )

        await orch.spawn(spec, "task")

        called_spec: SubagentSpec = orch.spawn.call_args.args[0]
        assert called_spec.tools == trusted_tools
