"""React strategy -- loop (LLM -> tool_call | final)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmline.hooks.dispatcher import HookDispatcher
    from swarmline.runtime.thin.auto_verify_loop import AutoVerifyLoop
    from swarmline.runtime.thin.native_tools import NativeToolCallAdapter
    from swarmline.runtime.thin.round_context import RoundContextRefresher


from swarmline.compaction import (
    CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY,
    read_compression_history_checkpoint,
)
from swarmline.evolution.stuck_detector import ToolCallRecord
from swarmline.resilience.checkpoint import CHECKPOINT_KEY_STEP, CHECKPOINT_KEY_TOTAL
from swarmline.observability.redaction import redact_secrets
from swarmline.runtime.structured_output import (
    append_structured_output_instruction,
    append_structured_output_instruction_for_mode,
)
from swarmline.runtime.structured_requests import (
    build_llm_call_kwargs,
    resolve_structured_request_strategy,
)
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.finalization import (
    CheckpointFn,
    finalize_with_validation,
)
from swarmline.runtime.thin.helpers import (
    _messages_to_lm,
    _should_buffer_postprocessing,
)
from swarmline.runtime.thin.loop_guards import LoopGuards, RunTimeBudgetExceeded
from swarmline.runtime.thin.llm_client import (
    StreamingLlmAttempt,
    run_buffered_llm_call,
    stream_llm_call,
)
from swarmline.runtime.thin.mid_run_hooks import (
    apply_transform_context,
    maybe_followup_requeue,
    run_post_turn_hooks,
)
from swarmline.context.budget import DEFAULT_CONTEXT_WINDOW_TOKENS
from swarmline.runtime.thin.parsers import extract_text_fallback, parse_envelope
from swarmline.runtime.thin.prompts import build_react_prompt
from swarmline.runtime.thin.round_context import track_call_usage
from swarmline.runtime.thin.usage import (
    _native_usage_calls,
    _record_missing_native_usage,
)
from swarmline.runtime.thin.tool_result_render import ToolResultRendering
from swarmline.runtime.thin.tool_result_offload import (
    CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD,
    CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD_FALLBACKS,
    resolve_tool_result_offload,
)
from swarmline.runtime.thin.tool_schema_snapshot import (
    CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT,
    resolve_pinned_tools,
)
from swarmline.runtime.iteration_budget import IterationBudget
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)

_logger = logging.getLogger(__name__)

# Edit-family tool names that trigger the file.edited session event (REQ-RCA-030).
# Kept as a module-level frozenset so both the text-ReAct and native paths share
# the same definition (DRY) without any per-call set allocation.
_EDIT_TOOL_NAMES: frozenset[str] = frozenset(
    {"edit", "write", "multi_edit", "multi_file_edit"}
)

# open-beta-hermes-saas Sprint 1a Stage 2 (REQ-LTK-005): opt-in soft landing on
# loop-limit exhaustion. Exact EN wording is part of the contract (spec +
# plan) -- do not reword without updating both.
_SOFT_LANDING_INSTRUCTION = (
    "You've reached the maximum number of tool-calling iterations for this turn. "
    "Reply with a final summary: what you accomplished, what remains, and the next "
    "concrete step. Do not call any tools."
)


async def _soft_landing_call(
    *,
    llm_call: Callable[..., Any],
    lm_messages: list[dict[str, str]],
    system_prompt: str,
    config: RuntimeConfig,
    on_retry: Callable[[int, float], None] | None,
    start_time: float,
    iterations: int,
    tool_calls_count: int,
    new_messages: list[Message],
    checkpoint: CheckpointFn | None,
    exit_reason: str = "loop_limit",
    instruction: str = _SOFT_LANDING_INSTRUCTION,
) -> RuntimeEvent | None:
    """One tool-less LLM call asking the model to summarize on loop-limit exhaustion.

    REQ-LTK-005: один дополнительный вызов без tool-схем. Базовый system_prompt
    дополняется только схемой результата; ReAct envelope и описания tools не
    передаются. Вызов идёт через llm_call, минуя native_adapter с его tools.

    REQ-LTK-007: ThinLlmError, включая отмену внутри LLM-вызова, возвращает
    ``None`` → прежний ``loop_limit`` без выдуманного итога. Отмена до/после
    вызова через checkpoint возвращает его событие без final.

    Общий finalizer проверяет output_type и verifier до выдачи final и считает
    usage/metrics. Schema-retry отключён только для этой финализации: бюджет
    допускает один дополнительный вызов, исходный config не изменяется.
    """
    landing_messages = [
        *lm_messages,
        {"role": "user", "content": instruction},
    ]
    landing_prompt = append_structured_output_instruction_for_mode(
        resolve_structured_request_strategy(config).mode,
        system_prompt,
        config.output_format,
    )
    llm_call_kwargs = build_llm_call_kwargs(config)
    llm_call_kwargs.pop("_swarmline_structured_strategy", None)
    # Провайдер объединяет extra_body с kwargs: очищаем оба уровня без мутации config.
    tool_fields = (
        "tools",
        "tool_choice",
        "functions",
        "function_call",
        "parallel_tool_calls",
    )
    for field in tool_fields:
        llm_call_kwargs.pop(field, None)
    if "extra_body" in llm_call_kwargs:
        llm_call_kwargs["extra_body"] = {
            key: value
            for key, value in llm_call_kwargs["extra_body"].items()
            if key not in tool_fields
        }
    checkpoint_event = await _run_checkpoint(checkpoint)
    if checkpoint_event is not None:
        return checkpoint_event
    usage_calls_before = _native_usage_calls()
    try:
        attempt = await run_buffered_llm_call(
            llm_call,
            landing_messages,
            landing_prompt,
            llm_kwargs=llm_call_kwargs,
            retry_policy=config.retry_policy,
            cancellation_token=config.cancellation_token,
            on_retry=on_retry,
        )
    except ThinLlmError:
        return None
    _record_missing_native_usage(attempt.usage, calls_before=usage_calls_before)

    async for event in finalize_with_validation(
        attempt.raw,
        replace(config, max_model_retries=0),
        landing_messages,
        landing_prompt,
        llm_call,
        start_time,
        iterations=iterations,
        tool_calls=tool_calls_count,
        new_messages_prefix=new_messages,
        checkpoint=checkpoint,
        provider_usage=attempt.usage,
        attempts=attempt.attempts,
    ):
        if event.is_final:
            return replace(
                event,
                data={
                    **event.data,
                    "native_metadata": {
                        **event.data.get("native_metadata", {}),
                        "exit_reason": exit_reason,
                    },
                },
            )
        return event
    return None


async def _maybe_dispatch_file_edited(
    session_dispatcher: HookDispatcher | None,
    tool_name: str,
    tool_args: dict[str, Any],
) -> None:
    """Dispatch file.edited if tool_name is an edit-family tool (DRY helper).

    Called from BOTH the text-ReAct and native tool-calling branches so the
    dispatch logic (tool-name guard + payload shape) is defined once.

    No-op when session_dispatcher is None (default) or the tool is not an
    edit-family tool — byte-identical to the pre-Task-5 code path.
    Fail-open behaviour is handled inside dispatch_session_event.
    """
    if session_dispatcher is None or tool_name not in _EDIT_TOOL_NAMES:
        return
    await session_dispatcher.dispatch_session_event(
        "file.edited",
        {
            "tool": tool_name,
            "path": str(tool_args.get("path", tool_args.get("file_path", ""))),
        },
    )


def _read_int(d: dict[str, object], key: str, default: int) -> int:
    """Read an int from a dict[str, object]; return *default* if absent or wrong type."""
    v = d.get(key, default)
    return v if isinstance(v, int) else default


def _read_lm_messages(d: dict[str, object], key: str) -> list[dict[str, str]] | None:
    """Read an lm_messages snapshot from a checkpoint dict.

    Returns None when the key is absent, not a list, empty, or contains any
    non-dict element.  The cast is intentional: checkpoints written by this
    module store list[dict[str, str]], but a third-party CheckpointPort could
    return a list with non-dict elements; rejecting those (treat as no valid
    snapshot) fails safe — the loop starts fresh rather than crashing
    downstream in ``llm_call`` / the native adapter.
    """
    v = d.get(key)
    if not isinstance(v, list) or not v:
        return None
    if not all(isinstance(e, dict) for e in v):
        return None
    return v  # ty: ignore[invalid-return-type]


def _read_frozen_offload_projections(
    d: dict[str, object] | None, key: str
) -> dict[str, str]:
    """Read the Stage 4 frozen tool-result-offload projection map from a
    checkpoint dict. Returns ``{}`` (fresh/no-op) when ``d`` is ``None``, the
    key is absent, the value is not a dict, or any key/value pair is not
    ``str``/``str`` -- same fail-safe contract as ``_read_lm_messages``: a
    malformed/foreign checkpoint value is treated as "nothing frozen yet"
    rather than crashing downstream.
    """
    if d is None:
        return {}
    v = d.get(key)
    if not isinstance(v, dict):
        return {}
    if not all(isinstance(k, str) and isinstance(val, str) for k, val in v.items()):
        return {}
    return v  # ty: ignore[invalid-return-type]


def _within_iteration_budget(iterations: int, config: RuntimeConfig) -> bool:
    """Return True when the loop should continue for the next iteration.

    Default path (use_iteration_budget=False): plain integer comparison —
    byte-identical to the pre-OSS-T3 ``iterations < config.max_iterations``
    guard so the default behaviour is unchanged.

    Opt-in path (use_iteration_budget=True): delegates to IterationBudget VO
    for the same semantics, exercising the VO on each turn.
    """
    if config.use_iteration_budget:
        return (
            not IterationBudget(max_iterations=config.max_iterations)
            .with_used(iterations)
            .is_exhausted()
        )
    return iterations < config.max_iterations


async def run_react(  # noqa: C901
    llm_call: Callable[..., Any],
    executor: ToolExecutor,
    messages: list[Message],
    system_prompt: str,
    tools: list[ToolSpec],
    config: RuntimeConfig,
    start_time: float,
    checkpoint: CheckpointFn | None = None,
    on_retry: Callable[[int, float], None] | None = None,
    native_adapter: NativeToolCallAdapter | None = None,
    auto_verify_loop: AutoVerifyLoop | None = None,
    session_dispatcher: HookDispatcher | None = None,
    round_refresher: RoundContextRefresher | None = None,
) -> AsyncIterator[RuntimeEvent]:
    """Run react."""
    _render = ToolResultRendering.from_config(config)  # CE-24: tool results as data
    _guards = LoopGuards.from_config(config)  # Sprint 1ce S5: inert unless enabled
    llm_call = _guards.bound(llm_call)  # time budget caps every model call
    lm_messages = _messages_to_lm(messages, rendering=_render)
    new_messages: list[Message] = []

    iterations = 0
    tool_calls_count = 0
    retries = 0
    last_raw = ""
    buffered_postprocessing = _should_buffer_postprocessing(config)
    thinking_metadata: dict[str, Any] | None = None

    # Self-evolution state
    _tool_history: list[ToolCallRecord] = []
    _recovery_attempts = 0

    # --- OSS-T4: opt-in resume from last durable checkpoint (default None = noop) ---
    _cp_saved: dict[str, object] | None = None
    if config.checkpoint_writer is not None and config.run_id:
        _cp_saved = await config.checkpoint_writer.load(config.run_id)
        if _cp_saved is not None:
            _cp_step = _read_int(_cp_saved, CHECKPOINT_KEY_STEP, 0)
            _cp_total = _read_int(
                _cp_saved, CHECKPOINT_KEY_TOTAL, config.max_iterations
            )
            yield RuntimeEvent.status(
                f"resumed from checkpoint step {_cp_step}/{_cp_total}"
            )
            iterations = _cp_step
            _cp_restored_msgs = _read_lm_messages(_cp_saved, "lm_messages")
            if _cp_restored_msgs is not None:
                lm_messages = _cp_restored_msgs
            _cp_tcc = _cp_saved.get("tool_calls_count")
            if isinstance(_cp_tcc, int):
                tool_calls_count = _cp_tcc

    # --- Stage 3 (AGR-004): tool schemas resolve ONCE per run and stay pinned
    # across every call sharing this run_id -- the byte-stable prefix/cache
    # boundary invariant from Stage 1/2 extends to the tools payload itself.
    # Reuses the SAME OSS-T4 checkpoint substrate loaded just above; no new
    # persistence mechanism, no taskloom coupling.
    tools, _tool_schema_snapshot = resolve_pinned_tools(tools, _cp_saved)

    # Stage 4 (Filesystem as context): load whatever frozen tool-result-offload
    # projections a PRIOR call of this run already produced. Loaded here (before
    # the M-1-lesson immediate persist just below) so that persist round-trips
    # this value rather than silently wiping it -- the M-1 fix (Stage 3)
    # unconditionally REPLACES the whole checkpoint state on every call; if
    # this key were omitted there, every run_react() call would erase any
    # offload state a previous turn had accumulated.
    _frozen_offload_projections = _read_frozen_offload_projections(
        _cp_saved, CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD
    )
    # Fix-cycle 2 (codex round 2, "Variant A"): write-failure full-body
    # fallbacks live in a SEPARATE checkpoint key/map -- never conflated with
    # _frozen_offload_projections (which must contain ONLY successful
    # offloads, since it drives both the aggregate soft-target accounting and
    # the sticky scratch_read re-add below).
    _frozen_offload_fallbacks = _read_frozen_offload_projections(
        _cp_saved, CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD_FALLBACKS
    )
    # Stage 6: this loop never modifies compression_history itself -- only
    # ThinRuntime.run()'s compaction step (runtime.py, BEFORE run_react()
    # starts) updates it. Read-and-round-trip it here for the SAME M-1-class
    # reason as the two maps above: every after_tool_call() write below fully
    # REPLACES the stored state, so omitting this key would silently wipe
    # whatever runtime.py's compaction step just persisted.
    _frozen_compaction_compression_history = read_compression_history_checkpoint(
        _cp_saved, CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY
    )

    # Fix-cycle 1 (M-1, codex round 1): persist the pinned snapshot IMMEDIATELY
    # here, not only inside the after_tool_call() sites below. A turn that
    # finishes with NO tool call at all (immediate final answer) would
    # otherwise never write a checkpoint, so a SECOND run_react() call sharing
    # this run_id could see a DIFFERENT tool set from whatever the live
    # registry happened to hand it -- pinning silently broken. Persisting here
    # (right after resolution, whether reused-verbatim or freshly minted)
    # guarantees the pin holds for every call of this run, tool call or not.
    if config.checkpoint_writer is not None and config.run_id:
        await config.checkpoint_writer.after_tool_call(
            run_id=config.run_id,
            step=iterations,
            total_steps=config.max_iterations,
            state={
                "iterations": iterations,
                "tool_calls_count": tool_calls_count,
                "lm_messages": list(lm_messages),
                CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT: _tool_schema_snapshot,
                CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD: _frozen_offload_projections,
                CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD_FALLBACKS: _frozen_offload_fallbacks,
                CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY: _frozen_compaction_compression_history,
            },
        )

    # --- Stage 3 (AGR-004): stage-based soft masking, opt-in via
    # RuntimeConfig.native_config["stage_enabled_tool_names"] (the same generic
    # passthrough mechanism as prompt_caching_enabled/_ttl). Narrows WHICH of
    # the already-pinned tool names may actually be invoked this turn without
    # ever touching the schema built below -- absent/wrong-shaped config is a
    # hard no-op (None => ToolExecutor.execute() applies no masking at all).
    #
    # Fix-cycle 1 (M-2, codex round 1): the allowlist is intersected with the
    # PINNED tool names -- a name outside the pinned schema snapshot (e.g. one
    # the live registry happens to expose this turn but that was never part of
    # the run's fixed tool set) can NEVER be enabled via masking, no matter
    # what the caller's allowlist says. Masking only ever narrows within the
    # pin; it must not be able to reach outside it.
    _pinned_tool_names = frozenset(t.name for t in tools)
    _stage_enabled_raw = config.native_config.get("stage_enabled_tool_names")
    _masked_tool_names: frozenset[str] | None = (
        frozenset(_stage_enabled_raw) & _pinned_tool_names
        if isinstance(_stage_enabled_raw, list | tuple | set | frozenset)
        else None
    )

    # Fix-cycle 1 (CRITICAL-3b / "Variant A", codex round 1, Stage 4): once an
    # offload has happened anywhere in THIS run, scratch_read must stay
    # enabled for the rest of the run -- otherwise a projection frozen while
    # scratch_read WAS available could become permanently unrestorable the
    # moment a LATER turn's stage_enabled_tool_names masks it out. This is a
    # deliberate, narrow intersection of Stage 3 masking and Stage 4 offload
    # state (not a general "masking can widen" mechanism): it only ever
    # re-adds a name ALREADY in the pinned schema (AGR-004 guarantees
    # "scratch_read" being offered at all means it is pinned for the WHOLE
    # run), so the M-2 invariant (masking never reaches outside the pin)
    # still holds -- this never enables a name outside _pinned_tool_names.
    #
    # Fix-cycle 2 (codex round 2, 3b): checks _frozen_offload_projections ONLY
    # (never _frozen_offload_fallbacks) -- a write-failure fallback has no
    # scratch key behind it, so a run whose ONLY frozen state is fallbacks
    # must NOT trigger this: masking stays byte-identical when nothing was
    # ever successfully offloaded.
    if (
        _frozen_offload_projections
        and "scratch_read" in _pinned_tool_names
        and _masked_tool_names is not None
    ):
        _masked_tool_names = _masked_tool_names | {"scratch_read"}

    # --- Stage 4 (Filesystem as context): large tool results are offloaded to
    # an external ScratchpadProvider and replaced in the context by a
    # restorable head+tail projection -- opt-in via
    # RuntimeConfig.native_config["scratchpad_provider"] (a live object, same
    # precedent as can_use_tool) + native_config["context_window_tokens"]
    # (generic, DEFAULT_CONTEXT_WINDOW_TOKENS shared with
    # CodingContextInputFilter -- one literal default, two subsystem-scoped
    # keys). Absent scratchpad_provider is a hard no-op: byte-identical to
    # pre-Stage-4 behaviour.
    _scratchpad_provider = config.native_config.get("scratchpad_provider")
    _offload_window_raw = config.native_config.get(
        "context_window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS
    )
    _offload_context_window_tokens = (
        max(int(_offload_window_raw), 1000)
        if isinstance(_offload_window_raw, (int, float))
        else DEFAULT_CONTEXT_WINDOW_TOKENS
    )
    # Restorability is a HARDER requirement than context size: offload only
    # ever engages when the model can ACTUALLY call scratch_read this run --
    # present in the pinned schema AND not masked out. Reuses the exact same
    # pin/mask state computed just above (Stage 3), never a second source of
    # truth for "what's really available this turn".
    _scratch_read_available = "scratch_read" in _pinned_tool_names and (
        _masked_tool_names is None or "scratch_read" in _masked_tool_names
    )

    prompt = build_react_prompt(
        append_structured_output_instruction(
            system_prompt,
            config.output_format,
            final_response_field="final_message",
        ),
        tools,
    )
    # Native tool-calling uses a CLEAN prompt: tools are passed to the provider natively
    # and the final structured output is produced in a separate Phase-2 call, so the
    # text-ReAct envelope / final_message nesting must NOT be imposed on the loop.
    native_loop_prompt = system_prompt
    _run_usage: dict[str, int] | None = None  # summed over calls (BL-89/BL-98)
    if round_refresher is not None and (
        _round_off := round_refresher.start_run(
            config,
            resumed=_read_lm_messages(_cp_saved or {}, "lm_messages") is not None,
            auto_verify=auto_verify_loop is not None,
        )
    ):
        yield RuntimeEvent.status(_round_off)

    while _within_iteration_budget(iterations, config):
        iterations += 1
        stream_emitted_text = False
        if round_refresher is not None:  # Sprint 1ce CE-9, rounds 2..N
            _refresh = await round_refresher.before_round(
                round_index=iterations,
                lm_messages=lm_messages,
                messages=messages,
                new_messages=new_messages,
                system_prompt=prompt,
            )
            lm_messages = _refresh.lm_messages
            if _refresh.compacted:
                _frozen_compaction_compression_history = (
                    round_refresher.compression_history
                )
                _guards.mark_compaction(lm_messages)
        if _guards.before_call(lm_messages):  # time budget / armed stop signal
            break

        # --- H4 Task 1: transform_context applied before every model call
        # (opt-in, default None = no-op passthrough, REQ-010) ---
        lm_messages = apply_transform_context(config, lm_messages)

        # --- Native tool calling path (Strangler Fig: opt-in) ---
        if native_adapter is not None and config.use_native_tools and tools:
            native_handled = False
            # Phase 2 finalize runs AFTER the native try/except (see below) so a structured
            # finalization error is never mistaken for a native-adapter failure. None = the
            # loop produced tool calls (or errored); a str = the loop's final text to finalize.
            native_finalize_text: str | None = None
            try:
                tool_defs = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    }
                    for t in tools
                ]
                native_call_kwargs = build_llm_call_kwargs(config)
                native_call_kwargs.pop("_swarmline_structured_strategy", None)
                native_call_kwargs.pop("response_format", None)
                usage_calls_before = _native_usage_calls()
                native_result = await _guards.bound(native_adapter.call_with_tools)(
                    lm_messages,
                    native_loop_prompt,
                    tool_defs,
                    **native_call_kwargs,
                )
                _record_missing_native_usage(
                    getattr(native_result, "usage", None),
                    calls_before=usage_calls_before,
                )
                _run_usage = track_call_usage(
                    round_refresher,
                    _run_usage,
                    getattr(native_result, "usage", None),
                    len(lm_messages),
                )

                if native_result.tool_calls:
                    # Budget check (same as JSON-in-text path)
                    if (
                        tool_calls_count + len(native_result.tool_calls)
                        > config.max_tool_calls
                    ):
                        # Tool budget exhausted. A weak / non-converging model can keep
                        # requesting tool calls forever; rather than erroring out (which loses
                        # everything gathered so far), STOP calling tools and FORCE a final
                        # structured answer from the accumulated context — the same Phase-2
                        # finalize the clean-stop path uses. Graceful degradation, not a crash.
                        forced_kwargs = build_llm_call_kwargs(config)
                        forced_kwargs.pop("_swarmline_structured_strategy", None)
                        forced_prompt = append_structured_output_instruction_for_mode(
                            resolve_structured_request_strategy(config).mode,
                            system_prompt,
                            config.output_format,
                            final_response_field=None,
                        )
                        async for event in finalize_with_validation(
                            native_result.text or "",
                            config,
                            lm_messages,
                            forced_prompt,
                            llm_call,
                            start_time,
                            iterations=iterations,
                            tool_calls=tool_calls_count,
                            new_messages_prefix=new_messages,
                            checkpoint=checkpoint,
                            llm_call_kwargs=forced_kwargs,
                            provider_usage=_run_usage,
                        ):
                            yield event
                        return

                    for ntc in native_result.tool_calls:
                        yield RuntimeEvent.tool_call_started(
                            name=ntc.name,
                            args=ntc.args,
                            correlation_id=ntc.id,
                        )

                    # Execute tool calls through executor (which runs hooks + policy)
                    # Parallel if >1, sequential otherwise
                    if len(native_result.tool_calls) > 1:
                        raw_results = await asyncio.gather(
                            *[
                                executor.execute(
                                    ntc.name,
                                    ntc.args,
                                    masked_tool_names=_masked_tool_names,
                                )
                                for ntc in native_result.tool_calls
                            ],
                            return_exceptions=True,
                        )
                        # Convert exceptions to JSON error strings
                        results: list[str] = []
                        for r in raw_results:
                            if isinstance(r, BaseException):
                                results.append(json.dumps({"error": str(r)}))
                            else:
                                results.append(r)
                    else:
                        results = [
                            await executor.execute(
                                native_result.tool_calls[0].name,
                                native_result.tool_calls[0].args,
                                masked_tool_names=_masked_tool_names,
                            )
                        ]

                    # Emit tool_call_finished events and count
                    for ntc, result in zip(native_result.tool_calls, results):
                        tool_ok = True
                        try:
                            parsed = json.loads(result)
                            if isinstance(parsed, dict) and "error" in parsed:
                                tool_ok = False
                        except (json.JSONDecodeError, TypeError):
                            pass
                        yield RuntimeEvent.tool_call_finished(
                            name=ntc.name,
                            correlation_id=ntc.id,
                            ok=tool_ok,
                            result_summary=result[:200],
                        )
                        tool_calls_count += 1
                        _guards.observe(ntc.name, ntc.args, result)

                    # --- Stage 4 (Filesystem as context): offload large tool
                    # results (opt-in, default None scratchpad_provider = no-op).
                    # Sequential (never parallel) so the aggregate-ceiling math
                    # in resolve_tool_result_offload() sees each prior offload
                    # within THIS batch before deciding the next one's budget.
                    # Only ONE call site of the shared decision function here;
                    # tool_ok/event-summary above already ran against the RAW
                    # results, so offload never corrupts error detection.
                    _offloaded_results: list[str] = []
                    _restore_keys: list[str | None] = []
                    for ntc, raw_result in zip(native_result.tool_calls, results):
                        _offload_outcome = await resolve_tool_result_offload(
                            call_id=ntc.id,
                            result=raw_result,
                            context_window_tokens=_offload_context_window_tokens,
                            scratchpad_provider=_scratchpad_provider,
                            scratch_read_available=_scratch_read_available,
                            frozen_projections=_frozen_offload_projections,
                            frozen_full_fallbacks=_frozen_offload_fallbacks,
                        )
                        _offloaded_results.append(_offload_outcome.text)
                        _restore_keys.append(
                            _render.restore_key(ntc.id, _offload_outcome)
                        )
                        _frozen_offload_projections = (
                            _offload_outcome.frozen_projections
                        )
                        _frozen_offload_fallbacks = (
                            _offload_outcome.frozen_full_fallbacks
                        )
                    results = _offloaded_results

                    # Append messages for next turn
                    if native_result.text:
                        lm_messages.append(
                            {"role": "assistant", "content": native_result.text}
                        )
                    for ntc, result, key in zip(
                        native_result.tool_calls, results, _restore_keys
                    ):
                        _rendered = _render.render(
                            ntc.name, result, prefix="Result", restore_key=key
                        )
                        lm_messages.append({"role": "user", "content": _rendered})
                    native_tool_calls = [
                        {"id": ntc.id, "name": ntc.name, "args": ntc.args}
                        for ntc in native_result.tool_calls
                    ]
                    new_messages.append(
                        Message(
                            role="assistant",
                            content=native_result.text or "",
                            tool_calls=native_tool_calls,
                        )
                    )
                    for ntc, result, key in zip(
                        native_result.tool_calls, results, _restore_keys
                    ):
                        new_messages.append(_render.tool_message(ntc.name, result, key))
                    if (_warned := _guards.flush(lm_messages)) is not None:
                        yield _warned

                    # --- OSS-T4: persist checkpoint after native tool calls (opt-in) ---
                    if config.checkpoint_writer is not None and config.run_id:
                        await config.checkpoint_writer.after_tool_call(
                            run_id=config.run_id,
                            step=iterations,
                            total_steps=config.max_iterations,
                            state={
                                "iterations": iterations,
                                "tool_calls_count": tool_calls_count,
                                "lm_messages": list(lm_messages),
                                CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT: _tool_schema_snapshot,
                                CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD: _frozen_offload_projections,
                                CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD_FALLBACKS: _frozen_offload_fallbacks,
                                CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY: _frozen_compaction_compression_history,
                            },
                        )

                    # --- RCA-Task 5: file.edited for native edit tools (opt-in, noop) ---
                    for ntc in native_result.tool_calls:
                        await _maybe_dispatch_file_edited(
                            session_dispatcher, ntc.name, ntc.args
                        )

                    native_handled = True

                else:
                    # Native tool loop finished (no further tool calls). Defer Phase 2
                    # finalization to AFTER this try/except (a falsy text is normalised to
                    # "" so the empty-stop case still finalizes). Doing it outside the try is
                    # deliberate: a finalization error must surface, not be swallowed as a
                    # native-adapter failure and trigger a redundant text-ReAct fallback.
                    native_finalize_text = native_result.text or ""
                    if _guards.empty_reply(native_finalize_text, lm_messages):
                        continue

            except RunTimeBudgetExceeded:
                break
            except Exception as exc:
                _logger.warning(
                    "Native tool calling failed, falling back to JSON-in-text (%s): %s",
                    type(exc).__name__,
                    redact_secrets(str(exc)),
                    extra={"exc_type": type(exc).__name__},
                )
                native_handled = False
                native_finalize_text = (
                    None  # Phase-1 native failure → fall back, do NOT finalize
                )

            if native_finalize_text is not None:
                # kernel-wiring Task 1 (I-008, REQ-001/004): follow-up requeue at the
                # native tool-calling natural-end seam (opt-in, default None = no-op).
                requeue = maybe_followup_requeue(
                    config=config,
                    llm_call=llm_call,
                    messages=messages,
                    new_messages=new_messages,
                    system_prompt=system_prompt,
                    start_time=start_time,
                    checkpoint=checkpoint,
                    executor=executor,
                    tools=tools,
                    on_retry=on_retry,
                    native_adapter=native_adapter,
                    session_dispatcher=session_dispatcher,
                )
                if requeue:
                    lm_messages.extend(requeue)
                    continue
                # Phase 2 (two-phase structured finalization). finalize_with_validation
                # returns the text as-is when valid (or when no structured output is
                # configured) and otherwise repairs it with a dedicated structured call that
                # carries provider-native response_format — the tool loop never carries it, so
                # flash-class models work. Structured retries inside finalize are NOT counted
                # as ``iterations`` (which counts agent-loop turns only). Errors raised here
                # propagate to the caller; they are not native-adapter failures and must NOT
                # silently fall back to text-ReAct.
                llm_call_kwargs = build_llm_call_kwargs(config)
                llm_call_kwargs.pop("_swarmline_structured_strategy", None)
                final_prompt = append_structured_output_instruction_for_mode(
                    resolve_structured_request_strategy(config).mode,
                    system_prompt,
                    config.output_format,
                    final_response_field=None,
                )
                # Surface the model's final text immediately (when not buffering), matching
                # the text-ReAct / clarify paths so the native path is not UX-silent before
                # the final event arrives.
                if not buffered_postprocessing and native_finalize_text:
                    yield RuntimeEvent.assistant_delta(native_finalize_text)
                async for event in finalize_with_validation(
                    native_finalize_text,
                    config,
                    lm_messages,
                    final_prompt,
                    llm_call,
                    start_time,
                    iterations=iterations,
                    tool_calls=tool_calls_count,
                    new_messages_prefix=new_messages,
                    checkpoint=checkpoint,
                    llm_call_kwargs=llm_call_kwargs,
                    provider_usage=_run_usage,
                ):
                    yield event
                return

            if native_handled:
                # --- H4 Task 1 (GPT-5.5 review FINDING 1): mid-run control hooks
                # must fire after a native tool-call turn too, not only the
                # text-ReAct branch below (opt-in, default None = no-op) ---
                outcome = run_post_turn_hooks(
                    config=config,
                    llm_call=llm_call,
                    messages=messages,
                    new_messages=new_messages,
                    system_prompt=system_prompt,
                    start_time=start_time,
                    checkpoint=checkpoint,
                    iterations=iterations,
                    tool_calls_count=tool_calls_count,
                    lm_messages=lm_messages,
                    prompt=native_loop_prompt,
                    turn_text=native_result.text or "",
                    executor=executor,
                    tools=tools,
                    on_retry=on_retry,
                    native_adapter=native_adapter,
                    session_dispatcher=session_dispatcher,
                )
                if outcome.should_stop:
                    if outcome.stop_status_event is not None:
                        yield outcome.stop_status_event
                    if outcome.stop_final_event is not None:
                        yield outcome.stop_final_event
                    return
                if outcome.steering_lm_messages:
                    lm_messages.extend(outcome.steering_lm_messages)
                continue

        try:
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            if buffered_postprocessing:
                attempt = await run_buffered_llm_call(
                    llm_call,
                    lm_messages,
                    prompt,
                    retry_policy=config.retry_policy,
                    cancellation_token=config.cancellation_token,
                    on_retry=on_retry,
                )
                if attempt.thinking:
                    yield RuntimeEvent.thinking_delta(attempt.thinking)
                    thinking_metadata = {
                        "thinking": attempt.thinking,
                        "non_compactable": True,
                    }
                stream_emitted_text = False
                raw = attempt.raw
            else:
                stream_result: StreamingLlmAttempt | None = None
                async for stream_item in stream_llm_call(
                    llm_call,
                    lm_messages,
                    prompt,
                    emit_final_message_delta=config.get_followup_messages is None,
                ):
                    if isinstance(stream_item, RuntimeEvent):
                        yield stream_item
                    else:
                        stream_result = stream_item
                if stream_result is not None:
                    raw = stream_result.raw
                    stream_emitted_text = stream_result.emitted_text_delta
                else:
                    checkpoint_event = await _run_checkpoint(checkpoint)
                    if checkpoint_event is not None:
                        yield checkpoint_event
                        return
                    raw = await llm_call(lm_messages, prompt)
                    stream_emitted_text = False
        except ThinLlmError as exc:
            if isinstance(exc, RunTimeBudgetExceeded):
                break
            yield RuntimeEvent.error(exc.error)
            return

        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return

        if _guards.empty_reply(raw, lm_messages):
            continue
        last_raw = raw
        envelope = parse_envelope(raw)

        if envelope is None:
            retries += 1
            if retries > config.max_model_retries:
                fallback_text = extract_text_fallback(last_raw)
                if fallback_text:
                    checkpoint_event = await _run_checkpoint(checkpoint)
                    if checkpoint_event is not None:
                        yield checkpoint_event
                        return
                    yield RuntimeEvent.status(
                        "LLM returned non-JSON output; using text fallback"
                    )
                    async for event in finalize_with_validation(
                        fallback_text,
                        config,
                        lm_messages,
                        prompt,
                        llm_call,
                        start_time,
                        iterations=iterations,
                        tool_calls=tool_calls_count,
                        new_messages_prefix=new_messages,
                        checkpoint=checkpoint,
                    ):
                        if not buffered_postprocessing and event.type == "final":
                            yield RuntimeEvent.assistant_delta(fallback_text)
                        yield event
                    return
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="bad_model_output",
                        message=f"LLM returned invalid JSON {retries} times in a row",
                        recoverable=False,
                    )
                )
                return
            continue

        retries = 0

        # --- tool_call ---
        if envelope.type == "tool_call" and envelope.tool:
            tc = envelope.tool

            # Budget check
            if tool_calls_count >= config.max_tool_calls:
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="budget_exceeded",
                        message=f"Превышен лимит tool_calls ({config.max_tool_calls})",
                        recoverable=False,
                    )
                )
                return

            cid = tc.correlation_id or f"c{tool_calls_count + 1}"

            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            yield RuntimeEvent.tool_call_started(
                name=tc.name,
                args=tc.args,
                correlation_id=cid,
            )

            result = await executor.execute(
                tc.name, tc.args, masked_tool_names=_masked_tool_names
            )

            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return

            tool_ok = True
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "error" in parsed:
                    tool_ok = False
            except (json.JSONDecodeError, TypeError):
                pass

            yield RuntimeEvent.tool_call_finished(
                name=tc.name,
                correlation_id=cid,
                ok=tool_ok,
                result_summary=result[:200],
            )

            tool_calls_count += 1
            _guards.observe(tc.name, tc.args, result)

            # --- Self-evolution: stuck detection ---
            if (
                config.evolution_enabled
                and config.stuck_detector is not None
                and config.recovery_cascade is not None
            ):
                record = ToolCallRecord.from_call(
                    tool_name=tc.name,
                    args=tc.args,
                    result=result,
                )
                _tool_history.append(record)
                signal = config.stuck_detector.detect(_tool_history)
                if signal is not None:
                    yield RuntimeEvent.status(f"stuck_detected: {signal.repeated_tool}")
                    recovery = config.recovery_cascade.get_recovery(
                        _recovery_attempts, signal, system_prompt
                    )
                    _recovery_attempts += 1
                    if not recovery.should_continue:
                        yield RuntimeEvent.status(
                            f"stuck_escalated: {recovery.recovery_prompt}"
                        )
                        return
                    yield RuntimeEvent.status(
                        f"recovery_applied: {recovery.strategy_used.value}"
                    )
                    lm_messages.append(
                        {"role": "user", "content": recovery.recovery_prompt}
                    )
                    _tool_history.clear()

            # --- Stage 4 (Filesystem as context): offload large tool results
            # (opt-in, default None scratchpad_provider = no-op). Applied AFTER
            # tool_ok/self-evolution above (which need the RAW result), so
            # offload never corrupts error-detection JSON parsing; only ONE
            # call site of the shared decision function.
            _offload_outcome = await resolve_tool_result_offload(
                call_id=cid,
                result=result,
                context_window_tokens=_offload_context_window_tokens,
                scratchpad_provider=_scratchpad_provider,
                scratch_read_available=_scratch_read_available,
                frozen_projections=_frozen_offload_projections,
                frozen_full_fallbacks=_frozen_offload_fallbacks,
            )
            result = _offload_outcome.text
            _frozen_offload_projections = _offload_outcome.frozen_projections
            _frozen_offload_fallbacks = _offload_outcome.frozen_full_fallbacks

            new_messages.append(
                Message(
                    role="assistant",
                    content=(
                        tc.assistant_message if hasattr(tc, "assistant_message") else ""
                    ),  # ty: ignore[invalid-argument-type]  # tc.assistant_message hasattr-narrow not propagated by ty
                    metadata={"tool_call": tc.name},
                )
            )
            _key = _render.restore_key(cid, _offload_outcome)
            new_messages.append(_render.tool_message(tc.name, result, _key))
            lm_messages.append({"role": "assistant", "content": f"Вызываю {tc.name}"})
            _rendered = _render.render(
                tc.name, result, prefix="Результат", restore_key=_key
            )
            lm_messages.append({"role": "user", "content": _rendered})
            if (_warned := _guards.flush(lm_messages)) is not None:
                yield _warned

            # --- RCA-Task 1: auto-verify re-inject (opt-in, default noop) ---
            # When enable_auto_lint_test=False (default), auto_verify_loop is None
            # and this block is never entered — byte-identical OFF path.
            if auto_verify_loop is not None and tc.name in (
                "edit",
                "write",
                "multi_edit",
                "multi_file_edit",
            ):
                _avl_fb = await auto_verify_loop.run()
                if _avl_fb is not None:
                    lm_messages.append(
                        {
                            "role": "user",
                            "content": _avl_fb.to_turn_message(),
                        }
                    )

            # --- RCA-Task 5: file.edited session event (opt-in, default noop) ---
            await _maybe_dispatch_file_edited(session_dispatcher, tc.name, tc.args)

            # --- OSS-T4: persist checkpoint after tool call (opt-in, default noop) ---
            if config.checkpoint_writer is not None and config.run_id:
                await config.checkpoint_writer.after_tool_call(
                    run_id=config.run_id,
                    step=iterations,
                    total_steps=config.max_iterations,
                    state={
                        "iterations": iterations,
                        "tool_calls_count": tool_calls_count,
                        "lm_messages": list(lm_messages),
                        CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT: _tool_schema_snapshot,
                        CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD: _frozen_offload_projections,
                        CHECKPOINT_KEY_TOOL_RESULT_OFFLOAD_FALLBACKS: _frozen_offload_fallbacks,
                        CHECKPOINT_KEY_COMPACTION_COMPRESSION_HISTORY: _frozen_compaction_compression_history,
                    },
                )

            if envelope.assistant_message:
                yield RuntimeEvent.status(envelope.assistant_message)

            # --- H4 Task 1: mid-run control hooks after a turn completes
            # (opt-in, default None = no-op, REQ-010). Shared with the native
            # tool-calling branch above via run_post_turn_hooks (GPT-5.5 review
            # FINDING 1) so both branches fire should_stop_after_turn /
            # get_steering_messages identically. ---
            outcome = run_post_turn_hooks(
                config=config,
                llm_call=llm_call,
                messages=messages,
                new_messages=new_messages,
                system_prompt=system_prompt,
                start_time=start_time,
                checkpoint=checkpoint,
                iterations=iterations,
                tool_calls_count=tool_calls_count,
                lm_messages=lm_messages,
                prompt=prompt,
                turn_text=raw,
                executor=executor,
                tools=tools,
                on_retry=on_retry,
                native_adapter=native_adapter,
                session_dispatcher=session_dispatcher,
            )
            if outcome.should_stop:
                # GPT-5.5 review FINDING 2: emit the terminal final event too
                # (not just status) so accumulated new_messages/metrics survive.
                if outcome.stop_status_event is not None:
                    yield outcome.stop_status_event
                if outcome.stop_final_event is not None:
                    yield outcome.stop_final_event
                return
            if outcome.steering_lm_messages:
                lm_messages.extend(outcome.steering_lm_messages)

            continue

        # --- final ---
        if envelope.type == "final" and envelope.final_message:
            text = envelope.final_message
            # kernel-wiring Task 1 (I-008, REQ-001/004): follow-up requeue at the
            # text-ReAct natural-end seam (opt-in, default None = no-op).
            requeue = maybe_followup_requeue(
                config=config,
                llm_call=llm_call,
                messages=messages,
                new_messages=new_messages,
                system_prompt=system_prompt,
                start_time=start_time,
                checkpoint=checkpoint,
                executor=executor,
                tools=tools,
                on_retry=on_retry,
                native_adapter=native_adapter,
                session_dispatcher=session_dispatcher,
            )
            if requeue:
                lm_messages.extend(requeue)
                continue
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            if not buffered_postprocessing and not stream_emitted_text:
                yield RuntimeEvent.assistant_delta(text)
            async for event in finalize_with_validation(
                text,
                config,
                lm_messages,
                prompt,
                llm_call,
                start_time,
                iterations=iterations,
                tool_calls=tool_calls_count,
                new_messages_prefix=new_messages,
                checkpoint=checkpoint,
                assistant_metadata=thinking_metadata,
            ):
                yield event
            return

        # --- clarify ---
        if envelope.type == "clarify":
            text = envelope.assistant_message or "Please clarify."
            if envelope.questions:
                qs = "\n".join(f"- {q.text}" for q in envelope.questions)
                text = f"{text}\n\n{qs}"

            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            if not buffered_postprocessing and not stream_emitted_text:
                yield RuntimeEvent.assistant_delta(text)
            async for event in finalize_with_validation(
                text,
                config,
                lm_messages,
                prompt,
                llm_call,
                start_time,
                iterations=iterations,
                tool_calls=tool_calls_count,
                new_messages_prefix=new_messages,
                checkpoint=checkpoint,
            ):
                yield event
            return

    # Loop limit reached -- REQ-LTK-005/006: opt-in soft landing, default off
    # (native_config.get returns None, `is True` is False) keeps this branch
    # byte-identical to the pre-Sprint-1a error path.
    if (_landing := _guards.landing(config)) is not None:
        landing_event = await _soft_landing_call(
            llm_call=llm_call,
            lm_messages=lm_messages,
            system_prompt=system_prompt,
            config=config,
            on_retry=on_retry,
            start_time=start_time,
            iterations=iterations,
            tool_calls_count=tool_calls_count,
            new_messages=new_messages,
            checkpoint=checkpoint,
            **_landing,
        )
        if landing_event is not None:
            yield landing_event
            return

    yield RuntimeEvent.error(
        _guards.stop_error()
        or RuntimeErrorData(
            kind="loop_limit",
            message=f"Превышен лимит итераций ({config.max_iterations})",
            recoverable=False,
        )
    )


async def _run_checkpoint(checkpoint: CheckpointFn | None) -> RuntimeEvent | None:
    if checkpoint is None:
        return None
    return await checkpoint()
