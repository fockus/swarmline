"""Tests for the RuntimeEvent -> EventJournal tap in ThinRuntime.run() (REQ-007/014/015).

Covers observability-events Task 2:
- REQ-007: every RuntimeEvent yielded by ThinRuntime.run() is also appended to
  the configured journal (side-channel tap, stream itself unfiltered).
- REQ-014: config.event_journal=None (default) -> byte-identical behavior,
  the journal path is never touched.
- REQ-015: a journal whose append() raises must not interrupt the run; the
  failure is surfaced via structured logging instead.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from structlog.testing import capture_logs

from swarmline.observability.journal import InMemoryEventJournal
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec


class _Boom(Exception):
    """Marker exception injected via athrow() in the proxy-forwarding test."""


class MockLLM:
    """Mock LLM returning queued responses, then a fallback final."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def __call__(self, messages: list[dict], system_prompt: str) -> str:
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return json.dumps({"type": "final", "final_message": "fallback"})


async def _collect(
    runtime: ThinRuntime,
    *,
    config: RuntimeConfig | None = None,
    tools: list[ToolSpec] | None = None,
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in runtime.run(
        messages=[Message(role="user", content="hello")],
        system_prompt="sys",
        active_tools=tools or [],
        config=config,
    ):
        events.append(ev)
    return events


class TestRuntimeEventJournalTap:
    """REQ-007: runtime events reach the journal when configured."""

    @pytest.mark.asyncio
    async def test_runtime_events_reach_journal_when_configured(self) -> None:
        journal = InMemoryEventJournal()
        llm = MockLLM([json.dumps({"type": "final", "final_message": "done"})])
        config = RuntimeConfig(runtime_name="thin", event_journal=journal)
        runtime = ThinRuntime(config=config, llm_call=llm)

        events = await _collect(runtime, config=config)

        assert events  # sanity: the run actually yielded something
        entries = [entry async for entry in journal.read()]
        assert len(entries) == len(events)
        for event, entry in zip(events, entries):
            assert entry.event_type == event.type
            assert entry.data == event.data

    @pytest.mark.asyncio
    async def test_tap_does_not_filter_or_reorder_the_stream(self) -> None:
        """The journal tap is a side-channel: the live stream is unchanged."""
        journal = InMemoryEventJournal()
        llm = MockLLM(
            [
                json.dumps({"type": "tool_call", "tool": {"name": "calc", "args": {}}}),
                json.dumps({"type": "final", "final_message": "done"}),
            ]
        )
        config = RuntimeConfig(runtime_name="thin", event_journal=journal)
        runtime = ThinRuntime(
            config=config, llm_call=llm, local_tools={"calc": lambda a: {"r": 1}}
        )

        events = await _collect(
            runtime,
            config=config,
            tools=[ToolSpec(name="calc", description="c", parameters={})],
        )

        assert events[-1].type == "final"
        assert await journal.last_seq() == len(events)


class TestRuntimeEventJournalTapOptOut:
    """REQ-014: event_journal=None (default) is byte-identical, journal untouched."""

    @pytest.mark.asyncio
    async def test_no_journal_configured_behavior_unchanged(self) -> None:
        llm = MockLLM([json.dumps({"type": "final", "final_message": "ok"})])
        config = RuntimeConfig(runtime_name="thin")
        assert config.event_journal is None
        runtime = ThinRuntime(config=config, llm_call=llm)

        events = await _collect(runtime, config=config)

        assert events[0].type == "status"
        assert events[-1].type == "final"

    @pytest.mark.asyncio
    async def test_run_returns_underlying_generator_when_no_journal(self) -> None:
        """REQ-014: run() returns _run_impl's async generator UNWRAPPED.

        Not a proxy: proves ``aclose``/``athrow``/``asend`` reach ``_run_impl``
        with zero added frames -- there is no wrapper object at all on this path.
        """
        llm = MockLLM([json.dumps({"type": "final", "final_message": "ok"})])
        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(config=config, llm_call=llm)

        result = runtime.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
            config=config,
        )

        assert inspect.isasyncgen(result)
        events = [ev async for ev in result]
        assert events[-1].type == "final"

    @pytest.mark.asyncio
    async def test_run_aclose_promptly_finalizes_inner_when_no_journal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REQ-014: aclose() on the unwrapped generator runs `_run_impl`'s
        `finally` immediately -- not deferred to GC (would happen if `run()`
        were itself an ``async def ... yield`` wrapper around `_run_impl`)."""
        marker = {"finalized": False}

        async def _fake_run_impl(
            self: ThinRuntime, **kwargs: Any
        ) -> AsyncIterator[RuntimeEvent]:
            try:
                yield RuntimeEvent.status("first")
                yield RuntimeEvent.status("second")
            finally:
                marker["finalized"] = True

        monkeypatch.setattr(ThinRuntime, "_run_impl", _fake_run_impl)

        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(config=config, llm_call=MockLLM([]))

        gen = runtime.run(
            messages=[], system_prompt="s", active_tools=[], config=config
        )
        first = await gen.__anext__()
        assert first.type == "status"
        assert marker["finalized"] is False

        await gen.aclose()

        assert marker["finalized"] is True


class TestRuntimeEventJournalTapProxyTransparency:
    """REQ-007/015: when a journal IS set, the proxy fully forwards control flow."""

    @pytest.mark.asyncio
    async def test_run_tapping_proxy_forwards_aclose_and_athrow_when_journal_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """athrow() is injected into `_run_impl` at its real suspension point,
        and aclose() still runs `_run_impl`'s `finally` -- while every value
        that actually flows through (including the recovery event yielded
        from inside the except-block) still reaches the journal."""
        marker = {"finalized": False}

        async def _fake_run_impl(
            self: ThinRuntime, **kwargs: Any
        ) -> AsyncIterator[RuntimeEvent]:
            try:
                yield RuntimeEvent.status("first")
                yield RuntimeEvent.status("second")
            except _Boom:
                yield RuntimeEvent.status("caught")
            finally:
                marker["finalized"] = True

        monkeypatch.setattr(ThinRuntime, "_run_impl", _fake_run_impl)

        journal = InMemoryEventJournal()
        config = RuntimeConfig(runtime_name="thin", event_journal=journal)
        runtime = ThinRuntime(config=config, llm_call=MockLLM([]))

        gen = runtime.run(
            messages=[], system_prompt="s", active_tools=[], config=config
        )
        assert not inspect.isasyncgen(gen)  # this IS the tapping proxy

        first = await gen.__anext__()
        assert first.type == "status" and first.data["text"] == "first"

        # athrow() must reach _run_impl's real suspension point -- observed by
        # the except-clause, which recovers by yielding "caught".
        recovered = await gen.athrow(_Boom())
        assert recovered.type == "status"
        assert recovered.data["text"] == "caught"
        assert marker["finalized"] is False  # still open, not closed yet

        await gen.aclose()
        assert marker["finalized"] is True

        entries = [entry async for entry in journal.read()]
        assert [entry.data.get("text") for entry in entries] == ["first", "caught"]


class TestRuntimeEventJournalTapFailureIsolation:
    """REQ-015: a broken journal must never interrupt the run."""

    @pytest.mark.asyncio
    async def test_journal_append_failure_logged_not_raised(self) -> None:
        class ExplodingJournal:
            async def append(self, event_type: str, data: dict[str, Any]) -> int:
                raise RuntimeError("journal backend unavailable")

            async def last_seq(self) -> int:
                return 0

        llm = MockLLM([json.dumps({"type": "final", "final_message": "ok"})])
        config = RuntimeConfig(runtime_name="thin", event_journal=ExplodingJournal())
        runtime = ThinRuntime(config=config, llm_call=llm)

        with capture_logs() as logs:
            events = await _collect(runtime, config=config)

        # The run completed normally despite every append() raising.
        assert events
        assert events[-1].type == "final"

        warnings = [entry for entry in logs if entry.get("log_level") == "warning"]
        assert warnings, f"expected a structured warning log, got: {logs}"
        assert all("journal backend unavailable" in str(w) for w in warnings) or any(
            "runtime_event_tap" in str(w.get("event", "")) for w in warnings
        )
