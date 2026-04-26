"""SwarmlineStack - facade for quick initialization of library components.

Single assembly point: the application passes config/prompts/skills paths
and capability configs, then receives ready-to-wire components.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

from swarmline.config.role_router import RoleRouterConfig, load_role_router_config
from swarmline.config.role_skills import YamlRoleSkillsLoader
from swarmline.context import DefaultContextBuilder
from swarmline.policy import DefaultToolIdCodec, DefaultToolPolicy
from swarmline.policy.tool_selector import ToolBudgetConfig
from swarmline.protocols import LocalToolResolver
from swarmline.routing import KeywordRoleRouter
from swarmline.runtime.factory import RuntimeFactory
from swarmline.runtime.model_policy import ModelPolicy
from swarmline.runtime.types import RuntimeConfig, ToolSpec
from swarmline.skills import SkillRegistry
from swarmline.skills.loader import YamlSkillLoader


@dataclass
class SwarmlineStack:
    """A ready-made set of library components for the application.

    Created via SwarmlineStack.create() - the single factory.
    Capability tools are assembled automatically and exposed through capability_specs/executors.
    """

    skill_registry: SkillRegistry
    context_builder: DefaultContextBuilder
    role_skills_loader: YamlRoleSkillsLoader
    role_router: KeywordRoleRouter
    role_router_config: RoleRouterConfig
    tool_policy: DefaultToolPolicy
    tool_id_codec: DefaultToolIdCodec
    model_policy: ModelPolicy
    runtime_factory: RuntimeFactory
    runtime_config: RuntimeConfig
    local_tool_resolver: LocalToolResolver | None
    # Capability tools - merged from all enabled capabilities
    capability_specs: dict[str, ToolSpec] = field(default_factory=dict)
    capability_executors: dict[str, Callable] = field(default_factory=dict)
    memory_bank_provider: Any | None = None
    memory_bank_prompt: str | None = None
    tool_budget_config: ToolBudgetConfig | None = None

    @classmethod
    def create(
        cls,
        *,
        prompts_dir: Path,
        skills_dir: Path,
        project_root: Path,
        escalate_roles: set[str] | None = None,
        runtime_config: RuntimeConfig | None = None,
        local_tool_resolver: LocalToolResolver | None = None,
        # --- Capability configs ---
        sandbox_provider: Any | None = None,
        web_provider: Any | None = None,
        todo_provider: Any | None = None,
        memory_bank_provider: Any | None = None,
        memory_bank_prompt: str | None = None,
        plan_manager: Any | None = None,
        plan_user_id: str = "",
        plan_topic_id: str = "",
        thinking_enabled: bool = True,
        allowed_system_tools: set[str] | None = None,
        tool_budget_config: ToolBudgetConfig | None = None,
    ) -> SwarmlineStack:
        """Create all library components from config paths.

        Args:
            prompts_dir: Directory with prompts.
            skills_dir: Directory with skills.
            project_root: Project root.
            escalate_roles: Roles for model escalation.
            runtime_config: Runtime config.
            local_tool_resolver: App-level resolver for local tools.
            sandbox_provider: SandboxProvider for builtin tools.
            web_provider: WebProvider for web tools.
            todo_provider: TodoProvider for todo tools.
            memory_bank_provider: MemoryBankProvider for memory tools.
            memory_bank_prompt: Prompt instruction for Memory Bank (P_MEMORY layer).
            plan_manager: PlanManager for planning tools.
            plan_user_id: user_id for the plan namespace.
            plan_topic_id: topic_id for the plan namespace.
            thinking_enabled: Enable the thinking tool.
            allowed_system_tools: Whitelist for system tools in ToolPolicy.
            tool_budget_config: Tool budget configuration.

        Returns:
            SwarmlineStack with ready-to-use components.
        """
        # Skills
        skill_loader = YamlSkillLoader(skills_dir, project_root=project_root)
        loaded_skills = skill_loader.load_all()
        skill_registry = SkillRegistry(
            loaded_skills,
            settings_mcp=skill_loader.settings_mcp_servers,
        )

        # Context
        context_builder = DefaultContextBuilder(prompts_dir)

        # Role config
        role_skills_loader = YamlRoleSkillsLoader(
            prompts_dir / "role_skills.yaml",
        )
        router_config = load_role_router_config(
            prompts_dir / "role_router.yaml",
        )
        role_router = KeywordRoleRouter(
            default_role=router_config.default_role,
            keyword_map=router_config.keywords,
        )

        # Policy - with system tool whitelist
        tool_id_codec = DefaultToolIdCodec()
        tool_policy = DefaultToolPolicy(
            codec=tool_id_codec,
            allowed_system_tools=allowed_system_tools,
        )

        # Model policy
        model_policy = ModelPolicy(
            escalate_roles=escalate_roles or set(),
        )

        # Runtime factory
        runtime_factory = RuntimeFactory()
        runtime_cfg = runtime_config or RuntimeConfig()

        # Capability tools - collect from enabled capabilities
        from swarmline.bootstrap.capabilities import collect_capability_tools

        cap_specs, cap_executors = collect_capability_tools(
            sandbox_provider=sandbox_provider,
            web_provider=web_provider,
            todo_provider=todo_provider,
            memory_bank_provider=memory_bank_provider,
            plan_manager=plan_manager,
            plan_user_id=plan_user_id,
            plan_topic_id=plan_topic_id,
            thinking_enabled=thinking_enabled,
            tool_budget_config=tool_budget_config,
        )

        if memory_bank_prompt is None and memory_bank_provider is not None:
            default_prompt_path = files("swarmline.memory_bank").joinpath(
                "default_prompt.md"
            )
            try:
                memory_bank_prompt = default_prompt_path.read_text(encoding="utf-8")
            except OSError:
                memory_bank_prompt = None

        return cls(
            skill_registry=skill_registry,
            context_builder=context_builder,
            role_skills_loader=role_skills_loader,
            role_router=role_router,
            role_router_config=router_config,
            tool_policy=tool_policy,
            tool_id_codec=tool_id_codec,
            model_policy=model_policy,
            runtime_factory=runtime_factory,
            runtime_config=runtime_cfg,
            local_tool_resolver=local_tool_resolver,
            capability_specs=cap_specs,
            capability_executors=cap_executors,
            memory_bank_provider=memory_bank_provider,
            memory_bank_prompt=memory_bank_prompt,
            tool_budget_config=tool_budget_config,
        )
