"""TDD tests for kernel-patterns spec, Task 4 — ReflectionKernel.

Covers REQ-003, REQ-009, Scenario 3 (Reflection заземлён на внешний сигнал:
arxiv 2310.01798 — intrinsic self-correction WITHOUT an external signal does
NOT work). Written BEFORE the implementation (TDD RED -> GREEN); see
``ReflectionKernel`` in ``swarmline.runtime.thin.kernels.reflection`` for the
design rationale.

Mirrors ``tests/unit/runtime/test_adapt_kernel.py``'s style: a fake
``llm_call`` that content-branches on the (real, composed) prompt so the
resulting event sequence proves genuine control-flow, not a tautology of a
fixed response list.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from swarmline.domain_types import RuntimeEvent
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.types import RuntimeConfig
from swarmline.types import SignalResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ===========================================================================
# ExternalSignal Protocol (domain contract)
# ===========================================================================


class TestExternalSignalProtocol:
    def test_conforming_fake_satisfies_isinstance_check(self) -> None:
        """A fake with an async evaluate() satisfies isinstance(x, ExternalSignal)."""
        from swarmline.protocols import ExternalSignal

        class FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                return SignalResult(passed=True, feedback="")  # pragma: no cover

        assert isinstance(FakeSignal(), ExternalSignal)

    def test_nonconforming_object_fails_isinstance_check(self) -> None:
        """An object without evaluate() does not satisfy isinstance(x, ExternalSignal)."""
        from swarmline.protocols import ExternalSignal

        class NotASignal:
            def check(self, output: str) -> bool:
                return True

        assert not isinstance(NotASignal(), ExternalSignal)

    def test_protocol_has_exactly_one_public_method(self) -> None:
        """ExternalSignal has exactly 1 method 'evaluate' (ISP)."""
        from swarmline.protocols import ExternalSignal

        public_methods = [
            name for name in dir(ExternalSignal) if not name.startswith("_")
        ]
        assert public_methods == ["evaluate"], (
            f"ExternalSignal must have exactly 1 method 'evaluate'; got: {public_methods}"
        )

    def test_import_from_protocols_package(self) -> None:
        """from swarmline.protocols import ExternalSignal works."""
        from swarmline.protocols import ExternalSignal  # noqa: F401

        assert ExternalSignal is not None


# ===========================================================================
# SignalResult (frozen domain dataclass)
# ===========================================================================


class TestSignalResult:
    def test_signal_result_frozen_mutation_raises_frozen_instance_error(self) -> None:
        """Mutating a SignalResult field raises FrozenInstanceError."""
        result = SignalResult(passed=True, feedback="ok")
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.passed = False  # type: ignore[misc]

    def test_signal_result_feedback_defaults_to_empty_string(self) -> None:
        """feedback is optional, defaulting to ''."""
        result = SignalResult(passed=True)
        assert result.feedback == ""

    def test_signal_result_stores_passed_and_feedback(self) -> None:
        result = SignalResult(passed=False, feedback="fix the thing")
        assert result.passed is False
        assert result.feedback == "fix the thing"


# ===========================================================================
# Construction — REQ-009: no self-judgement-only mode exists
# ===========================================================================


class TestReflectionKernelRequiresSignal:
    def test_cannot_construct_without_signal_argument(self) -> None:
        """ReflectionKernel() with no signal raises TypeError (required arg)."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        with pytest.raises(TypeError):
            ReflectionKernel()  # type: ignore[call-arg]

    def test_rejects_none_as_signal(self) -> None:
        """ReflectionKernel(signal=None) raises ValueError — no silent no-op signal."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        with pytest.raises(ValueError):
            ReflectionKernel(signal=None)  # type: ignore[arg-type]

    def test_requires_ctx_executor(self) -> None:
        """run() raises ValueError when ctx.executor is None (mirrors ADaPTKernel)."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                return SignalResult(passed=True)  # pragma: no cover

        ctx = _make_context(executor=None)
        kernel = ReflectionKernel(signal=_FakeSignal())
        with pytest.raises(ValueError):
            kernel.run(ctx)


# ===========================================================================
# MAJOR 3 (GPT-5.5 review round 3) — max_iterations must be validated at
# construction, never left to crash the loop/assert later (reflection.py:100)
# ===========================================================================


class TestReflectionKernelValidatesMaxIterations:
    def test_max_iterations_zero_raises_value_error_at_construction(self) -> None:
        """max_iterations=0 must raise ValueError in __init__ — fail-fast,
        never silently skip the loop and crash the internal
        ``assert last_final is not None`` afterwards."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                return SignalResult(passed=True)  # pragma: no cover

        with pytest.raises(ValueError):
            ReflectionKernel(signal=_FakeSignal(), max_iterations=0)

    def test_max_iterations_negative_raises_value_error_at_construction(self) -> None:
        """max_iterations=-1 must also raise ValueError in __init__."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                return SignalResult(passed=True)  # pragma: no cover

        with pytest.raises(ValueError):
            ReflectionKernel(signal=_FakeSignal(), max_iterations=-1)


# ===========================================================================
# Scenario 3 / REQ-003 — refine uses the external signal's feedback
# ===========================================================================


class TestReflectionUsesExternalSignalForRefine:
    async def test_reflection_uses_external_signal_for_refine(self) -> None:
        """A signal that fails once with feedback='FIX_X' then passes drives
        the SECOND generation's prompt to contain 'FIX_X', and the terminal
        final is the refined (passed) output — not the first attempt."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        eval_calls = 0

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                nonlocal eval_calls
                eval_calls += 1
                if eval_calls == 1:
                    return SignalResult(passed=False, feedback="FIX_X")
                return SignalResult(passed=True, feedback="")

        prompts: list[str] = []

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            prompts.append(prompt)
            if "FIX_X" in prompt:
                return json.dumps({"type": "final", "final_message": "REFINED_OK"})
            return json.dumps({"type": "final", "final_message": "ORIGINAL_BAD"})

        ctx = _make_context(llm_call=llm_call)
        kernel = ReflectionKernel(signal=_FakeSignal())
        events = [ev async for ev in kernel.run(ctx)]

        assert eval_calls == 2, (
            f"Expected exactly 2 signal.evaluate calls; got {eval_calls}"
        )
        assert len(prompts) == 2, f"Expected exactly 2 generations; got {len(prompts)}"
        assert "FIX_X" not in prompts[0], (
            f"First generation must not see refine feedback yet; got: {prompts[0]!r}"
        )
        assert "FIX_X" in prompts[1], (
            "Second generation's prompt must carry the EXTERNAL signal's "
            f"feedback ('FIX_X'); got: {prompts[1]!r}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "REFINED_OK", (
            f"Expected the refined (passed) output to be surfaced; got: {finals[0].data}"
        )

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], f"No error expected once the signal passes; got: {errors}"


# ===========================================================================
# MAJOR 1 (GPT-5.5 review round 3), revised for the drop-and-synthesize
# contract (GPT-5.5 review round 2 MAJOR logic defect fix) — a REJECTED
# attempt's answer content must never stream to the caller, and the PASSING
# attempt's answer content the caller does see must be exactly ONE
# synthesized delta equal to the validated final's text (reflection.py)
# ===========================================================================


class TestReflectionBuffersRejectedAttemptAnswerContent:
    async def test_rejected_attempt_never_forwarded_passing_attempt_synthesized(
        self,
    ) -> None:
        """A signal that REJECTS the first attempt ('ORIGINAL_BAD') then
        PASSES the refined attempt ('REFINED_OK') must never forward any
        event (delta or otherwise) carrying 'ORIGINAL_BAD' to the caller —
        that candidate was never validated, and its answer-content was
        dropped during generation (never buffered). The passing attempt's
        answer content the caller DOES see must be EXACTLY ONE synthesized
        assistant_delta equal to the validated final's text — re-synthesized
        from ``generated.text`` on signal.evaluate passing, not a replay of
        run_react's raw per-token deltas — before the terminal final."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        eval_calls = 0

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                nonlocal eval_calls
                eval_calls += 1
                if eval_calls == 1:
                    return SignalResult(passed=False, feedback="try again")
                return SignalResult(passed=True, feedback="")

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            if "try again" in prompt:
                return json.dumps({"type": "final", "final_message": "REFINED_OK"})
            return json.dumps({"type": "final", "final_message": "ORIGINAL_BAD"})

        ctx = _make_context(llm_call=llm_call)
        kernel = ReflectionKernel(signal=_FakeSignal())
        events = [ev async for ev in kernel.run(ctx)]

        assert eval_calls == 2, f"Expected exactly 2 evaluate calls; got {eval_calls}"

        for ev in events:
            assert "ORIGINAL_BAD" not in repr(ev), (
                "A REJECTED attempt's content must never be forwarded to "
                f"the caller (delta or otherwise); got event: {ev}"
            )

        deltas = [ev for ev in events if ev.type == "assistant_delta"]
        assert len(deltas) == 1, (
            "Exactly ONE synthesized assistant_delta is expected (the "
            f"validated final's text), not a replay of raw deltas; got: {deltas}"
        )
        assert deltas[0].data.get("text") == "REFINED_OK", (
            "The single synthesized delta must equal the PASSING attempt's "
            f"validated text; got: {deltas[0].data}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "REFINED_OK"

        # Ordering: the synthesized content must precede the terminal final.
        final_idx = events.index(finals[0])
        delta_idx = events.index(deltas[0])
        assert delta_idx < final_idx, (
            "Synthesized content must be yielded BEFORE the terminal final; "
            f"got delta at {delta_idx}, final at {final_idx} in: {events}"
        )

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], f"No error expected once the signal passes; got: {errors}"


# ===========================================================================
# GPT-5.5 review round 2, MAJOR (logic) — buffer-and-flush across a WHOLE
# run_react invocation is unsafe: run_react can internally re-stream a
# DIFFERENT (parse-failed) attempt's deltas within ONE invocation before
# emitting its single terminal final (react_strategy.py:475-542, the
# ``envelope is None: retries += 1; continue`` path). Fakes that exact
# re-stream shape at the run_react seam and proves ReflectionKernel's fix
# (drop-and-synthesize) makes the contamination structurally impossible.
# ===========================================================================


class TestReflectionSynthesizesFromValidatedFinalNotRawRestreamedDeltas:
    async def test_run_react_internal_restream_across_parse_retry_never_leaks_malformed_deltas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fakes run_react yielding, in ONE invocation: an assistant_delta
        for a malformed attempt ('BAD-malformed'), then an assistant_delta
        for the eventually-good attempt ('GOOD'), then a single terminal
        final whose text is 'GOOD' — exactly what run_react's internal
        parse-retry loop can do (stream a failed attempt's deltas, retry,
        stream a different attempt's deltas, then emit ONE final). With a
        PASSING signal, ReflectionKernel's output stream must contain
        EXACTLY ONE assistant_delta, equal to the final's text ('GOOD') —
        never 'BAD-malformed' anywhere. This is RED against the old
        buffer-and-flush implementation, which forwards the WHOLE buffer
        (both deltas) verbatim once the signal passes."""
        import swarmline.runtime.thin.kernels.reflection as reflection_module
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        async def fake_run_react(*args: Any, **kwargs: Any) -> Any:
            yield RuntimeEvent.assistant_delta("BAD-malformed")
            yield RuntimeEvent.assistant_delta("GOOD")
            yield RuntimeEvent.final("GOOD")

        monkeypatch.setattr(reflection_module, "run_react", fake_run_react)

        class _PassingSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                return SignalResult(passed=True, feedback="")

        ctx = _make_context(llm_call=None)
        kernel = ReflectionKernel(signal=_PassingSignal())
        events = [ev async for ev in kernel.run(ctx)]

        assert not any("BAD-malformed" in repr(ev) for ev in events), (
            "The malformed re-streamed attempt's content must NEVER appear "
            f"anywhere in ReflectionKernel's output stream; got: {events}"
        )

        deltas = [ev for ev in events if ev.type == "assistant_delta"]
        assert len(deltas) == 1, (
            "Expected exactly ONE assistant_delta (synthesized from the "
            "validated final's text), never a replay of run_react's raw "
            f"re-streamed deltas; got: {deltas}"
        )
        assert deltas[0].data.get("text") == "GOOD", (
            "The single synthesized delta must equal the validated final's "
            f"text ('GOOD'); got: {deltas[0].data}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "GOOD"

        final_idx = events.index(finals[0])
        delta_idx = events.index(deltas[0])
        assert delta_idx < final_idx, (
            "The synthesized delta must precede the terminal final; got "
            f"delta at {delta_idx}, final at {final_idx} in: {events}"
        )


# ===========================================================================
# Drop-and-synthesize edge case — an empty validated final text must never
# produce an empty synthesized assistant_delta
# ===========================================================================


class TestReflectionSynthesizedDeltaEmptyTextEdge:
    async def test_empty_final_text_emits_no_synthesized_delta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If ``generated.text`` is falsy (empty string) when the signal
        passes, ReflectionKernel must NOT synthesize/emit an empty
        assistant_delta — only the terminal final is yielded."""
        import swarmline.runtime.thin.kernels.reflection as reflection_module
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        async def fake_run_react(*args: Any, **kwargs: Any) -> Any:
            yield RuntimeEvent.final("")

        monkeypatch.setattr(reflection_module, "run_react", fake_run_react)

        class _PassingSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                return SignalResult(passed=True, feedback="")

        ctx = _make_context(llm_call=None)
        kernel = ReflectionKernel(signal=_PassingSignal())
        events = [ev async for ev in kernel.run(ctx)]

        deltas = [ev for ev in events if ev.type == "assistant_delta"]
        assert deltas == [], (
            "No synthesized assistant_delta should be emitted for an empty "
            f"validated final text; got: {deltas}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == ""


# ===========================================================================
# REQ-009 — the SIGNAL, not the model, gates continue/stop
# ===========================================================================


class TestReflectionRequiresSignalNotSelfJudgementOnly:
    async def test_signal_always_failing_forces_exactly_max_iterations_generations(
        self,
    ) -> None:
        """A signal that ALWAYS returns passed=False forces exactly
        max_iterations generations — the model confidently emits a 'final'
        envelope on every attempt (it always 'thinks' it's done), proving the
        SIGNAL — not model self-judgement — gates the loop (REQ-009).

        MAJOR 2 (GPT-5.5 review round 3): exhaustion WITHOUT the signal ever
        passing must surface a TERMINAL ``loop_limit`` error — never a
        normal `final` indistinguishable from a signal-APPROVED answer —
        mirroring ``ADaPTKernel``'s max_depth error (adapt.py:194-206). The
        failed last attempt's answer content must also never be synthesized
        or emitted (MAJOR 1 interaction, drop-and-synthesize contract)."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        eval_calls = 0

        class _AlwaysFailSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                nonlocal eval_calls
                eval_calls += 1
                return SignalResult(
                    passed=False, feedback=f"still wrong ({eval_calls})"
                )

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            # The model itself always confidently claims "final" — its own
            # judgement never says "keep going"; only the signal does.
            return json.dumps(
                {"type": "final", "final_message": f"attempt {gen_calls}"}
            )

        ctx = _make_context(llm_call=llm_call)
        kernel = ReflectionKernel(signal=_AlwaysFailSignal(), max_iterations=3)
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 3, (
            f"Expected exactly max_iterations (3) generations; got {gen_calls}"
        )
        assert eval_calls == 3, (
            f"Expected exactly 3 signal.evaluate calls; got {eval_calls}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], (
            "Exhaustion without a pass must NEVER surface a normal `final` "
            "— indistinguishable from a signal-approved answer at the "
            f"observable boundary (REQ-009 grounding); got: {events}"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        error_data = errors[0].data
        assert error_data.get("kind") == "loop_limit", (
            f"Expected kind='loop_limit' on exhaustion without a pass; "
            f"got: {error_data}"
        )
        message = error_data.get("message", "")
        assert "signal" in message.lower() and "never passed" in message.lower(), (
            f"Error message must reference the signal never passing within "
            f"max_iterations; got: {message!r}"
        )
        details = error_data.get("details") or {}
        assert details.get("last_output") == "attempt 3", (
            f"Error details must reference the LAST attempt's output text; "
            f"got: {details}"
        )
        assert details.get("last_feedback") == "still wrong (3)", (
            f"Error details must reference the LAST SignalResult.feedback; "
            f"got: {details}"
        )

        # MAJOR 1 interaction: since the signal never passes, NO answer
        # content is ever synthesized/emitted for ANY attempt — every
        # attempt's answer-content was dropped during generation and the
        # signal never passed to trigger synthesis.
        deltas = [ev for ev in events if ev.type == "assistant_delta"]
        assert deltas == [], (
            "No assistant_delta should ever be emitted when the signal "
            f"never passes across all attempts; got deltas: {deltas}"
        )


# ===========================================================================
# Global/non-recoverable errors propagate WITHOUT looping (Task 3 discipline)
# ===========================================================================


class TestReflectionPropagatesGlobalErrorsWithoutLooping:
    async def test_runtime_crash_propagates_without_looping_or_evaluating(self) -> None:
        """A run_react-terminal error (runtime_crash: provider failure) must
        propagate immediately — NOT trigger a refine retry, and signal.evaluate
        must never run (there is no output to ground a verdict on)."""
        from swarmline.runtime.thin.errors import ThinLlmError
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel
        from swarmline.runtime.types import RuntimeErrorData

        eval_calls = 0

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                nonlocal eval_calls
                eval_calls += 1
                return SignalResult(passed=True)  # pragma: no cover

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            raise ThinLlmError(
                RuntimeErrorData(kind="runtime_crash", message="provider crashed")
            )

        ctx = _make_context(llm_call=llm_call)
        kernel = ReflectionKernel(signal=_FakeSignal(), max_iterations=3)
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 1, (
            f"A global error must propagate immediately, no retry generation; "
            f"got {gen_calls} calls"
        )
        assert eval_calls == 0, (
            "signal.evaluate must never run for a global runtime error"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "runtime_crash", (
            f"Expected the propagated error to keep kind='runtime_crash'; got: {errors[0].data}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], "No success should be reported when the runtime crashed"

    async def test_cancelled_propagates_without_looping_or_evaluating(self) -> None:
        """A cancelled run_react (checkpoint fires kind='cancelled' during
        generation) must propagate that exact error — NOT trigger a refine
        retry, and signal.evaluate must never run."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel
        from swarmline.runtime.thin.runtime_support import cancelled_event

        eval_calls = 0

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                nonlocal eval_calls
                eval_calls += 1
                return SignalResult(passed=True)  # pragma: no cover

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            return json.dumps({"type": "final", "final_message": "should not run"})

        class _CancelledToken:
            is_cancelled = True

        async def cancelling_checkpoint() -> RuntimeEvent | None:
            return cancelled_event(_CancelledToken())

        ctx = _make_context(llm_call=llm_call, checkpoint=cancelling_checkpoint)
        kernel = ReflectionKernel(signal=_FakeSignal(), max_iterations=3)
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 0, (
            f"Cancellation must short-circuit before ANY llm_call; got {gen_calls} calls"
        )
        assert eval_calls == 0, (
            "signal.evaluate must never run once cancellation is observed"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "cancelled"

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], "No success should be reported when cancelled"


# ===========================================================================
# Checkpoint — cancellation between generation and signal.evaluate
# ===========================================================================


class TestReflectionChecksCheckpointBeforeEvaluate:
    async def test_checkpoint_cancel_before_evaluate_skips_signal_and_refine(
        self,
    ) -> None:
        """A checkpoint that is clean throughout ONE direct 'final' generation
        (empirically 4 polls — see run_react's own internal checkpoints plus
        finalize_with_validation's) but flips to 'cancelled' exactly on the
        NEXT poll (this kernel's own pre-evaluate checkpoint, mirroring
        adapt.py::_decompose's discipline) must skip signal.evaluate AND any
        refine generation entirely."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel
        from swarmline.runtime.thin.runtime_support import cancelled_event

        checkpoint_calls = 0

        class _CancelledToken:
            is_cancelled = True

        async def checkpoint() -> RuntimeEvent | None:
            nonlocal checkpoint_calls
            checkpoint_calls += 1
            if checkpoint_calls <= 4:
                return None
            return cancelled_event(_CancelledToken())

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            return json.dumps({"type": "final", "final_message": "done"})

        eval_calls = 0

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                nonlocal eval_calls
                eval_calls += 1
                return SignalResult(passed=False, feedback="x")  # pragma: no cover

        ctx = _make_context(llm_call=llm_call, checkpoint=checkpoint)
        kernel = ReflectionKernel(signal=_FakeSignal(), max_iterations=3)
        events = [ev async for ev in kernel.run(ctx)]

        assert gen_calls == 1, (
            f"Only the first generation should run before cancellation is "
            f"observed; got {gen_calls} calls"
        )
        assert eval_calls == 0, (
            "signal.evaluate must never run once the pre-evaluate checkpoint "
            "observes cancellation"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "cancelled"

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], "No success should be reported when cancelled"


# ===========================================================================
# VERIFY-gate gap 1 — isolated first-iteration pass (reflection.py:164-166)
# ===========================================================================


class TestReflectionFirstIterationPassRequiresNoRefine:
    async def test_reflection_passes_on_first_iteration_single_generation(
        self,
    ) -> None:
        """A signal that passes on the VERY FIRST iteration must yield
        exactly ONE generation and exactly ONE signal.evaluate call, with NO
        refine step at all — proving the result.passed branch
        (reflection.py:164-166) is reachable in true isolation, not only as
        the tail of a prior refine (unlike
        ``test_reflection_uses_external_signal_for_refine``, which only
        exercises this branch on iteration 2)."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        eval_calls = 0

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                nonlocal eval_calls
                eval_calls += 1
                return SignalResult(passed=True, feedback="")

        prompts: list[str] = []

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            prompts.append(prompt)
            return json.dumps({"type": "final", "final_message": "FIRST_TRY_OK"})

        ctx = _make_context(llm_call=llm_call)
        kernel = ReflectionKernel(signal=_FakeSignal(), max_iterations=3)
        events = [ev async for ev in kernel.run(ctx)]

        assert len(prompts) == 1, (
            f"Expected exactly ONE generation (no refine); got {len(prompts)}"
        )
        assert eval_calls == 1, (
            f"Expected exactly ONE signal.evaluate call; got {eval_calls}"
        )
        assert not any("Refine your previous answer" in p for p in prompts), (
            "An immediate first-iteration pass must never build a refine "
            f"prompt (build_plan_step_prompt must not run); got: {prompts}"
        )
        assert not any(
            ev.type == "status" and "refining" in ev.text for ev in events
        ), (
            "No 'refining' status is expected when the signal passes on "
            f"iteration 1; got: {events}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "FIRST_TRY_OK", (
            "Expected the FIRST (and only) generation's output to be "
            f"surfaced verbatim; got: {finals[0].data}"
        )

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], f"No error expected on an immediate pass; got: {errors}"


# ===========================================================================
# VERIFY-gate gap 2 — checkpoint AFTER signal.evaluate (reflection.py:161-162)
# ===========================================================================


class TestReflectionChecksCheckpointAfterEvaluate:
    async def test_reflection_post_evaluate_checkpoint_cancel_surfaces_cancelled(
        self,
    ) -> None:
        """A checkpoint that stays clean through run_react's own internal
        polls AND this kernel's PRE-evaluate checkpoint (so signal.evaluate
        actually runs) but flips to 'cancelled' on the very NEXT poll — this
        kernel's POST-evaluate checkpoint (reflection.py:161-162) — must
        surface the cancellation and skip refine entirely, even though the
        signal itself returned passed=False (which would otherwise trigger a
        refine generation). Empirically, ONE direct-final generation costs
        run_react 4 internal checkpoint polls (see
        ``test_checkpoint_cancel_before_evaluate_skips_signal_and_refine``,
        which flips on call 5 = this kernel's PRE-evaluate checkpoint to
        prove signal.evaluate is skipped). Here call 5 must stay clean (so
        evaluate runs) and call 6 — the POST-evaluate checkpoint — flips."""
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel
        from swarmline.runtime.thin.runtime_support import cancelled_event

        checkpoint_calls = 0

        class _CancelledToken:
            is_cancelled = True

        async def checkpoint() -> RuntimeEvent | None:
            nonlocal checkpoint_calls
            checkpoint_calls += 1
            if checkpoint_calls <= 5:
                return None
            return cancelled_event(_CancelledToken())

        gen_calls = 0

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal gen_calls
            gen_calls += 1
            return json.dumps({"type": "final", "final_message": "done"})

        eval_calls = 0

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                nonlocal eval_calls
                eval_calls += 1
                # Would otherwise trigger a refine — proving the POST-evaluate
                # checkpoint, not the signal's verdict, is what stops the
                # loop here.
                return SignalResult(passed=False, feedback="would-refine")

        ctx = _make_context(llm_call=llm_call, checkpoint=checkpoint)
        kernel = ReflectionKernel(signal=_FakeSignal(), max_iterations=3)
        events = [ev async for ev in kernel.run(ctx)]

        assert eval_calls == 1, (
            f"signal.evaluate must run exactly once (the checkpoint that "
            f"cancels fires AFTER it, not before); got {eval_calls}"
        )
        assert gen_calls == 1, (
            "No refine generation should run once the POST-evaluate "
            f"checkpoint observes cancellation; got {gen_calls} calls"
        )
        assert checkpoint_calls == 6, (
            "Expected checkpoint to be polled exactly 6 times (4 internal "
            "to run_react + this kernel's PRE- and POST-evaluate checks) "
            f"before cancellation is observed; got {checkpoint_calls}"
        )

        errors = [ev for ev in events if ev.is_error]
        assert len(errors) == 1, f"Expected exactly one terminal error; got: {events}"
        assert errors[0].data.get("kind") == "cancelled"

        finals = [ev for ev in events if ev.is_final]
        assert finals == [], (
            "No success should be reported when cancelled post-evaluate"
        )


# ===========================================================================
# VERIFY-gate gap 3 — surfaced final's usage/metrics are never zeroed
# (H4-Task1 bug class, reflection.py:51-57)
# ===========================================================================


class TestReflectionSurfacedFinalPreservesUsageMetrics:
    async def test_reflection_surfaced_final_preserves_usage_metrics_unzeroed(
        self,
    ) -> None:
        """Regression guard for the H4-Task1 bug class (reflection.py
        module docstring, lines 51-57): when the signal passes, the
        surfaced terminal final must be the SAME object run_react /
        finalize_with_validation produced — its usage/metrics/new_messages
        must be exactly what ``_build_usage``/``_build_metrics`` computed
        for THIS generation's own (lm_messages, prompt, text), never zeroed
        or hand-reconstructed by ReflectionKernel (mirrors the parity
        pattern in test_kernel_mid_run_hooks.py's
        TestStopAfterTurnUsageParity, the harness's own precedent for this
        exact bug class — the kernel-fixture style here has no knob to
        inject a raw usage sentinel, since finalize_with_validation always
        computes usage/metrics internally from the real
        lm_messages/prompt/text)."""
        from swarmline.runtime.thin.finalization import _build_usage
        from swarmline.runtime.thin.kernels.reflection import ReflectionKernel

        class _FakeSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                return SignalResult(passed=True, feedback="")

        prompts: list[str] = []
        lm_messages_seen: list[list[dict[str, Any]]] = []

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            prompts.append(prompt)
            lm_messages_seen.append(list(messages))
            return json.dumps({"type": "final", "final_message": "PASS_TEXT"})

        ctx = _make_context(llm_call=llm_call)
        kernel = ReflectionKernel(signal=_FakeSignal(), max_iterations=3)
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

        # usage and metrics must agree (same _build_usage output threaded
        # through _build_metrics), not two independently-zeroed numbers.
        assert usage.get("input_tokens") == metrics.get("tokens_in")
        assert usage.get("output_tokens") == metrics.get("tokens_out")
        assert usage.get("input_tokens", 0) > 0, (
            f"usage.input_tokens must be > 0 for a non-empty generation; got: {usage}"
        )
        assert usage.get("output_tokens", 0) > 0, (
            f"usage.output_tokens must be > 0 for a non-empty generation; got: {usage}"
        )

        # Direct parity: recompute the EXACT usage the inner generation must
        # have produced for its own (lm_messages, prompt, text) and assert
        # the surfaced final carries it byte-for-byte — proving
        # ReflectionKernel forwards run_react's own final object as-is (no
        # dataclasses.replace, no rewritten/zeroed payload).
        expected_usage = _build_usage(lm_messages_seen[0], prompts[0], "PASS_TEXT")
        assert usage == expected_usage, (
            f"Surfaced usage must equal the inner generation's own usage "
            f"payload exactly; expected {expected_usage}, got {usage}"
        )

        assert new_messages[-1].get("content") == "PASS_TEXT", (
            "new_messages must carry the surfaced text verbatim, not a "
            f"reconstructed one; got: {new_messages}"
        )
