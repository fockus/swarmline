"""Planner strategy -- plan JSON -> step execution -> final assembly."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Callable
from typing import Any

from swarmline.runtime.structured_output import append_structured_output_instruction
from swarmline.runtime.thin.conversational import run_conversational
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.finalization import CheckpointFn, finalize_with_validation
from swarmline.runtime.thin.helpers import _messages_to_lm
from swarmline.runtime.thin.parsers import parse_envelope, parse_plan
from swarmline.runtime.thin.prompts import (
    build_final_assembly_prompt,
    build_plan_step_prompt,
    build_planner_prompt,
)
from swarmline.runtime.thin.react_strategy import run_react
from swarmline.runtime.thin.schemas import PlanSchema
from swarmline.runtime.thin.verification_capture import ledger_from_plan
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)


def _capture_plan_ledger(config: RuntimeConfig, plan: PlanSchema) -> RuntimeConfig:
    """Return a config carrying a plan-derived verification ledger, or *config* unchanged.

    kernel-wiring spec, Task 2 (I-034, REQ-005..008). Wires the previously
    orphaned :func:`~swarmline.runtime.thin.verification_capture.ledger_from_plan`
    into the planner's FINAL-assembly finalize path so a caller who opted
    into verification (``config.verifier`` set) gets a ledger derived from
    the plan's own ``success_criteria`` without hand-authoring one.

    Returns *config* unchanged (same object, no-op) when:

    * ``config.verifier is None`` (REQ-007) — verify-before-done stays
      opt-in; we never populate a ledger the gate would act on unless the
      caller also supplied a verifier.
    * ``config.verification_ledger is not None`` (REQ-006) — a
      caller-supplied ledger is never overridden.

    Otherwise returns ``dataclasses.replace(config,
    verification_ledger=ledger_from_plan(plan))`` — a NEW ``RuntimeConfig``
    instance; the caller's *config* is never mutated (REQ-005/REQ-008).
    """
    if config.verifier is None:
        return config
    if config.verification_ledger is not None:
        return config
    return dataclasses.replace(config, verification_ledger=ledger_from_plan(plan))


async def run_planner(
    llm_call: Callable[..., Any],
    executor: ToolExecutor,
    messages: list[Message],
    system_prompt: str,
    tools: list[ToolSpec],
    config: RuntimeConfig,
    start_time: float,
    checkpoint: CheckpointFn | None = None,
) -> AsyncIterator[RuntimeEvent]:
    """Planner-lite: plan -> step execution -> final assembly."""
    # Step 1: get plan from LLM
    prompt = build_planner_prompt(system_prompt, tools)
    lm_messages = _messages_to_lm(messages)

    try:
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return
        raw = await llm_call(lm_messages, prompt)
    except ThinLlmError as exc:
        yield RuntimeEvent.error(exc.error)
        return
    checkpoint_event = await _run_checkpoint(checkpoint)
    if checkpoint_event is not None:
        yield checkpoint_event
        return
    plan = parse_plan(raw)

    if plan is None:
        # Retry
        try:
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            raw = await llm_call(lm_messages, prompt)
        except ThinLlmError as exc:
            yield RuntimeEvent.error(exc.error)
            return
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return
        plan = parse_plan(raw)

    if plan is None:
        yield RuntimeEvent.error(
            RuntimeErrorData(
                kind="bad_model_output",
                message="LLM did not return a valid plan after 2 attempts",
                recoverable=False,
            )
        )
        return

    # Convergence point: `plan` is now guaranteed non-None regardless of
    # whether it parsed on the first attempt or the retry above (REQ-005).
    finalize_config = _capture_plan_ledger(config, plan)

    yield RuntimeEvent.status(f"План: {plan.goal} ({len(plan.steps)} шагов)")
    steps_preview = " -> ".join(
        f"{idx}. {step.title} [{step.mode}]"
        for idx, step in enumerate(plan.steps, start=1)
    )
    if steps_preview:
        yield RuntimeEvent.status(f"Следующие шаги: {steps_preview}")

    step_results: list[str] = []
    new_messages: list[Message] = []
    total_tool_calls = 0

    for idx, step in enumerate(plan.steps, start=1):
        yield RuntimeEvent.status(
            f"Шаг {idx}/{len(plan.steps)}: {step.title} (режим: {step.mode})"
        )

        step_context = (
            "\n".join(step_results) if step_results else "Нет предыдущих шагов."
        )

        step_config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=step.max_iterations,
            max_tool_calls=config.max_tool_calls - total_tool_calls,
            max_model_retries=config.max_model_retries,
            model=config.model,
        )

        step_text = ""

        if step.mode == "react":
            async for event in run_react(
                llm_call,
                executor,
                messages,
                system_prompt=build_plan_step_prompt(
                    system_prompt,
                    step.title,
                    step_context,
                    tools,
                ),
                tools=tools,
                config=step_config,
                start_time=start_time,
                checkpoint=checkpoint,
            ):
                if event.type in (
                    "tool_call_started",
                    "tool_call_finished",
                    "status",
                    "assistant_delta",
                ):
                    yield event
                elif event.type == "final":
                    step_text = event.data.get("text", "")
                    total_tool_calls += event.data.get("metrics", {}).get(
                        "tool_calls_count", 0
                    )
                elif event.type == "error":
                    yield event
                    return
        else:
            # conversational sub-step
            async for event in run_conversational(
                llm_call,
                messages,
                system_prompt=build_plan_step_prompt(
                    system_prompt,
                    step.title,
                    step_context,
                    [],
                ),
                config=step_config,
                start_time=start_time,
                checkpoint=checkpoint,
            ):
                if event.type == "assistant_delta":
                    yield event
                elif event.type == "final":
                    step_text = event.data.get("text", "")
                elif event.type == "error":
                    yield event
                    return

        step_results.append(step_text)

    assembly_prompt = build_final_assembly_prompt(
        append_structured_output_instruction(
            system_prompt,
            config.output_format,
            final_response_field="final_message",
        ),
        plan.goal,
        step_results,
        plan.final_format,
    )
    try:
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return
        raw = await llm_call(lm_messages, assembly_prompt)
    except ThinLlmError as exc:
        yield RuntimeEvent.error(exc.error)
        return
    checkpoint_event = await _run_checkpoint(checkpoint)
    if checkpoint_event is not None:
        yield checkpoint_event
        return
    envelope = parse_envelope(raw)

    if envelope and envelope.type == "final" and envelope.final_message:
        final_text = envelope.final_message
    else:
        final_text = raw  # fallback

    checkpoint_event = await _run_checkpoint(checkpoint)
    if checkpoint_event is not None:
        yield checkpoint_event
        return
    yield RuntimeEvent.assistant_delta(final_text)
    async for event in finalize_with_validation(
        final_text,
        finalize_config,
        lm_messages,
        assembly_prompt,
        llm_call,
        start_time,
        iterations=len(plan.steps) + 2,
        tool_calls=total_tool_calls,
        new_messages_prefix=new_messages,
        checkpoint=checkpoint,
    ):
        yield event


async def _run_checkpoint(checkpoint: CheckpointFn | None) -> RuntimeEvent | None:
    if checkpoint is None:
        return None
    return await checkpoint()
