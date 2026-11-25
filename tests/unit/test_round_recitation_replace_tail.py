"""Replace-the-tail recitation before every model round (taskloom Sprint 1ce Stage 6, AGR-082).

Driven through the real ``ThinRuntime`` ReAct loop with a scripted native model
that records every request; the live plan provider returns a new list each round.
In ``replace_tail`` mode the projection holds exactly one recitation, always the
last message; the prefix before it never changes between rounds (prompt cache).
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from swarmline.compaction import CompactionConfig
from swarmline.domain_types import Message
from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.round_context import RoundContextRefresher
from swarmline.runtime.thin.round_recitation import RecitationTail
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import RuntimeConfig, ToolSpec

from _compaction_fakes import structured_summary

REQUEST = "Work through the checklist."
SYSTEM = "You are a careful worker."
TAG = "<plan-recitation>"
STEP = ToolSpec(
    name="step",
    description="Do one step",
    parameters={"type": "object", "properties": {"n": {"type": "integer"}}},
)
# sha256 of the recorded requests of ``_append_scenario`` on the pre-Stage-6 code.
APPEND_MODE_GOLDEN = "182999d9a9e97230c8ea0b959d7297a227ac28a077b23f776af7bf5b39b0a717"


async def step(n: int) -> str:
    return f"step {n} done"


class _Model:
    def __init__(self, rounds: int) -> None:
        self._rounds = rounds
        self.requests: list[list[dict[str, Any]]] = []

    async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
        self.requests.append(copy.deepcopy(messages))
        i = len(self.requests)
        if i <= self._rounds:
            return NativeToolCallResult(
                text=f"working {i}",
                tool_calls=(NativeToolCall(id=f"c{i}", name="step", args={"n": i}),),
                stop_reason="tool_use",
            )
        return NativeToolCallResult(text="finished")


class _Plan:
    """Live plan: a different list every time it is read; ``texts`` overrides."""

    def __init__(self, texts: list[str] | None = None) -> None:
        self.reads = 0
        self._texts = texts

    async def __call__(self) -> str:
        self.reads += 1
        if self._texts is not None:
            return self._texts[min(self.reads, len(self._texts)) - 1]
        return f"- [in_progress] item {self.reads}\n- [pending] next"


def _config(native: dict[str, Any], **over: Any) -> RuntimeConfig:
    base: dict[str, Any] = dict(
        runtime_name="thin",
        model="openrouter:google/gemini-3.5-flash",
        use_native_tools=True,
        max_iterations=40,
        max_tool_calls=40,
        native_config=native,
    )
    base.update(over)
    return RuntimeConfig(**base)


async def _run(config: RuntimeConfig, model: _Model) -> list[Any]:
    async def _summarizer(messages, system_prompt, **kwargs):
        return structured_summary("S")

    runtime = ThinRuntime(
        config=config,
        llm_call=_summarizer,
        local_tools={"step": step},
        native_adapter=model,
    )
    return [
        ev
        async for ev in runtime.run(
            messages=[Message(role="user", content=REQUEST)],
            system_prompt=SYSTEM,
            active_tools=[STEP],
            config=config,
            mode_hint="react",
        )
    ]


def _replace(plan: _Plan) -> dict[str, Any]:
    return {
        "recitation_plan_provider": plan,
        "recitation_round_cadence": 5,
        "recitation_mode": "replace_tail",
    }


def _recitations(messages: list[dict[str, Any]]) -> list[int]:
    return [i for i, m in enumerate(messages) if str(m["content"]).startswith(TAG)]


async def test_ten_rounds_exactly_one_recitation_in_projection() -> None:
    model = _Model(rounds=9)
    plan = _Plan()

    await _run(_config(_replace(plan)), model)

    assert len(model.requests) == 10
    for n, request in enumerate(model.requests, start=1):
        assert _recitations(request) == [len(request) - 1], f"round {n}"
        assert f"item {n}\n" in request[-1]["content"]
    assert plan.reads == 10


async def test_prefix_before_recitation_byte_identical_to_previous_round() -> None:
    model = _Model(rounds=9)

    await _run(_config(_replace(_Plan())), model)

    req = model.requests
    for n in range(len(req) - 1):
        assert req[n + 1][: len(req[n]) - 1] == req[n][:-1], f"rounds {n + 1}->{n + 2}"


async def test_round_one_recited_in_replace_mode() -> None:
    model = _Model(rounds=0)

    await _run(_config(_replace(_Plan())), model)

    assert len(model.requests) == 1
    assert model.requests[0][-1]["content"].startswith(TAG)
    assert model.requests[0][0]["content"] == REQUEST


async def test_empty_list_removes_stale_recitation_and_adds_none() -> None:
    model = _Model(rounds=3)
    plan = _Plan(["- [in_progress] a", "- [in_progress] b", "   ", ""])

    await _run(_config(_replace(plan)), model)

    assert [len(_recitations(r)) for r in model.requests] == [1, 1, 0, 0]
    assert not model.requests[2][-1]["content"].startswith(TAG)


async def test_provider_failure_keeps_last_recitation_at_tail() -> None:
    calls = {"n": 0}

    async def _flaky() -> str:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("store down")
        return f"- [in_progress] v{calls['n']}"

    model = _Model(rounds=2)

    await _run(_config(_replace(_flaky)), model)  # type: ignore[arg-type]

    tails = [r[-1]["content"] for r in model.requests]
    assert all(t.startswith(TAG) for t in tails)
    assert "v1" in tails[0] and "v1" in tails[1] and "v3" in tails[2]
    assert [len(_recitations(r)) for r in model.requests] == [1, 1, 1]


async def test_compaction_leaves_single_fresh_recitation_at_tail() -> None:
    compaction = CompactionConfig(
        threshold_tokens=80_000,
        context_window_tokens=6_000,
        max_output_reserve_tokens=500,
        preserve_recent_pairs=1,
        per_round=True,
        round_hysteresis_tokens=1_000,
    )

    async def big_step(n: int) -> str:
        return f"step {n}: " + f"row-{n} " * 1_500

    model = _Model(rounds=12)
    plan = _Plan()
    config = _config(_replace(plan), compaction=compaction)
    runtime = ThinRuntime(
        config=config,
        llm_call=lambda *a, **k: _summary(),
        local_tools={"step": big_step},
        native_adapter=model,
    )
    [
        ev
        async for ev in runtime.run(
            messages=[Message(role="user", content=REQUEST)],
            system_prompt=SYSTEM,
            active_tools=[STEP],
            config=config,
            mode_hint="react",
        )
    ]

    shrunk = [
        n
        for n in range(1, len(model.requests))
        if len(model.requests[n]) < len(model.requests[n - 1])
    ]
    assert shrunk, "the scenario must compact at least once"
    for n, request in enumerate(model.requests, start=1):
        assert _recitations(request) == [len(request) - 1]
        assert f"item {n}\n" in request[-1]["content"]


async def _summary() -> str:
    return structured_summary("S")


async def test_provider_payload_has_no_marker_keys() -> None:
    model = _Model(rounds=3)

    await _run(_config(_replace(_Plan())), model)

    for request in model.requests:
        for message in request:
            assert set(message) <= {"role", "content"}, message


async def test_unknown_mode_falls_back_to_append() -> None:
    tail = RecitationTail(_Plan(), mode="bogus", cadence=2)  # type: ignore[arg-type]

    assert tail.mode == "append"
    refresher = RoundContextRefresher(
        plan_provider=_Plan(), recitation_cadence=0, recitation_mode="replace_tail"
    )
    outcome = await refresher.before_round(
        round_index=1,
        lm_messages=[{"role": "user", "content": REQUEST}],
        messages=[],
        new_messages=[],
        system_prompt=SYSTEM,
    )
    assert outcome.recited and outcome.lm_messages[-1]["content"].startswith(TAG)


def _append_scenario_native(plan: _Plan) -> dict[str, Any]:
    return {"recitation_plan_provider": plan, "recitation_round_cadence": 2}


async def test_append_mode_default_byte_identical() -> None:
    model = _Model(rounds=6)

    await _run(_config(_append_scenario_native(_Plan())), model)

    digest = hashlib.sha256(
        json.dumps(model.requests, sort_keys=True).encode()
    ).hexdigest()
    assert digest == APPEND_MODE_GOLDEN
    # Append mode accumulates: rounds 3, 5 and 7 each added one more copy.
    assert [len(_recitations(r)) for r in model.requests] == [0, 0, 1, 1, 2, 2, 3]
