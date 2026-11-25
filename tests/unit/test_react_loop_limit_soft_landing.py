"""Loop-limit soft landing (open-beta-hermes-saas Sprint 1a Stage 2).

Covers REQ-LTK-005 (opt-in single toolless LLM call summarizing the turn),
REQ-LTK-006 (default path stays byte-identical to the pre-existing
``loop_limit`` error), and REQ-LTK-007 (a failed/cancelled landing call falls
back to the ``loop_limit`` error instead of fabricating a summary).

TDD red phase: written BEFORE the ``native_config["loop_limit_soft_landing"]``
branch exists in ``react_strategy.py``. Drives ``run_react`` directly (same
harness style as ``test_react_native_path.py``) rather than through
``ThinRuntime`` — ``ThinRuntime._run_impl`` re-checks cancellation after every
``tool_call_started``/``tool_call_finished``/``final`` event and would
short-circuit before the strategy-level soft-landing branch under test ever
runs.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace

import pytest
from pydantic import BaseModel, Field

from swarmline.runtime.cancellation import CancellationToken
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.finalization import CheckpointFn
from swarmline.runtime.thin.llm_client import LlmCallResult
from swarmline.runtime.thin.native_tools import (
    NativeToolCall,
    NativeToolCallAdapter,
    NativeToolCallResult,
)
from swarmline.runtime.thin.strategies import run_react
from swarmline.runtime.thin.usage import (
    begin_native_usage_scope,
    end_native_usage_scope,
    record_native_usage,
)
from swarmline.runtime.types import (
    ModelRequestOptions,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)
from swarmline.types import AcceptanceCriterion, VerificationLedger
from swarmline.verification import LedgerCodeVerifier

_TOOL_CALL_JSON = json.dumps(
    {"type": "tool_call", "tool": {"name": "noop", "args": {}}}
)
_SYSTEM_PROMPT = "SYSTEM-SENTINEL: you are a helper."
_SOFT_LANDING_INSTRUCTION = (
    "You've reached the maximum number of tool-calling iterations for this turn. "
    "Reply with a final summary: what you accomplished, what remains, and the next "
    "concrete step. Do not call any tools."
)


def _noop_tool(**kwargs: object) -> str:
    return json.dumps({"result": "ok"})


def _raise(exc: BaseException) -> str:
    raise exc


class _ScriptedLLM:
    """Tool-call JSON for the first ``max_iter`` calls; ``landing()`` answers the next one.

    ``landing`` is invoked lazily (only if a call past ``max_iter`` actually happens) so
    it can raise to simulate a failing/cancelled soft-landing call.
    """

    def __init__(self, max_iter: int, landing: Callable[[], object]) -> None:
        self._max_iter = max_iter
        self._landing = landing
        self.calls: list[tuple[list, str]] = []
        self.kwargs: list[dict[str, object]] = []

    async def __call__(self, messages: list, prompt: str, **kwargs: object) -> object:
        self.calls.append((messages, prompt))
        self.kwargs.append(kwargs)
        if len(self.calls) <= self._max_iter:
            return _TOOL_CALL_JSON
        return self._landing()


def _config(max_iter: int, **overrides: object) -> RuntimeConfig:
    base = RuntimeConfig(
        runtime_name="thin", max_iterations=max_iter, max_tool_calls=1000
    )
    return replace(base, **overrides)


async def _drive(
    llm_call: Callable[..., object],
    config: RuntimeConfig,
    checkpoint: CheckpointFn | None = None,
    native_adapter: NativeToolCallAdapter | None = None,
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in run_react(
        llm_call,
        ToolExecutor(local_tools={"noop": _noop_tool}),
        messages=[],
        system_prompt=_SYSTEM_PROMPT,
        tools=[ToolSpec(name="noop", description="do nothing", parameters={})],
        config=config,
        start_time=time.monotonic(),
        checkpoint=checkpoint,
        native_adapter=native_adapter,
    ):
        events.append(ev)
    return events


def _errors(events: list[RuntimeEvent]) -> list[RuntimeEvent]:
    return [e for e in events if e.type == "error"]


def _finals(events: list[RuntimeEvent]) -> list[RuntimeEvent]:
    return [e for e in events if e.type == "final"]


# --- REQ-LTK-006: default path is byte-identical --------------------------


@pytest.mark.asyncio
async def test_loop_limit_without_flag_emits_error_event_byte_identical() -> None:
    max_iter = 3
    llm = _ScriptedLLM(max_iter, landing=lambda: "must never be reached")
    config = _config(max_iter)

    events = await _drive(llm, config)

    error_events = _errors(events)
    assert len(error_events) == 1
    assert (
        error_events[0].data
        == RuntimeErrorData(
            kind="loop_limit",
            message=f"Превышен лимит итераций ({max_iter})",
            recoverable=False,
        ).to_dict()
    )
    assert not _finals(events)
    assert len(llm.calls) == max_iter


# --- REQ-LTK-005: opt-in single toolless call ------------------------------


@pytest.mark.asyncio
async def test_loop_limit_with_flag_makes_exactly_one_toolless_call() -> None:
    max_iter = 3
    llm = _ScriptedLLM(max_iter, landing=lambda: "Summary text.")
    config = _config(max_iter, native_config={"loop_limit_soft_landing": True})

    await _drive(llm, config)

    assert len(llm.calls) == max_iter + 1
    tool_call_prompt = llm.calls[0][1]
    landing_prompt = llm.calls[-1][1]
    # The react-built prompt embeds the JSON envelope instructions + tool schema text;
    # the landing call must use the raw system prompt instead — no tool schemas.
    assert tool_call_prompt != _SYSTEM_PROMPT
    assert "noop" in tool_call_prompt
    assert landing_prompt == _SYSTEM_PROMPT
    assert "noop" not in landing_prompt
    landing_messages = llm.calls[-1][0]
    assert landing_messages[-1] == {
        "role": "user",
        "content": _SOFT_LANDING_INSTRUCTION,
    }


@pytest.mark.asyncio
async def test_soft_landing_final_text_is_model_summary() -> None:
    max_iter = 2
    summary = "Accomplished: X. Remaining: Y. Next: Z."
    llm = _ScriptedLLM(max_iter, landing=lambda: summary)
    config = _config(max_iter, native_config={"loop_limit_soft_landing": True})

    events = await _drive(llm, config)

    finals = _finals(events)
    assert len(finals) == 1
    assert finals[0].data["text"] == summary
    assert not _errors(events)


@pytest.mark.asyncio
async def test_soft_landing_marks_exit_reason_loop_limit() -> None:
    max_iter = 2
    llm = _ScriptedLLM(max_iter, landing=lambda: "done")
    config = _config(max_iter, native_config={"loop_limit_soft_landing": True})

    events = await _drive(llm, config)

    finals = _finals(events)
    assert len(finals) == 1
    assert finals[0].data["native_metadata"] == {"exit_reason": "loop_limit"}


# --- REQ-LTK-007: failure / cancellation never fabricates a summary -------


@pytest.mark.asyncio
async def test_soft_landing_llm_failure_falls_back_to_loop_limit_error() -> None:
    max_iter = 2
    boom = ThinLlmError(
        RuntimeErrorData(
            kind="runtime_crash", message="provider exploded", recoverable=False
        )
    )
    llm = _ScriptedLLM(max_iter, landing=lambda: _raise(boom))
    config = _config(max_iter, native_config={"loop_limit_soft_landing": True})

    events = await _drive(llm, config)

    error_events = _errors(events)
    assert len(error_events) == 1
    assert error_events[0].data["kind"] == "loop_limit"
    assert not _finals(events)
    assert len(llm.calls) == max_iter + 1  # the landing attempt WAS made, just failed


@pytest.mark.asyncio
async def test_soft_landing_respects_cancellation_token() -> None:
    max_iter = 2
    token = CancellationToken()
    token.cancel()
    llm = _ScriptedLLM(max_iter, landing=lambda: "unreachable")
    config = _config(
        max_iter,
        cancellation_token=token,
        native_config={"loop_limit_soft_landing": True},
    )

    events = await _drive(llm, config)

    error_events = _errors(events)
    assert len(error_events) == 1
    assert error_events[0].data["kind"] == "loop_limit"
    assert not _finals(events)
    assert len(llm.calls) == max_iter  # cancellation caught before the landing llm_call


@pytest.mark.asyncio
async def test_soft_landing_usage_included_in_final_usage() -> None:
    max_iter = 2
    landing_usage = {"input_tokens": 42, "output_tokens": 7, "total_tokens": 49}
    llm = _ScriptedLLM(
        max_iter,
        landing=lambda: LlmCallResult(text="summary", usage=landing_usage),
    )
    config = _config(max_iter, native_config={"loop_limit_soft_landing": True})

    events = await _drive(llm, config)

    finals = _finals(events)
    assert len(finals) == 1
    usage = finals[0].data["usage"]
    assert usage["input_tokens"] == 42
    assert usage["output_tokens"] == 7
    assert usage["total_tokens"] == 49
    assert usage["estimated"] is False
    assert usage["usage_source"] == "native"


@pytest.mark.parametrize("native_records_usage", [False, True])
@pytest.mark.parametrize("landing_records_usage", [False, True])
@pytest.mark.parametrize("landing_reports_usage", [False, True])
@pytest.mark.parametrize("guards_enabled", [False, True])
async def test_soft_landing_preserves_native_run_usage_without_double_counting(
    native_records_usage: bool,
    landing_records_usage: bool,
    landing_reports_usage: bool,
    guards_enabled: bool,
) -> None:
    class _Native:
        async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
            if native_records_usage:
                record_native_usage(10_000, 1_000)
            return NativeToolCallResult(
                tool_calls=(NativeToolCall(id="c1", name="noop", args={}),),
                usage={"input_tokens": 10_000, "output_tokens": 1_000},
            )

    async def landing(messages, prompt, **kwargs):
        if landing_records_usage:
            record_native_usage(42, 7)
        if not landing_reports_usage:
            return "summary"
        return LlmCallResult(
            text="summary", usage={"input_tokens": 42, "output_tokens": 7}
        )

    scope = begin_native_usage_scope()
    try:
        events = await _drive(
            landing,
            _config(
                1,
                use_native_tools=True,
                native_config={
                    "loop_limit_soft_landing": True,
                    "loop_guards_enabled": guards_enabled,
                    "run_budget_seconds": 60,
                },
            ),
            native_adapter=_Native(),
        )
    finally:
        end_native_usage_scope(scope)

    usage = _finals(events)[0].data["usage"]
    landing_counted = landing_reports_usage or landing_records_usage
    assert usage["input_tokens"] == 10_000 + (42 if landing_counted else 0)
    assert usage["output_tokens"] == 1_000 + (7 if landing_counted else 0)
    assert usage["total_tokens"] == 11_000 + (49 if landing_counted else 0)
    assert usage["estimated"] is False


class _LandingSummary(BaseModel):
    summary: str = Field(min_length=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("typed_output", [False, True])
@pytest.mark.parametrize("verification", [None, False, True])
async def test_soft_landing_validation_config_enforces_completion_contract(
    typed_output: bool, verification: bool | None
) -> None:
    max_iter = 2
    summary = '{"summary": "Work remains."}' if typed_output else "Work remains."
    llm = _ScriptedLLM(max_iter, landing=lambda: summary)

    async def verify_output(ctx: object) -> tuple[bool, str]:
        assert getattr(ctx, "output", None) == summary
        return verification is True, "acceptance evidence"

    criterion = AcceptanceCriterion(
        id="complete", description="task accepted", kind="code", check_ref="acceptance"
    )
    config = _config(
        max_iter,
        native_config={"loop_limit_soft_landing": True},
        output_type=_LandingSummary if typed_output else None,
        verification_ledger=VerificationLedger(criteria=(criterion,)),
        verifier=(
            LedgerCodeVerifier({"acceptance": verify_output})
            if verification is not None
            else None
        ),
    )

    events = await _drive(llm, config)

    assert len(llm.calls) == max_iter + 1
    assert config.max_model_retries == 2
    if verification is False:
        assert not _finals(events)
        assert len(_errors(events)) == 1
        error = _errors(events)[0].data
        assert error["kind"] == "guardrail_tripwire"
        unmet = error["details"]["unmet"]
        assert unmet[0]["criterion_id"] == "complete"
        assert unmet[0]["reason"] == "failed"
        assert unmet[0]["evidence"] == "acceptance evidence"
    else:
        assert not _errors(events)
        assert len(_finals(events)) == 1
        final = _finals(events)[0]
        assert final.text == summary
        assert final.data["native_metadata"] == {"exit_reason": "loop_limit"}
        if typed_output:
            assert final.structured_output == _LandingSummary(summary="Work remains.")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "summary", ["not json", '{"other": "value"}', '{"summary": ""}']
)
async def test_soft_landing_invalid_typed_output_blocks_without_repair_call(
    summary: str,
) -> None:
    max_iter = 2
    llm = _ScriptedLLM(max_iter, landing=lambda: summary)
    config = _config(
        max_iter,
        native_config={"loop_limit_soft_landing": True},
        output_type=_LandingSummary,
    )

    events = await _drive(llm, config)

    assert not _finals(events)
    assert len(_errors(events)) == 1
    assert _errors(events)[0].data["kind"] == "bad_model_output"
    assert len(llm.calls) == max_iter + 1
    assert config.max_model_retries == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_mode", ["prompt", "auto", "native"])
async def test_soft_landing_typed_output_requests_schema_without_tools(
    structured_mode: str,
) -> None:
    max_iter = 2
    llm = _ScriptedLLM(max_iter, landing=lambda: '{"summary": "Next step."}')
    config = _config(
        max_iter,
        model="gpt-4o",
        native_config={"loop_limit_soft_landing": True},
        output_type=_LandingSummary,
        structured_mode=structured_mode,
        request_options=ModelRequestOptions(
            extra={"tools": [{"name": "noop"}], "tool_choice": "required"}
        ),
    )

    events = await _drive(llm, config)

    assert len(llm.calls) == max_iter + 1
    assert not _errors(events)
    assert _finals(events)[0].structured_output == _LandingSummary(summary="Next step.")
    assert "noop" not in llm.calls[-1][1]
    assert "tools" not in llm.kwargs[-1]
    assert "tool_choice" not in llm.kwargs[-1]
    if structured_mode == "prompt":
        assert '"summary"' in llm.calls[-1][1]
    else:
        assert llm.kwargs[-1]["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "_LandingSummary",
                "strict": True,
                "schema": _LandingSummary.model_json_schema(),
            },
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("extra_body", [None, {"custom_option": "retained"}])
async def test_soft_landing_nested_tools_removed_without_config_mutation(
    extra_body: dict[str, object] | None,
) -> None:
    max_iter = 2
    llm = _ScriptedLLM(max_iter, landing=lambda: "summary")
    tool_options = {
        "tools": [{"type": "function", "function": {"name": "noop"}}],
        "tool_choice": "required",
        "functions": [{"name": "legacy"}],
        "function_call": {"name": "legacy"},
        "parallel_tool_calls": False,
    }
    request_options = ModelRequestOptions(
        extra={
            **tool_options,
            "extra_body": (
                {**tool_options, **extra_body} if extra_body is not None else None
            ),
        }
    )
    original_options = deepcopy(request_options.extra)
    config = _config(
        max_iter,
        native_config={"loop_limit_soft_landing": True},
        request_options=request_options,
    )

    events = await _drive(llm, config)

    assert not _errors(events)
    assert len(_finals(events)) == 1
    assert len(llm.calls) == max_iter + 1
    assert llm.kwargs[-1].get("extra_body") == extra_body
    assert not tool_options.keys() & llm.kwargs[-1].keys()
    assert request_options.extra == original_options


@pytest.mark.asyncio
async def test_soft_landing_checkpoint_cancelled_before_call_skips_llm() -> None:
    llm = _ScriptedLLM(0, landing=lambda: "unreachable")
    cancellation = RuntimeEvent.error(
        RuntimeErrorData(kind="cancelled", message="stopped", recoverable=False)
    )

    async def checkpoint() -> RuntimeEvent | None:
        return cancellation

    # Бюджет уже исчерпан: первый checkpoint приходится на начало посадки.
    config = _config(0, native_config={"loop_limit_soft_landing": True})

    events = await _drive(llm, config, checkpoint=checkpoint)

    assert _errors(events) == [cancellation]
    assert not _finals(events)
    assert not llm.calls


@pytest.mark.asyncio
async def test_soft_landing_cancellation_during_verification_blocks_final() -> None:
    token = CancellationToken()
    max_iter = 2
    llm = _ScriptedLLM(max_iter, landing=lambda: "summary")

    async def cancel_during_verification(ctx: object) -> tuple[bool, str]:
        token.cancel()
        return True, "accepted before cancellation"

    async def checkpoint() -> RuntimeEvent | None:
        if token.is_cancelled:
            return RuntimeEvent.error(
                RuntimeErrorData(
                    kind="cancelled", message="cancelled", recoverable=False
                )
            )
        return None

    config = _config(
        max_iter,
        cancellation_token=token,
        native_config={"loop_limit_soft_landing": True},
        verification_ledger=VerificationLedger(
            criteria=(
                AcceptanceCriterion(
                    id="complete",
                    description="accepted",
                    kind="code",
                    check_ref="acceptance",
                ),
            )
        ),
        verifier=LedgerCodeVerifier({"acceptance": cancel_during_verification}),
    )

    events = await _drive(llm, config, checkpoint=checkpoint)

    assert not _finals(events)
    assert len(_errors(events)) == 1
    assert _errors(events)[0].data["kind"] == "cancelled"
    assert len(llm.calls) == max_iter + 1
