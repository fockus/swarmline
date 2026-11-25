"""Shared fakes/helpers for graph-composition streaming tests.

Extracted from ``test_harness_graph_streaming.py`` (graph-composition
Task 5) so that file stays under the 400-line cap -- same convention as
``_fake_redis.py``. Not a test module: pytest never collects it.

Fake seam: identical to ``test_harness_graph_apply.py`` -- lazily imported
``ThinRuntime`` is monkeypatched at its own module (``THIN_RUNTIME_PATH``);
``WorkflowGraph`` stays REAL.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from swarmline.harness.graph_assembly import _GraphAgentRuntime
from swarmline.harness.spec import CompositionSpec, HarnessSpec, WorkerSpec
from swarmline.orchestration.workflow_graph import WorkflowGraph
from swarmline.runtime.types import Message

THIN_RUNTIME_PATH = "swarmline.runtime.thin.runtime.ThinRuntime"


def _fake_thin_runtime_cls(
    outputs: dict[str, str],
    *,
    fail_mode_hint: str | None = None,
    block_mode_hint: str | None = None,
    entered: asyncio.Event | None = None,
    release: asyncio.Event | None = None,
    on_call: Callable[[str | None], None] | None = None,
    cancelled: asyncio.Event | None = None,
) -> type:
    """Deterministic fake ``ThinRuntime`` keyed by ``mode_hint``.
    *fail_mode_hint* yields a terminal error instead of a final.
    *block_mode_hint* signals *entered* then blocks on *release* (liveness /
    ``cancel()``/abandonment proofs -- required together with it); if the
    block is cancelled, *cancelled* (if given) is set before re-raising.
    *on_call* fires per ``mode_hint`` seen (proves a later node never ran).
    """

    class _FakeThinRuntime:
        def __init__(self, **_: Any) -> None:
            pass

        def run(self, *, messages, system_prompt, active_tools, mode_hint=None, **__):
            if on_call is not None:
                on_call(mode_hint)

            async def _events():
                from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent

                if mode_hint == fail_mode_hint:
                    yield RuntimeEvent.error(
                        RuntimeErrorData(kind="tool_error", message="boom")
                    )
                    return
                if mode_hint == block_mode_hint:
                    entered.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        if cancelled is not None:
                            cancelled.set()
                        raise
                yield RuntimeEvent.final(text=outputs[mode_hint])

            return _events()

        async def cleanup(self) -> None:
            pass

    return _FakeThinRuntime


def _direct_runtime(composition: CompositionSpec) -> _GraphAgentRuntime:
    """A ``_GraphAgentRuntime`` against a REAL ``WorkflowGraph`` -- no
    ``Agent``/``HarnessBuilder`` involved."""
    return _GraphAgentRuntime(HarnessSpec(composition=composition), WorkflowGraph)


async def _collect(runtime: _GraphAgentRuntime) -> list[Any]:
    return [
        event
        async for event in runtime.run(
            messages=[Message(role="user", content="swarmline")],
            system_prompt="sp",
            active_tools=[],
        )
    ]


def _progress(events: list[Any]) -> list[tuple[str, str]]:
    return [(e.data["role"], e.data["phase"]) for e in events if e.type == "status"]


def _rw_workers() -> tuple[WorkerSpec, ...]:
    return (
        WorkerSpec(role="researcher", kernel="react"),
        WorkerSpec(role="writer", kernel="adapt"),
    )


def _abc_workers() -> tuple[WorkerSpec, ...]:
    return (
        WorkerSpec(role="a", kernel="react"),
        WorkerSpec(role="b", kernel="adapt"),
        WorkerSpec(role="c", kernel="reflection"),
    )
