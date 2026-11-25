"""Integration tests for retry policy with ThinRuntime — Phase 7D.

Tests that ThinRuntime correctly retries LLM calls when retry_policy is set,
stops after exhausting retries, and preserves backward compatibility.
"""

from __future__ import annotations

import json
from typing import Any

from swarmline.retry import ExponentialBackoff
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
)
import pytest

pytestmark = pytest.mark.integration


async def _collect_events(runtime: ThinRuntime, user_text: str) -> list[RuntimeEvent]:
    """Helper: run ThinRuntime and collect all events."""
    messages = [Message(role="user", content=user_text)]
    events: list[RuntimeEvent] = []
    async for event in runtime.run(
        messages=messages,
        system_prompt="You are a test assistant.",
        active_tools=[],
    ):
        events.append(event)
    return events


class TestThinRuntimeRetryIntegration:
    """Integration tests for retry logic in ThinRuntime."""

    async def test_retry_on_llm_error_succeeds_on_second_attempt(self) -> None:
        """ThinRuntime with ExponentialBackoff retries on LLM error, succeeds on 2nd try."""
        call_count = 0

        async def flaky_llm(
            messages: list[dict[str, str]],
            system_prompt: str,
            **kwargs: Any,
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ThinLlmError(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message="Rate limit exceeded",
                        recoverable=True,
                    )
                )
            return '{"type": "final", "final_message": "Success after retry"}'

        policy = ExponentialBackoff(max_retries=3, base_delay=0.01, jitter=False)
        config = RuntimeConfig(runtime_name="thin", retry_policy=policy)
        runtime = ThinRuntime(config=config, llm_call=flaky_llm)

        events = await _collect_events(runtime, "hello")

        # Should have retried and succeeded
        assert call_count == 2
        final_events = [e for e in events if e.is_final]
        assert len(final_events) == 1
        assert "Success after retry" in final_events[0].data["text"]

        # Should have emitted a retry status event
        status_events = [e for e in events if e.type == "status"]
        retry_statuses = [s for s in status_events if "Retry" in s.data.get("text", "")]
        assert len(retry_statuses) >= 1

    async def test_retry_exhausted_emits_error(self) -> None:
        """ThinRuntime with ExponentialBackoff emits error when retries exhausted."""
        call_count = 0

        async def always_fail_llm(
            messages: list[dict[str, str]],
            system_prompt: str,
            **kwargs: Any,
        ) -> str:
            nonlocal call_count
            call_count += 1
            raise ThinLlmError(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message="Service unavailable",
                    recoverable=True,
                )
            )

        policy = ExponentialBackoff(max_retries=2, base_delay=0.01, jitter=False)
        config = RuntimeConfig(runtime_name="thin", retry_policy=policy)
        runtime = ThinRuntime(config=config, llm_call=always_fail_llm)

        events = await _collect_events(runtime, "hello")

        # Should have attempted 1 initial + 2 retries = 3 calls
        assert call_count == 3
        error_events = [e for e in events if e.is_error]
        assert len(error_events) == 1
        assert "Service unavailable" in error_events[0].data["message"]

    async def test_retry_on_stream_iteration_error_succeeds_on_second_attempt(
        self,
    ) -> None:
        """Stream-time ThinLlmError is retried when retry_policy is configured."""
        call_count = 0

        async def flaky_stream_llm(
            messages: list[dict[str, str]],
            system_prompt: str,
            **kwargs: Any,
        ) -> Any:
            nonlocal call_count
            call_count += 1
            if kwargs.get("stream"):
                if call_count == 1:

                    async def _broken():
                        raise ThinLlmError(
                            RuntimeErrorData(
                                kind="runtime_crash",
                                message="Stream interrupted",
                                recoverable=True,
                            )
                        )
                        yield ""

                    return _broken()

                async def _ok():
                    yield '{"type":"final","final_message":"Success after retry"}'

                return _ok()

            return '{"type": "final", "final_message": "Success after retry"}'

        policy = ExponentialBackoff(max_retries=2, base_delay=0.01, jitter=False)
        config = RuntimeConfig(runtime_name="thin", retry_policy=policy)
        runtime = ThinRuntime(config=config, llm_call=flaky_stream_llm)

        events = await _collect_events(runtime, "hello")

        assert call_count == 2
        final_events = [e for e in events if e.is_final]
        assert len(final_events) == 1
        assert final_events[0].data["text"] == "Success after retry"
        retry_statuses = [
            e
            for e in events
            if e.type == "status" and "Retry attempt" in e.data.get("text", "")
        ]
        assert len(retry_statuses) >= 1

    async def test_retry_exhausted_on_stream_iteration_error_emits_terminal_error(
        self,
    ) -> None:
        """Stream-time failures still surface as error after retry budget is exhausted."""
        call_count = 0

        async def always_fail_stream_llm(
            messages: list[dict[str, str]],
            system_prompt: str,
            **kwargs: Any,
        ) -> Any:
            nonlocal call_count
            call_count += 1
            if kwargs.get("stream"):

                async def _broken():
                    raise ThinLlmError(
                        RuntimeErrorData(
                            kind="runtime_crash",
                            message="Stream interrupted",
                            recoverable=True,
                        )
                    )
                    yield ""

                return _broken()

            raise AssertionError("non-stream fallback is not expected")

        policy = ExponentialBackoff(max_retries=2, base_delay=0.01, jitter=False)
        config = RuntimeConfig(runtime_name="thin", retry_policy=policy)
        runtime = ThinRuntime(config=config, llm_call=always_fail_stream_llm)

        events = await _collect_events(runtime, "hello")

        assert call_count == 3
        error_events = [e for e in events if e.is_error]
        assert len(error_events) == 1
        assert "Stream interrupted" in error_events[0].data["message"]

    async def test_no_retry_policy_backward_compatible(self) -> None:
        """ThinRuntime without retry_policy does NOT retry (backward compat)."""
        call_count = 0

        async def fail_once_llm(
            messages: list[dict[str, str]],
            system_prompt: str,
            **kwargs: Any,
        ) -> str:
            nonlocal call_count
            call_count += 1
            raise ThinLlmError(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message="API error",
                    recoverable=True,
                )
            )

        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(config=config, llm_call=fail_once_llm)

        events = await _collect_events(runtime, "hello")

        # No retry — only 1 call
        assert call_count == 1
        error_events = [e for e in events if e.is_error]
        assert len(error_events) == 1


class TestAgentConfigRetryPolicyIntegration:
    """AgentConfig.retry_policy threaded through runtime_wiring into ThinRuntime.

    Exercises the real facade seam (AgentConfig -> build_portable_runtime_plan ->
    RuntimeConfig -> ThinRuntime.run) rather than constructing RuntimeConfig by
    hand, so the wiring change is covered end-to-end. Only the LLM boundary is
    faked (external service boundary); the tool executor is a real callable so a
    replay would be observable as a second invocation.
    """

    async def test_retries_transient_llm_error_without_replaying_completed_tool_call(
        self,
    ) -> None:
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        tool_invocations: list[dict[str, Any]] = []

        def double(args: dict[str, Any]) -> dict[str, Any]:
            tool_invocations.append(dict(args))
            return {"result": args["x"] * 2}

        call_count = 0

        async def flaky_llm(
            messages: list[dict[str, str]],
            system_prompt: str,
            **kwargs: Any,
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Turn 1: LLM asks for a tool call — executed exactly once.
                return json.dumps(
                    {
                        "type": "tool_call",
                        "tool": {
                            "name": "double",
                            "args": {"x": 21},
                            "correlation_id": "c1",
                        },
                        "assistant_message": "",
                    }
                )
            if call_count == 2:
                # Turn 2 (first attempt after the tool result): transient failure.
                raise ThinLlmError(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message="Transient upstream error",
                        recoverable=True,
                    )
                )
            # Turn 2, retried: succeeds without redoing the tool call.
            return json.dumps({"type": "final", "final_message": "Answer: 42"})

        policy = ExponentialBackoff(max_retries=2, base_delay=0.01, jitter=False)
        agent_config = AgentConfig(system_prompt="test", retry_policy=policy)

        plan = build_portable_runtime_plan(agent_config, "thin")
        assert plan.config.retry_policy is policy

        runtime = ThinRuntime(
            config=plan.config,
            llm_call=flaky_llm,
            local_tools={"double": double},
        )

        events: list[RuntimeEvent] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="double 21")],
            system_prompt="test",
            active_tools=[],
            mode_hint="react",
        ):
            events.append(event)

        # The tool executed exactly once — the retried LLM call must not
        # re-trigger execution of an already-completed tool call.
        assert tool_invocations == [{"x": 21}]
        assert call_count == 3

        final_events = [e for e in events if e.type == "final"]
        assert len(final_events) == 1
        assert "42" in final_events[0].data["text"]

        retry_statuses = [
            e
            for e in events
            if e.type == "status" and "Retry attempt" in e.data.get("text", "")
        ]
        assert len(retry_statuses) >= 1
