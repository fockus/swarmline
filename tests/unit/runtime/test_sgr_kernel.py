"""TDD tests for kernel-patterns spec, Task 5 — SGRKernel.

Covers REQ-004, REQ-011, Scenario 2 (SGR ведёт цикл по typed NextStep: SGR
makes ``NextStep`` the control-flow DRIVER — swarmline's existing
``parse_nextstep`` — instead of mere metadata). Written BEFORE the
implementation (TDD RED -> GREEN); see ``SGRKernel`` in
``swarmline.runtime.thin.kernels.sgr`` for the design rationale.

Mirrors ``tests/unit/runtime/test_adapt_kernel.py`` /
``test_reflection_kernel.py``'s style: fakes content-branch on the (real,
composed) prompt so the resulting event sequence proves genuine
control-flow, not a tautology of a fixed response list. TOOL_CALL/FINAL
delegation is proven two ways: (a) a monkeypatched ``run_react`` sentinel
proves SGR actually calls it and forwards its events untouched, and (b) a
REAL ``run_react`` + fake ``llm_call`` proves usage/metrics parity
end-to-end (H4-Task1 bug class regression guard).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from swarmline.domain_types import RuntimeEvent
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.types import RuntimeConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SGR_MARKER = "SGR NextStep Output"  # from nextstep_system_instruction()


async def _noop_checkpoint() -> RuntimeEvent | None:
    return None


def _make_context(**overrides: Any) -> Any:
    """Build a minimal valid KernelContext for testing (real ToolExecutor)."""
    from swarmline.types import KernelContext

    defaults: dict[str, Any] = {
        "llm_call": None,
        "messages": [],
        "system_prompt": "You are a helper.",
        "config": RuntimeConfig(runtime_name="thin"),
        "start_time": 0.0,
        "checkpoint": _noop_checkpoint,
        "executor": ToolExecutor(),
    }
    defaults.update(overrides)
    return KernelContext(**defaults)


def _nextstep_json(
    action: str,
    confidence: float = 0.8,
    reasoning: str = "because reasons",
    current_state: str = "observing the task",
) -> str:
    """Build a valid NextStep JSON payload (matches nextstep.py's schema)."""
    return json.dumps(
        {
            "current_state": current_state,
            "plan": ["step-1"],
            "options": ["optA", "optB"],
            "reasoning": reasoning,
            "action": action,
            "confidence": confidence,
        }
    )


def _react_final_envelope(text: str) -> str:
    """A valid run_react ReAct-envelope JSON that resolves to a final."""
    return json.dumps({"type": "final", "final_message": text})


# ===========================================================================
# Construction — fail-fast max_steps validation (mirrors ADaPT/Reflection)
# ===========================================================================


class TestSGRKernelConstruction:
    def test_max_steps_zero_raises_value_error_at_construction(self) -> None:
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        with pytest.raises(ValueError):
            SGRKernel(max_steps=0)

    def test_max_steps_negative_raises_value_error_at_construction(self) -> None:
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        with pytest.raises(ValueError):
            SGRKernel(max_steps=-1)

    def test_run_raises_value_error_when_executor_is_none(self) -> None:
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        ctx = _make_context(executor=None)
        kernel = SGRKernel()
        with pytest.raises(ValueError):
            kernel.run(ctx)


# ===========================================================================
# ExecutionKernel Protocol conformance (domain contract)
# ===========================================================================


class TestSGRKernelExecutionKernelProtocol:
    def test_sgr_kernel_satisfies_execution_kernel_protocol(self) -> None:
        from swarmline.protocols.kernel import ExecutionKernel
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        assert isinstance(SGRKernel(), ExecutionKernel)


# ===========================================================================
# Scenario 2 / REQ-004 — control flow driven by NextStep.action
# ===========================================================================


class TestSGRDrivesControlFlowByNextStepAction:
    async def test_sgr_drives_control_flow_by_nextstep_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """action=TOOL_CALL + a confidence value delegates this turn to
        run_react: SGR emits an observable 'TOOL_CALL' status BEFORE
        delegating, run_react is actually invoked (sentinel event proves
        it), and its terminal final is surfaced untouched."""
        import swarmline.runtime.thin.kernels.sgr as sgr_module
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            assert _SGR_MARKER in prompt
            return _nextstep_json("TOOL_CALL", confidence=0.77)

        react_calls: list[tuple[Any, ...]] = []

        async def fake_run_react(*args: Any, **kwargs: Any) -> Any:
            react_calls.append(args)
            yield RuntimeEvent.status("SENTINEL_REACT_STARTED")
            yield RuntimeEvent.final("TOOL_RESULT")

        monkeypatch.setattr(sgr_module, "run_react", fake_run_react)

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 1, (
            f"Expected exactly ONE NextStep generation; got {gen_calls}"
        )
        assert len(react_calls) == 1, (
            f"Expected run_react delegated exactly once; got {len(react_calls)}"
        )
        # run_react must be delegated on the ORIGINAL system_prompt (index 3
        # of the positional call — llm_call, executor, messages, system_prompt).
        assert react_calls[0][3] == "You are a helper."

        statuses = [ev for ev in events if ev.type == "status"]
        assert any("TOOL_CALL" in s.text and "0.77" in s.text for s in statuses), (
            f"Expected an observable status naming the TOOL_CALL branch and "
            f"its confidence; got: {statuses}"
        )
        sentinel_statuses = [s for s in statuses if s.text == "SENTINEL_REACT_STARTED"]
        assert len(sentinel_statuses) == 1, (
            f"run_react's own forwarded events must appear in the stream; got: {events}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "TOOL_RESULT"

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], (
            f"No error expected on a clean TOOL_CALL delegation; got: {errors}"
        )

        # Ordering: SGR's own branch-choice status precedes run_react's forwarded events.
        branch_idx = events.index(
            next(s for s in statuses if "TOOL_CALL" in s.text and "0.77" in s.text)
        )
        sentinel_idx = events.index(sentinel_statuses[0])
        assert branch_idx < sentinel_idx

    async def test_final_action_delegates_to_react_and_surfaces_untouched_final(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """action=FINAL also delegates to run_react (NextStep carries no
        answer text of its own) and surfaces its terminal untouched."""
        import swarmline.runtime.thin.kernels.sgr as sgr_module
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            return _nextstep_json("FINAL", confidence=0.91)

        react_calls: list[tuple[Any, ...]] = []

        async def fake_run_react(*args: Any, **kwargs: Any) -> Any:
            react_calls.append(args)
            yield RuntimeEvent.final("FINALIZED_ANSWER")

        monkeypatch.setattr(sgr_module, "run_react", fake_run_react)

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert len(react_calls) == 1
        statuses = [ev for ev in events if ev.type == "status"]
        assert any("FINAL" in s.text and "0.91" in s.text for s in statuses)

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1
        assert finals[0].data.get("text") == "FINALIZED_ANSWER"

    async def test_ask_clarification_action_yields_user_input_requested_terminal(
        self,
    ) -> None:
        """action=ASK_CLARIFICATION yields a terminal user_input_requested
        carrying step.reasoning/step.current_state — no run_react call."""
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            return _nextstep_json(
                "ASK_CLARIFICATION",
                reasoning="need the target file path",
                current_state="stuck at step 2",
            )

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 1
        assert len(events) == 1, f"Expected exactly ONE terminal event; got: {events}"
        assert events[0].type == "user_input_requested"
        prompt_text = events[0].data.get("prompt", "")
        assert "need the target file path" in prompt_text
        assert "stuck at step 2" in prompt_text

    async def test_fail_action_yields_terminal_error(self) -> None:
        """action=FAIL yields a terminal error carrying step.reasoning."""
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            return _nextstep_json("FAIL", reasoning="cannot access resource X")

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert len(events) == 1, f"Expected exactly ONE terminal event; got: {events}"
        assert events[0].is_error
        assert events[0].data["kind"] == "runtime_crash", (
            f"FAIL error-kind mapping is fixed to 'runtime_crash' (see module "
            f"docstring); got: {events[0].data['kind']!r}"
        )
        assert "cannot access resource X" in events[0].data.get("message", "")

    async def test_replan_action_loops_and_regenerates_nextstep(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """action=REPLAN emits a status and loops — a NEW NextStep is
        generated next iteration — bounded by max_steps; eventually
        resolving via TOOL_CALL proves the loop actually re-drives."""
        import swarmline.runtime.thin.kernels.sgr as sgr_module
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            if gen_calls < 3:
                return _nextstep_json("REPLAN", reasoning=f"replan #{gen_calls}")
            return _nextstep_json("TOOL_CALL", confidence=0.5)

        async def fake_run_react(*args: Any, **kwargs: Any) -> Any:
            yield RuntimeEvent.final("DONE_AFTER_REPLAN")

        monkeypatch.setattr(sgr_module, "run_react", fake_run_react)

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel(max_steps=5)
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 3, (
            f"Expected exactly 3 NextStep generations; got {gen_calls}"
        )
        replan_statuses = [
            ev for ev in events if ev.type == "status" and "REPLAN" in ev.text
        ]
        assert len(replan_statuses) == 2, (
            f"Expected exactly 2 REPLAN status events; got: {replan_statuses}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1
        assert finals[0].data.get("text") == "DONE_AFTER_REPLAN"


# ===========================================================================
# REQ-011 — parse failure / unrecognised action fall back to ReAct
# ===========================================================================


class TestSGRFallsBackToReactOnParseFailure:
    async def test_sgr_falls_back_to_react_on_parse_failure(self) -> None:
        """A raw response that is not valid NextStep JSON must fall back to
        REAL ReAct handling (REQ-011) — the turn COMPLETES via run_react's
        own terminal, NOT a failure. Uses the REAL run_react (no
        monkeypatch) + a content-branching fake llm_call, and asserts the
        fallback ran on the ORIGINAL system_prompt (no SGR instrumentation
        leaking through — ctx.system_prompt is never mutated)."""
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        prompts: list[str] = []

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            prompts.append(prompt)
            if _SGR_MARKER in prompt:
                return "this is not json at all, just prose garbage"
            return _react_final_envelope("FALLBACK_OK")

        original_prompt = "You are a helper."
        ctx = _make_context(llm_call=llm_call, system_prompt=original_prompt)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "FALLBACK_OK"

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], (
            f"Parse failure must fall back to ReAct, never fail the turn; got: {errors}"
        )

        # The fallback's own prompt (2nd llm_call, run_react's real prompt
        # builder) must be derived from the ORIGINAL system_prompt, not the
        # SGR-instrumented one -- and ctx itself is untouched (frozen dataclass).
        assert len(prompts) == 2
        assert _SGR_MARKER not in prompts[1]
        assert original_prompt in prompts[1]
        assert ctx.system_prompt == original_prompt

    async def test_unknown_action_falls_back_to_react(self) -> None:
        """An unrecognised action string is exactly as untrustworthy as
        unparseable JSON (REQ-011 spirit) — falls back to ReAct."""
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            if _SGR_MARKER in prompt:
                return _nextstep_json("TELEPORT")
            return _react_final_envelope("FALLBACK_UNKNOWN_ACTION_OK")

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1
        assert finals[0].data.get("text") == "FALLBACK_UNKNOWN_ACTION_OK"

        errors = [ev for ev in events if ev.is_error]
        assert errors == []


# ===========================================================================
# Delegated run_react errors propagate — no swallowing, no retry-as-REPLAN
# ===========================================================================


class TestSGRPropagatesDelegatedReactErrors:
    async def test_tool_call_run_react_error_propagates_without_swallowing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import swarmline.runtime.thin.kernels.sgr as sgr_module
        from swarmline.runtime.thin.kernels.sgr import SGRKernel
        from swarmline.runtime.types import RuntimeErrorData

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            return _nextstep_json("TOOL_CALL", confidence=0.6)

        react_calls = 0

        async def fake_run_react(*args: Any, **kwargs: Any) -> Any:
            nonlocal react_calls
            react_calls += 1
            yield RuntimeEvent.error(
                RuntimeErrorData(kind="tool_error", message="tool blew up")
            )

        monkeypatch.setattr(sgr_module, "run_react", fake_run_react)

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 1, "No retry generation once a delegated error is seen"
        assert react_calls == 1

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "tool_error", (
            f"The delegated error's kind must be propagated untouched; got: {errors[0].data}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], "No success should be reported when run_react errored"


# ===========================================================================
# _delegate() zero-terminal safety net — dead-by-default stuck-escalation
# corner (react_strategy.py:616-620) must never end SGR's turn with zero
# terminals (MAJOR verify-stage finding).
# ===========================================================================


class TestSGRDelegateSynthesizesTerminalWhenReactYieldsNone:
    async def test_delegate_synthesizes_error_terminal_when_react_ends_without_terminal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates react_strategy.py's opt-in "stuck escalation" corner:
        run_react's stream ends after a status event with NO final and NO
        error at all. SGRKernel's _delegate() must synthesize exactly one
        terminal error (kind="runtime_crash") rather than silently ending
        the turn with zero terminals -- mirrors reflection.py:222-233's
        `generated is None` guard exactly."""
        import swarmline.runtime.thin.kernels.sgr as sgr_module
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            return _nextstep_json("TOOL_CALL", confidence=0.5)

        async def fake_run_react_no_terminal(*args: Any, **kwargs: Any) -> Any:
            yield RuntimeEvent.status("stuck_escalated: give up gracefully")
            # No final, no error -- simulates react_strategy.py:616-620's
            # `if not recovery.should_continue: ...; return` corner.

        monkeypatch.setattr(sgr_module, "run_react", fake_run_react_no_terminal)

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        terminals = [ev for ev in events if ev.is_final or ev.is_error]
        assert len(terminals) == 1, (
            f"Expected exactly ONE terminal event synthesized when the "
            f"delegated run_react stream ends without one; got: {events}"
        )
        assert terminals[0].is_error
        assert terminals[0].data.get("kind") == "runtime_crash"
        assert terminals[0] is events[-1], (
            f"The synthesized terminal must be the LAST event; got: {events}"
        )


# ===========================================================================
# ThinLlmError during the NextStep-generation ctx.llm_call is surfaced as
# that exact terminal error (mirrors test_adapt_kernel.py's ~677-690 /
# test_reflection_kernel.py's ~536-560 ThinLlmError coverage).
# ===========================================================================


class TestSGRNextStepGenerationLlmErrorPropagates:
    async def test_thin_llm_error_during_nextstep_generation_surfaces_as_terminal_error(
        self,
    ) -> None:
        """ctx.llm_call raising ThinLlmError while generating a NextStep
        (sgr.py's own try/except, BEFORE any run_react delegation) must
        surface as that exact terminal error -- no hang, no silent
        swallow, no run_react call at all."""
        from swarmline.runtime.thin.errors import ThinLlmError
        from swarmline.runtime.thin.kernels.sgr import SGRKernel
        from swarmline.runtime.types import RuntimeErrorData

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            raise ThinLlmError(
                RuntimeErrorData(kind="mcp_timeout", message="provider timed out")
            )

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 1, "No retry generation once ThinLlmError is raised"
        assert len(events) == 1, f"Expected exactly ONE terminal event; got: {events}"
        assert events[0].is_error
        assert events[0].data.get("kind") == "mcp_timeout", (
            f"The raised ThinLlmError's kind must be surfaced untouched; "
            f"got: {events[0].data}"
        )
        assert "provider timed out" in events[0].data.get("message", "")


# ===========================================================================
# Checkpoint discipline — before AND after the NextStep-generation llm_call
# ===========================================================================


class TestSGRChecksCheckpointAroundNextStepGeneration:
    async def test_checkpoint_cancel_before_llm_call_skips_generation(self) -> None:
        from swarmline.runtime.thin.kernels.sgr import SGRKernel
        from swarmline.runtime.thin.runtime_support import cancelled_event

        class _CancelledToken:
            is_cancelled = True

        async def checkpoint() -> RuntimeEvent | None:
            return cancelled_event(_CancelledToken())

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            return _nextstep_json("TOOL_CALL")  # pragma: no cover

        ctx = _make_context(llm_call=llm_call, checkpoint=checkpoint)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 0, (
            f"Cancellation must short-circuit before ANY llm_call; got {gen_calls} calls"
        )
        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1
        assert errors[0].data.get("kind") == "cancelled"
        assert [ev for ev in events if ev.is_final] == []

    async def test_checkpoint_cancel_after_llm_call_skips_action_dispatch(self) -> None:
        from swarmline.runtime.thin.kernels.sgr import SGRKernel
        from swarmline.runtime.thin.runtime_support import cancelled_event

        checkpoint_calls = 0

        class _CancelledToken:
            is_cancelled = True

        async def checkpoint() -> RuntimeEvent | None:
            nonlocal checkpoint_calls
            checkpoint_calls += 1
            if checkpoint_calls == 1:
                return None
            return cancelled_event(_CancelledToken())

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            return _nextstep_json("TOOL_CALL")

        ctx = _make_context(llm_call=llm_call, checkpoint=checkpoint)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 1, "Exactly one generation before post-checkpoint cancels"
        assert checkpoint_calls == 2

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1
        assert errors[0].data.get("kind") == "cancelled"
        assert events == [errors[0]], (
            f"No action-dispatch events (status/etc.) once post-llm_call "
            f"checkpoint cancels; got: {events}"
        )

    async def test_ctx_checkpoint_none_runs_without_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ctx.checkpoint=None must be tolerated (checkpoint is optional):
        the `if ctx.checkpoint is not None` guards before/after the
        NextStep-generation llm_call must be exercised and skip cleanly,
        never call a None, and the run must still yield exactly one
        terminal."""
        import swarmline.runtime.thin.kernels.sgr as sgr_module
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            return _nextstep_json("TOOL_CALL", confidence=0.5)

        async def fake_run_react(*args: Any, **kwargs: Any) -> Any:
            yield RuntimeEvent.final("DONE_NO_CHECKPOINT")

        monkeypatch.setattr(sgr_module, "run_react", fake_run_react)

        ctx = _make_context(llm_call=llm_call, checkpoint=None)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        terminals = [ev for ev in events if ev.is_final or ev.is_error]
        assert len(terminals) == 1, (
            f"Expected exactly ONE terminal event with checkpoint=None; got: {events}"
        )
        assert terminals[0].is_final
        assert terminals[0].data.get("text") == "DONE_NO_CHECKPOINT"


# ===========================================================================
# max_steps exhaustion — reachable ONLY when every iteration is REPLAN
# ===========================================================================


class TestSGRMaxStepsExhaustion:
    async def test_all_replan_exhausts_max_steps_and_yields_loop_limit_error(
        self,
    ) -> None:
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            return _nextstep_json("REPLAN", reasoning=f"still thinking ({gen_calls})")

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel(max_steps=3)
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 3, (
            f"Expected exactly max_steps (3) generations; got {gen_calls}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], (
            "Exhaustion must NEVER surface a normal `final` — never a "
            f"success-shaped terminal; got: {events}"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        error_data = errors[0].data
        assert error_data.get("kind") == "loop_limit"
        details = error_data.get("details") or {}
        assert details.get("last_action") == "REPLAN"
        assert details.get("last_reasoning") == "still thinking (3)"


# ===========================================================================
# Surfaced final preserves usage/metrics (H4-Task1 bug class regression)
# ===========================================================================


class TestSGRSurfacedFinalPreservesUsageMetrics:
    async def test_sgr_surfaced_final_preserves_usage_metrics_unzeroed(self) -> None:
        """Delegating via the FINAL action to a REAL run_react (no
        monkeypatch) must surface exactly what finalize_with_validation
        computed for THIS generation's own (lm_messages, prompt, text) —
        never zeroed or hand-reconstructed by SGRKernel."""
        from swarmline.runtime.thin.finalization import _build_usage
        from swarmline.runtime.thin.kernels.sgr import SGRKernel

        prompts: list[str] = []
        lm_messages_seen: list[list[dict[str, Any]]] = []

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            if _SGR_MARKER in prompt:
                return _nextstep_json("FINAL", confidence=0.99)
            prompts.append(prompt)
            lm_messages_seen.append(list(messages))
            return _react_final_envelope("PASS_TEXT")

        ctx = _make_context(llm_call=llm_call)
        kernel = SGRKernel()
        events = [ev async for ev in kernel.run(ctx)]

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        final_data = finals[0].data

        usage = final_data.get("usage")
        metrics = final_data.get("metrics")
        new_messages = final_data.get("new_messages")
        assert usage, f"final.usage must NOT be empty/zeroed; got: {usage}"
        assert metrics, f"final.metrics must NOT be empty/zeroed; got: {metrics}"
        assert new_messages, (
            f"final.new_messages must NOT be empty; got: {new_messages}"
        )

        assert usage.get("input_tokens") == metrics.get("tokens_in")
        assert usage.get("output_tokens") == metrics.get("tokens_out")
        assert usage.get("input_tokens", 0) > 0
        assert usage.get("output_tokens", 0) > 0

        expected_usage = _build_usage(lm_messages_seen[0], prompts[0], "PASS_TEXT")
        assert usage == expected_usage, (
            f"Surfaced usage must equal the inner generation's own usage "
            f"payload exactly; expected {expected_usage}, got {usage}"
        )
        assert new_messages[-1].get("content") == "PASS_TEXT"
