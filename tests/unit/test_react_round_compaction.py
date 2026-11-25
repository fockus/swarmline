"""Sprint 1ce Stage 3 (CE-9): compaction before EVERY model round, end to end.

Driven through the real ``ThinRuntime`` (startup compaction, kernel dispatch,
ReAct loop, tool executor) with a scripted native model and a scripted
summarizer — no network. The model records every request it receives, so the
tests assert on exactly what a provider would have been sent.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from typing import Any

import pytest

from swarmline.compaction import CompactionConfig
from swarmline.context.budget import estimate_tokens
from swarmline.domain_types import Message
from swarmline.resilience.checkpoint import CheckpointWriter, InMemoryCheckpointStore
from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import RuntimeConfig, ToolSpec

from _compaction_fakes import FILLER, structured_summary

REQUEST = "Collect the sixty shard reports and list every failing shard."
SYSTEM = "You are a shard auditor."
WINDOW = 16_000
RESERVE = 2_000
BUDGET = WINDOW - RESERVE
FETCH = ToolSpec(
    name="fetch",
    description="Fetch one shard report",
    parameters={"type": "object", "properties": {"n": {"type": "integer"}}},
)


async def fetch(n: int) -> str:
    # ~8 000 chars ~ 2 000 tokens per result, distinct per call (no dedup).
    return f"shard {n} report: " + f"line-{n} ok " * 800


class _ScriptedModel:
    """Native adapter: ``rounds`` tool-calling turns, then a final answer."""

    def __init__(self, rounds: int) -> None:
        self._rounds = rounds
        self.requests: list[dict[str, Any]] = []

    async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
        self.requests.append(
            {"messages": copy.deepcopy(messages), "system_prompt": system_prompt}
        )
        i = len(self.requests)
        if i <= self._rounds:
            return NativeToolCallResult(
                text=f"step {i}",
                tool_calls=(
                    NativeToolCall(id=f"call_{i}", name="fetch", args={"n": i}),
                ),
                stop_reason="tool_use",
            )
        return NativeToolCallResult(text="all shards collected")


class _Summarizer:
    """The runtime's ``llm_call``: only the compaction summarizer reaches it."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, messages, system_prompt, **kwargs):
        self.calls += 1
        return structured_summary(f"S{self.calls}")


def _config(compaction: CompactionConfig | None, **over) -> RuntimeConfig:
    base: dict[str, Any] = dict(
        runtime_name="thin",
        model="openrouter:google/gemini-3.5-flash",
        use_native_tools=True,
        max_iterations=80,
        max_tool_calls=100,
        compaction=compaction,
        native_config={"compaction_llm_model": "weak-summarizer"},
    )
    base.update(over)
    return RuntimeConfig(**base)


def _small_window(**over) -> CompactionConfig:
    base: dict[str, Any] = dict(
        threshold_tokens=80_000,
        context_window_tokens=WINDOW,
        max_output_reserve_tokens=RESERVE,
        preserve_recent_pairs=2,
        per_round=True,
        round_hysteresis_tokens=3_000,
    )
    base.update(over)
    return CompactionConfig(**base)


async def _run(
    config: RuntimeConfig,
    model: _ScriptedModel,
    summarizer: _Summarizer,
    history: list[Message] | None = None,
) -> list[Any]:
    runtime = ThinRuntime(
        config=config,
        llm_call=summarizer,
        local_tools={"fetch": fetch},
        native_adapter=model,
    )
    return [
        ev
        async for ev in runtime.run(
            messages=[*(history or []), Message(role="user", content=REQUEST)],
            system_prompt=SYSTEM,
            active_tools=[FETCH],
            config=config,
            mode_hint="react",
        )
    ]


def _request_tokens(request: dict[str, Any]) -> int:
    return estimate_tokens(request["system_prompt"]) + sum(
        estimate_tokens(m["content"]) for m in request["messages"]
    )


def _is_result(message: dict[str, Any]) -> bool:
    return message["role"] == "user" and message["content"].startswith(
        ("Result fetch:", "Tool result from fetch:")
    )


def _broken_pairs(messages: list[dict[str, Any]]) -> int:
    broken = 0
    for i, message in enumerate(messages):
        if _is_result(message):
            prev = messages[i - 1] if i else None
            if prev is None or prev["role"] != "assistant":
                broken += 1
    return broken


def _digest(messages: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _round_compactions(caplog: pytest.LogCaptureFixture) -> list[int]:
    return [
        r.compaction_round  # type: ignore[attr-defined]
        for r in caplog.records
        if r.getMessage().startswith("compaction.round")
    ]


@pytest.mark.parametrize(
    ("tiers", "expected_tier"),
    [({}, "collapse"), ({"tier_1_enabled": False}, "summary")],
    ids=["tier1-collapse", "tier2-summary"],
)
async def test_sixty_round_run_stays_under_window_with_round_compaction(
    tiers: dict[str, bool], expected_tier: str, caplog: pytest.LogCaptureFixture
) -> None:
    model = _ScriptedModel(rounds=60)
    summarizer = _Summarizer()

    with caplog.at_level(logging.INFO, logger="swarmline.runtime.thin.round_context"):
        events = await _run(_config(_small_window(**tiers)), model, summarizer)

    finals = [ev for ev in events if ev.type == "final"]
    assert len(finals) == 1 and finals[0].data["text"] == "all shards collected"
    assert len(model.requests) == 61
    over = [i for i, r in enumerate(model.requests) if _request_tokens(r) > BUDGET]
    assert over == [], f"requests over window-reserve: {over}"
    assert len(_round_compactions(caplog)) >= 1
    tiers_used = {r.tier for r in caplog.records if hasattr(r, "compaction_round")}  # type: ignore[attr-defined]
    assert tiers_used == {expected_tier}
    assert sum(_broken_pairs(r["messages"]) for r in model.requests) == 0
    for request in model.requests:
        assert REQUEST in "\n".join(m["content"] for m in request["messages"])
    # The transcript handed to the host keeps every tool exchange.
    tool_messages = [m for m in finals[0].data["new_messages"] if m["role"] == "tool"]
    assert len(tool_messages) == 60


async def test_cache_prefix_hash_stable_between_compactions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = _ScriptedModel(rounds=60)

    with caplog.at_level(logging.INFO, logger="swarmline.runtime.thin.round_context"):
        await _run(_config(_small_window()), model, _Summarizer())

    compacted_before = set(_round_compactions(caplog))
    assert compacted_before, "the scenario must compact at least once"
    stable_pairs = 0
    for n in range(len(model.requests) - 1):
        # Round numbers are 1-based: request n is round n + 1.
        if (n + 2) in compacted_before:
            continue
        current = model.requests[n]["messages"]
        following = model.requests[n + 1]["messages"]
        assert _digest(following[: len(current)]) == _digest(current), (
            f"prefix rewritten between rounds {n + 1} and {n + 2} without compaction"
        )
        stable_pairs += 1
    assert stable_pairs >= 30
    assert len({r["system_prompt"] for r in model.requests}) == 1


async def test_round_one_does_not_double_compact() -> None:
    # A history already over the budget: startup compaction runs once for
    # round 1; the per-round refresher must not compact round 1 again.
    history: list[Message] = []
    for i in range(40):
        history.append(Message(role="user", content=f"earlier ask {i}: {FILLER}"))
        history.append(
            Message(role="assistant", content=f"earlier answer {i}: {FILLER}")
        )
    model = _ScriptedModel(rounds=0)
    summarizer = _Summarizer()

    await _run(_config(_small_window()), model, summarizer, history=history)

    assert len(model.requests) == 1
    assert summarizer.calls == 1


async def test_resumed_run_surfaces_round_compaction_disabled_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The checkpoint of an earlier call of this run holds an lm-only projection:
    # it has no structured twin, so round compaction is off for the run.
    store = InMemoryCheckpointStore()
    writer = CheckpointWriter(store, namespace="sw:")
    run_id = "run-resumed-round-compaction"
    restored = [{"role": "user", "content": REQUEST}]
    await writer.after_tool_call(
        run_id=run_id,
        step=1,
        total_steps=80,
        state={"lm_messages": restored, "tool_calls_count": 0},
    )
    model = _ScriptedModel(rounds=12)

    with caplog.at_level(logging.INFO, logger="swarmline.runtime.thin.round_context"):
        events = await _run(
            _config(_small_window(), checkpoint_writer=writer, run_id=run_id),
            model,
            _Summarizer(),
        )

    statuses = [ev.data.get("text", "") for ev in events if ev.type == "status"]
    assert any("round compaction disabled" in s for s in statuses), statuses
    assert _round_compactions(caplog) == []
    assert any(ev.type == "final" for ev in events)


# Pinned on the pre-Stage-3 baseline (swarmline d91d641): no refresher = same bytes.
_GOLDEN_OFF = "36cac39297a1788e972c87aab630fcf07612e95bbece4fa5238059d3d1dab288"


@pytest.mark.parametrize(
    "compaction",
    [None, CompactionConfig(threshold_tokens=80_000, per_round=False)],
    ids=["no-compaction", "per-round-off"],
)
async def test_refresher_absent_is_byte_identical(
    compaction: CompactionConfig | None,
) -> None:
    model = _ScriptedModel(rounds=4)

    await _run(_config(compaction, native_config={}), model, _Summarizer())

    assert _digest([r["messages"] for r in model.requests]) == _GOLDEN_OFF
    assert {r["system_prompt"] for r in model.requests} == {SYSTEM}
