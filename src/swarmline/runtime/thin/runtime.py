"""Runtime module."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from functools import partial
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmline.commands.registry import CommandRegistry
    from swarmline.compaction import ConversationCompactionFilter
    from swarmline.governance.protocols import SecretBoundaryPort
    from swarmline.hooks.dispatcher import HookDispatcher
    from swarmline.hooks.registry import HookRegistry
    from swarmline.multi_agent.workspace import ExecutionWorkspace
    from swarmline.policy.tool_policy import DefaultToolPolicy
    from swarmline.policy.toolset_policy import ToolsetPolicy
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig
    from swarmline.runtime.thin.native_tools import NativeToolCallAdapter

from swarmline.observability.redaction import redact_secrets
from swarmline.runtime.cost import CostTracker, load_pricing
from swarmline.runtime.thin.builtin_tools import create_thin_builtin_tools
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.executor import CanUseToolCallback, ToolExecutor
from swarmline.runtime.thin.helpers import _should_buffer_postprocessing
from swarmline.runtime.thin.llm_client import default_llm_call
from swarmline.runtime.thin.kernels import get_default_kernel_registry
from swarmline.runtime.thin.round_context import build_round_context_refresher
from swarmline.runtime.thin.usage import (
    begin_native_usage_scope,
    end_native_usage_scope,
)
from swarmline.runtime.thin.runtime_support import (
    _JournalTappingAsyncIterator,
    auto_wrap_retriever,
    budget_exceeded_event,
    cancelled_event,
    extract_last_user_text,
    make_default_llm_call,
    run_guardrails,
    wrap_user_llm_call,
    wrap_with_event_bus,
)
from swarmline.runtime.structured_requests import resolve_structured_request_strategy
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)
from swarmline.types import KernelContext


class ThinRuntime:
    """Thin Runtime implementation."""

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        llm_call: Callable[..., Any] | None = None,
        local_tools: dict[str, Callable[..., Any]] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        sandbox: Any | None = None,
        hook_registry: HookRegistry | None = None,
        tool_policy: DefaultToolPolicy | None = None,
        subagent_config: Any | None = None,
        coding_profile: CodingProfileConfig | None = None,
        workspace: ExecutionWorkspace | None = None,
        command_registry: CommandRegistry | None = None,
        native_adapter: NativeToolCallAdapter | None = None,
        toolset_policy: ToolsetPolicy | None = None,
        spawn_role: str = "default",
        current_depth: int = 0,
        secret_boundary: SecretBoundaryPort | None = None,
        can_use_tool: CanUseToolCallback | None = None,
    ) -> None:
        self._config = config or RuntimeConfig(runtime_name="thin")
        self._command_registry = command_registry
        # REQ-ORC-040/041/042/043: spawn-time toolset scoping + real recursion
        # depth for LLM-initiated `spawn_agent` calls. All three default to the
        # pre-existing legacy values (None / "default" / 0) so byte-identical
        # behavior holds for every caller that does not opt in.
        self._toolset_policy = toolset_policy
        self._spawn_role = spawn_role
        # Fail fast on a negative depth (fix-cycle 2, MINOR-3): a negative
        # current_depth would silently reset/bypass the depth-guard in
        # create_subagent_executor (current_depth >= max_depth never trips).
        if current_depth < 0:
            raise ValueError(
                f"ThinRuntime current_depth must be >= 0, got {current_depth}"
            )
        self._current_depth = current_depth
        # REQ-ORC-044 (fix-cycle 2): scans an untrusted child's return across
        # ALL THREE exit paths — spawn_agent foreground JSON, monitor_agent
        # JSON, and the orchestrator's background-complete event/callback
        # (threaded into ThinSubagentOrchestrator below). Default None
        # preserves legacy raw passthrough.
        self._secret_boundary = secret_boundary
        self._auto_wrap_retriever()
        self._retry_events: list[RuntimeEvent] = []
        if llm_call is not None:
            raw_llm_call = self._wrap_user_llm_call(llm_call)
        else:
            raw_llm_call = self._make_default_llm_call()
        if self._config.event_bus is not None:
            raw_llm_call = self._wrap_with_event_bus(raw_llm_call)
        self._llm_call = raw_llm_call

        # --- Weak-model compaction adapter (REQ-RCA-010, RCA Task 2) ---
        # Build a one-shot aux llm_call that targets the weak model declared in
        # models.yaml for the active main model.  Only constructed when:
        #   (a) coding_profile is set and enable_model_tiering is True, AND
        #   (b) the active model declares a weak_model in models.yaml.
        # When None (default), ConversationCompactionFilter gets llm_call=None —
        # byte-identical to the pre-Task-2 construction (REQ-RCA-070).
        self._compaction_llm_call: Callable[..., Any] | None = None
        if coding_profile is not None and coding_profile.enable_model_tiering:
            from swarmline.runtime.model_settings import (
                ModelSettingsResolver,
                build_aux_llm_call,
            )

            _settings = ModelSettingsResolver().resolve(self._config.model)
            if _settings.weak_model_name is not None:
                self._compaction_llm_call = build_aux_llm_call(
                    raw_llm_call,
                    self._config,
                    _settings.weak_model_name,
                )
        if self._compaction_llm_call is None:
            # codex R1 [6 MAJOR]: Tier 2 (LLM summarization) must not be
            # gated EXCLUSIVELY on coding_profile.enable_model_tiering -- a
            # caller who wants Stage 6's compaction cascade (Ступень B)
            # without the coding-agent model-tiering machinery would
            # otherwise never get a working Tier 2 at all, only Tier 0/1/3.
            # Opt-in via native_config["compaction_llm_model"] (a plain
            # model name string), fully decoupled from coding_profile.
            # Absent/blank is a hard no-op — byte-identical to before this.
            _compaction_model_override = self._config.native_config.get(
                "compaction_llm_model"
            )
            if (
                isinstance(_compaction_model_override, str)
                and _compaction_model_override.strip()
            ):
                from swarmline.runtime.model_settings import build_aux_llm_call

                self._compaction_llm_call = build_aux_llm_call(
                    raw_llm_call,
                    self._config,
                    _compaction_model_override,
                )

        # --- Architect mode (REQ-RCA-011/012, RCA Task 3) ---
        # Store the resolved editor model name when enable_architect=True AND the
        # active model declares an editor_model in models.yaml.
        # When None (default), run() takes the normal react path — byte-identical.
        self._architect_editor_model: str | None = None
        if coding_profile is not None and coding_profile.enable_architect:
            from swarmline.runtime.model_settings import ModelSettingsResolver

            _arch_settings = ModelSettingsResolver().resolve(self._config.model)
            if _arch_settings.editor_model_name is not None:
                self._architect_editor_model = _arch_settings.editor_model_name

        # Hook dispatch (optional)
        self._hook_dispatcher = self._build_hook_dispatcher(hook_registry)

        # Merge user local_tools with sandbox built-in executors
        merged_local_tools = dict(local_tools or {})
        _builtin_specs, builtin_executors = create_thin_builtin_tools(sandbox)
        self._builtin_specs = _builtin_specs
        for name, executor in builtin_executors.items():
            # User tools take priority over built-ins
            if name not in merged_local_tools:
                merged_local_tools[name] = executor

        # Subagent tool wiring (spawn_agent + monitor_agent)
        self._subagent_tool_spec: ToolSpec | None = None
        self._monitor_agent_tool_spec: ToolSpec | None = None
        self._subagent_orchestrator: Any | None = None
        self._subagent_config_obj: Any | None = None
        self._bg_events: list[RuntimeEvent] = []
        if subagent_config is not None:
            from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
            from swarmline.runtime.thin.subagent_tool import (
                MONITOR_AGENT_TOOL_SPEC,
                SUBAGENT_TOOL_SPEC,
                create_monitor_executor,
                create_subagent_executor,
            )

            async def _on_bg_complete(event: RuntimeEvent) -> None:
                self._bg_events.append(event)

            base_path = getattr(subagent_config, "base_path", None)
            max_worktrees = int(getattr(subagent_config, "max_worktrees", 5))
            background_timeout = getattr(subagent_config, "background_timeout", None)
            workspace_impl = workspace
            if workspace_impl is None and base_path is not None:
                from swarmline.multi_agent.workspace import LocalWorkspace

                workspace_impl = LocalWorkspace(event_bus=self._config.event_bus)

            self._subagent_orchestrator = ThinSubagentOrchestrator(
                max_concurrent=subagent_config.max_concurrent,
                max_worktrees=max_worktrees,
                base_path=base_path,
                workspace=workspace_impl,
                llm_call=raw_llm_call,
                local_tools=merged_local_tools,
                mcp_servers=mcp_servers,
                runtime_config=self._config,
                coding_profile=coding_profile,
                tool_policy=tool_policy,
                hook_registry=hook_registry,
                can_use_tool=can_use_tool,
                on_background_complete=_on_bg_complete,
                background_timeout=background_timeout,
                secret_boundary=self._secret_boundary,
            )
            self._subagent_config_obj = subagent_config
            # Initial executor with builtin specs only; run() updates with actual active_tools
            initial_tool_specs = list(_builtin_specs.values())
            subagent_executor = create_subagent_executor(
                self._subagent_orchestrator,
                subagent_config,
                initial_tool_specs,
                current_depth=self._current_depth,
                toolset_policy=self._toolset_policy,
                spawn_role=self._spawn_role,
                secret_boundary=self._secret_boundary,
            )
            merged_local_tools["spawn_agent"] = subagent_executor
            self._subagent_tool_spec = SUBAGENT_TOOL_SPEC

            monitor_executor = create_monitor_executor(
                self._subagent_orchestrator, secret_boundary=self._secret_boundary
            )
            merged_local_tools["monitor_agent"] = monitor_executor
            self._monitor_agent_tool_spec = MONITOR_AGENT_TOOL_SPEC

        self._executor = ToolExecutor(
            local_tools=merged_local_tools,
            mcp_servers=mcp_servers,
            hook_dispatcher=self._hook_dispatcher,
            tool_policy=tool_policy,
            can_use_tool=can_use_tool,
        )

        # MCP resource tool spec (expose to LLM when mcp_servers are configured)
        self._mcp_resource_tool_spec: ToolSpec | None = None
        if mcp_servers:
            from swarmline.runtime.thin.executor import READ_MCP_RESOURCE_SPEC

            self._mcp_resource_tool_spec = READ_MCP_RESOURCE_SPEC

        # Native tool calling adapter (stored for use_native_tools opt-in)
        self._native_adapter: Any | None = None
        if llm_call is None and self._config.use_native_tools:
            # Using default adapter-based call — store adapter for native tools
            try:
                from swarmline.runtime.provider_resolver import resolve_provider
                from swarmline.runtime.thin.llm_providers import get_cached_adapter
                from swarmline.runtime.thin.native_tools import (
                    NativeToolCallAdapter as _NativeToolCallAdapter,
                )

                provider = resolve_provider(
                    self._config.model,
                    base_url=self._config.base_url,
                    api_key=self._config.api_key,
                )
                adapter = get_cached_adapter(provider)
                if isinstance(adapter, _NativeToolCallAdapter):
                    self._native_adapter = adapter
            except Exception as exc:
                import logging

                logging.getLogger(__name__).warning(
                    "Failed to create native tool adapter, will fall back to JSON-in-text (%s): %s",
                    type(exc).__name__,
                    redact_secrets(str(exc)),
                    extra={"exc_type": type(exc).__name__},
                )

        # User-supplied native adapter takes precedence over the auto-resolved one.
        # None default preserves existing behaviour byte-identical (backward-compat guard).
        if native_adapter is not None:
            self._native_adapter = native_adapter

        # Cost tracking
        self._cost_tracker: CostTracker | None = None
        if self._config.cost_budget is not None:
            self._cost_tracker = CostTracker(
                budget=self._config.cost_budget,
                pricing=load_pricing(),
            )

    @staticmethod
    def _build_hook_dispatcher(
        hook_registry: HookRegistry | None,
    ) -> HookDispatcher | None:
        """Build HookDispatcher from HookRegistry if provided."""
        if hook_registry is None:
            return None
        from swarmline.hooks.dispatcher import DefaultHookDispatcher

        return DefaultHookDispatcher(hook_registry)

    def _auto_wrap_retriever(self) -> None:
        """Auto-wrap config.retriever into input_filters if not already present."""
        auto_wrap_retriever(self._config)

    @staticmethod
    def _wrap_user_llm_call(user_fn: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a user-provided llm_call to accept (and forward) the ``config`` kwarg.

        User callables that already accept ``config`` get it as-is.
        Legacy callables that don't accept ``config`` have it silently stripped
        so existing code keeps working without modification.
        """
        return wrap_user_llm_call(user_fn)

    def _make_default_llm_call(self) -> Callable[..., Any]:
        """Make default llm call.

        Returns a callable that accepts an optional ``config`` keyword.
        When provided, the per-call config is forwarded to ``default_llm_call``
        instead of the constructor config, enabling per-call model/provider overrides.
        """
        return make_default_llm_call(self._config, default_llm_call)

    def _wrap_with_event_bus(self, llm_call: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap LLM call with EventBus emit for LLM_call_start/LLM_call_end.

        Forwards the ``config`` keyword so that per-call overrides reach the
        underlying ``llm_call`` and event metadata reflects the actual model.
        """
        return wrap_with_event_bus(llm_call, self._config)

    def cancel(self) -> None:
        """Cancel the current operation via CancellationToken."""
        if self._config.cancellation_token is not None:
            self._config.cancellation_token.cancel()

    async def __aenter__(self) -> ThinRuntime:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Exit async context manager - calls cleanup()."""
        await self.cleanup()

    def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run.

        Returns the mode dispatch / react loop's event stream (``_run_impl``).

        REQ-014: a plain (non-generator) function so the ``event_journal=None``
        path can return ``_run_impl``'s async generator UNWRAPPED -- byte-
        identical to the pre-tap behaviour, with zero added frames and
        ``aclose``/``athrow``/``asend`` reaching ``_run_impl`` exactly as
        before (an ``async def ... yield``-based wrapper here would instead
        defer ``aclose`` finalization to GC and intercept ``athrow`` before it
        reaches ``_run_impl``'s real suspension point -- not byte-identical).

        REQ-007/015: when ``effective_config.event_journal`` is set, the
        stream is wrapped in ``_JournalTappingAsyncIterator``, which taps every
        yielded ``RuntimeEvent`` into the journal as a side-channel while fully
        forwarding ``asend``/``athrow``/``aclose`` to ``_run_impl`` -- a broken
        journal can never interrupt the run (see ``journal_tap``).
        """
        effective_config = config or self._config
        inner = self._run_impl(
            messages=messages,
            system_prompt=system_prompt,
            active_tools=active_tools,
            config=config,
            mode_hint=mode_hint,
        )
        journal = effective_config.event_journal
        if journal is None:
            return inner
        return _JournalTappingAsyncIterator(inner, journal)

    async def _run_impl(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncGenerator[RuntimeEvent, None]:
        """Run the mode dispatch / react loop (see ``run`` for the journal tap)."""
        effective_config = config or self._config
        start_time = time.monotonic()
        tracker = self._cost_tracker
        # The run keeps its own native-usage totals; a run nested inside a tool of
        # another run (same task, same ContextVar) must not wipe or consume the
        # parent's totals, so the caller's totals are restored when this run ends.
        usage_scope = begin_native_usage_scope()
        try:
            cancelled_event = self._cancelled_event(effective_config.cancellation_token)
            if cancelled_event is not None:
                yield cancelled_event
                return

            # Pre-call budget check
            if tracker is not None and tracker.check_budget() == "exceeded":
                yield self._budget_exceeded_event(
                    tracker, prefix="Cost budget exceeded before call"
                )
                return

            try:
                resolve_structured_request_strategy(effective_config)
            except ValueError as exc:
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="capability_unsupported",
                        message=str(exc),
                        recoverable=False,
                        details={"model": effective_config.model},
                    )
                )
                return

            user_text = self._extract_last_user_text(messages)

            # --- Built-in tool specs: feature_mode controls exposure (plan E2) ---
            # portable (default): built-ins stay hidden unless the caller passes
            # them in active_tools; hybrid/native_first (or allow_native_features)
            # expose the sandbox built-ins automatically, user tools winning on
            # name collisions.
            if self._builtin_specs:
                from swarmline.runtime.thin.builtin_tools import (
                    filter_thin_builtins_by_mode,
                    merge_tools_with_builtins,
                )

                effective_mode = effective_config.feature_mode
                if (
                    effective_config.allow_native_features
                    and effective_mode == "portable"
                ):
                    effective_mode = "hybrid"
                exposed_builtins = filter_thin_builtins_by_mode(
                    list(self._builtin_specs.values()), feature_mode=effective_mode
                )
                if exposed_builtins:
                    active_tools = merge_tools_with_builtins(
                        active_tools, exposed_builtins, feature_mode=effective_mode
                    )

            # --- MCP resource tool: append spec to active_tools ---
            if self._mcp_resource_tool_spec is not None:
                active_tools = [*active_tools, self._mcp_resource_tool_spec]

            # --- Subagent tool: append spec to active_tools + update executor with full tool list ---
            if self._subagent_tool_spec is not None:
                active_tools = [*active_tools, self._subagent_tool_spec]
            if self._monitor_agent_tool_spec is not None:
                active_tools = [*active_tools, self._monitor_agent_tool_spec]
                # Update executor with actual active_tools for correct tool inheritance
                if (
                    self._subagent_orchestrator is not None
                    and self._subagent_config_obj is not None
                ):
                    from swarmline.runtime.thin.subagent_tool import (
                        create_subagent_executor,
                    )

                    updated_executor = create_subagent_executor(
                        self._subagent_orchestrator,
                        self._subagent_config_obj,
                        active_tools,
                        current_depth=self._current_depth,
                        toolset_policy=self._toolset_policy,
                        spawn_role=self._spawn_role,
                        secret_boundary=self._secret_boundary,
                    )
                    self._executor._local_tools["spawn_agent"] = updated_executor

            # --- UserPromptSubmit hook ---
            if self._hook_dispatcher is not None:
                transformed = await self._hook_dispatcher.dispatch_user_prompt(
                    user_text
                )
                if transformed != user_text:
                    user_text = transformed
                    if messages and messages[-1].role == "user":
                        messages = list(messages)
                        messages[-1] = Message(role="user", content=user_text)

            # --- Command intercept ---
            # Only intercept single-line text starting with / that resolves to a registered command.
            # URLs, paths, and unknown /text pass through to LLM.
            if (
                self._command_registry is not None
                and self._command_registry.is_command(user_text)
                and "\n" not in user_text.strip()
            ):
                cmd_name, cmd_args = self._command_registry.parse_command(user_text)
                if self._command_registry.resolve(cmd_name) is not None:
                    cmd_result = await self._command_registry.execute(
                        cmd_name, args=cmd_args
                    )
                    yield RuntimeEvent.final(text=cmd_result)
                    if self._hook_dispatcher is not None:
                        await self._hook_dispatcher.dispatch_stop(
                            result_text=cmd_result
                        )
                        # --- RCA-Task 5: session.idle on command-intercept (end-of-turn) ---
                        await self._hook_dispatcher.dispatch_session_event(
                            "session.idle", {}
                        )
                    return

            # --- Input guardrails ---
            if effective_config.input_guardrails:
                guard_error = await self._run_guardrails(
                    effective_config.input_guardrails,
                    user_text,
                    effective_config,
                )
                if guard_error is not None:
                    yield guard_error
                    return

            # --- Compaction filter (auto-created from config.compaction) ---
            # Kept for the react loop: per-round compaction (CE-9) reuses THIS
            # instance, so the anti-thrashing history is shared across rounds.
            compaction_filter: ConversationCompactionFilter | None = None
            if effective_config.compaction is not None:
                from swarmline.compaction import (
                    CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY,
                    ConversationCompactionFilter,
                    read_compression_history_checkpoint,
                )

                # Stage 6 anti-thrashing history is persisted through the SAME
                # OSS-T4 checkpoint substrate react_strategy.py's own
                # load-before-persist-block sites use (resilience/checkpoint.py).
                # This filter is constructed fresh every run() call (unlike the
                # react loop, this step runs once, before run_react() starts), so
                # the prior value must be loaded here explicitly rather than
                # carried on the instance.
                _cp_saved_for_compaction: dict[str, object] | None = None
                if (
                    effective_config.checkpoint_writer is not None
                    and effective_config.run_id
                ):
                    _cp_saved_for_compaction = (
                        await effective_config.checkpoint_writer.load(
                            effective_config.run_id
                        )
                    )
                _prior_compression_history = read_compression_history_checkpoint(
                    _cp_saved_for_compaction,
                    CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY,
                )

                compaction_filter = ConversationCompactionFilter(
                    config=effective_config.compaction,
                    llm_call=self._compaction_llm_call,
                    compression_history=_prior_compression_history,
                )
                messages, system_prompt = await compaction_filter.filter(
                    messages,
                    system_prompt,
                )

                # Merge-forward EVERYTHING already in _cp_saved_for_compaction
                # (e.g. a prior turn's _tool_schema_snapshot/_tool_result_offload)
                # before writing -- this write must never wipe state it doesn't
                # know about (the M-1-class bug: CheckpointWriter.save_checkpoint
                # fully REPLACES the stored dict, it does not merge). step/
                # total_steps are ROUND-TRIPPED from whatever was already saved
                # (never re-derived here) so this write can never regress the
                # actual resume position react_strategy.py tracks.
                if (
                    effective_config.checkpoint_writer is not None
                    and effective_config.run_id
                ):
                    from swarmline.resilience.checkpoint import (
                        CHECKPOINT_KEY_STEP,
                        CHECKPOINT_KEY_TOTAL,
                    )

                    _base_state = _cp_saved_for_compaction or {}
                    _preserved_step = _base_state.get(CHECKPOINT_KEY_STEP, 0)
                    _preserved_total = _base_state.get(
                        CHECKPOINT_KEY_TOTAL, effective_config.max_iterations
                    )
                    await effective_config.checkpoint_writer.after_tool_call(
                        run_id=effective_config.run_id,
                        step=(
                            _preserved_step if isinstance(_preserved_step, int) else 0
                        ),
                        total_steps=(
                            _preserved_total
                            if isinstance(_preserved_total, int)
                            else effective_config.max_iterations
                        ),
                        state={
                            **_base_state,
                            CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY: (
                                compaction_filter.compression_history
                            ),
                        },
                    )

                # --- RCA-Task 5: session.compacted event (opt-in, default noop) ---
                if self._hook_dispatcher is not None:
                    await self._hook_dispatcher.dispatch_session_event(
                        "session.compacted", {}
                    )

            # --- Input filters ---
            if effective_config.input_filters:
                for f in effective_config.input_filters:
                    messages, system_prompt = await f.filter(messages, system_prompt)

            # Resolve execution mode — explicit, else structural. No regex routing.
            # Priority: explicit (valid) mode_hint > tool-aware default (tools present
            # → react) > conversational. Whether to call a tool on a given turn is the
            # model's decision (native tool_choice=auto); we never guess the mode from
            # the user's wording. ``planner`` is reachable ONLY via mode_hint="planner".
            # FINDING 1: validated against the LIVE registry — not the import-time
            # -frozen VALID_MODES snapshot — so a kernel registered programmatically
            # (REQ-006) or via a 'swarmline.kernels' entry point (REQ-007) AFTER
            # import is still dispatchable by mode_hint.
            if (
                mode_hint is not None
                and mode_hint in get_default_kernel_registry().modes()
            ):
                mode = mode_hint
            elif active_tools:
                mode = "react"
            else:
                mode = "conversational"

            yield RuntimeEvent.status(f"Mode: {mode}")

            # Extended thinking warning for non-Anthropic models
            if effective_config.thinking is not None:
                from swarmline.runtime.provider_resolver import (
                    resolve_provider as _resolve,
                )

                _resolved = _resolve(
                    effective_config.model, base_url=effective_config.base_url
                )
                if _resolved.sdk_type != "anthropic":
                    yield RuntimeEvent.status(
                        "Warning: extended thinking is only supported for Anthropic models; "
                        f"'{effective_config.model}' uses {_resolved.provider}"
                    )

            # Flush any buffered retry events from previous calls
            self._retry_events.clear()
            buffered_postprocessing = _should_buffer_postprocessing(effective_config)
            emitted_text_delta = False
            last_result_text = ""

            async def checkpoint() -> RuntimeEvent | None:
                return self._cancelled_event(effective_config.cancellation_token)

            # Bind effective config into llm_call so strategies use the correct
            # model/provider without needing signature changes.
            llm_call: Callable[..., Any] = partial(
                self._llm_call, config=effective_config
            )

            # Collect events; intercept final for output guardrails
            try:
                strategy: AsyncIterator[RuntimeEvent]

                # Architect mode overrides the react kernel with a specialised
                # two-model strategy.  This is the only remaining mode-specific
                # branch; all other dispatch goes through the kernel registry.
                if mode == "react" and self._architect_editor_model is not None:
                    from swarmline.runtime.thin.architect import run_architect_strategy

                    strategy = run_architect_strategy(
                        raw_llm_call=self._llm_call,
                        executor=self._executor,
                        messages=messages,
                        system_prompt=system_prompt,
                        tools=active_tools,
                        base_config=effective_config,
                        start_time=start_time,
                        main_model=effective_config.model,
                        editor_model=self._architect_editor_model,
                        checkpoint=checkpoint,
                        on_retry=self._buffer_retry_status,
                        native_adapter=(
                            self._native_adapter
                            if effective_config.use_native_tools
                            else None
                        ),
                        session_dispatcher=self._hook_dispatcher,
                    )
                else:
                    # Registry-based dispatch (REQ-005).  KernelContext normalises
                    # the varying strategy signatures into a single call shape.
                    # session_dispatcher flows through KernelContext (REQ-002) so
                    # ReactKernelAdapter can pass it to run_react for file.edited
                    # session events.
                    ctx = KernelContext(
                        llm_call=llm_call,
                        messages=messages,
                        system_prompt=system_prompt,
                        config=effective_config,
                        start_time=start_time,
                        checkpoint=checkpoint,
                        executor=self._executor,
                        tools=active_tools,
                        on_retry=self._buffer_retry_status,
                        native_adapter=(
                            self._native_adapter
                            if effective_config.use_native_tools
                            else None
                        ),
                        session_dispatcher=self._hook_dispatcher,
                        external_signal=effective_config.external_signal,
                        # Sprint 1ce CE-9: None unless per-round compaction or a
                        # live plan provider is opted into (byte-identical off).
                        round_refresher=build_round_context_refresher(
                            effective_config, compaction_filter
                        ),
                    )
                    kernel = get_default_kernel_registry().get(mode)
                    strategy = kernel.run(ctx)

                # EventBus reference for emitting tool call events
                event_bus = effective_config.event_bus

                # --- RCA-Task 5 F1: track whether the strategy yielded a terminal
                # error event.  session.idle is suppressed on error paths so that
                # callers can distinguish a normal end-of-turn from an error turn.
                errored = False

                async for event in strategy:
                    if event.is_error:
                        errored = True
                    # --- Emit buffered retry status events ---
                    if self._retry_events:
                        for retry_evt in self._retry_events:
                            yield retry_evt
                        self._retry_events.clear()

                    # --- EventBus: emit tool call events ---
                    if event_bus is not None:
                        if event.type == "tool_call_started":
                            await event_bus.emit("tool_call_start", event.data)
                        elif event.type == "tool_call_finished":
                            await event_bus.emit("tool_call_end", event.data)

                    if event.type == "assistant_delta":
                        emitted_text_delta = True

                    # Track last result text for Stop hook
                    if event.is_final:
                        last_result_text = event.data.get("text", "")

                    if event.type in {
                        "assistant_delta",
                        "tool_call_started",
                        "tool_call_finished",
                        "final",
                    }:
                        cancelled_event = self._cancelled_event(
                            effective_config.cancellation_token
                        )
                        if cancelled_event is not None:
                            yield cancelled_event
                            return

                    # --- Cost tracking on final event ---
                    budget_status = "ok"
                    if event.is_final and tracker is not None:
                        usage = event.data.get("usage", {})
                        metrics = event.data.get("metrics", {})
                        tokens_in = int(
                            usage.get("input_tokens", metrics.get("tokens_in", 0)) or 0
                        )
                        tokens_out = int(
                            usage.get("output_tokens", metrics.get("tokens_out", 0))
                            or 0
                        )
                        model = metrics.get("model", effective_config.model)
                        tracker.record(model, tokens_in, tokens_out)
                        event.data["total_cost_usd"] = tracker.total_cost_usd
                        budget_status = tracker.check_budget()

                    # --- Output guardrails on final event ---
                    if event.is_final and effective_config.output_guardrails:
                        response_text = event.data.get("text", "")
                        guard_error = await self._run_guardrails(
                            effective_config.output_guardrails,
                            response_text,
                            effective_config,
                        )
                        if guard_error is not None:
                            yield guard_error
                            return

                    if event.is_final and tracker is not None:
                        if budget_status == "warning":
                            yield RuntimeEvent.status(
                                "Budget warning: "
                                f"${tracker.total_cost_usd:.4f} spent, "
                                f"{tracker.total_tokens} tokens used"
                            )
                        elif budget_status == "exceeded":
                            yield self._budget_exceeded_event(
                                tracker,
                                prefix="Cost budget exceeded after response",
                            )
                            return

                    if (
                        event.is_final
                        and buffered_postprocessing
                        and not emitted_text_delta
                        and event.data.get("text", "")
                    ):
                        yield RuntimeEvent.assistant_delta(str(event.data["text"]))
                        emitted_text_delta = True

                    # --- Drain pending background completion events ---
                    if self._bg_events:
                        for bg_evt in self._bg_events:
                            yield bg_evt
                        self._bg_events.clear()

                    yield event

                # --- Stop hook on normal/error completion; session.idle only on success ---
                # Contract: session.idle fires only when the turn reached a NORMAL terminal
                # state (main-loop success, command-intercept success).  Error events yielded
                # by the strategy and raised-exception teardown both OMIT session.idle so
                # callers can reliably distinguish a clean end-of-turn from an error turn.
                if self._hook_dispatcher is not None:
                    await self._hook_dispatcher.dispatch_stop(
                        result_text=last_result_text
                    )
                    # --- RCA-Task 5 F1: session.idle only when no error event was yielded ---
                    if not errored:
                        await self._hook_dispatcher.dispatch_session_event(
                            "session.idle", {}
                        )

            except ThinLlmError as exc:
                # Emit any buffered retry events before the final error
                if self._retry_events:
                    for retry_evt in self._retry_events:
                        yield retry_evt
                    self._retry_events.clear()
                yield RuntimeEvent.error(exc.error)
                if self._hook_dispatcher is not None:
                    await self._hook_dispatcher.dispatch_stop(
                        result_text=str(exc.error.message)
                    )
            except Exception as e:
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message=f"ThinRuntime crash: {e}",
                        recoverable=False,
                    )
                )
                if self._hook_dispatcher is not None:
                    await self._hook_dispatcher.dispatch_stop(result_text=str(e))
        finally:
            end_native_usage_scope(usage_scope)

    @staticmethod
    def _extract_last_user_text(messages: list[Message]) -> str:
        """Extract last user text."""
        return extract_last_user_text(messages)

    @staticmethod
    async def _run_guardrails(
        guardrails: list[Any],
        text: str,
        config: RuntimeConfig,
    ) -> RuntimeEvent | None:
        """Run guardrails in parallel. Return error event if any fails, else None."""
        return await run_guardrails(guardrails, text, config)

    @staticmethod
    def _cancelled_event(token: Any | None) -> RuntimeEvent | None:
        return cancelled_event(token)

    @staticmethod
    def _raise_if_cancelled(token: Any | None) -> None:
        if token is None or not token.is_cancelled:
            return
        raise ThinLlmError(
            RuntimeErrorData(
                kind="cancelled",
                message="Operation cancelled",
                recoverable=False,
            )
        )

    @staticmethod
    def _budget_exceeded_event(
        tracker: CostTracker,
        *,
        prefix: str,
    ) -> RuntimeEvent:
        return budget_exceeded_event(tracker, prefix=prefix)

    async def _sleep_with_cancellation(self, delay: float, token: Any | None) -> None:
        if delay <= 0:
            return
        if token is None:
            await asyncio.sleep(delay)
            return

        remaining = delay
        step = 0.05
        while remaining > 0:
            self._raise_if_cancelled(token)
            wait_for = min(step, remaining)
            await asyncio.sleep(wait_for)
            remaining -= wait_for
        self._raise_if_cancelled(token)

    def _buffer_retry_status(self, attempt: int, delay: float) -> None:
        self._retry_events.append(
            RuntimeEvent.status(f"Retry attempt {attempt}, delay {delay:.1f}s")
        )

    async def cleanup(self) -> None:
        """Cleanup."""
        await self._executor.aclose()
