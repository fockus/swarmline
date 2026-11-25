"""Shared wiring helpers for portable runtime entrypoints."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_dispatch import merge_hooks
from swarmline.agent.runtime_factory_port import (
    RuntimeFactoryPort,
    build_runtime_factory,
)
from swarmline.context.budget import DEFAULT_CONTEXT_WINDOW_TOKENS
from swarmline.runtime.cost import CostBudget
from swarmline.runtime.types import RuntimeConfig, ThinkingConfig, ToolSpec

_PORTABLE_MCP_RUNTIMES = frozenset({"thin", "deepagents", "openai_agents"})
# pi_sdk/temporal cannot host client-side MCP: forward mcp_servers anyway so
# the registry factory's documented fail-fast fires instead of a silent drop.
_FAIL_FAST_MCP_RUNTIMES = frozenset({"pi_sdk", "temporal"})


def _resolve_thinking_config(
    raw_thinking: dict[str, Any] | ThinkingConfig | None,
) -> ThinkingConfig | None:
    """Translate AgentConfig.thinking into the portable RuntimeConfig.thinking
    (I-098a).

    AgentConfig.__post_init__ always normalizes ``thinking`` into
    ``{"type": "enabled"|"adaptive"|"disabled", "budget_tokens": N}`` (or
    leaves it None); the typed ``ThinkingConfig`` case is handled too, in case
    a caller bypasses that normalization.

    Mirrors the capability validator's enabled/disabled semantics
    (``runtime/factory.py._validate_config_against_capabilities``, which
    treats any dict with ``type != "disabled"`` as enabled) so a value that
    passed capability validation as "enabled" is never silently dropped here
    -- only ``None`` and the explicit ``{"type": "disabled"}`` produce
    ``None``:

    - ``None`` -> None.
    - typed ``ThinkingConfig`` -> passthrough unchanged.
    - dict ``{"type": "disabled", ...}`` -> None.
    - dict ``{"type": "adaptive", ...}`` -> raises ValueError. Adaptive
      thinking is claude_sdk-specific (native SDK budget auto-tuning); the
      portable runtimes have no equivalent, so silently coercing it to a
      fixed default budget would misrepresent the request. Pass an explicit
      ``ThinkingConfig(budget_tokens=...)`` instead.
    - dict ``{"type": "enabled"|<missing>, "budget_tokens": N}`` ->
      ``ThinkingConfig(budget_tokens=N)``; missing/``None`` budget_tokens
      defaults to 10_000 (matching ``options_builder._resolve_thinking``'s
      default). ``N`` must be a plain ``int`` (``bool`` excluded, since
      ``bool`` is a ``int`` subclass in Python) and strictly positive,
      otherwise raises ValueError naming the offending value -- an unchecked
      non-int budget would otherwise crash pi_sdk's numeric comparison
      (``_thinking_level_from_runtime_config``) at run time instead of at
      config time.
    - any other ``type`` value -> raises ValueError (mirrors
      ``options_builder._resolve_thinking``'s unknown-type error).
    """
    if raw_thinking is None:
        return None
    if isinstance(raw_thinking, ThinkingConfig):
        return raw_thinking
    kind = raw_thinking.get("type", "enabled")
    if kind == "disabled":
        return None
    if kind == "adaptive":
        raise ValueError(
            "thinking={'type': 'adaptive'} is claude_sdk-specific (native SDK "
            "budget auto-tuning) and has no portable-runtime equivalent. Pass "
            "an explicit swarmline.runtime.types.ThinkingConfig(budget_tokens=...) "
            "instead."
        )
    if kind != "enabled":
        raise ValueError(
            f"Unknown thinking type: {kind!r}. Expected: 'enabled', 'adaptive', 'disabled'"
        )
    budget_tokens = raw_thinking.get("budget_tokens")
    if budget_tokens is None:
        return ThinkingConfig()
    if (
        isinstance(budget_tokens, bool)
        or not isinstance(budget_tokens, int)
        or budget_tokens <= 0
    ):
        raise ValueError(
            f"thinking.budget_tokens must be a positive int, got {budget_tokens!r}"
        )
    return ThinkingConfig(budget_tokens=budget_tokens)


async def _noop_lint(_content: str) -> tuple[str, ...]:
    """Default lint callable for the in-turn verify-loop: reports no errors.

    ponytail: no-op default keeps the verify-loop path live but silent. Inject a
    real ``async (content) -> tuple[str, ...]`` via
    ``native_config["coding_lint_callable"]`` to surface edit-introduced lint.
    """
    return ()


@dataclass(frozen=True)
class PortableRuntimePlan:
    """Portable runtime request assembled from AgentConfig."""

    config: RuntimeConfig
    create_kwargs: dict[str, Any]
    active_tools: list[ToolSpec]


def build_portable_runtime_plan(
    agent_config: AgentConfig,
    runtime_name: str,
    *,
    session_id: str | None = None,
    runtime_factory: RuntimeFactoryPort | None = None,
) -> PortableRuntimePlan:
    """Build RuntimeConfig/create kwargs for portable entrypoints."""
    factory = runtime_factory or build_runtime_factory()
    factory.validate_agent_config(agent_config)

    # I-098a fix round 2 (major finding): gate thinking translation on the
    # ACTUALLY resolved thinking_stream capability level for this runtime,
    # mirroring factory._validate_config_against_capabilities's own
    # `get_capabilities(...).resolve(config)` step -- NOT the static
    # per-runtime table, which would diverge: thin's thinking_stream is
    # itself conditional on the configured model's provider
    # (capabilities.py `_resolve_thin` narrows it to "none" for non-anthropic
    # providers), so only `.resolve(agent_config)` reproduces what the
    # validator actually checked.
    #
    # A runtime whose resolved level is "none" already had a chance to reject
    # `thinking` above: strict_capabilities=True (default) raised ValueError
    # there; strict_capabilities=False only warned-and-degraded. The
    # pre-I-098a baseline for that degrade path is DROP (thinking never
    # reached the portable plan at all for those runtimes) -- so this passes
    # thinking=None instead of letting `_resolve_thinking_config`'s stricter
    # adaptive/invalid-budget checks raise a second, unrelated ValueError on
    # an already-degraded runtime. Runtimes that DO have the capability keep
    # the loud validation unconditionally (no degrade path ever applies to
    # them, so this is a strict improvement, not a weakening).
    try:
        thinking_supported = (
            factory.get_capabilities(runtime_override=runtime_name)
            .resolve(agent_config)
            .level("thinking_stream")
            != "none"
        )
    except Exception:  # custom factories without v2 capabilities (may return
        # None or raise): keep the pre-I-098a baseline -- translate `thinking`
        # unconditionally; only a factory that RESOLVES to "none" degrades.
        thinking_supported = True
    resolved_thinking = (
        _resolve_thinking_config(agent_config.thinking) if thinking_supported else None
    )

    runtime_config = RuntimeConfig(
        runtime_name=runtime_name,
        max_model_retries=(
            agent_config.max_model_retries
            if agent_config.max_model_retries is not None
            else RuntimeConfig().max_model_retries
        ),
        model=factory.resolve_agent_model(agent_config),
        base_url=agent_config.base_url,
        api_key=agent_config.api_key,
        output_format=agent_config.output_format,
        output_type=agent_config.output_type,
        structured_mode=agent_config.structured_mode,
        structured_schema_name=agent_config.structured_schema_name,
        structured_strict=agent_config.structured_strict,
        request_options=agent_config.request_options,
        feature_mode=agent_config.feature_mode,
        required_capabilities=agent_config.require_capabilities,
        allow_native_features=agent_config.allow_native_features,
        native_config=dict(agent_config.native_config),
        use_native_tools=(
            agent_config.use_native_tools
            if agent_config.use_native_tools is not None
            else (
                agent_config.structured_mode in {"native", "auto"}
                or bool(agent_config.provider_tools)
            )
        ),
        provider_tools=agent_config.provider_tools,
        max_iterations=(
            agent_config.max_turns
            if agent_config.max_turns is not None
            else RuntimeConfig().max_iterations
        ),
        # AGR-074 (taskloom Sprint 1ce S3): hosts size the tool-call budget to
        # their turn budget; swarmline's default of 8 ends long runs early.
        max_tool_calls=_positive_int(
            agent_config.native_config.get("max_tool_calls"),
            RuntimeConfig().max_tool_calls,
        ),
        retry_policy=agent_config.retry_policy,
        # I-098a: thinking is already consumed generically by ThinRuntime
        # (thin/runtime.py) and derived into PiSdkOptions.thinking_level by
        # PiSdkRuntime; gated on the resolved thinking_stream capability
        # above (thinking_stream_level/resolved_thinking) so a degraded
        # runtime (thinking_stream == "none") never reaches
        # `_resolve_thinking_config`'s stricter loud checks.
        thinking=resolved_thinking,
        # I-098a: activates thin's existing CostTracker (thin/runtime.py) and
        # pi_sdk's native cost accounting; runtimes without cost_tracking
        # capability are already rejected above.
        cost_budget=(
            CostBudget(
                max_cost_usd=agent_config.max_budget_usd, action_on_exceed="error"
            )
            if agent_config.max_budget_usd is not None
            else None
        ),
    )
    if runtime_name == "deepagents":
        # resume_session_id (I-098a) takes precedence over the session_id
        # parameter: an explicit request to resume a specific conversation id
        # must win over whatever session the caller happens to be running in.
        thread_id = agent_config.resume_session_id or session_id
        if thread_id is not None:
            runtime_config.native_config = {
                **runtime_config.native_config,
                "thread_id": thread_id,
            }
    if runtime_name == "pi_sdk":
        # pi_sdk handles project instructions natively in the Node bridge:
        # forward the unified toggle so False actually disables the loader.
        pi_extra: dict[str, Any] = {
            **runtime_config.extra,
            "project_instructions": bool(agent_config.project_instructions),
        }
        if agent_config.resume_session_id is not None:
            # Documented fallback consumed by PiSdkOptions.resume_session_file
            # when the option itself is not set (pi_sdk/types.py, pi_sdk/runtime.py).
            pi_extra["pi_session_file"] = agent_config.resume_session_id
        if agent_config.env:
            # Subprocess runtime: merged into the bridge's env at launch time,
            # with explicit PiSdkOptions.env entries always winning for the
            # same key (see PiSdkRuntime._build_env_overrides).
            pi_extra["env"] = dict(agent_config.env)
        runtime_config.extra = pi_extra
    if runtime_name == "cli" and agent_config.env:
        # Subprocess runtime: forwarded into CliAgentRuntime's subprocess env,
        # with explicit CliConfig.env entries always winning for the same key
        # (see cli/runtime.py _build_subprocess_env).
        runtime_config.extra = {
            **runtime_config.extra,
            "env": dict(agent_config.env),
        }

    create_kwargs: dict[str, Any] = {
        "tool_executors": {
            tool_definition.name: tool_definition.handler
            for tool_definition in agent_config.tools
        }
    }
    if runtime_name in _PORTABLE_MCP_RUNTIMES and agent_config.mcp_servers:
        create_kwargs["mcp_servers"] = agent_config.mcp_servers
    elif runtime_name in _FAIL_FAST_MCP_RUNTIMES and agent_config.mcp_servers:
        create_kwargs["mcp_servers"] = agent_config.mcp_servers

    if agent_config.runtime_options is not None:
        _apply_runtime_options(
            runtime_name, agent_config.runtime_options, create_kwargs
        )

    # Merge hooks from config + middleware for portable runtimes
    merged_hooks = merge_hooks(agent_config.hooks, agent_config.middleware)
    if merged_hooks is not None:
        create_kwargs["hook_registry"] = merged_hooks

    # Tool policy enforcement
    if agent_config.tool_policy is not None:
        create_kwargs["tool_policy"] = agent_config.tool_policy

    # can_use_tool permission callback (I-098b): thin ONLY, like
    # subagent_config/coding_profile below -- other portable runtime
    # constructors (deepagents/openai_agents/pi_sdk/cli/temporal) do not
    # accept this kwarg. Setting can_use_tool on a runtime without the
    # "permissions" capability already raises ValueError above in
    # `factory.validate_agent_config` (capabilities.py: only claude_sdk and
    # thin declare "permissions" != "none"), so this branch is unreachable
    # for the other runtimes by the time we get here.
    if runtime_name == "thin" and agent_config.can_use_tool is not None:
        create_kwargs["can_use_tool"] = agent_config.can_use_tool

    # Subagent configuration
    if runtime_name == "thin" and agent_config.subagent_config is not None:
        subagent_config = agent_config.subagent_config
        if subagent_config.base_path is None:
            if agent_config.cwd is None:
                raise ValueError(
                    "AgentConfig.cwd is required when subagent_config is enabled. "
                    "Set cwd to a git repository path so worktree isolation can be initialized."
                )
            subagent_config = replace(subagent_config, base_path=agent_config.cwd)
        create_kwargs["subagent_config"] = subagent_config

    # Command registry
    if agent_config.command_registry is not None:
        create_kwargs["command_registry"] = agent_config.command_registry

    active_tools = [
        tool_definition.to_tool_spec() for tool_definition in agent_config.tools
    ]

    # Coding profile: inject coding tool pack + policy scope (after active_tools built)
    if (
        runtime_name == "thin"
        and agent_config.coding_profile is not None
        and agent_config.coding_profile.enabled
    ):
        from swarmline.context.coding_input_filter import CodingContextInputFilter
        from swarmline.policy.tool_policy import DefaultToolPolicy
        from swarmline.runtime.thin.coding_toolpack import (
            CODING_TOOL_NAMES,
            build_coding_toolpack,
        )
        from swarmline.tools.sandbox_local import LocalSandboxProvider
        from swarmline.tools.types import SandboxConfig

        create_kwargs["coding_profile"] = agent_config.coding_profile

        # Build coding tool pack from a default sandbox
        cwd = agent_config.cwd
        if cwd is None:
            raise ValueError(
                "AgentConfig.cwd is required when coding_profile is enabled. "
                "Set cwd to the working directory for the coding agent."
            )
        sandbox_config = SandboxConfig(
            root_path=cwd,
            user_id="coding",
            topic_id="agent",
            allow_host_execution=agent_config.coding_profile.allow_host_execution,
        )
        sandbox = LocalSandboxProvider(sandbox_config)
        coding_pack = build_coding_toolpack(sandbox, config=agent_config.coding_profile)

        # Add coding tool specs to active tools
        for spec in coding_pack.specs.values():
            active_tools.append(spec)

        # Add coding tool executors to create_kwargs
        existing_executors = create_kwargs.get("tool_executors", {})
        existing_executors.update(coding_pack.executors)
        create_kwargs["tool_executors"] = existing_executors

        # Build/merge policy: coding tools allowed + any existing policy
        coding_allowed = set(CODING_TOOL_NAMES)
        # When the ranked repo-map is enabled, the code-intel tools are wired into
        # the pack (Task 3) — admit them so they are actually callable.
        if agent_config.coding_profile.enable_repo_map_ranking:
            from swarmline.runtime.thin.coding_toolpack import (
                CODING_CODE_INTEL_TOOL_NAMES,
            )

            coding_allowed = coding_allowed | set(CODING_CODE_INTEL_TOOL_NAMES)
        # Lazy skill tool (RCA Task 6, REQ-RCA-040): admit read_skill in policy
        # when the flag is on.  Off → byte-identical (tool never registered).
        if agent_config.coding_profile.enable_lazy_skills:
            coding_allowed = coding_allowed | {"read_skill"}
        if isinstance(agent_config.tool_policy, DefaultToolPolicy):
            coding_allowed = coding_allowed | set(
                agent_config.tool_policy.allowed_system_tools
            )
        create_kwargs["tool_policy"] = DefaultToolPolicy(
            allowed_system_tools=coding_allowed,
        )

        # Lazy skill tool — wire read_skill executor + spec (RCA Task 6).
        # Only when enable_lazy_skills=True AND a registry is supplied via
        # native_config["skill_registry"].  Off OR no registry → nothing added
        # (byte-identical to pre-Task-6 behaviour, REQ-RCA-070).
        if agent_config.coding_profile.enable_lazy_skills:
            _skill_reg = agent_config.native_config.get("skill_registry")
            if _skill_reg is not None:
                from swarmline.skills.skill_tool import create_skill_read_tool

                _read_spec, _read_executor = create_skill_read_tool(_skill_reg)
                active_tools.append(_read_spec)
                create_kwargs["tool_executors"]["read_skill"] = _read_executor

        # Git checkpoints (Task 7, REQ-SCA-060): when enable_git_checkpoints AND a
        # host supplies a git-backed WorkspaceSession + GitOperationsPort +
        # OwnChangesTrackerPort via native_config, register a PostToolUse hook that
        # commits a checkpoint after a SUCCESSFUL edit. Registered FIRST — before the
        # guard and verify blocks below — so it reads the RAW edit JSON before any
        # hook annotates it. The dispatcher chains PostToolUse output; the guard's
        # Post hook APPENDS churn/escalation hints, which would make a later json
        # parse fail. CheckpointPostHook never modifies tool_output (returns None),
        # so registering it first leaves the guard registered after it still
        # observing the raw outcome too. (_edit_succeeded also tolerates a trailing
        # annotation via raw_decode, covering any host-supplied modifying post hook.)
        # Missing deps → nothing registered; a non-git session → checkpoint() no-ops
        # (skip silently, DoD). Same FRESH-registry discipline; flag off → byte-identical.
        if agent_config.coding_profile.enable_git_checkpoints:
            cp_git = agent_config.native_config.get("git_operations")
            cp_session = agent_config.native_config.get("workspace_session")
            cp_tracker = agent_config.native_config.get("own_changes_tracker")
            if cp_git is not None and cp_session is not None and cp_tracker is not None:
                from swarmline.hooks.registry import HookRegistry
                from swarmline.runtime.thin.edit_checkpointer import (
                    EditCheckpointer,
                    register_edit_checkpoint_hooks,
                )

                checkpoint_registry = HookRegistry()
                existing_registry = create_kwargs.get("hook_registry")
                if existing_registry is not None:
                    for event_name in existing_registry.list_events():
                        for entry in existing_registry.get_hooks(event_name):
                            checkpoint_registry._add(
                                event_name, entry.callback, entry.matcher
                            )
                register_edit_checkpoint_hooks(
                    checkpoint_registry,
                    checkpointer=EditCheckpointer(cp_git, cp_tracker, sandbox),
                    session=cp_session,
                    config=agent_config.coding_profile,
                )
                create_kwargs["hook_registry"] = checkpoint_registry

        # Anti-flailing guards + provenance (Task 6): registered BEFORE the verify
        # loop (below) so the guard's Post hook observes the RAW edit-executor JSON
        # outcome. The dispatcher chains PostToolUse output; if verify ran first it
        # would append a "[verify]" block, the guard's json.loads would then fail,
        # and a successful (or failed) edit would record NO outcome — leaving
        # consecutive_failures unreset near the hard cap (REQ-SCA-050). Fresh-registry
        # discipline: NEVER mutate AgentConfig.hooks — merge_hooks returns the
        # user-owned registry by reference when there is exactly one, so copy any
        # existing entries into a FRESH registry and add ours. Idempotent across
        # repeated builds (the source registry is only ever read, never mutated).
        if agent_config.coding_profile.enable_edit_guards:
            from swarmline.hooks.registry import HookRegistry
            from swarmline.runtime.thin.edit_guards import (
                EditGuardState,
                register_edit_guard_hooks,
            )

            guard_registry = HookRegistry()
            existing_registry = create_kwargs.get("hook_registry")
            if existing_registry is not None:
                for event_name in existing_registry.list_events():
                    for entry in existing_registry.get_hooks(event_name):
                        guard_registry._add(event_name, entry.callback, entry.matcher)
            guard_tracker = agent_config.native_config.get("own_changes_tracker")
            guard_state = EditGuardState.with_defaults()
            register_edit_guard_hooks(
                guard_registry,
                state=guard_state,
                tracker=guard_tracker,
                session_id=session_id,
                config=agent_config.coding_profile,
            )
            create_kwargs["hook_registry"] = guard_registry

        # In-turn verify-loop (T4): when enable_post_edit_verify, register the
        # Pre/Post edit-snapshot hooks so edit-introduced lint surfaces mid-turn.
        # Registered AFTER the guard block so the guard's Post hook reads the raw
        # outcome first; verify's Post hook then appends its "[verify]" feedback onto
        # whatever it receives. Same fresh-registry discipline: copy existing entries
        # (incl. any guard hooks) into a FRESH registry, add ours, never mutate
        # AgentConfig.hooks — keeping repeated builds idempotent.
        if agent_config.coding_profile.enable_post_edit_verify:
            from swarmline.hooks.registry import HookRegistry
            from swarmline.orchestration.lint_delta import BaselineSubtractionLinter
            from swarmline.runtime.thin.edit_verify_coordinator import (
                EditSnapshotCoordinator,
                register_edit_verify_hooks,
            )
            from swarmline.runtime.thin.reflection import ReflectionState

            lint_callable = agent_config.native_config.get("coding_lint_callable")
            if not callable(lint_callable):
                lint_callable = _noop_lint
            verify_registry = HookRegistry()
            existing_registry = create_kwargs.get("hook_registry")
            if existing_registry is not None:
                for event_name in existing_registry.list_events():
                    for entry in existing_registry.get_hooks(event_name):
                        verify_registry._add(event_name, entry.callback, entry.matcher)
            # Per-run reflection budget (Task 5): bounds how long edit-introduced
            # verify failures keep being fed back before a terminal note finalizes.
            reflection = ReflectionState(
                max_reflections=agent_config.coding_profile.max_reflections
            )
            register_edit_verify_hooks(
                verify_registry,
                EditSnapshotCoordinator(
                    sandbox,
                    delta_linter=BaselineSubtractionLinter(lint_callable),
                    reflection=reflection,
                ),
                agent_config.coding_profile,
            )
            create_kwargs["hook_registry"] = verify_registry

        # Type-aware LSP verify (Task 8, REQ-SCA-070/071/072): when enable_lsp_verify
        # AND a host supplies a code-workspace WorkspaceSession via native_config,
        # register a Pre/Post pyright-diagnostics hook per edit tool. The Pre hook
        # snapshots baseline diagnostics on a persistent per-(tenant,workspace) pyright
        # session; the Post hook surfaces edit-introduced type errors via the gated
        # `lsp` criterion. Registered AFTER the T4 verify block so its [verify] lint
        # feedback is read first; the LSP Post hook then appends its own [lsp] block.
        # Same FRESH-registry discipline: copy existing entries (incl. guard/verify
        # hooks) into a FRESH registry, never mutate AgentConfig.hooks — idempotent
        # across repeated builds. Flag off OR the workspace seam absent → nothing
        # registered (byte-identical default path, the GATE).
        if agent_config.coding_profile.enable_lsp_verify:
            lsp_session = agent_config.native_config.get("workspace_session")
            if lsp_session is not None:
                from swarmline.agent.lsp import PyrightSessionFactory
                from swarmline.agent.lsp.coordinator import (
                    LspVerifyCoordinator,
                    register_lsp_verify_hooks,
                )
                from swarmline.hooks.registry import HookRegistry

                lsp_tenant = agent_config.native_config.get("lsp_tenant_id")
                lsp_workspace = agent_config.native_config.get("lsp_workspace_id")
                tenant_id = (
                    lsp_tenant
                    if isinstance(lsp_tenant, str) and lsp_tenant
                    else "default"
                )
                workspace_id = (
                    lsp_workspace
                    if isinstance(lsp_workspace, str) and lsp_workspace
                    else str(getattr(lsp_session, "session_id", "default"))
                )
                lsp_registry = HookRegistry()
                existing_registry = create_kwargs.get("hook_registry")
                if existing_registry is not None:
                    for event_name in existing_registry.list_events():
                        for entry in existing_registry.get_hooks(event_name):
                            lsp_registry._add(event_name, entry.callback, entry.matcher)
                # Named local: the SAME factory the coordinator uses is reaped by
                # the Stop hook register_lsp_verify_hooks installs, so the pyright
                # processes it spins up never survive past run end (DoD).
                lsp_factory = PyrightSessionFactory()
                register_lsp_verify_hooks(
                    lsp_registry,
                    LspVerifyCoordinator(
                        factory=lsp_factory,
                        session=lsp_session,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        config=agent_config.coding_profile,
                    ),
                    agent_config.coding_profile,
                )
                create_kwargs["hook_registry"] = lsp_registry

        board_context = agent_config.native_config.get("coding_board_context")
        search_context = agent_config.native_config.get("coding_search_context")
        skill_profile_text = agent_config.native_config.get("coding_skill_profile")
        session_store = agent_config.native_config.get("task_session_store")
        session_agent_id = agent_config.native_config.get(
            "task_session_agent_id", "coding"
        )
        budget_tokens_raw = agent_config.native_config.get(
            "coding_context_budget_tokens", 2000
        )
        # Fix-cycle 1 (M-3, codex round 1, Stage 3): the skill-listing budget
        # ratio (SKILL_LISTING_BUDGET_RATIO) is only correct relative to the
        # model's ACTUAL context window -- the constructor default (200_000)
        # is a reasonable fallback, not a universal truth. Same generic
        # passthrough convention as coding_context_budget_tokens above.
        # Stage 4 (context-engineering-manus-parity): shared with
        # tool_result_offload.py's own native_config["context_window_tokens"]
        # read via the SAME DEFAULT_CONTEXT_WINDOW_TOKENS constant -- two
        # differently-named keys (different subsystems/layers), one literal
        # default, never independently drifting.
        context_window_tokens_raw = agent_config.native_config.get(
            "coding_context_window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS
        )
        if skill_profile_text is None:
            skill_profile_text = (
                "Coding profile enabled. "
                f"allow_host_execution={agent_config.coding_profile.allow_host_execution}"
            )
        # Per-model-family edit-format steering (Task 2). Only when edit_strategy
        # is "auto": resolve the model's family → format and append the guidance to
        # the coding brief. Unknown family → neutral → empty brief → no append, so
        # any non-"auto" strategy (incl. the legacy default) stays byte-identical.
        if agent_config.coding_profile.edit_strategy == "auto":
            from swarmline.runtime.thin.edit_format_policy import (
                EditFormatPolicy,
                steering_brief,
            )

            fmt = EditFormatPolicy.default().format_for(runtime_config.model or "")
            brief = steering_brief(fmt)
            if brief:
                skill_profile_text = f"{skill_profile_text}\n\n{brief}"
        runtime_config = replace(
            runtime_config,
            input_filters=[
                *runtime_config.input_filters,
                CodingContextInputFilter(
                    workspace_cwd=cwd,
                    board_text=board_context if isinstance(board_context, str) else "",
                    search_text=search_context
                    if isinstance(search_context, str)
                    else "",
                    skill_profile_text=str(skill_profile_text),
                    task_session_store=session_store,
                    task_session_agent_id=(
                        str(session_agent_id)
                        if isinstance(session_agent_id, str)
                        else "coding"
                    ),
                    task_session_task_id=session_id,
                    budget_tokens=(
                        int(budget_tokens_raw)
                        if isinstance(budget_tokens_raw, (int, float))
                        else 2000
                    ),
                    # Lazy skill loading (RCA Task 6): thread flag + registry so the
                    # filter can produce names-only profile when the flag is on.
                    skill_registry=agent_config.native_config.get("skill_registry"),
                    lazy_skills=agent_config.coding_profile.enable_lazy_skills,
                    context_window_tokens=(
                        int(context_window_tokens_raw)
                        if isinstance(context_window_tokens_raw, (int, float))
                        else DEFAULT_CONTEXT_WINDOW_TOKENS
                    ),
                ),
            ],
        )

        # LLM-initiated child agents need the same sandbox template so the
        # worker runtime can rebind coding tools to a per-worktree sandbox.
        runtime_subagent_cfg = create_kwargs.get("subagent_config")
        if (
            runtime_subagent_cfg is not None
            and getattr(runtime_subagent_cfg, "sandbox_config", None) is None
        ):
            create_kwargs["subagent_config"] = replace(
                runtime_subagent_cfg,
                sandbox_config=sandbox_config,
            )

    # Stage 5 (context-engineering-manus-parity): plan/todo recitation by
    # cadence of human turns -- generic (NOT gated on coding_profile, unlike
    # CodingContextInputFilter above). Opt-in via
    # native_config["recitation_plan_text"]; absent/blank is a hard no-op
    # (byte-identical to pre-Stage-5 behaviour -- RecitationInputFilter isn't
    # even constructed).
    recitation_plan_text_raw = agent_config.native_config.get("recitation_plan_text")
    if isinstance(recitation_plan_text_raw, str) and recitation_plan_text_raw.strip():
        from swarmline.context.recitation_input_filter import (
            RECITATION_CADENCE,
            RecitationInputFilter,
        )

        recitation_summary_raw = agent_config.native_config.get(
            "recitation_plan_summary_text"
        )
        recitation_cadence_raw = agent_config.native_config.get(
            "recitation_cadence", RECITATION_CADENCE
        )
        runtime_config = replace(
            runtime_config,
            input_filters=[
                *runtime_config.input_filters,
                RecitationInputFilter(
                    plan_text=recitation_plan_text_raw,
                    plan_summary_text=(
                        recitation_summary_raw
                        if isinstance(recitation_summary_raw, str)
                        else None
                    ),
                    cadence=(
                        int(recitation_cadence_raw)
                        if isinstance(recitation_cadence_raw, (int, float))
                        else RECITATION_CADENCE
                    ),
                ),
            ],
        )

    # Stage 6 (context-engineering-manus-parity), Ступень B: compaction
    # cascade -- generic opt-in via native_config["compaction_enabled"].
    # ConversationCompactionFilter + CompactionConfig were already a
    # complete, self-contained primitive (RuntimeConfig.compaction, consumed
    # unconditionally in ThinRuntime._run_impl); this block only closes the
    # composition-root wiring gap (same shape as BL-77 for tool_result_
    # offload) so a caller can opt in via native_config instead of hand-
    # building RuntimeConfig. Absent/falsy is a hard no-op -- runtime_config.
    # compaction stays None, byte-identical to pre-Stage-6 behaviour.
    if agent_config.native_config.get("compaction_enabled") is True:
        from swarmline.compaction import CompactionConfig

        _default_compaction = CompactionConfig()
        threshold_raw = agent_config.native_config.get("compaction_threshold_tokens")
        window_raw = agent_config.native_config.get("compaction_context_window_tokens")
        reserve_raw = agent_config.native_config.get(
            "compaction_max_output_reserve_tokens"
        )
        preserve_raw = agent_config.native_config.get(
            "compaction_preserve_recent_pairs"
        )
        compactable_tools_raw = agent_config.native_config.get(
            "compaction_compactable_tool_names"
        )
        # BL-81: Ступень A (Tier-0 hash-dedup) was the one CompactionConfig knob
        # with no native_config key, so a host could reach it only by hand-building
        # CompactionConfig. Same defensive shape as the other knobs -- a
        # wrong-typed value falls back to the conservative default (False) rather
        # than silently adding a tier.
        dedup_raw = agent_config.native_config.get("compaction_dedup_enabled")
        # Sprint 1ce: optional "## Context Recovery" summary section (a host
        # emits it only when the run has a recovery tool such as history_search).
        recovery_hint_raw = agent_config.native_config.get("compaction_recovery_hint")
        # Sprint 1ce CE-9: compaction before every model round (opt-in).
        per_round_raw = agent_config.native_config.get("compaction_per_round")
        hysteresis_raw = agent_config.native_config.get(
            "compaction_round_hysteresis_tokens"
        )
        runtime_config = replace(
            runtime_config,
            compaction=CompactionConfig(
                threshold_tokens=(
                    int(threshold_raw)
                    if isinstance(threshold_raw, (int, float))
                    else _default_compaction.threshold_tokens
                ),
                context_window_tokens=(
                    int(window_raw) if isinstance(window_raw, (int, float)) else None
                ),
                max_output_reserve_tokens=(
                    int(reserve_raw)
                    if isinstance(reserve_raw, (int, float))
                    else _default_compaction.max_output_reserve_tokens
                ),
                preserve_recent_pairs=(
                    int(preserve_raw)
                    if isinstance(preserve_raw, (int, float))
                    else _default_compaction.preserve_recent_pairs
                ),
                compactable_tool_names=(
                    frozenset(compactable_tools_raw)
                    if isinstance(compactable_tools_raw, (list, tuple, set, frozenset))
                    else _default_compaction.compactable_tool_names
                ),
                dedup_enabled=(
                    dedup_raw
                    if isinstance(dedup_raw, bool)
                    else _default_compaction.dedup_enabled
                ),
                recovery_hint=(
                    recovery_hint_raw
                    if isinstance(recovery_hint_raw, str) and recovery_hint_raw
                    else None
                ),
                per_round=(
                    per_round_raw
                    if isinstance(per_round_raw, bool)
                    else _default_compaction.per_round
                ),
                round_hysteresis_tokens=(
                    int(hysteresis_raw)
                    if isinstance(hysteresis_raw, (int, float))
                    and not isinstance(hysteresis_raw, bool)
                    else _default_compaction.round_hysteresis_tokens
                ),
            ),
        )

    return PortableRuntimePlan(
        config=runtime_config,
        create_kwargs=create_kwargs,
        active_tools=active_tools,
    )


def _positive_int(raw: Any, default: int) -> int:
    """``raw`` as a positive int (floats truncated), else ``default``; bool is not a number."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 1:
        return default
    return int(raw)


def _apply_runtime_options(
    runtime_name: str,
    runtime_options: Any,
    create_kwargs: dict[str, Any],
) -> None:
    """Map typed runtime options into factory kwargs."""
    if runtime_name == "pi_sdk":
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        if not isinstance(runtime_options, PiSdkOptions):
            raise ValueError(
                "runtime='pi_sdk' expects runtime_options=PiSdkOptions(...)"
            )
        create_kwargs["pi_options"] = runtime_options
        return

    if runtime_name == "cli":
        from swarmline.runtime.cli.types import CliConfig

        if not isinstance(runtime_options, CliConfig):
            raise ValueError("runtime='cli' expects runtime_options=CliConfig(...)")
        create_kwargs["cli_config"] = runtime_options
        return

    if runtime_name == "openai_agents":
        from swarmline.runtime.openai_agents.types import OpenAIAgentsConfig

        if not isinstance(runtime_options, OpenAIAgentsConfig):
            raise ValueError(
                "runtime='openai_agents' expects runtime_options=OpenAIAgentsConfig(...)"
            )
        create_kwargs["agents_config"] = runtime_options
        return

    raise ValueError(f"runtime_options are not supported for runtime='{runtime_name}'")
