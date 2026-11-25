"""Shared test scaffolding for ``test_followup_requeue.py`` (kernel-wiring Task 1).

Extracted so the test module stays under the 400-line file-size cap (mirrors
the ``tests/unit/_graph_streaming_fakes.py`` / ``tests/unit/_fake_redis.py``
convention for tests/ file-size discipline). Pure scaffolding — no
behavior/assertions live here, only fakes/helpers reused by ≥2 tests.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from swarmline.runtime.thin.native_tools import NativeToolCallResult
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeEvent, ToolSpec

TOOL = ToolSpec(name="noop", description="do nothing", parameters={})


def noop_tool(**kwargs: object) -> str:
    return json.dumps({"result": "ok"})


async def collect(runtime: ThinRuntime) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content="go")],
        system_prompt="You are a helper.",
        active_tools=[TOOL],
        mode_hint="react",
    ):
        events.append(ev)
    return events


async def unreachable_llm(messages: Any, prompt: Any, **kwargs: Any) -> str:
    raise AssertionError(
        "text-ReAct llm_call must not be reached — native adapter handles the turn"
    )


class FinishNoToolsNativeAdapter:
    """Native adapter that immediately finishes each turn with no tool calls.

    Mirrors the fake native adapters in ``test_kernel_mid_run_hooks.py``
    (``_StopAfterOneNativeAdapter`` / ``_RecordingNativeAdapter``): records
    every ``messages`` snapshot it is called with, so a test can assert the
    follow-up message reached the model on the NEXT native turn.
    """

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.call_count = 0
        self.seen_messages: list[list[dict[str, Any]]] = []

    async def call_with_tools(
        self, messages: Any, system_prompt: str, tools: Any, **kwargs: Any
    ) -> NativeToolCallResult:
        self.call_count += 1
        self.seen_messages.append([dict(m) for m in messages])
        text = self._texts.pop(0) if self._texts else "done"
        return NativeToolCallResult(text=text, tool_calls=())


class SequentialStreamingLLM:
    """Streams each turn's ``final_message`` JSON token-by-token.

    Mirrors ``MockStreamingLLM`` in ``tests/unit/test_thin_streaming.py``:
    ``stream=True`` returns an async-iterable of small string chunks;
    ``stream=False`` returns the full envelope. Used to prove a streaming
    text-ReAct turn does NOT leak the requeued turn's answer via
    ``assistant_delta`` before ``maybe_followup_requeue`` runs — the native
    seam and the buffered/non-streaming text seam already suppress it
    (their ``continue`` fires before any ``assistant_delta``); streaming was
    the outlier (GPT-5.5 review MAJOR).
    """

    def __init__(self, final_texts: list[str]) -> None:
        self._final_texts = list(final_texts)
        self.call_count = 0

    async def __call__(
        self, messages: list, system_prompt: str, *, stream: bool = False
    ) -> str | AsyncIterator[str]:
        idx = self.call_count
        self.call_count += 1
        text = self._final_texts[idx] if idx < len(self._final_texts) else "done"
        envelope = json.dumps({"type": "final", "final_message": text})
        if stream:
            return self._chunks(envelope)
        return envelope

    @staticmethod
    async def _chunks(payload: str) -> AsyncIterator[str]:
        for i in range(0, len(payload), 8):
            yield payload[i : i + 8]
