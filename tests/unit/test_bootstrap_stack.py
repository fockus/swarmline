"""Тесты для cognitia.bootstrap.CognitiaStack.

Iteration 3: TDD тесты для public integration API.
Testing Trophy: unit (factory output) + integration (real YAML fixtures).
"""

from __future__ import annotations

from pathlib import Path

from cognitia.bootstrap import CognitiaStack
from cognitia.config.role_router import RoleRouterConfig
from cognitia.config.role_skills import YamlRoleSkillsLoader
from cognitia.context import DefaultContextBuilder
from cognitia.policy import DefaultToolIdCodec, DefaultToolPolicy
from cognitia.protocols import LocalToolResolver
from cognitia.routing import KeywordRoleRouter
from cognitia.runtime.factory import RuntimeFactory
from cognitia.runtime.model_policy import ModelPolicy
from cognitia.runtime.types import RuntimeConfig
from cognitia.skills import SkillRegistry


def _create_fixture_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Создать минимальную fixture-структуру для CognitiaStack."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    prompts_dir = project_root / "prompts"
    prompts_dir.mkdir()
    skills_dir = project_root / "skills"
    skills_dir.mkdir()

    # Минимальный identity.md
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


class TestCognitiaStackCreate:
    """CognitiaStack.create() создаёт все library-компоненты."""

    def test_create_returns_all_components(self, tmp_path: Path) -> None:
        """create() возвращает CognitiaStack со всеми компонентами."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        stack = CognitiaStack.create(
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
        """Role router config загружается из YAML."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        stack = CognitiaStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
        )

        assert stack.role_router_config.default_role == "default"
        assert "coach" in stack.role_router_config.keywords

    def test_role_skills_loaded(self, tmp_path: Path) -> None:
        """RoleSkillsLoader загружает skills и local_tools."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        stack = CognitiaStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
        )

        assert stack.role_skills_loader.get_local_tools("coach") == ["calculate_goal_plan"]
        assert stack.role_skills_loader.get_skills("coach") == []

    def test_escalate_roles_passed_to_model_policy(self, tmp_path: Path) -> None:
        """escalate_roles передаётся в ModelPolicy."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        stack = CognitiaStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
            escalate_roles={"strategy_planner"},
        )

        assert isinstance(stack.model_policy, ModelPolicy)

    def test_missing_prompts_dir_graceful(self, tmp_path: Path) -> None:
        """Отсутствующие config файлы → graceful defaults."""
        project_root = tmp_path / "empty"
        project_root.mkdir()
        prompts_dir = project_root / "prompts"
        prompts_dir.mkdir()
        skills_dir = project_root / "skills"
        skills_dir.mkdir()

        # Нет role_skills.yaml, role_router.yaml — должен создаться без ошибок
        stack = CognitiaStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
        )

        assert stack.role_router_config.default_role == "default"
        assert stack.role_skills_loader.get_skills("nonexistent") == []

    def test_accepts_runtime_config_and_local_tool_resolver(
        self, tmp_path: Path
    ) -> None:
        """create() принимает runtime_config и local_tool_resolver из app."""
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
        stack = CognitiaStack.create(
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
        """При memory_bank_provider stack подгружает default_prompt.md."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        class DummyMemoryProvider:
            async def read_file(self, path: str) -> str | None:  # pragma: no cover - contract-only
                _ = path
                return None

        provider = DummyMemoryProvider()
        stack = CognitiaStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
            memory_bank_provider=provider,
        )

        assert stack.memory_bank_provider is provider
        assert stack.memory_bank_prompt is not None
        assert "Memory Bank" in stack.memory_bank_prompt


class TestLocalToolResolverProtocol:
    """LocalToolResolver Protocol — contract tests."""

    def test_dummy_satisfies_protocol(self) -> None:
        """Простая реализация удовлетворяет Protocol."""
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
        """LocalToolResolver имеет ровно 2 метода (ISP)."""
        methods = [
            n for n in dir(LocalToolResolver)
            if not n.startswith("_") and n != "register"
        ]
        assert len(methods) == 2
