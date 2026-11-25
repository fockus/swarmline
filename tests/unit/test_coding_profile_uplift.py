"""Tests for Task 0 — Config flags + propagation seam.

REQ-SCA-080, REQ-SCA-081.
TDD phase: tests written first, implementation follows.

Naming convention: test_<what>_<condition>_<result>
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from swarmline.runtime.thin.coding_profile import CodingProfileConfig


class TestCodingProfileConfigDefaultsPreserveLegacyBehaviour:
    """REQ-SCA-080: backward-compatible config extension.

    Old 2-field construction must still work identically.
    New fields must have off/neutral defaults.
    """

    def test_codingprofileconfig_defaults_preserve_legacy_behaviour(self) -> None:
        """CodingProfileConfig() (no kwargs) constructs with legacy fields at old defaults
        AND new fields at their off/neutral defaults.
        """
        cfg = CodingProfileConfig()

        # Legacy fields — unchanged defaults
        assert cfg.enabled is True
        assert cfg.allow_host_execution is True

        # New fields — off/neutral defaults
        assert cfg.edit_strategy == "legacy"
        assert cfg.enable_repo_map_ranking is False
        assert cfg.enable_post_edit_verify is False
        assert cfg.enable_lsp_verify is False
        assert cfg.enable_edit_guards is False
        assert cfg.enable_git_checkpoints is False
        assert cfg.max_reflections == 3
        assert cfg.repo_map_max_tokens == 4000

    def test_codingprofileconfig_2arg_legacy_construction_still_works(self) -> None:
        """CodingProfileConfig(enabled=False, allow_host_execution=False) still valid."""
        cfg = CodingProfileConfig(enabled=False, allow_host_execution=False)

        assert cfg.enabled is False
        assert cfg.allow_host_execution is False
        # New fields still at defaults
        assert cfg.edit_strategy == "legacy"
        assert cfg.enable_repo_map_ranking is False
        assert cfg.enable_post_edit_verify is False
        assert cfg.enable_lsp_verify is False
        assert cfg.enable_edit_guards is False
        assert cfg.enable_git_checkpoints is False
        assert cfg.max_reflections == 3
        assert cfg.repo_map_max_tokens == 4000

    def test_codingprofileconfig_still_frozen(self) -> None:
        """Extended config remains immutable (frozen=True)."""
        cfg = CodingProfileConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.edit_strategy = "patch"  # type: ignore[misc]

    def test_codingprofileconfig_still_dataclass(self) -> None:
        """CodingProfileConfig is still a proper frozen dataclass after extension."""
        assert dataclasses.is_dataclass(CodingProfileConfig)
        fields = {f.name for f in dataclasses.fields(CodingProfileConfig)}
        assert "enabled" in fields
        assert "allow_host_execution" in fields
        assert "edit_strategy" in fields
        assert "max_reflections" in fields
        assert "repo_map_max_tokens" in fields

    def test_codingprofileconfig_equality_still_value_based(self) -> None:
        """Two configs with same extended values are equal."""
        a = CodingProfileConfig()
        b = CodingProfileConfig()
        assert a == b

    def test_codingprofileconfig_new_fields_explicit_construction(self) -> None:
        """All new fields can be set explicitly."""
        cfg = CodingProfileConfig(
            enabled=True,
            allow_host_execution=True,
            edit_strategy="auto",
            enable_repo_map_ranking=True,
            enable_post_edit_verify=True,
            enable_lsp_verify=True,
            enable_edit_guards=True,
            enable_git_checkpoints=True,
            max_reflections=5,
            repo_map_max_tokens=8000,
        )
        assert cfg.edit_strategy == "auto"
        assert cfg.enable_repo_map_ranking is True
        assert cfg.enable_post_edit_verify is True
        assert cfg.enable_lsp_verify is True
        assert cfg.enable_edit_guards is True
        assert cfg.enable_git_checkpoints is True
        assert cfg.max_reflections == 5
        assert cfg.repo_map_max_tokens == 8000

    def test_codingprofileconfig_edit_strategy_literal_values(self) -> None:
        """All four edit_strategy literals are accepted."""
        for strategy in ("legacy", "search_replace", "patch", "auto"):
            cfg = CodingProfileConfig(edit_strategy=strategy)  # type: ignore[arg-type]
            assert cfg.edit_strategy == strategy


class TestAllFlagsOffNoNewToolsOrHooks:
    """REQ-SCA-080: with all flags OFF, build_coding_toolpack output is byte-identical.

    No new tools, no new hooks registered when config=None or all flags off.
    """

    def test_all_flags_off_no_new_tools_or_hooks(self, coding_sandbox: Any) -> None:
        """build_coding_toolpack(sandbox, config=CodingProfileConfig()) EQUALS
        build_coding_toolpack(sandbox) — identical tool names, identical executor
        key set, and identical normalized ToolSpec data per tool.

        Asserts on the EXACT key sets and full spec data (not just counts) so
        this regression would actually catch any byte-level drift introduced by
        flag-gated paths in Tasks 1-8 (B2 propagation seam).
        """
        from swarmline.runtime.thin.coding_toolpack import build_coding_toolpack

        pack_no_config = build_coding_toolpack(coding_sandbox)
        pack_all_off = build_coding_toolpack(
            coding_sandbox, config=CodingProfileConfig()
        )

        # Exact tool-name set parity (visible surface).
        assert pack_no_config.tool_names == pack_all_off.tool_names
        # Exact executor key-set parity (executable surface) — not just count.
        assert set(pack_no_config.executors.keys()) == set(
            pack_all_off.executors.keys()
        )

        # Normalized ToolSpec data must be identical per tool.
        def _normalize(specs: Any) -> dict[str, dict[str, Any]]:
            return {
                name: {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                    "is_local": spec.is_local,
                }
                for name, spec in specs.items()
            }

        assert _normalize(pack_no_config.specs) == _normalize(pack_all_off.specs)

    def test_config_none_identical_to_no_config(self, coding_sandbox: Any) -> None:
        """build_coding_toolpack(sandbox, config=None) identical to no-config call."""
        from swarmline.runtime.thin.coding_toolpack import build_coding_toolpack

        pack_implicit = build_coding_toolpack(coding_sandbox)
        pack_explicit_none = build_coding_toolpack(coding_sandbox, config=None)

        assert pack_implicit.tool_names == pack_explicit_none.tool_names
        assert len(pack_implicit.executors) == len(pack_explicit_none.executors)

    def test_no_multi_file_edit_in_legacy_mode(self, coding_sandbox: Any) -> None:
        """multi_file_edit is NOT in the toolpack when all flags are default (legacy)."""
        from swarmline.runtime.thin.coding_toolpack import build_coding_toolpack

        pack = build_coding_toolpack(coding_sandbox, config=CodingProfileConfig())
        assert "multi_file_edit" not in pack.tool_names

    def test_no_multi_file_edit_when_config_none(self, coding_sandbox: Any) -> None:
        """multi_file_edit is NOT in the toolpack when config=None."""
        from swarmline.runtime.thin.coding_toolpack import build_coding_toolpack

        pack = build_coding_toolpack(coding_sandbox, config=None)
        assert "multi_file_edit" not in pack.tool_names

    def test_create_sandbox_tools_accepts_config_param(
        self, coding_sandbox: Any
    ) -> None:
        """create_sandbox_tools now accepts keyword-only config param without error."""
        from swarmline.tools.builtin import create_sandbox_tools

        # Both calls must succeed without TypeError
        specs1, executors1 = create_sandbox_tools(coding_sandbox)
        specs2, executors2 = create_sandbox_tools(coding_sandbox, config=None)
        specs3, executors3 = create_sandbox_tools(
            coding_sandbox, config=CodingProfileConfig()
        )

        # All three produce the same tool set
        assert set(specs1.keys()) == set(specs2.keys()) == set(specs3.keys())
        assert (
            set(executors1.keys()) == set(executors2.keys()) == set(executors3.keys())
        )

    def test_build_coding_toolpack_accepts_config_kwarg(
        self, coding_sandbox: Any
    ) -> None:
        """build_coding_toolpack signature accepts keyword-only config param."""
        from swarmline.runtime.thin.coding_toolpack import build_coding_toolpack

        # config must be keyword-only — positional should fail
        with pytest.raises(TypeError):
            build_coding_toolpack(coding_sandbox, CodingProfileConfig())  # type: ignore[call-arg]

    def test_existing_8_sandbox_tools_present_with_config(
        self, coding_sandbox: Any
    ) -> None:
        """All 8 canonical sandbox tools still present with config kwarg."""
        from swarmline.runtime.thin.coding_toolpack import (
            CODING_SANDBOX_TOOL_NAMES,
            build_coding_toolpack,
        )

        pack = build_coding_toolpack(coding_sandbox, config=CodingProfileConfig())
        assert CODING_SANDBOX_TOOL_NAMES.issubset(pack.tool_names)


class TestRuntimeWiringPropagatesCodingProfile:
    """REQ-SCA-081: B2 propagation seam reaches the toolpack builder.

    build_portable_runtime_plan must thread the agent's coding_profile into
    build_coding_toolpack so flag-gated paths receive the same config the
    parent agent declared.
    """

    def test_runtime_wiring_passes_coding_profile_to_toolpack(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build_portable_runtime_plan passes AgentConfig.coding_profile as the
        config kwarg into build_coding_toolpack (patched where wiring resolves it).
        """
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.runtime.types import ToolSpec

        captured: dict[str, Any] = {}

        class _FakePack:
            specs = {
                "read": ToolSpec(name="read", description="d", parameters={}),
            }
            executors = {"read": (lambda args: "ok")}

        def _spy_build_coding_toolpack(
            _sandbox: Any, *, config: Any = None, todo_provider: Any = None
        ) -> Any:
            captured["config"] = config
            return _FakePack()

        # Patch where runtime_wiring resolves the symbol (lazy import target).
        monkeypatch.setattr(
            "swarmline.runtime.thin.coding_toolpack.build_coding_toolpack",
            _spy_build_coding_toolpack,
        )

        coding_profile = CodingProfileConfig(
            enabled=True,
            edit_strategy="search_replace",
            enable_repo_map_ranking=True,
        )
        agent_config = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            coding_profile=coding_profile,
        )

        build_portable_runtime_plan(agent_config, "thin")

        assert captured["config"] is coding_profile


class TestRuntimeWiringEditVerifyHooks:
    """REQ-SCA-030/031/032: the in-turn verify-loop must be reachable in prod.

    When enable_post_edit_verify is set, build_portable_runtime_plan must build
    an EditSnapshotCoordinator and register one Pre + one Post hook per edit/write
    tool name into the hook registry passed to the runtime. When the flag is off,
    the default path registers nothing (byte-identical legacy behaviour).
    """

    _EDIT_TOOLS = sorted(("edit", "write", "multi_edit", "multi_file_edit"))

    def _plan_for(self, tmp_path: Any, *, enable: bool) -> Any:
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        agent_config = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            coding_profile=CodingProfileConfig(
                enabled=True, enable_post_edit_verify=enable
            ),
        )
        return build_portable_runtime_plan(agent_config, "thin")

    def test_registers_edit_verify_hooks_when_enabled(self, tmp_path: Any) -> None:
        plan = self._plan_for(tmp_path, enable=True)
        registry = plan.create_kwargs.get("hook_registry")

        assert registry is not None
        pre = sorted(e.matcher for e in registry.get_hooks("PreToolUse"))
        post = sorted(e.matcher for e in registry.get_hooks("PostToolUse"))
        assert pre == self._EDIT_TOOLS
        assert post == self._EDIT_TOOLS

    def test_no_edit_verify_hooks_when_disabled(self, tmp_path: Any) -> None:
        plan = self._plan_for(tmp_path, enable=False)

        # No config hooks + flag off → the verify-loop adds no registry at all.
        assert plan.create_kwargs.get("hook_registry") is None

    def test_idempotent_and_does_not_mutate_user_registry(self, tmp_path: Any) -> None:
        """Repeated builds keep ONE edit-verify set and never mutate the user's
        registry (merge_hooks returns it by reference when there is exactly one).
        """
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.hooks.registry import HookRegistry

        async def _user_post(*, tool_name: str, tool_input: dict, tool_output: str):
            return None

        user_registry = HookRegistry()
        user_registry.on_post_tool_use(_user_post, matcher="read")

        agent_config = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            hooks=user_registry,
            coding_profile=CodingProfileConfig(
                enabled=True, enable_post_edit_verify=True
            ),
        )

        plan1 = build_portable_runtime_plan(agent_config, "thin")
        plan2 = build_portable_runtime_plan(agent_config, "thin")

        # User registry untouched: still only its single "read" Post hook.
        assert [e.matcher for e in user_registry.get_hooks("PostToolUse")] == ["read"]
        assert user_registry.get_hooks("PreToolUse") == []

        # Each build is idempotent and a FRESH registry (not the user object),
        # preserving the user hook plus exactly one edit-verify set.
        for plan in (plan1, plan2):
            reg = plan.create_kwargs["hook_registry"]
            assert reg is not user_registry
            pre = sorted(e.matcher for e in reg.get_hooks("PreToolUse"))
            post = sorted(e.matcher for e in reg.get_hooks("PostToolUse"))
            assert pre == self._EDIT_TOOLS
            assert post == sorted([*self._EDIT_TOOLS, "read"])


class TestRuntimeWiringEditGuardHooks:
    """REQ-SCA-050/051/052: anti-flailing guards + provenance must be wired in prod.

    When enable_edit_guards is set, build_portable_runtime_plan must register one
    Pre + one Post guard hook per edit/write tool name PLUS a provenance Post hook
    on read and bash — into a FRESH registry that never mutates AgentConfig.hooks.
    When the flag is off, the guard wiring registers nothing.
    """

    _EDIT_TOOLS = sorted(("edit", "write", "multi_edit", "multi_file_edit"))

    def _config(
        self, tmp_path: Any, *, enable: bool, native_config: dict | None = None
    ) -> Any:
        from swarmline.agent.config import AgentConfig

        return AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            native_config=native_config or {},
            coding_profile=CodingProfileConfig(enabled=True, enable_edit_guards=enable),
        )

    def test_registers_guard_hooks_when_enabled(self, tmp_path: Any) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = self._config(tmp_path, enable=True)
        plan = build_portable_runtime_plan(cfg, "thin")
        registry = plan.create_kwargs.get("hook_registry")

        assert registry is not None
        pre = sorted(e.matcher for e in registry.get_hooks("PreToolUse"))
        post = sorted(e.matcher for e in registry.get_hooks("PostToolUse"))
        # Pre: one guard per edit/write tool.
        assert pre == self._EDIT_TOOLS
        # Post: one guard per edit/write tool + provenance on read and bash.
        assert post == sorted([*self._EDIT_TOOLS, "read", "bash"])

    def test_no_guard_hooks_when_disabled(self, tmp_path: Any) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = self._config(tmp_path, enable=False)
        plan = build_portable_runtime_plan(cfg, "thin")
        assert plan.create_kwargs.get("hook_registry") is None

    def test_guards_idempotent_and_do_not_mutate_user_registry(
        self, tmp_path: Any
    ) -> None:
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.hooks.registry import HookRegistry

        async def _user_post(*, tool_name: str, tool_input: dict, tool_output: str):
            return None

        user_registry = HookRegistry()
        user_registry.on_post_tool_use(_user_post, matcher="grep")

        cfg = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            hooks=user_registry,
            coding_profile=CodingProfileConfig(enabled=True, enable_edit_guards=True),
        )

        plan1 = build_portable_runtime_plan(cfg, "thin")
        plan2 = build_portable_runtime_plan(cfg, "thin")

        # User registry untouched.
        assert [e.matcher for e in user_registry.get_hooks("PostToolUse")] == ["grep"]
        assert user_registry.get_hooks("PreToolUse") == []

        for plan in (plan1, plan2):
            reg = plan.create_kwargs["hook_registry"]
            assert reg is not user_registry
            pre = sorted(e.matcher for e in reg.get_hooks("PreToolUse"))
            post = sorted(e.matcher for e in reg.get_hooks("PostToolUse"))
            assert pre == self._EDIT_TOOLS
            assert post == sorted([*self._EDIT_TOOLS, "read", "bash", "grep"])

    def test_verify_and_guards_share_one_fresh_registry(self, tmp_path: Any) -> None:
        """Both verify + guards on → ONE fresh registry, user's untouched, idempotent."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.hooks.registry import HookRegistry

        async def _user_pre(*, tool_name: str, tool_input: dict):
            return None

        user_registry = HookRegistry()
        user_registry.on_pre_tool_use(_user_pre, matcher="glob")

        cfg = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            hooks=user_registry,
            coding_profile=CodingProfileConfig(
                enabled=True,
                enable_post_edit_verify=True,
                enable_edit_guards=True,
            ),
        )

        plan1 = build_portable_runtime_plan(cfg, "thin")
        plan2 = build_portable_runtime_plan(cfg, "thin")

        # User registry never mutated.
        assert [e.matcher for e in user_registry.get_hooks("PreToolUse")] == ["glob"]
        assert user_registry.get_hooks("PostToolUse") == []

        for plan in (plan1, plan2):
            reg = plan.create_kwargs["hook_registry"]
            assert reg is not user_registry
            pre = sorted(e.matcher for e in reg.get_hooks("PreToolUse"))
            post = sorted(e.matcher for e in reg.get_hooks("PostToolUse"))
            # Verify Pre (edit tools) + guard Pre (edit tools) + user "glob".
            assert pre == sorted([*self._EDIT_TOOLS, *self._EDIT_TOOLS, "glob"])
            # Verify Post (edit) + guard Post (edit) + provenance (read, bash).
            assert post == sorted(
                [*self._EDIT_TOOLS, *self._EDIT_TOOLS, "read", "bash"]
            )

    def test_guard_post_precedes_verify_post_for_edit_tools(
        self, tmp_path: Any
    ) -> None:
        """Both flags on → the guard Post hook is registered BEFORE the verify Post
        hook for each edit tool, so the guard parses the raw JSON outcome before
        verify appends its [verify] block (REQ-SCA-050)."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.runtime.thin.edit_guards import PostEditGuardHook
        from swarmline.runtime.thin.edit_verify_coordinator import (
            EditSnapshotCoordinator,
        )

        cfg = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            coding_profile=CodingProfileConfig(
                enabled=True,
                enable_post_edit_verify=True,
                enable_edit_guards=True,
            ),
        )
        reg = build_portable_runtime_plan(cfg, "thin").create_kwargs["hook_registry"]

        for tool in self._EDIT_TOOLS:
            callbacks = [
                e.callback for e in reg.get_hooks("PostToolUse") if e.matcher == tool
            ]
            guard_idx = next(
                i for i, cb in enumerate(callbacks) if isinstance(cb, PostEditGuardHook)
            )
            verify_idx = next(
                i
                for i, cb in enumerate(callbacks)
                if isinstance(getattr(cb, "__self__", None), EditSnapshotCoordinator)
            )
            assert guard_idx < verify_idx, (
                f"guard Post must precede verify Post for {tool!r} so it reads the "
                "raw edit outcome before verify annotates it"
            )


class TestRuntimeWiringCheckpointHooks:
    """REQ-SCA-060: enable_git_checkpoints must REACH EditCheckpointer in prod.

    When the flag is set AND a host supplies a git-backed WorkspaceSession +
    GitOperationsPort + OwnChangesTrackerPort via native_config, a PostToolUse
    checkpoint hook is registered per edit/write tool. Flag off, or any dep
    missing → nothing registered (skip silently, byte-identical default path).
    """

    _EDIT_TOOLS = sorted(("edit", "write", "multi_edit", "multi_file_edit"))

    def _git_native_config(self, tmp_path: Any) -> dict:
        from swarmline.workspace.git_local import LocalGitOperations
        from swarmline.workspace.mutation import OwnChangesTracker
        from swarmline.workspace.types import MutationMode, WorkspaceSession

        session = WorkspaceSession.create(
            session_id="sess-1",
            repo_root=str(tmp_path),
            branch="main",
            worktree_path=str(tmp_path),
            mutation_mode=MutationMode.AUTO_APPLY,
        )
        return {
            "git_operations": LocalGitOperations(),
            "workspace_session": session,
            "own_changes_tracker": OwnChangesTracker(),
        }

    def _plan(self, tmp_path: Any, *, enable: bool, native_config: dict) -> Any:
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            native_config=native_config,
            coding_profile=CodingProfileConfig(
                enabled=True, enable_git_checkpoints=enable
            ),
        )
        return build_portable_runtime_plan(cfg, "thin")

    def test_registers_checkpoint_hooks_when_enabled_with_git_deps(
        self, tmp_path: Any
    ) -> None:
        from swarmline.runtime.thin.edit_checkpointer import CheckpointPostHook

        plan = self._plan(
            tmp_path, enable=True, native_config=self._git_native_config(tmp_path)
        )
        reg = plan.create_kwargs.get("hook_registry")
        assert reg is not None
        cp_matchers = sorted(
            e.matcher
            for e in reg.get_hooks("PostToolUse")
            if isinstance(e.callback, CheckpointPostHook)
        )
        assert cp_matchers == self._EDIT_TOOLS

    def test_no_checkpoint_hooks_when_disabled(self, tmp_path: Any) -> None:
        plan = self._plan(
            tmp_path, enable=False, native_config=self._git_native_config(tmp_path)
        )
        # Flag off → the checkpoint block registers nothing (no other hooks here).
        assert plan.create_kwargs.get("hook_registry") is None

    def test_no_checkpoint_hooks_when_git_deps_missing(self, tmp_path: Any) -> None:
        # Flag ON but native_config has no git_operations/workspace_session → skip.
        plan = self._plan(tmp_path, enable=True, native_config={})
        assert plan.create_kwargs.get("hook_registry") is None


class TestRuntimeWiringLspVerifyHooks:
    """REQ-SCA-070/071/072: type-aware LSP verify must REACH prod via the flag.

    When enable_lsp_verify is set AND a host supplies a code-workspace
    WorkspaceSession via native_config, build_portable_runtime_plan registers a
    Pre + Post pyright-diagnostics hook per edit/write tool, into a FRESH registry
    that never mutates AgentConfig.hooks. Flag off, or the workspace seam missing →
    nothing registered (byte-identical default path — the GATE).
    """

    _EDIT_TOOLS = sorted(("edit", "write", "multi_edit", "multi_file_edit"))

    def _plan(self, tmp_path: Any, *, enable: bool, with_seam: bool) -> Any:
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.workspace.types import WorkspaceSession

        native_config: dict[str, Any] = {}
        if with_seam:
            native_config["workspace_session"] = WorkspaceSession.create(
                session_id="sess-1", repo_root=str(tmp_path), branch="main"
            )
        cfg = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            native_config=native_config,
            coding_profile=CodingProfileConfig(enabled=True, enable_lsp_verify=enable),
        )
        return build_portable_runtime_plan(cfg, "thin")

    @staticmethod
    def _lsp_matchers(registry: Any, event: str) -> list[str]:
        from swarmline.agent.lsp.coordinator import LspVerifyCoordinator

        return sorted(
            entry.matcher
            for entry in registry.get_hooks(event)
            if isinstance(
                getattr(entry.callback, "__self__", None), LspVerifyCoordinator
            )
        )

    def test_registers_lsp_hooks_when_enabled_with_seam(self, tmp_path: Any) -> None:
        plan = self._plan(tmp_path, enable=True, with_seam=True)
        registry = plan.create_kwargs.get("hook_registry")

        assert registry is not None
        assert self._lsp_matchers(registry, "PreToolUse") == self._EDIT_TOOLS
        assert self._lsp_matchers(registry, "PostToolUse") == self._EDIT_TOOLS

    def test_no_lsp_hooks_when_disabled(self, tmp_path: Any) -> None:
        plan = self._plan(tmp_path, enable=False, with_seam=True)
        # Flag off → the LSP block registers nothing (no other hooks here) → byte-id.
        # GATE: this includes NO Stop hook (registry is None ⇒ no events at all).
        assert plan.create_kwargs.get("hook_registry") is None

    def test_registers_lsp_stop_hook_when_enabled_with_seam(
        self, tmp_path: Any
    ) -> None:
        """ON + seam ⇒ exactly one Stop hook owned by the LSP coordinator.

        REQ: the per-(tenant,workspace) pyright processes the factory spins up must
        be reaped at run end — so the wiring registers a Stop hook that closes the
        factory. Without it, pyright subprocesses leak past the run.
        """
        from swarmline.agent.lsp.coordinator import LspVerifyCoordinator

        plan = self._plan(tmp_path, enable=True, with_seam=True)
        registry = plan.create_kwargs.get("hook_registry")

        assert registry is not None
        lsp_stop = [
            entry
            for entry in registry.get_hooks("Stop")
            if isinstance(
                getattr(entry.callback, "__self__", None), LspVerifyCoordinator
            )
        ]
        assert len(lsp_stop) == 1

    async def test_lsp_stop_hook_reaps_the_factory(self, tmp_path: Any) -> None:
        """Dispatching the registered Stop hook awaits the factory's close_all."""
        from unittest.mock import AsyncMock

        from swarmline.agent.lsp.coordinator import LspVerifyCoordinator

        plan = self._plan(tmp_path, enable=True, with_seam=True)
        registry = plan.create_kwargs["hook_registry"]
        stop_entry = next(
            entry
            for entry in registry.get_hooks("Stop")
            if isinstance(
                getattr(entry.callback, "__self__", None), LspVerifyCoordinator
            )
        )
        coordinator = stop_entry.callback.__self__
        spy = AsyncMock()
        coordinator._factory.close_all = spy

        await stop_entry.callback(result_text="done")

        spy.assert_awaited_once()

    def test_no_lsp_hooks_when_workspace_seam_absent(self, tmp_path: Any) -> None:
        # Flag ON but native_config has no workspace_session → skip silently.
        plan = self._plan(tmp_path, enable=True, with_seam=False)
        assert plan.create_kwargs.get("hook_registry") is None

    def test_lsp_composes_with_post_edit_verify(self, tmp_path: Any) -> None:
        """Both post-edit-verify and lsp-verify on → ONE fresh registry carrying
        BOTH the verify hooks and the LSP hooks (LSP copies existing entries)."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.runtime.thin.edit_verify_coordinator import (
            EditSnapshotCoordinator,
        )
        from swarmline.workspace.types import WorkspaceSession

        cfg = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            native_config={
                "workspace_session": WorkspaceSession.create(
                    session_id="sess-1", repo_root=str(tmp_path), branch="main"
                )
            },
            coding_profile=CodingProfileConfig(
                enabled=True,
                enable_post_edit_verify=True,
                enable_lsp_verify=True,
            ),
        )
        registry = build_portable_runtime_plan(cfg, "thin").create_kwargs[
            "hook_registry"
        ]

        # LSP Post hooks present per edit tool.
        assert self._lsp_matchers(registry, "PostToolUse") == self._EDIT_TOOLS
        # The T4 verify Post hooks survived the LSP copy into the fresh registry.
        verify_post = sorted(
            entry.matcher
            for entry in registry.get_hooks("PostToolUse")
            if isinstance(
                getattr(entry.callback, "__self__", None), EditSnapshotCoordinator
            )
        )
        assert verify_post == self._EDIT_TOOLS

    def test_lsp_does_not_mutate_user_registry(self, tmp_path: Any) -> None:
        """The user's HookRegistry is never mutated; each build is idempotent."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.hooks.registry import HookRegistry
        from swarmline.workspace.types import WorkspaceSession

        async def _user_post(*, tool_name: str, tool_input: dict, tool_output: str):
            return None

        user_registry = HookRegistry()
        user_registry.on_post_tool_use(_user_post, matcher="read")

        cfg = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            hooks=user_registry,
            native_config={
                "workspace_session": WorkspaceSession.create(
                    session_id="sess-1", repo_root=str(tmp_path), branch="main"
                )
            },
            coding_profile=CodingProfileConfig(enabled=True, enable_lsp_verify=True),
        )

        plan1 = build_portable_runtime_plan(cfg, "thin")
        plan2 = build_portable_runtime_plan(cfg, "thin")

        # User registry untouched: still only its single "read" Post hook.
        assert [e.matcher for e in user_registry.get_hooks("PostToolUse")] == ["read"]
        assert user_registry.get_hooks("PreToolUse") == []

        for plan in (plan1, plan2):
            reg = plan.create_kwargs["hook_registry"]
            assert reg is not user_registry
            assert self._lsp_matchers(reg, "PreToolUse") == self._EDIT_TOOLS
            post = sorted(e.matcher for e in reg.get_hooks("PostToolUse"))
            # LSP Post per edit tool + the preserved user "read" hook.
            assert post == sorted([*self._EDIT_TOOLS, "read"])
