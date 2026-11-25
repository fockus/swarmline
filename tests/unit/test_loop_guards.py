"""Deterministic stop signals and the run time budget (taskloom Sprint 1ce Stage 5).

Drives ``run_react`` directly with a scripted model (no network) and a fake clock
(``loop_guards._monotonic`` patched; nothing sleeps for the budget):

- no progress: the same call with the same (de-volatilised) result warns once, a
  second signal soft-lands with ``exit_reason="no_progress"``;
- a loop after compaction: re-running the tail of calls from before a compaction
  is the same signal;
- an empty model reply is retried once with a nudge, a second one fails the run
  with ``empty_model_response`` instead of an empty completion;
- the run time budget: a wrap-up notice appended at the tail at 80%, a soft landing
  with ``exit_reason="time_budget"`` at 100%, every model call capped by what is left;
- guards off: requests byte-identical to the pre-Stage-5 loop (golden hash).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import pytest

from swarmline.evolution.stuck_detector import StuckDetector, ToolCallRecord
from swarmline.runtime.thin import loop_guards
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.loop_guards import (
    EMPTY_MODEL_RESPONSE,
    EMPTY_REPLY_NOTICE,
    NO_PROGRESS_NOTICE,
    TIME_BUDGET_NOTICE,
    LoopGuards,
    RunTimeBudgetExceeded,
)
from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.strategies import run_react
from swarmline.runtime.types import RuntimeConfig, RuntimeEvent, ToolSpec

_SYSTEM_PROMPT = "SYSTEM-SENTINEL: you are a helper."
_LANDING_MARK = "Do not call any tools."


def _tool_call(name: str, **args: object) -> str:
    return json.dumps({"type": "tool_call", "tool": {"name": name, "args": args}})


def _final(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


class _Clock:
    """Fake monotonic clock: the model advances it, nothing really sleeps."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(loop_guards, "_monotonic", fake)
    return fake


class _Model:
    """Scripted text-ReAct model. ``script(n)`` answers the n-th (1-based) loop call;
    a soft-landing request (last message asks for a tool-less summary) gets
    ``landing``. Every request is recorded; ``tick`` seconds pass per call."""

    def __init__(
        self,
        script: Callable[[int], str],
        *,
        clock: _Clock | None = None,
        tick: float = 0.0,
        landing: str = "SUMMARY: stopped",
    ) -> None:
        self._script = script
        self._clock = clock
        self._tick = tick
        self._landing = landing
        self.requests: list[tuple[list[dict[str, str]], str, dict[str, Any]]] = []
        self.loop_calls = 0

    async def __call__(
        self, messages: list[dict[str, str]], prompt: str, **kwargs: Any
    ) -> str:
        self.requests.append(([dict(m) for m in messages], prompt, dict(kwargs)))
        if self._clock is not None:
            self._clock.now += self._tick
        if messages and _LANDING_MARK in messages[-1]["content"]:
            return self._landing
        self.loop_calls += 1
        return self._script(self.loop_calls)


def _config(
    native: dict[str, object] | None = None, **overrides: object
) -> RuntimeConfig:
    base = RuntimeConfig(
        runtime_name="thin",
        max_iterations=30,
        max_tool_calls=1_000,
        native_config=dict(native or {}),
    )
    return replace(base, **overrides)


_GUARDS_ON: dict[str, object] = {"loop_guards_enabled": True}


def _tools(**handlers: Callable[..., str]) -> tuple[ToolExecutor, list[ToolSpec]]:
    specs = [ToolSpec(name=n, description=f"{n} tool", parameters={}) for n in handlers]
    return ToolExecutor(local_tools=dict(handlers)), specs


async def _drive(
    model: Callable[..., Any],
    config: RuntimeConfig,
    tools: tuple[ToolExecutor, list[ToolSpec]] | None = None,
    **kwargs: Any,
) -> list[RuntimeEvent]:
    executor, specs = tools or _tools(probe=lambda **_: "same result")
    events: list[RuntimeEvent] = []
    async for event in run_react(
        model,
        executor,
        messages=[],
        system_prompt=_SYSTEM_PROMPT,
        tools=specs,
        config=config,
        start_time=time.monotonic(),
        **kwargs,
    ):
        events.append(event)
    return events


def _statuses(events: list[RuntimeEvent]) -> list[str]:
    return [e.text for e in events if e.type == "status"]


def _final_event(events: list[RuntimeEvent]) -> RuntimeEvent:
    finals = [e for e in events if e.type == "final"]
    assert len(finals) == 1, [e.type for e in events]
    return finals[0]


def _exit_reason(events: list[RuntimeEvent]) -> object:
    return _final_event(events).data.get("native_metadata", {}).get("exit_reason")


def _tool_runs(events: list[RuntimeEvent]) -> int:
    return sum(1 for e in events if e.type == "tool_call_finished")


# --- no progress ------------------------------------------------------------


async def test_identical_call_and_result_twice_warns_once() -> None:
    """The first call plus two identical repeats (StuckDetector's exact-repeat
    threshold) raise ONE warning, appended right after the third result; a model
    that then finishes completes normally."""
    model = _Model(lambda n: _tool_call("probe") if n <= 3 else _final("done"))

    events = await _drive(model, _config(_GUARDS_ON))

    assert _final_event(events).text == "done"
    assert _exit_reason(events) is None
    assert [s for s in _statuses(events) if s.startswith("loop_guard.warned")] == [
        "loop_guard.warned: probe"
    ]
    warned_request = model.requests[3][0]
    assert warned_request[-1] == {"role": "user", "content": NO_PROGRESS_NOTICE}
    assert "probe" in warned_request[-2]["content"], (
        "the notice follows the third tool result"
    )
    assert sum(m["content"] == NO_PROGRESS_NOTICE for m in warned_request) == 1
    assert all(
        NO_PROGRESS_NOTICE not in m["content"]
        for req in model.requests[:3]
        for m in req[0]
    )


async def test_second_signal_soft_lands_with_no_progress_exit_reason() -> None:
    model = _Model(lambda n: _tool_call("probe"))

    events = await _drive(model, _config(_GUARDS_ON))

    final = _final_event(events)
    assert final.text == "SUMMARY: stopped"
    assert _exit_reason(events) == "no_progress"
    assert _tool_runs(events) == 4, (
        "warned on the 3rd identical call, landed after the 4th"
    )
    landing_messages, landing_prompt, _ = model.requests[-1]
    assert landing_prompt == _SYSTEM_PROMPT, "the landing call carries no tool schemas"
    assert "repeating the same tool call" in landing_messages[-1]["content"]
    assert len(model.requests) == 5


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            '{"status": "ok", "at": "2026-09-27T10:00:00Z"}',
            '{"status": "ok", "at": "2026-09-27T10:00:07.123+03:00"}',
        ),
        (
            "job 3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b queued",
            "job 0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d queued",
        ),
        ('{"rows": 3, "duration": 0.12}', '{"rows": 3, "duration": 4.5}'),
        (
            '{"rows": 3, "meta": {"elapsed_ms": 12, "pid": 101}}',
            '{"rows": 3, "meta": {"elapsed_ms": 900, "pid": 7}}',
        ),
        ('[{"pid": 1, "name": "a"}]', '[{"pid": 2, "name": "a"}]'),
    ],
    ids=["timestamp", "uuid", "duration", "elapsed-pid-nested", "list-of-objects"],
)
def test_volatile_fields_ignored_in_result_fingerprint(first: str, second: str) -> None:
    assert ToolCallRecord.compute_result_hash(
        first
    ) == ToolCallRecord.compute_result_hash(second)


def test_result_fingerprint_changes_with_real_content() -> None:
    assert ToolCallRecord.compute_result_hash(
        '{"rows": 3, "duration": 1}'
    ) != ToolCallRecord.compute_result_hash('{"rows": 4, "duration": 1}')
    assert ToolCallRecord.compute_result_hash(
        "build failed"
    ) != ToolCallRecord.compute_result_hash("build passed")


async def test_same_args_different_result_counts_as_progress() -> None:
    """Polling: the same call whose result keeps changing is progress, not a loop."""
    counter = iter(range(100))
    tools = _tools(poll=lambda **_: json.dumps({"done": 0, "seen": next(counter)}))
    model = _Model(
        lambda n: _tool_call("poll") if n <= 6 else _final("finished polling")
    )

    events = await _drive(model, _config(_GUARDS_ON), tools)

    assert _final_event(events).text == "finished polling"
    assert not [s for s in _statuses(events) if s.startswith("loop_guard")]
    assert _tool_runs(events) == 6


def test_stuck_detector_exact_repeat_is_result_aware_only_when_hash_given() -> None:
    """Additive ``result_hash``: set, a changing result breaks the repeat; unset
    (the pre-Stage-5 records), the detector behaves exactly as before."""
    args_hash = ToolCallRecord.compute_args_hash({})
    legacy = [ToolCallRecord("poll", args_hash, f"r{i}") for i in range(3)]
    hashed = [
        ToolCallRecord("poll", args_hash, f"r{i}", result_hash=f"h{i}")
        for i in range(3)
    ]
    detector = StuckDetector()

    assert detector.detect(legacy) is not None
    assert detector.detect_latest_repeat(legacy) is not None
    assert detector.detect_latest_repeat(hashed) is None


def test_stuck_detector_latest_repeat_on_empty_history_is_none() -> None:
    assert StuckDetector().detect_latest_repeat([]) is None


def test_stuck_detector_latest_repeat_ignores_an_old_loop_the_model_left() -> None:
    args_hash = ToolCallRecord.compute_args_hash({})
    same = ToolCallRecord("probe", args_hash, "x", result_hash="h")
    moved_on = ToolCallRecord("other", args_hash, "y", result_hash="k")

    assert StuckDetector().detect_latest_repeat([same, same, same, moved_on]) is None


async def test_model_that_changes_approach_after_warning_is_not_stopped() -> None:
    tools = _tools(
        probe=lambda **_: "same result", other=lambda **kw: f"page {kw.get('n')}"
    )

    def script(n: int) -> str:
        if n <= 3:
            return _tool_call("probe")
        return _tool_call("other", n=n) if n <= 7 else _final("changed approach")

    events = await _drive(_Model(script), _config(_GUARDS_ON), tools)

    assert _final_event(events).text == "changed approach"
    assert _exit_reason(events) is None
    assert len([s for s in _statuses(events) if s.startswith("loop_guard.warned")]) == 1


async def test_parallel_identical_calls_in_one_round_fingerprinted_each() -> None:
    """Native tool calling: every call of a parallel batch is fingerprinted; one round
    raises at most one signal, so three identical calls in ONE round warn (not stop)."""
    batch = tuple(NativeToolCall(id=f"c{i}", name="probe", args={}) for i in range(3))

    class _Native:
        def __init__(self) -> None:
            self.results = [
                NativeToolCallResult(tool_calls=batch),
                NativeToolCallResult(text="native done"),
            ]
            self.requests: list[list[dict[str, str]]] = []

        async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
            self.requests.append([dict(m) for m in messages])
            return self.results.pop(0)

    native = _Native()
    events = await _drive(
        _Model(lambda n: _final("unused")),
        _config(_GUARDS_ON, use_native_tools=True),
        native_adapter=native,
    )

    assert _final_event(events).text == "native done"
    assert _tool_runs(events) == 3
    assert [s for s in _statuses(events) if s.startswith("loop_guard")] == [
        "loop_guard.warned: probe"
    ]
    assert native.requests[1][-1] == {"role": "user", "content": NO_PROGRESS_NOTICE}


# --- loop after compaction ----------------------------------------------------


@dataclass
class _Refresh:
    lm_messages: list[dict[str, str]]
    compacted: bool


class _CompactingRefresher:
    """Stands in for the Stage 3 per-round refresher: reports a compaction before
    ``compact_at_round`` and otherwise leaves the projection untouched."""

    compression_history: tuple[()] = ()

    def __init__(self, compact_at_round: int | None) -> None:
        self._round = compact_at_round

    def start_run(self, config, *, resumed: bool, auto_verify: bool) -> None:
        return None

    async def before_round(
        self, *, round_index, lm_messages, messages, new_messages, system_prompt
    ):
        return _Refresh(lm_messages=lm_messages, compacted=round_index == self._round)


def _reread_script(n: int) -> str:
    files = ["a.py", "b.py", "c.py"]
    if n <= 6:
        return _tool_call("read", path=files[(n - 1) % 3])
    return _final("read everything")


@pytest.mark.parametrize(
    ("compact_at", "warned"),
    [(4, True), (None, False)],
    ids=["after-compaction", "no-compaction"],
)
async def test_post_compaction_repeat_of_pre_compaction_tail_detected(
    compact_at: int | None, warned: bool
) -> None:
    """a, b, c, [compaction], a, b, c: no single call repeats three times, so only the
    post-compaction detector can see the model re-reading what it read before."""
    tools = _tools(read=lambda **kw: f"contents of {kw['path']}")

    events = await _drive(
        _Model(_reread_script),
        _config(_GUARDS_ON),
        tools,
        round_refresher=_CompactingRefresher(compact_at),
    )

    assert _final_event(events).text == "read everything"
    signals = [s for s in _statuses(events) if s.startswith("loop_guard.warned")]
    assert signals == (["loop_guard.warned: read"] if warned else [])


# --- empty model reply ----------------------------------------------------------


async def test_empty_reply_retried_once_then_failed_with_error() -> None:
    model = _Model(lambda n: "  ")

    events = await _drive(model, _config(_GUARDS_ON))

    errors = [e for e in events if e.type == "error"]
    assert [e.data["message"] for e in errors] == [EMPTY_MODEL_RESPONSE]
    assert not [e for e in events if e.type == "final"], (
        "an empty reply never completes the run"
    )
    assert len(model.requests) == 2
    assert model.requests[1][0][-1] == {"role": "user", "content": EMPTY_REPLY_NOTICE}


async def test_empty_reply_after_tool_result_recovers_on_retry() -> None:
    """The real flash-model failure: a blank reply right after a tool result. One
    nudge, the model answers, the run completes; the streak resets on an answer."""
    replies = {1: _tool_call("probe"), 2: "", 3: _final("recovered")}
    model = _Model(lambda n: replies[n])

    events = await _drive(model, _config(_GUARDS_ON))

    assert _final_event(events).text == "recovered"
    assert model.requests[2][0][-1] == {"role": "user", "content": EMPTY_REPLY_NOTICE}


async def test_native_empty_reply_is_nudged_then_answered() -> None:
    class _Native:
        def __init__(self) -> None:
            self.results = [
                NativeToolCallResult(text=""),
                NativeToolCallResult(text="native answer"),
            ]
            self.requests: list[list[dict[str, str]]] = []

        async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
            self.requests.append([dict(m) for m in messages])
            return self.results.pop(0)

    native = _Native()
    events = await _drive(
        _Model(lambda n: _final("unused")),
        _config(_GUARDS_ON, use_native_tools=True),
        native_adapter=native,
    )

    assert _final_event(events).text == "native answer"
    assert native.requests[1][-1] == {"role": "user", "content": EMPTY_REPLY_NOTICE}


# --- run time budget ------------------------------------------------------------


async def test_time_budget_notice_at_80_percent_once_appended_at_tail(
    clock: _Clock,
) -> None:
    budget = {**_GUARDS_ON, "run_budget_seconds": 100}
    model = _Model(
        lambda n: _tool_call("probe", n=n) if n <= 4 else _final("delivered"),
        clock=clock,
        tick=20,
    )

    events = await _drive(model, _config(budget))

    assert _final_event(events).text == "delivered"
    noticed = [
        i
        for i, (msgs, _, _) in enumerate(model.requests)
        if any(m["content"] == TIME_BUDGET_NOTICE for m in msgs)
    ]
    assert noticed and noticed[0] == 4, (
        "first request sent at >=80% of the budget (t=80s)"
    )
    fifth, fourth = model.requests[4][0], model.requests[3][0]
    assert fifth[-1] == {"role": "user", "content": TIME_BUDGET_NOTICE}
    assert fifth[: len(fourth)] == fourth, (
        "the notice is appended; the prefix is untouched"
    )
    assert (
        sum(m["content"] == TIME_BUDGET_NOTICE for m in model.requests[-1][0]) == 1
    ), "once per run"


async def test_time_budget_exhausted_soft_lands_with_time_budget_exit_reason(
    clock: _Clock,
) -> None:
    model = _Model(lambda n: _tool_call("probe", n=n), clock=clock, tick=30)

    events = await _drive(model, _config({**_GUARDS_ON, "run_budget_seconds": 100}))

    assert _final_event(events).text == "SUMMARY: stopped"
    assert _exit_reason(events) == "time_budget"
    assert _tool_runs(events) == 4, (
        "t=120s after the 4th call; the 5th request is the landing"
    )
    assert (
        "time budget for this run is exhausted" in model.requests[-1][0][-1]["content"]
    )


async def test_llm_timeout_capped_by_remaining_budget(clock: _Clock) -> None:
    """A model call that would outlive the budget is cut at what is left (here 50 ms
    of real time), and the run soft-lands instead of hanging."""
    hang = asyncio.Event()
    calls = 0

    async def model(messages, prompt, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            clock.now += 99.95  # 50 ms of budget left for the next call
            return _tool_call("probe")
        if messages and _LANDING_MARK in messages[-1]["content"]:
            return "SUMMARY: out of time"
        await hang.wait()
        raise AssertionError("unreachable: the budget cap cancels this call")

    started = time.monotonic()
    events = await asyncio.wait_for(
        _drive(model, _config({**_GUARDS_ON, "run_budget_seconds": 100})), timeout=5
    )

    assert time.monotonic() - started < 2
    assert _final_event(events).text == "SUMMARY: out of time"
    assert _exit_reason(events) == "time_budget"


@pytest.mark.parametrize(
    "reply",
    [
        NativeToolCallResult(text="late answer"),
        NativeToolCallResult(
            tool_calls=(NativeToolCall(id="late", name="probe", args={}),)
        ),
    ],
    ids=["final-answer", "tool-call"],
)
async def test_native_call_exceeding_time_budget_is_cancelled_and_soft_lands(
    reply: NativeToolCallResult,
    clock: _Clock,
) -> None:
    cancelled = False
    native_calls = 0

    class _Native:
        async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
            nonlocal cancelled, native_calls
            native_calls += 1
            if native_calls == 1:
                clock.now += 99.95
                return NativeToolCallResult(
                    tool_calls=(NativeToolCall(id="first", name="probe", args={}),)
                )
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                cancelled = True
                raise
            return reply

    model = _Model(lambda n: _final("unexpected fallback"))

    events = await _drive(
        model,
        _config({**_GUARDS_ON, "run_budget_seconds": 100}, use_native_tools=True),
        native_adapter=_Native(),
    )

    assert cancelled
    assert _exit_reason(events) == "time_budget"
    assert _final_event(events).text == "SUMMARY: stopped"
    assert _tool_runs(events) == 1
    assert model.loop_calls == 0
    assert len(model.requests) == 1


async def test_native_call_caller_cancellation_propagates_without_fallback() -> None:
    started = asyncio.Event()
    cancelled = False

    class _Native:
        async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
            nonlocal cancelled
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled = True
                raise

    model = _Model(lambda n: _final("unexpected fallback"))
    task = asyncio.create_task(
        _drive(
            model,
            _config({**_GUARDS_ON, "run_budget_seconds": 60}, use_native_tools=True),
            native_adapter=_Native(),
        )
    )
    await started.wait()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled
    assert model.requests == []


async def test_streamed_reply_stalling_past_the_budget_soft_lands(
    clock: _Clock,
) -> None:
    async def stalled_stream():
        clock.now += 99.95  # the reply starts, then stalls: 50 ms of budget left
        yield '{"type": "fin'
        await asyncio.Event().wait()

    async def model(messages, prompt, **kwargs):
        if messages and _LANDING_MARK in messages[-1]["content"]:
            return "SUMMARY: stalled"
        if kwargs.get("stream"):
            return stalled_stream()
        raise TypeError("stream only")

    events = await asyncio.wait_for(
        _drive(model, _config({**_GUARDS_ON, "run_budget_seconds": 100})), timeout=5
    )

    assert _exit_reason(events) == "time_budget"


async def test_bounded_call_keeps_the_callers_own_shorter_timeout(
    clock: _Clock,
) -> None:
    """Capped by the budget, never extended: the provider's own timeout still wins
    when it fires first, and is not relabelled as the run's time budget."""
    guards = LoopGuards.from_config(
        _config({**_GUARDS_ON, "run_budget_seconds": 1_000})
    )

    async def own_timeout(*args, **kwargs):
        raise TimeoutError("provider timeout")

    with pytest.raises(TimeoutError, match="provider timeout"):
        await guards.bound(own_timeout)([], "p")
    assert guards.stop_reason is None


async def test_expired_budget_refuses_further_calls(clock: _Clock) -> None:
    guards = LoopGuards.from_config(_config({**_GUARDS_ON, "run_budget_seconds": 10}))
    clock.now += 11

    async def never(*args, **kwargs):
        raise AssertionError("must not be called")

    with pytest.raises(RunTimeBudgetExceeded):
        await guards.bound(never)([], "p")
    assert guards.stop_reason == "time_budget"


def test_budget_counts_from_the_start_of_this_execution(clock: _Clock) -> None:
    """A run resumed after a crash builds new guards: its budget starts now."""
    clock.now = 50_000.0
    guards = LoopGuards.from_config(_config({**_GUARDS_ON, "run_budget_seconds": 100}))
    clock.now += 70

    assert guards.before_call([]) is False
    assert guards.stop_reason is None


@pytest.mark.parametrize(
    "value",
    [0, -5, True, "1800", None],
    ids=["zero", "negative", "bool", "string", "none"],
)
def test_invalid_budget_disables_only_the_time_budget(value: object) -> None:
    guards = LoopGuards.from_config(
        _config({**_GUARDS_ON, "run_budget_seconds": value})
    )

    async def call(*args, **kwargs):
        return "x"

    assert guards.bound(call) is call
    assert guards.enabled is True


# --- guards off -----------------------------------------------------------------

# sha256 of every request (messages, prompt, kwargs) the scenario below sends, taken
# on the pre-Stage-5 baseline (swarmline 91debe3) BEFORE loop_guards existed.
_GOLDEN_OFF = "87b8a2bae4de7c16ccfae56ff53b465dc3b4533591e2bf68f691e87b8898fbb3"


def _golden_script(n: int) -> str:
    return {5: ""}.get(n, _tool_call("probe") if n <= 4 else _final("golden done"))


@pytest.mark.parametrize(
    "native",
    [{}, {"loop_guards_enabled": False, "run_budget_seconds": 1}],
    ids=["keys-absent", "flag-false-with-budget"],
)
async def test_guards_disabled_requests_byte_identical(
    native: dict[str, object],
) -> None:
    model = _Model(_golden_script)

    events = await _drive(model, _config(native))

    assert _final_event(events).text == "golden done"
    digest = hashlib.sha256(
        json.dumps(model.requests, sort_keys=True, default=str).encode()
    ).hexdigest()
    assert digest == _GOLDEN_OFF
    assert not [s for s in _statuses(events) if s.startswith("loop_guard")]


# --- edges: streaming under budget, compaction, failed landings ------------------


async def test_streamed_reply_within_budget_completes(clock: _Clock) -> None:
    async def stream():
        for part in ('{"type": "final", ', '"final_message": "streamed"}'):
            yield part

    async def model(messages, prompt, **kwargs):
        return stream()

    events = await _drive(model, _config({**_GUARDS_ON, "run_budget_seconds": 100}))

    assert _final_event(events).text == "streamed"


async def test_compaction_after_wrap_up_notice_restores_it_at_the_tail(
    clock: _Clock,
) -> None:
    """The rebuild after a compaction drops lm-only messages; the notice comes back."""
    model = _Model(
        lambda n: _tool_call("probe", n=n) if n <= 9 else _final("done"),
        clock=clock,
        tick=10,
    )

    events = await _drive(
        model,
        _config({**_GUARDS_ON, "run_budget_seconds": 100}),
        round_refresher=_CompactingRefresher(10),
    )

    assert _final_event(events).text == "done"
    # Notice at round 9 (t=80s); compaction before round 10 (t=90s).
    tenth = model.requests[9][0]
    assert tenth[-1] == {"role": "user", "content": TIME_BUDGET_NOTICE}
    assert sum(m["content"] == TIME_BUDGET_NOTICE for m in tenth) == 2, (
        "the notice sent at 80% + its restore"
    )


async def test_disabled_guards_ignore_compaction() -> None:
    guards = LoopGuards.from_config(_config())
    messages: list[dict[str, str]] = []

    guards.mark_compaction(messages)
    guards.observe("probe", {}, "x")

    assert (
        messages == []
        and guards.flush(messages) is None
        and guards.stop_error() is None
    )


async def test_failed_no_progress_landing_ends_with_a_loop_guard_error() -> None:
    async def model(messages, prompt, **kwargs):
        if messages and _LANDING_MARK in messages[-1]["content"]:
            from swarmline.runtime.thin.errors import ThinLlmError
            from swarmline.runtime.types import RuntimeErrorData

            raise ThinLlmError(
                RuntimeErrorData(kind="runtime_crash", message="provider down")
            )
        return _tool_call("probe")

    events = await _drive(model, _config(_GUARDS_ON))

    errors = [e.data for e in events if e.type == "error"]
    assert [(e["kind"], e["message"]) for e in errors] == [
        ("loop_limit", "Run stopped by the loop guard: no_progress")
    ]


async def test_enabled_guards_keep_the_plain_loop_limit_error() -> None:
    tools = _tools(read=lambda **kw: f"page {kw['n']}")
    model = _Model(lambda n: _tool_call("read", n=n))

    events = await _drive(model, _config(_GUARDS_ON, max_iterations=3), tools)

    errors = [e.data for e in events if e.type == "error"]
    assert [(e["kind"], e["message"]) for e in errors] == [
        ("loop_limit", "Превышен лимит итераций (3)")
    ]


# --- verify fixes (W1, W5) ------------------------------------------------------


async def test_loop_limit_landing_after_the_budget_ran_out_still_completes(
    clock: _Clock,
) -> None:
    """W1: the iteration limit and the time budget run out together — the loop-limit
    landing call is the wrap-up, so the exhausted budget must not cut it."""
    model = _Model(lambda n: _tool_call("probe", n=n), clock=clock, tick=60)
    native = {**_GUARDS_ON, "run_budget_seconds": 100, "loop_limit_soft_landing": True}

    events = await _drive(model, _config(native, max_iterations=2))

    assert _final_event(events).text == "SUMMARY: stopped"
    assert _exit_reason(events) == "loop_limit"


async def test_post_compaction_reread_after_a_prior_warning_only_warns() -> None:
    """W5: after an earlier warning, re-reading the three files read just before a
    compaction is a legitimate recovery of lost context — warn, never land on it."""
    tools = _tools(
        probe=lambda **_: "same result", read=lambda **kw: f"contents of {kw['path']}"
    )
    files = ["a.py", "b.py", "c.py"]

    def script(n: int) -> str:
        if n <= 3:
            return _tool_call("probe")
        if n <= 9:
            return _tool_call("read", path=files[(n - 4) % 3])
        return _final("recovered the context")

    events = await _drive(
        _Model(script),
        _config(_GUARDS_ON),
        tools,
        round_refresher=_CompactingRefresher(7),
    )

    assert _final_event(events).text == "recovered the context"
    assert _exit_reason(events) is None
    warned = [s for s in _statuses(events) if s.startswith("loop_guard.warned")]
    assert warned == ["loop_guard.warned: probe", "loop_guard.warned: read"]


async def test_second_post_compaction_loop_after_its_warning_lands() -> None:
    """The post-compaction signal only warns the FIRST time; the model that then
    keeps re-running the same tail after the next compaction is stopped."""
    tools = _tools(read=lambda **kw: f"contents of {kw['path']}")
    files = ["a.py", "b.py", "c.py"]
    model = _Model(lambda n: _tool_call("read", path=files[(n - 1) % 3]))

    class _Twice(_CompactingRefresher):
        async def before_round(
            self, *, round_index, lm_messages, messages, new_messages, system_prompt
        ):
            return _Refresh(lm_messages=lm_messages, compacted=round_index in (4, 7))

    events = await _drive(
        model, _config(_GUARDS_ON), tools, round_refresher=_Twice(None)
    )

    assert _exit_reason(events) == "no_progress"
    assert [s for s in _statuses(events) if s.startswith("loop_guard.warned")] == [
        "loop_guard.warned: read"
    ]
