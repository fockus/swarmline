"""Tests for swarmline.bootstrap.SwarmlineStack. Iteration 3: TDD tests for public integration API.
Testing Trophy: unit (factory output) + integration (real YAML fixtures)."""

from __future__ import annotations

from pathlib import Path

from swarmline.bootstrap import SwarmlineStack
from swarmline.config.role_router import RoleRouterConfig
from swarmline.config.role_skills import YamlRoleSkillsLoader
from swarmline.context import DefaultContextBuilder
from swarmline.policy import DefaultToolIdCodec, DefaultToolPolicy
from swarmline.policy.tool_selector import ToolBudgetConfig, ToolGroup
from swarmline.protocols import LocalToolResolver
from swarmline.routing import KeywordRoleRouter
from swarmline.runtime.factory import RuntimeFactory
from swarmline.runtime.model_policy import ModelPolicy
from swarmline.runtime.types import RuntimeConfig
from swarmline.skills import SkillRegistry


def _create_fixture_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a minimal fixture structure for SwarmlineStack."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    prompts_dir = project_root / "prompts"
    prompts_dir.mkdir()
    skills_dir = project_root / "skills"
    skills_dir.mkdir()

    # Minimal identity.md
    (prompts_dir / "identity.md").write_text("You are a helpful assistant.", encoding="utf-8")

    # Role skills YAML
    (prompts_dir / "role_skills.yaml").write_text(
        "default:\n  skills: []\n  local_tools: []\ncoach:\n  skills: []\n  local_tools: [calculate_goal_plan]\n",
        encoding="utf-8",
    )

    # Role router YAML
    (prompts_dir / "role_router.yaml").write_text(
        "default_role: default\nkeywords:\n  coach:\n    - помоги\n",
        encoding="utf-8",
    )

    return project_root, prompts_dir, skills_dir


class TestSwarmlineStackCreate:
    """SwarmlineStack.create() creates all library components."""

    def test_create_returns_all_components(self, tmp_path: Path) -> None:
        """create() returns SwarmlineStack with all components."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        stack = SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
        )

        assert isinstance(stack.skill_registry, SkillRegistry)
        assert isinstance(stack.context_builder, DefaultContextBuilder)
        assert isinstance(stack.role_skills_loader, YamlRoleSkillsLoader)
        assert isinstance(stack.role_router, KeywordRoleRouter)
        assert isinstance(stack.role_router_config, RoleRouterConfig)
        assert isinstance(stack.tool_policy, DefaultToolPolicy)
        assert isinstance(stack.tool_id_codec, DefaultToolIdCodec)
        assert isinstance(stack.model_policy, ModelPolicy)
        assert isinstance(stack.runtime_factory, RuntimeFactory)
        assert isinstance(stack.runtime_config, RuntimeConfig)
        assert stack.local_tool_resolver is None

    def test_role_router_config_loaded(self, tmp_path: Path) -> None:
        """Role router config loads from YAML."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        stack = SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
        )

        assert stack.role_router_config.default_role == "default"
        assert "coach" in stack.role_router_config.keywords

    def test_role_skills_loaded(self, tmp_path: Path) -> None:
        """RoleSkillsLoader loads skills and local_tools."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        stack = SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
        )

        assert stack.role_skills_loader.get_local_tools("coach") == ["calculate_goal_plan"]
        assert stack.role_skills_loader.get_skills("coach") == []

    def test_escalate_roles_passed_to_model_policy(self, tmp_path: Path) -> None:
        """escalate_roles is passed in ModelPolicy."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        stack = SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
            escalate_roles={"strategy_planner"},
        )

        assert isinstance(stack.model_policy, ModelPolicy)

    def test_missing_prompts_dir_graceful(self, tmp_path: Path) -> None:
        """Missing config files -> graceful defaults."""
        project_root = tmp_path / "empty"
        project_root.mkdir()
        prompts_dir = project_root / "prompts"
        prompts_dir.mkdir()
        skills_dir = project_root / "skills"
        skills_dir.mkdir()

        # Not role_skills.yaml, role_router.yaml - should be created without errors
        stack = SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
        )

        assert stack.role_router_config.default_role == "default"
        assert stack.role_skills_loader.get_skills("nonexistent") == []

    def test_accepts_runtime_config_and_local_tool_resolver(self, tmp_path: Path) -> None:
        """create() takes runtime_config and local_tool_resolver from app."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        class DummyResolver:
            def resolve(self, tool_name: str):  # pragma: no cover - smoke-only contract
                _ = tool_name
                return None

            def list_tools(self) -> list[str]:
                return []

        runtime_config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            base_url="https://example.test",
        )
        resolver = DummyResolver()
        stack = SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
            runtime_config=runtime_config,
            local_tool_resolver=resolver,
        )

        assert stack.runtime_config.runtime_name == "thin"
        assert stack.runtime_config.base_url == "https://example.test"
        assert stack.local_tool_resolver is resolver

    def test_memory_bank_prompt_autoloaded_when_provider_passed(self, tmp_path: Path) -> None:
        """When memory_bank_provider stack loads default_prompt.md."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        class DummyMemoryProvider:
            async def read_file(self, path: str) -> str | None:  # pragma: no cover - contract-only
                _ = path
                return None

        provider = DummyMemoryProvider()
        stack = SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
            memory_bank_provider=provider,
        )

        assert stack.memory_bank_provider is provider
        assert stack.memory_bank_prompt is not None
        assert "Memory Bank" in stack.memory_bank_prompt

    def test_tool_budget_config_applies_to_capability_tools(self, tmp_path: Path) -> None:
        """tool_budget_config really limits the set of capability tools."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        class _Sandbox:
            async def read_file(self, path: str):  # pragma: no cover - contract-only
                _ = path
                return ""

            async def write_file(self, path: str, content: str):  # pragma: no cover - contract-only
                _ = (path, content)
                return None

            async def execute(self, command: str):  # pragma: no cover - contract-only
                _ = command
                return None

            async def list_dir(self, path: str = "."):  # pragma: no cover - contract-only
                _ = path
                return []

            async def glob_files(self, pattern: str):  # pragma: no cover - contract-only
                _ = pattern
                return []

        class _Web:
            async def fetch(self, url: str):  # pragma: no cover - contract-only
                _ = url
                return ""

            async def search(self, query: str):  # pragma: no cover - contract-only
                _ = query
                return []

        budget = ToolBudgetConfig(
            max_tools=2,
            group_priority=[ToolGroup.WEB, ToolGroup.ALWAYS],
        )
        stack = SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
            sandbox_provider=_Sandbox(),
            web_provider=_Web(),
            thinking_enabled=True,
            tool_budget_config=budget,
        )

        assert len(stack.capability_specs) <= 2
        assert set(stack.capability_specs.keys()) <= {"web_fetch", "web_search", "thinking"}


class TestLocalToolResolverProtocol:
    """LocalToolResolver Protocol — contract tests."""

    def test_dummy_satisfies_protocol(self) -> None:
        """A simple implementation satisfies Protocol."""
        from collections.abc import Callable
        from typing import Any

        class DummyResolver:
            def resolve(self, tool_name: str) -> Callable[..., Any] | None:
                if tool_name == "my_tool":
                    return lambda **kwargs: "result"
                return None

            def list_tools(self) -> list[str]:
                return ["my_tool"]

        resolver = DummyResolver()
        assert resolver.list_tools() == ["my_tool"]
        assert resolver.resolve("my_tool") is not None
        assert resolver.resolve("unknown") is None

    def test_isp_2_methods(self) -> None:
        """LocalToolResolver has exactly 2 methods (ISP)."""
        methods = [n for n in dir(LocalToolResolver) if not n.startswith("_") and n != "register"]
        assert len(methods) == 2
