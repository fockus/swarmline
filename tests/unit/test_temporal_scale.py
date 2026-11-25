"""Unit tests for phase-4 scale hardening: reference-based history,
continue-as-new resume state, and the eval trace exporter. Pure — no
temporalio, no server.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

from swarmline.eval.types import ScorerResult
from swarmline.runtime.temporal.eval_export import (
    run_to_eval_result,
    score_run_results,
)
from swarmline.runtime.temporal.loop_logic import drive_agent_loop
from swarmline.runtime.temporal.options import TemporalRuntimeOptions
from swarmline.runtime.temporal.payloads import (
    AgentRunInput,
    AgentRunResult,
    LlmStepInput,
    LlmStepOutput,
    ToolStepInput,
    ToolStepOutput,
)
from swarmline.runtime.temporal.state import (
    InMemoryHistoryStore,
    MessageStoreHistoryAdapter,
)

# ---------------------------------------------------------------------------
# History stores
# ---------------------------------------------------------------------------


class TestInMemoryHistoryStore:
    async def test_append_and_load(self) -> None:
        store = InMemoryHistoryStore()

        rev = await store.append("r1", [{"role": "user", "content": "hi"}])
        rev = await store.append(
            "r1", [{"role": "assistant", "content": "a"}], expected_revision=rev
        )

        assert rev == 2
        loaded = await store.load("r1")
        assert [m["role"] for m in loaded] == ["user", "assistant"]

    async def test_duplicate_append_is_skipped(self) -> None:
        store = InMemoryHistoryStore()
        await store.append("r1", [{"role": "user", "content": "hi"}])
        rev = await store.append(
            "r1", [{"role": "assistant", "content": "a"}], expected_revision=1
        )

        # Activity retry redelivers the same delta with a stale revision
        rev_after_retry = await store.append(
            "r1", [{"role": "assistant", "content": "a"}], expected_revision=1
        )

        assert rev == rev_after_retry == 2
        assert len(await store.load("r1")) == 2

    async def test_runs_are_isolated(self) -> None:
        store = InMemoryHistoryStore()
        await store.append("r1", [{"role": "user", "content": "one"}])
        await store.append("r2", [{"role": "user", "content": "two"}])

        assert (await store.load("r1"))[0]["content"] == "one"
        assert (await store.load("r2"))[0]["content"] == "two"


class FakeMessageStore:
    """Duck-typed swarmline MessageStore."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], list[SimpleNamespace]] = {}

    async def save_message(
        self,
        user_id: str,
        topic_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        content_blocks: list[dict[str, Any]] | None = None,
    ) -> None:
        self.records.setdefault((user_id, topic_id), []).append(
            SimpleNamespace(
                role=role,
                content=content,
                tool_calls=tool_calls,
                name=name,
                metadata=metadata,
            )
        )

    async def get_messages(
        self, user_id: str, topic_id: str, limit: int = 10
    ) -> list[SimpleNamespace]:
        return self.records.get((user_id, topic_id), [])[-limit:]

    async def count_messages(self, user_id: str, topic_id: str) -> int:
        return len(self.records.get((user_id, topic_id), []))


class TestMessageStoreHistoryAdapter:
    async def test_roundtrip_through_message_store(self) -> None:
        adapter = MessageStoreHistoryAdapter(FakeMessageStore())

        rev = await adapter.append(
            "r1",
            [
                {"role": "user", "content": "hi"},
                {"role": "tool", "content": "42", "name": "calc"},
            ],
        )

        assert rev == 2
        loaded = await adapter.load("r1")
        assert loaded[0] == {"role": "user", "content": "hi"}
        assert loaded[1] == {"role": "tool", "content": "42", "name": "calc"}

    async def test_duplicate_append_is_skipped(self) -> None:
        adapter = MessageStoreHistoryAdapter(FakeMessageStore())
        await adapter.append("r1", [{"role": "user", "content": "hi"}])

        rev = await adapter.append(
            "r1", [{"role": "user", "content": "hi"}], expected_revision=0
        )

        assert rev == 1
        assert len(await adapter.load("r1")) == 1


# ---------------------------------------------------------------------------
# Loop driver: reference mode + continue-as-new resume state
# ---------------------------------------------------------------------------


def _run_input(**overrides: Any) -> AgentRunInput:
    defaults: dict[str, Any] = {
        "messages": [{"role": "user", "content": "hi"}],
        "system_prompt": "sys",
        "tools": [{"name": "calc", "description": "d", "parameters": {}}],
        "run_id": "r1",
        "model": "m1",
    }
    defaults.update(overrides)
    return AgentRunInput(**defaults)


class ScriptedLlm:
    def __init__(self, outputs: list[LlmStepOutput]) -> None:
        self._outputs = list(outputs)
        self.calls: list[LlmStepInput] = []

    async def __call__(self, step: LlmStepInput) -> LlmStepOutput:
        # Snapshot messages: the driver passes its live list (the real
        # workflow serializes it at dispatch), so record what was visible
        # at call time.
        self.calls.append(dataclasses.replace(step, messages=list(step.messages)))
        return self._outputs.pop(0)


async def _ok_tool(step: ToolStepInput) -> ToolStepOutput:
    return ToolStepOutput(
        name=step.name, correlation_id=step.correlation_id, ok=True, result="42"
    )


def _tool_call(correlation_id: str = "c1") -> LlmStepOutput:
    return LlmStepOutput(
        kind="tool_call",
        raw='{"type": "tool_call"}',
        tool_name="calc",
        tool_args={"x": 1},
        correlation_id=correlation_id,
    )


def _final(text: str = "done") -> LlmStepOutput:
    return LlmStepOutput(kind="final", text=text)


def _store_appender(store: InMemoryHistoryStore, run_id: str = "r1") -> Any:
    async def append(messages: list[dict[str, Any]], expected_revision: int) -> int:
        return await store.append(run_id, messages, expected_revision)

    return append


class TestReferenceHistoryDriver:
    async def test_llm_steps_carry_revision_not_messages(self) -> None:
        store = InMemoryHistoryStore()
        llm = ScriptedLlm([_tool_call(), _final()])

        result = await drive_agent_loop(
            _run_input(use_reference_history=True),
            llm,
            _ok_tool,
            append_history=_store_appender(store),
        )

        assert result.status == "ok"
        # No conversation in LLM payloads — only revisions
        assert llm.calls[0].messages == []
        assert llm.calls[0].history_revision == 1  # seeded input
        assert llm.calls[1].history_revision == 3  # + assistant/result delta
        stored = await store.load("r1")
        assert [m["role"] for m in stored] == ["user", "assistant", "user"]
        assert "Result calc: 42" in stored[2]["content"]
        assert result.history_revision == 3

    async def test_continue_boundary_returns_resume_state(self) -> None:
        store = InMemoryHistoryStore()
        llm = ScriptedLlm([_tool_call()])

        segment = await drive_agent_loop(
            _run_input(use_reference_history=True, continue_after_iterations=1),
            llm,
            _ok_tool,
            append_history=_store_appender(store),
        )

        assert segment.status == "continue"
        assert segment.iterations == 1
        assert segment.tool_calls == 1
        assert segment.history_revision == 3
        assert len(segment.new_messages) == 2  # assistant tool_call + tool result

    async def test_resumed_segment_merges_carried_state(self) -> None:
        store = InMemoryHistoryStore()
        first = ScriptedLlm([_tool_call()])
        inp = _run_input(use_reference_history=True, continue_after_iterations=1)
        segment = await drive_agent_loop(
            inp, first, _ok_tool, append_history=_store_appender(store)
        )

        # What workflow.continue_as_new carries into the next segment
        resumed_input = dataclasses.replace(
            inp,
            messages=[],
            history_revision=segment.history_revision,
            start_iteration=segment.iterations,
            tool_calls_used=segment.tool_calls,
            carried_new_messages=segment.new_messages,
            carried_events=segment.events,
        )
        second = ScriptedLlm([_final("across segments")])
        result = await drive_agent_loop(
            resumed_input, second, _ok_tool, append_history=_store_appender(store)
        )

        assert result.status == "ok"
        assert result.text == "across segments"
        assert result.iterations == 2  # global count across segments
        assert result.tool_calls == 1
        assert len(result.new_messages) == 3  # carried pair + final assistant
        # No re-seed: the store still holds exactly one conversation
        assert len(await store.load("r1")) == 3
        assert second.calls[0].history_revision == 3

    async def test_max_iterations_is_global_across_segments(self) -> None:
        store = InMemoryHistoryStore()
        llm = ScriptedLlm([_tool_call()])

        result = await drive_agent_loop(
            _run_input(use_reference_history=True, max_iterations=6, start_iteration=5),
            llm,
            _ok_tool,
            append_history=_store_appender(store),
        )

        assert result.status == "error"
        assert result.error_kind == "loop_limit"
        assert result.iterations == 6

    async def test_without_append_callback_stays_inline(self) -> None:
        llm = ScriptedLlm([_tool_call(), _final()])

        result = await drive_agent_loop(
            _run_input(use_reference_history=True), llm, _ok_tool
        )

        assert result.status == "ok"
        # Inline fallback: full conversation travels in LLM payloads
        assert llm.calls[0].history_revision == -1
        assert llm.calls[0].messages == [{"role": "user", "content": "hi"}]
        assert len(llm.calls[1].messages) == 3


# ---------------------------------------------------------------------------
# Options validation
# ---------------------------------------------------------------------------


class TestScaleOptions:
    def test_continue_as_new_requires_reference_history(self) -> None:
        with pytest.raises(ValueError, match="use_reference_history"):
            TemporalRuntimeOptions(continue_as_new_after_iterations=10)

    def test_valid_combination(self) -> None:
        options = TemporalRuntimeOptions(
            use_reference_history=True, continue_as_new_after_iterations=10
        )
        assert options.continue_as_new_after_iterations == 10

    def test_from_config_reads_scale_keys(self) -> None:
        from swarmline.runtime.types import RuntimeConfig

        options = TemporalRuntimeOptions.from_config(
            RuntimeConfig(
                runtime_name="temporal",
                extra={
                    "temporal": {
                        "use_reference_history": True,
                        "continue_as_new_after_iterations": 25,
                        "redact_payloads": False,
                        "otel_interceptor": True,
                    }
                },
            )
        )

        assert options.use_reference_history
        assert options.continue_as_new_after_iterations == 25
        assert not options.redact_payloads
        assert options.otel_interceptor


# ---------------------------------------------------------------------------
# Eval trace export
# ---------------------------------------------------------------------------


def _run_result(**overrides: Any) -> AgentRunResult:
    defaults: dict[str, Any] = {
        "text": "the answer",
        "new_messages": [],
        "events": [{"id": "e1", "type": "assistant_delta", "data": {}}],
        "iterations": 2,
        "tool_calls": 1,
    }
    defaults.update(overrides)
    return AgentRunResult(**defaults)


class DummyScorer:
    name = "dummy"

    async def score(self, case: Any, output: str) -> ScorerResult:
        return ScorerResult(score=1.0 if output else 0.0, reason="scored")


class TestEvalExport:
    def test_ok_run_becomes_unscored_trace(self) -> None:
        trace = run_to_eval_result("r1", "what is 6*7?", _run_result())

        assert trace.case.id == "r1"
        assert trace.case.input == "what is 6*7?"
        assert trace.output == "the answer"
        assert trace.error is None
        assert trace.case.context["iterations"] == 2
        assert trace.case.context["event_types"] == ["assistant_delta"]
        assert "temporal-run" in trace.case.tags

    def test_failed_run_carries_error(self) -> None:
        trace = run_to_eval_result(
            "r1",
            "q",
            _run_result(status="error", error_kind="loop_limit", error_message="max"),
        )

        assert trace.error == "loop_limit: max"
        assert not trace.passed

    async def test_score_run_results_builds_report(self) -> None:
        ok_trace = run_to_eval_result("r1", "q", _run_result())
        failed_trace = run_to_eval_result(
            "r2", "q", _run_result(status="error", error_kind="loop_limit")
        )

        report = await score_run_results([ok_trace, failed_trace], [DummyScorer()])

        assert report.total == 2
        assert report.passed == 1
        scored = report.results[0]
        assert scored.scores["dummy"].score == 1.0
        assert report.results[1].scores == {}  # failed runs are not scored
