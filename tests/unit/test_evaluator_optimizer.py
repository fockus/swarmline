"""TDD tests for workflow-patterns spec, Task 2 — evaluator-optimizer.

Covers REQ-008 (JudgeAgentSignal implements the EXISTING ExternalSignal
port), REQ-009 (ZERO new kernel/engine/port — the loop is the EXISTING
``ReflectionKernel``), REQ-010 (refine-until-pass / exhaustion surfaces
``loop_limit``, not an unvalidated answer) and REQ-011 (the evaluator is
INJECTED, separate from the generator's ``ctx.llm_call`` — self-judgement is
unreliable, arxiv 2310.01798).

Mirrors ``tests/unit/runtime/test_reflection_kernel.py``'s construction /
fake-generator pattern: a minimal valid ``KernelContext`` via a local
``_make_context`` helper, and a fake ``llm_call`` that returns the
``run_react`` JSON final-envelope shape so the REAL ``ReflectionKernel`` (not
a stub) drives the loop end to end.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from swarmline.domain_types import RuntimeEvent
from swarmline.protocols import ExternalSignal
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.kernels.reflection import ReflectionKernel
from swarmline.runtime.types import RuntimeConfig
from swarmline.types import KernelContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop_checkpoint() -> RuntimeEvent | None:
    return None


def _make_context(**overrides: Any) -> KernelContext:
    """Build a minimal valid KernelContext for testing (real ToolExecutor).

    Mirrors ``tests/unit/runtime/test_reflection_kernel.py::_make_context``.
    """
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


def _final_envelope(text: str) -> str:
    """A run_react-shaped JSON final envelope, mirrors test_reflection_kernel.py."""
    return json.dumps({"type": "final", "final_message": text})


# ===========================================================================
# REQ-008 — JudgeAgentSignal implements the EXISTING ExternalSignal port
# ===========================================================================


class TestJudgeAgentSignalImplementsExternalSignal:
    async def test_judge_agent_signal_implements_external_signal(self) -> None:
        """isinstance(JudgeAgentSignal(...), ExternalSignal) holds (structural,
        via the runtime_checkable Protocol); a FAIL verdict from the injected
        evaluator yields SignalResult(passed=False, feedback=<non-empty>), a
        PASS verdict yields SignalResult(passed=True, feedback="")."""
        from swarmline.orchestration.evaluator_optimizer import JudgeAgentSignal

        async def fake_evaluator(prompt: str) -> str:
            if "GOOD" in prompt:
                return "PASS"
            return "FAIL\nMissing the required greeting."

        signal = JudgeAgentSignal(evaluator=fake_evaluator)
        assert isinstance(signal, ExternalSignal), (
            "JudgeAgentSignal must structurally satisfy the runtime_checkable "
            "ExternalSignal Protocol"
        )

        ctx = _make_context()

        fail_result = await signal.evaluate("BAD output", ctx)
        assert fail_result.passed is False
        assert fail_result.feedback != "", (
            "A FAIL verdict must carry non-empty actionable feedback"
        )
        assert "greeting" in fail_result.feedback.lower()

        pass_result = await signal.evaluate("GOOD output", ctx)
        assert pass_result.passed is True
        assert pass_result.feedback == "", (
            "SignalResult convention: feedback is empty when passed=True"
        )


# ===========================================================================
# REQ-009/010, scenario 3 — drives the REAL ReflectionKernel to refine until
# the judge passes, within max_iterations
# ===========================================================================


class TestReflectionKernelRefinesUntilJudgePasses:
    async def test_reflection_kernel_refines_until_judge_passes(self) -> None:
        """A fake evaluator returning fail -> fail -> pass drives the REAL
        ReflectionKernel (constructed with signal=JudgeAgentSignal(...)) to
        refine twice (feedback injected into regeneration each time) and
        stop on the passing verdict, within max_iterations. The final output
        is the signal-validated (third attempt's) text."""
        from swarmline.orchestration.evaluator_optimizer import JudgeAgentSignal

        judge_calls = 0

        async def fake_evaluator(prompt: str) -> str:
            nonlocal judge_calls
            judge_calls += 1
            if judge_calls == 1:
                return "FAIL\nAdd more detail about X."
            if judge_calls == 2:
                return "FAIL\nStill missing detail about Y."
            return "PASS"

        prompts: list[str] = []

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            prompts.append(prompt)
            if "detail about Y" in prompt:
                return _final_envelope("THIRD_ATTEMPT_OK")
            if "detail about X" in prompt:
                return _final_envelope("SECOND_ATTEMPT_BAD")
            return _final_envelope("FIRST_ATTEMPT_BAD")

        ctx = _make_context(llm_call=llm_call)
        kernel = ReflectionKernel(
            signal=JudgeAgentSignal(evaluator=fake_evaluator), max_iterations=5
        )
        events = [ev async for ev in kernel.run(ctx)]

        assert judge_calls == 3, f"Expected exactly 3 judge calls; got {judge_calls}"
        assert len(prompts) == 3, f"Expected exactly 3 generations; got {len(prompts)}"
        assert "detail about X" in prompts[1], (
            "Second generation must carry the judge's first feedback"
        )
        assert "detail about Y" in prompts[2], (
            "Third generation must carry the judge's second feedback"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "THIRD_ATTEMPT_OK", (
            "The signal-validated (third) attempt's text must be surfaced"
        )

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], f"No error expected once the judge passes; got: {errors}"


# ===========================================================================
# REQ-011 — evaluator is injected SEPARATE from the generator's ctx.llm_call
# ===========================================================================


class TestEvaluatorDistinctFromGeneratorLlmCall:
    async def test_evaluator_distinct_from_generator_llm_call(self) -> None:
        """The injected evaluator is called to produce the verdict; the
        generator's ctx.llm_call is NEVER consulted for judging (separate
        mock counters prove the two are distinct calls)."""
        from swarmline.orchestration.evaluator_optimizer import JudgeAgentSignal

        evaluator_calls = 0
        generator_calls = 0

        async def fake_evaluator(prompt: str) -> str:
            nonlocal evaluator_calls
            evaluator_calls += 1
            # If the generator's llm_call output ever leaked into the
            # evaluator's own call count, this would be indistinguishable
            # from self-judgement -- assert the counters stay independent.
            return "PASS"

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal generator_calls
            generator_calls += 1
            return _final_envelope("ANSWER")

        ctx = _make_context(llm_call=llm_call)
        signal = JudgeAgentSignal(evaluator=fake_evaluator)
        kernel = ReflectionKernel(signal=signal, max_iterations=3)
        events = [ev async for ev in kernel.run(ctx)]

        assert evaluator_calls == 1, (
            f"The injected evaluator must be called exactly once; got {evaluator_calls}"
        )
        assert generator_calls == 1, (
            f"The generator's ctx.llm_call must be called exactly once (for "
            f"generation only, never for judging); got {generator_calls}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"

        # Direct proof the evaluator itself never touches ctx.llm_call: call
        # evaluate() again in isolation with ctx.llm_call replaced by a
        # sentinel that raises if invoked.
        async def exploding_llm_call(*args: Any, **kw: Any) -> str:
            raise AssertionError(
                "ctx.llm_call must never be consulted by JudgeAgentSignal.evaluate"
            )

        isolated_ctx = _make_context(llm_call=exploding_llm_call)
        result = await signal.evaluate("some output", isolated_ctx)
        assert result.passed is True


# ===========================================================================
# REQ-010 — exhaustion surfaces the REUSED kernel's loop_limit terminal
# error, never the last unvalidated answer
# ===========================================================================


class TestExhaustionSurfacesLoopLimitNotUnvalidatedAnswer:
    async def test_exhaustion_surfaces_loop_limit_not_unvalidated_answer(
        self,
    ) -> None:
        """A fake evaluator that ALWAYS fails drives the REAL ReflectionKernel
        to exhaust max_iterations without ever passing -- the kernel yields
        its terminal loop_limit error (REUSED, existing kernel behaviour),
        never a normal `final` carrying the last unvalidated answer."""
        from swarmline.orchestration.evaluator_optimizer import JudgeAgentSignal

        judge_calls = 0

        async def always_fail_evaluator(prompt: str) -> str:
            nonlocal judge_calls
            judge_calls += 1
            return f"FAIL\nstill wrong ({judge_calls})"

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            return _final_envelope(f"attempt {gen_calls}")

        ctx = _make_context(llm_call=llm_call)
        kernel = ReflectionKernel(
            signal=JudgeAgentSignal(evaluator=always_fail_evaluator),
            max_iterations=3,
        )
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 3, f"Expected exactly 3 generations; got {gen_calls}"
        assert judge_calls == 3, f"Expected exactly 3 judge calls; got {judge_calls}"

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], (
            "Exhaustion without a judge pass must never surface a normal "
            f"`final` (the last unvalidated answer); got: {events}"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "loop_limit", (
            f"Expected the REUSED kernel's loop_limit terminal error; got: {errors[0].data}"
        )
        details = errors[0].data.get("details") or {}
        assert details.get("last_output") == "attempt 3"
        assert "still wrong (3)" in details.get("last_feedback", "")


# ===========================================================================
# Extra — an unparseable/ambiguous verdict defaults to safe FAIL, never a
# silent PASS (an unreliable judge must not rubber-stamp arbitrary output)
# ===========================================================================


class TestUnparseableVerdictDefaultsToSafeFail:
    async def test_unparseable_verdict_defaults_to_fail_with_raw_text(self) -> None:
        """A verdict that contains neither a leading PASS nor FAIL token
        must default to passed=False, carrying the raw verdict text as
        feedback -- an ambiguous/malfunctioning judge must never silently
        approve a candidate."""
        from swarmline.orchestration.evaluator_optimizer import JudgeAgentSignal

        async def ambiguous_evaluator(prompt: str) -> str:
            return "I'm not sure, this looks okay-ish but maybe not."

        signal = JudgeAgentSignal(evaluator=ambiguous_evaluator)
        ctx = _make_context()
        result = await signal.evaluate("some output", ctx)

        assert result.passed is False, (
            "An unparseable verdict must default to FAIL, never silently PASS"
        )
        assert result.feedback != "", "Feedback must carry the raw verdict text"
        assert "okay-ish" in result.feedback

    @pytest.mark.parametrize("empty_verdict", ["", "   ", "\n\t  \n"])
    async def test_empty_verdict_fails_closed_with_nonempty_feedback(
        self, empty_verdict: str
    ) -> None:
        """An empty / whitespace-only evaluator verdict must fail-closed
        (passed=False) AND carry non-empty diagnostic feedback -- otherwise
        ReflectionKernel's refine/loop_limit path would surface a blank
        last_feedback (REQ-008: feedback is never empty on a fail)."""
        from swarmline.orchestration.evaluator_optimizer import JudgeAgentSignal

        async def empty_evaluator(prompt: str) -> str:
            return empty_verdict

        signal = JudgeAgentSignal(evaluator=empty_evaluator)
        result = await signal.evaluate("some output", _make_context())

        assert result.passed is False, "An empty verdict must never silently PASS"
        assert result.feedback.strip() != "", (
            "An empty verdict must still yield non-empty diagnostic feedback"
        )


# ===========================================================================
# Sanity — JudgeAgentSignal construction requires a non-None evaluator
# ===========================================================================


class TestJudgeAgentSignalConstruction:
    def test_construction_rejects_none_evaluator(self) -> None:
        from swarmline.orchestration.evaluator_optimizer import JudgeAgentSignal

        with pytest.raises(ValueError):
            JudgeAgentSignal(evaluator=None)  # type: ignore[arg-type]
