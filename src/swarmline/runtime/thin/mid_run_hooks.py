"""Mid-run control hook helpers shared by any loop kernel.

kernel-patterns spec, Task 1 (Covers REQ-010): ``should_stop_after_turn`` /
``get_steering_messages`` / ``get_followup_messages`` / ``transform_context``
are optional fields on ``RuntimeConfig`` (default None). This module builds a
normalized ``KernelContext`` snapshot of the current turn state to hand to
the ctx-based hooks, and applies ``transform_context`` to a strategy's
LM-facing message list — so any kernel (ReAct today, Plan-Execute/ADaPT/
Reflection/SGR later) can reuse the same wiring instead of duplicating it.

Every helper is a no-op passthrough when the corresponding config hook is
None — existing kernels keep byte-identical behaviour until a hook is set.

GPT-5.5 review (post-Task-1, both MAJOR) added ``run_post_turn_hooks``:
- FINDING 1: post-turn hooks (``should_stop_after_turn`` / ``get_steering_messages``)
  used to be wired ONLY into the text-ReAct branch of ``run_react`` — a native
  tool-calling turn ``continue``d immediately and never ran them. This helper is
  now called from BOTH branches so the behaviour is identical regardless of
  which path produced the turn.
- FINDING 2: a graceful stop used to yield only a ``status`` event and
  ``return`` — losing the accumulated ``new_messages``/metrics and breaking any
  consumer that requires a final-or-error terminal event. ``run_post_turn_hooks``
  now builds a terminal ``RuntimeEvent.final`` (no extra model call) whenever
  ``should_stop_after_turn`` returns True.

GPT-5.5 review round 2 (MAJOR) — the FINDING-2 stop-final above zeroed
``usage``/``metrics`` (``text=""``, ``tokens_in=tokens_out=0``). ThinRuntime's
cost tracker reads the FINAL event's ``usage``/``metrics``, so a graceful stop
after a real turn was recording 0 tokens / $0 cost and could silently miss a
budget warning/exceeded signal. ``run_post_turn_hooks`` now takes the same
``lm_messages`` / ``prompt`` / turn-output-text inputs
``finalization._make_final_event`` uses and calls the SAME
``_build_usage`` + ``_build_metrics`` building blocks to compute the
stop-final's usage — it does NOT call ``_make_final_event`` itself (that would
also append a duplicate assistant ``Message`` to ``new_messages``, which the
caller already appended, and would route through structured-output
validation/retry, which must not run on a mid-loop stop).

conformance-audit Basket 1 item 6 (plan stage 30) — ``transform_context`` was
an open seam: a raw ``Callable[[list], list]`` with no contract stopping a
future implementation from mutating/reordering/dropping the stable prefix of
``lm_messages``, silently breaking build-once / KV-cache prompt stability for
every consumer that hashes or caches on the message prefix. 0 real consumers
exist today (grep-verified across swarmline + taskloom) — closed cheaply now
with a prefix-immutable, tail-append-only contract enforced directly inside
``apply_transform_context`` (see its docstring and
``TransformContextContractError``).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.finalization import CheckpointFn, _build_usage
from swarmline.runtime.thin.helpers import _build_metrics, _messages_to_lm
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec
from swarmline.types import KernelContext

if TYPE_CHECKING:
    from swarmline.hooks.dispatcher import HookDispatcher
    from swarmline.runtime.thin.native_tools import NativeToolCallAdapter

__all__ = [
    "PostTurnHookOutcome",
    "TransformContextContractError",
    "apply_transform_context",
    "build_turn_snapshot",
    "maybe_followup_requeue",
    "run_post_turn_hooks",
]


class TransformContextContractError(RuntimeError):
    """Raised when a ``transform_context`` hook mutates the stable prefix.

    Contract (conformance-audit Basket 1 item 6 / plan stage 30):
    ``transform_context`` may only APPEND new entries to the TAIL of
    ``lm_messages`` — every entry already present before the call must come
    back byte-identical, in the same order, at the head of the returned
    list. Reordering, rewriting, or dropping any pre-existing entry breaks
    build-once / KV-cache prompt-prefix stability for any runtime/provider
    that caches on the message prefix, so it is rejected rather than allowed
    to silently corrupt the prefix.
    """


async def _noop_checkpoint() -> RuntimeEvent | None:
    """Fallback ``CheckpointFn`` used only inside ``build_turn_snapshot``.

    ``KernelContext.checkpoint`` is a required field, but a strategy's own
    ``checkpoint`` parameter is optional (``None`` when the caller does not
    use durable checkpointing). This stands in so the read-only hook
    snapshot always satisfies the KernelContext contract — it is never
    registered as the loop's actual checkpoint and never persists anything.
    """
    return None


def build_turn_snapshot(
    *,
    llm_call: Callable[..., Any],
    messages: list[Message],
    new_messages: list[Message],
    system_prompt: str,
    config: RuntimeConfig,
    start_time: float,
    checkpoint: CheckpointFn | None,
    executor: ToolExecutor | None = None,
    tools: list[ToolSpec] | None = None,
    on_retry: Callable[..., Any] | None = None,
    native_adapter: NativeToolCallAdapter | None = None,
    session_dispatcher: HookDispatcher | None = None,
) -> KernelContext:
    """Build a read-only ``KernelContext`` snapshot of the turn so far.

    Passed to ``should_stop_after_turn`` / ``get_steering_messages`` /
    ``get_followup_messages`` (REQ-010) so mid-run hooks see the same
    normalized shape as the top-level dispatch ``KernelContext`` — built
    purely from the calling strategy's own locals, no duplicated state.
    ``messages`` is the original turn input plus every ``Message`` the
    strategy has accumulated so far this run (conversation-so-far view).
    """
    return KernelContext(
        llm_call=llm_call,
        messages=[*messages, *new_messages],
        system_prompt=system_prompt,
        config=config,
        start_time=start_time,
        checkpoint=checkpoint if checkpoint is not None else _noop_checkpoint,
        executor=executor,
        tools=tools,
        on_retry=on_retry,
        native_adapter=native_adapter,
        session_dispatcher=session_dispatcher,
    )


def apply_transform_context(
    config: RuntimeConfig, lm_messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Apply ``config.transform_context`` to *lm_messages* before a model call.

    No-op passthrough when the hook is unset (default None) — byte-identical
    to pre-H4 behaviour.

    Contract (conformance-audit Basket 1 item 6 / plan stage 30): the hook
    may ONLY append new entries to the TAIL of *lm_messages*. Every entry
    already present in *lm_messages* before the call MUST be returned
    byte-identical and in the same order, at the head of the result — this
    protects build-once / KV-cache prompt-prefix stability, which a pruning/
    reordering/rewriting hook would silently break. Enforced on every call
    (0 real consumers set this hook today, so this closes the seam before
    anything can rely on the unsafe behaviour). A ``baseline`` deep copy is
    taken of *lm_messages* BEFORE the hook runs (fixed verify-cycle finding 1:
    comparing against the live *lm_messages* object AFTER the call let a hook
    that mutates in place — top-level or nested — and returns the SAME list
    object pass the check, since the list would then equal itself). Only the
    ``transform_context is None`` no-op path stays copy-free — the deepcopy
    cost is paid only when a hook is actually set.

    The hook's return value is materialized to a plain ``list`` via
    ``list(...)`` EXACTLY ONCE, and that SAME materialized list is both
    validated AND returned (fixed GPT-5.5 review finding 2: validating a
    slice of the returned OBJECT — e.g. ``transformed[:prefix_len]`` — then
    separately returning that same object trusts the object's own
    ``__getitem__``; a container whose slice access reports an honest prefix
    while iteration/materialization (what ``list()`` and every downstream
    consumer actually reads) exposes different, tampered content could
    smuggle a poisoned prefix past a slice-only check). Materializing once
    and reusing that result for both the check and the return value means
    there is only one canonical view of the data — nothing downstream can
    observe anything other than what was validated.

    Scope boundary (deliberate, not a gap): this contract compares message
    entries by ``!=`` (structural/value equality of plain dict content). It
    does not, and is not intended to, defend against an entry object with a
    deliberately deceptive ``__eq__``/``__hash__`` that reports equal to the
    baseline while actually differing when later read by the LLM call —
    ``lm_messages`` entries are plain ``dict``s in every real caller, and
    guarding against adversarial custom value objects here would add
    complexity with no real consumer to protect against.

    Raises ``TransformContextContractError`` — instead of silently
    corrupting the prefix — when the materialized list's head does not
    match the baseline.
    """
    if config.transform_context is None:
        return lm_messages
    prefix_len = len(lm_messages)
    baseline = copy.deepcopy(lm_messages)
    transformed_list = list(config.transform_context(lm_messages))
    if transformed_list[:prefix_len] != baseline:
        raise TransformContextContractError(
            f"transform_context must not mutate, reorder, or drop any of the "
            f"original {prefix_len} message(s) — it may only append new "
            "entries to the tail (build-once/KV-cache prefix stability "
            "contract, conformance-audit Basket 1 item 6)."
        )
    return transformed_list


@dataclass(frozen=True)
class PostTurnHookOutcome:
    """Result of running post-turn mid-run hooks after a completed tool-call turn.

    Returned by ``run_post_turn_hooks`` so the CALLER (native tool-calling
    branch or text-ReAct branch of ``run_react``) decides what to yield and
    whether to keep looping — the helper itself never yields; it is a plain
    (side-effect-free) function so both branches can share it identically.

    * ``should_stop`` — True when ``should_stop_after_turn`` fired. The caller
      must yield ``stop_status_event`` then ``stop_final_event`` (both are
      always set together when ``should_stop`` is True) and ``return``.
    * ``steering_lm_messages`` — LM-facing messages (already lowered via
      ``_messages_to_lm``) to append to ``lm_messages`` before the NEXT model
      call. Empty when ``get_steering_messages`` is unset or stopping.
    """

    should_stop: bool
    stop_status_event: RuntimeEvent | None = None
    stop_final_event: RuntimeEvent | None = None
    steering_lm_messages: list[dict[str, Any]] = field(default_factory=list)


def run_post_turn_hooks(
    *,
    config: RuntimeConfig,
    llm_call: Callable[..., Any],
    messages: list[Message],
    new_messages: list[Message],
    system_prompt: str,
    start_time: float,
    checkpoint: CheckpointFn | None,
    iterations: int,
    tool_calls_count: int,
    lm_messages: list[dict[str, Any]],
    prompt: str,
    turn_text: str = "",
    executor: ToolExecutor | None = None,
    tools: list[ToolSpec] | None = None,
    on_retry: Callable[..., Any] | None = None,
    native_adapter: NativeToolCallAdapter | None = None,
    session_dispatcher: HookDispatcher | None = None,
) -> PostTurnHookOutcome:
    """Run ``should_stop_after_turn`` / ``get_steering_messages`` after a turn.

    Shared by BOTH the native tool-calling branch and the text-ReAct branch of
    ``run_react`` (GPT-5.5 review FINDING 1 — native turns previously skipped
    these hooks entirely because the native branch ``continue``d immediately).

    No-op passthrough (``should_stop=False``, no events, no steering messages)
    when BOTH hooks are unset (default None) — the ``KernelContext`` snapshot
    is not even built in that case, so default behaviour stays byte-identical
    and costs nothing extra. ``lm_messages``/``prompt``/``turn_text`` are not
    even read in this early-return path.

    On a graceful stop, builds a terminal ``RuntimeEvent.final`` that preserves
    the accumulated ``new_messages`` (GPT-5.5 review FINDING 2 — a stop used to
    yield only a ``status`` event and lose everything gathered so far) AND
    carries real usage/metrics (GPT-5.5 review ROUND 2 MAJOR — a stop used to
    zero ``tokens_in``/``tokens_out``/usage, which made ThinRuntime's cost
    tracker record $0 and silently miss budget signalling).

    ``lm_messages`` (the LM-facing running conversation, already updated with
    this turn's own tool-call/tool-result entries by the caller) and ``prompt``
    (the system prompt actually used for this turn's LLM call — the built
    react prompt on the text path, ``native_loop_prompt`` on the native path)
    together with ``turn_text`` (the raw text this turn's LLM call produced —
    e.g. the raw JSON-envelope response on the text path, ``native_result.text``
    on the native path) are fed into ``finalization._build_usage`` — the EXACT
    same helper ``finalization._make_final_event`` uses on a normal loop exit —
    so the resulting ``usage``/``metrics`` are computed via the SAME path, not
    hand-rolled. ``_make_final_event`` itself is deliberately NOT called here:
    it also appends a new assistant ``Message`` to ``new_messages`` (the caller
    already appended this turn's messages — that would duplicate) and routes
    through structured-output validation/retry, which must not run on a
    mid-loop stop (no extra model call is acceptable here).
    """
    if config.should_stop_after_turn is None and config.get_steering_messages is None:
        return PostTurnHookOutcome(should_stop=False)

    turn_ctx = build_turn_snapshot(
        llm_call=llm_call,
        messages=messages,
        new_messages=new_messages,
        system_prompt=system_prompt,
        config=config,
        start_time=start_time,
        checkpoint=checkpoint,
        executor=executor,
        tools=tools,
        on_retry=on_retry,
        native_adapter=native_adapter,
        session_dispatcher=session_dispatcher,
    )

    if config.should_stop_after_turn is not None and config.should_stop_after_turn(
        turn_ctx
    ):
        usage = _build_usage(lm_messages, prompt, turn_text)
        metrics = _build_metrics(
            start_time,
            config,
            iterations=iterations,
            tool_calls=tool_calls_count,
            tokens_in=usage["input_tokens"],
            tokens_out=usage["output_tokens"],
        )
        final_event = RuntimeEvent.final(
            text="",
            new_messages=list(new_messages),
            metrics=metrics,
            usage=usage,
        )
        return PostTurnHookOutcome(
            should_stop=True,
            stop_status_event=RuntimeEvent.status("stopped_after_turn"),
            stop_final_event=final_event,
        )

    steering_lm_messages: list[dict[str, Any]] = []
    if config.get_steering_messages is not None:
        steering = config.get_steering_messages(turn_ctx)
        if steering:
            steering_lm_messages = _messages_to_lm(steering)

    return PostTurnHookOutcome(
        should_stop=False, steering_lm_messages=steering_lm_messages
    )


def maybe_followup_requeue(
    *,
    config: RuntimeConfig,
    llm_call: Callable[..., Any],
    messages: list[Message],
    new_messages: list[Message],
    system_prompt: str,
    start_time: float,
    checkpoint: CheckpointFn | None,
    executor: ToolExecutor | None = None,
    tools: list[ToolSpec] | None = None,
    on_retry: Callable[..., Any] | None = None,
    native_adapter: NativeToolCallAdapter | None = None,
    session_dispatcher: HookDispatcher | None = None,
) -> list[dict[str, Any]] | None:
    """Follow-up messages to requeue at a natural end of the loop, or None.

    kernel-wiring spec, Task 1 (I-008, Requirement 1). Third member of the
    ``run_post_turn_hooks``/``build_turn_snapshot`` mid-run-hook family: called
    from BOTH natural-end seams of ``run_react`` (the text-ReAct ``final``
    envelope and the native tool-calling loop finishing with no further tool
    calls) right before the existing finalize call.

    No-op passthrough (``None``, NO ``KernelContext`` snapshot built) when
    ``config.get_followup_messages`` is unset — byte-identical default
    (REQ-003), mirroring ``run_post_turn_hooks``'s own early-return
    (mid_run_hooks.py:205) when both of its hooks are unset. Every other
    input here is read only after that guard, so an unset hook costs nothing
    extra.

    When the hook is set, builds the SAME ``KernelContext`` snapshot
    ``run_post_turn_hooks`` builds (via ``build_turn_snapshot``), calls
    ``config.get_followup_messages(ctx)``, and returns the result LOWERED to
    lm-message dict form via ``_messages_to_lm`` — ready to ``extend`` onto
    the strategy's own ``lm_messages``. A ``None``/empty result from the hook
    is returned as ``None`` so the caller's ``if requeue:`` guard is falsy and
    control falls through to the unchanged finalize path.

    The CALLER (``run_react``) decides what happens next: a truthy result is
    appended to ``lm_messages`` and the loop ``continue``s; the loop's own
    ``iterations < config.max_iterations`` budget gate (react_strategy.py:130,
    unchanged, no fresh counter) is what guarantees termination (REQ-002) —
    this helper never yields events and never touches iteration state.
    """
    if config.get_followup_messages is None:
        return None

    turn_ctx = build_turn_snapshot(
        llm_call=llm_call,
        messages=messages,
        new_messages=new_messages,
        system_prompt=system_prompt,
        config=config,
        start_time=start_time,
        checkpoint=checkpoint,
        executor=executor,
        tools=tools,
        on_retry=on_retry,
        native_adapter=native_adapter,
        session_dispatcher=session_dispatcher,
    )

    result = config.get_followup_messages(turn_ctx)
    return _messages_to_lm(result) if result else None
