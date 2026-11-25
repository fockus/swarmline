"""Sprint 1ce Stage 3 (CE-9): per-round compaction and recitation.

``RoundContextRefresher.before_round`` runs before model rounds 2..N of a
ReAct loop. Compaction works on the STRUCTURED view (``messages`` +
``new_messages``, where tool call/result pairs are explicit) and rebuilds the
LM projection from it; recitation only ever appends at the tail. No LLM is
called: summarizers are scripted.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json

import pytest

from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
from swarmline.context.budget import estimate_tokens
from swarmline.domain_types import Message
from swarmline.runtime.thin.helpers import _messages_to_lm
from swarmline.runtime.thin.round_context import (
    RoundContextRefresher,
    build_round_context_refresher,
)
from swarmline.runtime.types import RuntimeConfig

from _compaction_fakes import scripted_summarizer, structured_summary

REQUEST = "Audit every billing endpoint and report the broken ones."
SYSTEM = "You are a careful auditor."
RESULT_BODY = "row " * 300  # ~1200 chars ~ 300 tokens


def _native_group(i: int, calls: int = 1, results: int | None = None) -> list[Message]:
    tool_calls = [
        {"id": f"c{i}_{k}", "name": "read", "args": {"n": i, "k": k}}
        for k in range(calls)
    ]
    out = [Message(role="assistant", content=f"step {i}", tool_calls=tool_calls)]
    for k in range(calls if results is None else results):
        out.append(Message(role="tool", content=f"r{i}_{k} {RESULT_BODY}", name="read"))
    return out


def _text_group(i: int) -> list[Message]:
    return [
        Message(role="assistant", content="", metadata={"tool_call": "read"}),
        Message(role="tool", content=f"r{i} {RESULT_BODY}", name="read"),
    ]


def _transcript(groups: int, shape: str = "native") -> list[Message]:
    new: list[Message] = []
    for i in range(groups):
        if shape == "text":
            new.extend(_text_group(i))
        elif shape == "multi":
            new.extend(_native_group(i, calls=2))
        elif shape == "partial" and i == 1:
            # malformed native group: 3 calls declared, 2 results present
            new.extend(_native_group(i, calls=3, results=2))
            new.append(Message(role="user", content=f"note {i}"))
        else:
            new.extend(_native_group(i))
    return new


def _config(**over) -> CompactionConfig:
    base = dict(
        threshold_tokens=2_000,
        preserve_recent_pairs=2,
        per_round=True,
        round_hysteresis_tokens=500,
        tier_2_enabled=False,
    )
    base.update(over)
    return CompactionConfig(**base)


def _refresher(config: CompactionConfig, **kw) -> RoundContextRefresher:
    llm = kw.pop("llm_call", None)
    compaction_filter = ConversationCompactionFilter(config=config, llm_call=llm)
    return RoundContextRefresher(
        compaction_filter=compaction_filter, compaction_config=config, **kw
    )


def _lm(messages: list[Message], new: list[Message]) -> list[dict]:
    return _messages_to_lm([*messages, *new])


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def _round(refresher, round_index, messages, new, lm=None):
    lm = _lm(messages, new) if lm is None else lm
    return await refresher.before_round(
        round_index=round_index,
        lm_messages=lm,
        messages=messages,
        new_messages=new,
        system_prompt=SYSTEM,
    )


def _result_runs(lm: list[dict]) -> list[tuple[str, int]]:
    """(initiator content, number of tool results right after it) per initiator;
    an orphan result run (no initiator before it) is reported as ("<orphan>", n)."""
    runs: list[tuple[str, int]] = []
    i = 0
    while i < len(lm):
        content = lm[i]["content"]
        is_result = lm[i]["role"] == "user" and content.startswith("Tool result from")
        if is_result:
            j = i
            while j < len(lm) and lm[j]["content"].startswith("Tool result from"):
                j += 1
            runs.append(("<orphan>", j - i))
            i = j
            continue
        if lm[i]["role"] == "assistant" and "Tool call" in content:
            j = i + 1
            while j < len(lm) and lm[j]["content"].startswith("Tool result from"):
                j += 1
            runs.append((content, j - i - 1))
            i = j
            continue
        i += 1
    return runs


# ---------------------------------------------------------------------------
# 3.1 compaction per round
# ---------------------------------------------------------------------------


async def test_under_threshold_returns_same_list_object() -> None:
    refresher = _refresher(_config(threshold_tokens=100_000))
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(2)
    lm = _lm(messages, new)

    outcome = await _round(refresher, 2, messages, new, lm)

    assert outcome.lm_messages is lm
    assert outcome.compacted is False
    assert outcome.recited is False


async def test_over_threshold_compacts_structured_view_and_rebuilds_projection() -> (
    None
):
    refresher = _refresher(_config())
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(12)
    lm = _lm(messages, new)
    lm_snapshot = copy.deepcopy(lm)

    outcome = await _round(refresher, 2, messages, new, lm)

    assert outcome.compacted is True
    assert outcome.tokens_before > 2_000
    assert outcome.tokens_after < outcome.tokens_before
    assert outcome.tokens_after <= 2_000
    rendered = "\n".join(m["content"] for m in outcome.lm_messages)
    # Tier 1 collapsed the old pairs; the artifact reaches the model (F-1).
    assert 'source="compaction-collapsed"' in rendered
    # Projection is rebuilt from the structured view, the request survives.
    assert outcome.lm_messages[0] == {"role": "user", "content": REQUEST}
    assert lm == lm_snapshot, "the caller's projection must not be mutated"


@pytest.mark.parametrize("shape", ["multi", "text", "partial"])
async def test_compaction_keeps_tool_call_result_pairs_atomic(shape: str) -> None:
    # Tier 3 only: units are dropped whole or kept whole.
    config = _config(tier_1_enabled=False, threshold_tokens=2_500)
    refresher = _refresher(config)
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(10, shape=shape)
    before_runs = dict(_result_runs(_lm(messages, new)))

    outcome = await _round(refresher, 2, messages, new)

    assert outcome.compacted is True
    after_runs = _result_runs(outcome.lm_messages)
    assert after_runs, "the recent units must survive"
    for initiator, count in after_runs:
        assert initiator != "<orphan>", "a tool result lost its call"
        assert count == before_runs[initiator], f"unit split: {initiator!r}"


async def test_pending_tool_call_without_result_is_never_split_or_dropped() -> None:
    refresher = _refresher(_config(tier_1_enabled=False))
    messages = [Message(role="user", content=REQUEST)]
    pending = Message(
        role="assistant",
        content="about to read",
        tool_calls=[{"id": "pending_1", "name": "read", "args": {}}],
    )
    new = [*_transcript(10), pending]

    outcome = await _round(refresher, 2, messages, new)

    assert outcome.compacted is True
    assert outcome.lm_messages[-1] == _messages_to_lm([pending])[0]


async def test_hysteresis_prevents_recompaction_next_round() -> None:
    refresher = _refresher(_config())
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(12)
    first = await _round(refresher, 2, messages, new)
    assert first.compacted is True

    # One more small exchange lands on the rebuilt projection.
    extra = [
        Message(
            role="assistant",
            content="step x",
            tool_calls=[{"id": "x", "name": "read", "args": {}}],
        ),
        Message(role="tool", content="short", name="read"),
    ]
    new.extend(extra)
    lm = [*first.lm_messages, *_messages_to_lm(extra)]
    second = await _round(refresher, 3, messages, new, lm)

    assert second.compacted is False
    assert second.lm_messages is lm


async def test_shared_filter_history_triggers_anti_thrashing_across_rounds() -> None:
    # The region worth summarizing is tiny next to the preserved tail, so every
    # summary (LLM and fallback) saves < 10% and is rejected: each rejected
    # attempt is recorded, and after two of them the summarizer is not called.
    calls: list[tuple[str, str]] = []
    config = _config(
        tier_1_enabled=False,
        tier_2_enabled=True,
        tier_3_enabled=False,
        preserve_recent_pairs=1,
        threshold_tokens=1_000,
        round_hysteresis_tokens=100,
    )
    compaction_filter = ConversationCompactionFilter(
        config=config, llm_call=scripted_summarizer(structured_summary(), calls)
    )
    refresher = RoundContextRefresher(
        compaction_filter=compaction_filter, compaction_config=config
    )
    messages = [
        Message(role="user", content=REQUEST),
        Message(role="assistant", content="ok"),
    ]
    huge = "tail " * 2_000
    new = [
        Message(role="user", content="go"),
        Message(role="assistant", content=huge),
        Message(role="user", content=huge),
    ]

    seen = []
    for round_index in (2, 3, 4):
        outcome = await _round(refresher, round_index, messages, new)
        assert outcome.compacted is False
        seen.append(len(calls))

    assert seen == [1, 2, 2]
    assert len(refresher.compression_history) == 2
    assert compaction_filter.compression_history == refresher.compression_history
    assert all(
        r["tokens_before"] == r["tokens_after"] for r in refresher.compression_history
    )


async def test_new_messages_transcript_untouched_by_round_compaction() -> None:
    refresher = _refresher(_config())
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(12)
    snapshot = copy.deepcopy(new)
    identities = [id(m) for m in new]

    outcome = await _round(refresher, 2, messages, new)

    assert outcome.compacted is True
    assert new == snapshot
    assert [id(m) for m in new] == identities


async def test_resumed_run_disables_round_compaction_with_status() -> None:
    refresher = _refresher(_config())
    status = refresher.start_run(
        RuntimeConfig(runtime_name="thin"), resumed=True, auto_verify=False
    )
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(12)
    lm = _lm(messages, new)

    outcome = await _round(refresher, 2, messages, new, lm)

    assert status is not None and "resumed" in status
    assert outcome.compacted is False
    assert outcome.lm_messages is lm


@pytest.mark.parametrize(
    "producer",
    [
        "get_steering_messages",
        "get_followup_messages",
        "transform_context",
        "recovery_cascade",
        "auto_verify_loop",
    ],
)
async def test_lm_only_producers_configured_disable_round_compaction(
    producer: str,
) -> None:
    refresher = _refresher(_config())
    hooks = {
        "get_steering_messages": lambda ctx: [],
        "get_followup_messages": lambda ctx: [],
        "transform_context": lambda lm: lm,
        "recovery_cascade": object(),
    }
    config = RuntimeConfig(
        runtime_name="thin",
        **({producer: hooks[producer]} if producer in hooks else {}),
    )

    status = refresher.start_run(
        config, resumed=False, auto_verify=producer == "auto_verify_loop"
    )
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(12)
    lm = _lm(messages, new)
    outcome = await _round(refresher, 2, messages, new, lm)

    assert status is not None and producer in status
    assert outcome.compacted is False
    assert outcome.lm_messages is lm


async def test_recitation_only_refresher_never_reports_compaction_disabled() -> None:
    async def _provider() -> str:
        return "plan"

    refresher = RoundContextRefresher(plan_provider=_provider, recitation_cadence=1)

    assert (
        refresher.start_run(
            RuntimeConfig(runtime_name="thin", transform_context=lambda lm: lm),
            resumed=True,
            auto_verify=True,
        )
        is None
    )
    assert refresher.compression_history == []


async def test_no_lm_only_producers_keeps_round_compaction_enabled() -> None:
    refresher = _refresher(_config())
    status = refresher.start_run(
        RuntimeConfig(runtime_name="thin"), resumed=False, auto_verify=False
    )

    assert status is None


# ---------------------------------------------------------------------------
# 3.2 recitation per round
# ---------------------------------------------------------------------------


def _live_plan(texts: list[str]):
    state = {"calls": 0}

    async def _provider() -> str:
        state["calls"] += 1
        return texts[min(state["calls"], len(texts)) - 1]

    return _provider, state


async def test_recitation_on_round_cadence_appends_live_plan_at_tail() -> None:
    provider, state = _live_plan(["- [ ] plan v1", "- [x] plan v1\n- [ ] plan v2"])
    refresher = RoundContextRefresher(plan_provider=provider, recitation_cadence=2)
    messages = [Message(role="user", content=REQUEST)]
    lm = _lm(messages, [])

    recited_rounds = []
    for round_index in range(2, 7):
        prefix_hash = _hash(lm)
        prefix_len = len(lm)
        outcome = await _round(refresher, round_index, messages, [], lm)
        assert _hash(outcome.lm_messages[:prefix_len]) == prefix_hash, "append-only"
        if outcome.recited:
            recited_rounds.append(round_index)
            assert outcome.lm_messages[-1]["role"] == "user"
            assert outcome.lm_messages[-1]["content"].startswith("<plan-recitation>")
        lm = outcome.lm_messages

    assert recited_rounds == [3, 5]
    assert state["calls"] == 2
    assert "plan v2" in lm[-1]["content"], "the LIVE plan is recited, not a snapshot"


@pytest.mark.parametrize("failure", ["error", "timeout"])
async def test_recitation_provider_timeout_or_error_skips_round(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    async def _provider() -> str:
        if failure == "error":
            raise RuntimeError("todo store down")
        await asyncio.sleep(1)
        return "never"

    refresher = RoundContextRefresher(
        plan_provider=_provider,
        recitation_cadence=1,
        recitation_timeout_seconds=0.01,
    )
    lm = _lm([Message(role="user", content=REQUEST)], [])

    with caplog.at_level("WARNING", logger="swarmline.runtime.thin.round_context"):
        outcome = await _round(
            refresher, 2, [Message(role="user", content=REQUEST)], [], lm
        )

    assert outcome.recited is False
    assert outcome.lm_messages is lm
    assert any("recitation" in r.getMessage() for r in caplog.records)


async def test_blank_live_plan_is_not_recited() -> None:
    async def _provider() -> str:
        return "   "

    refresher = RoundContextRefresher(plan_provider=_provider, recitation_cadence=1)
    lm = _lm([Message(role="user", content=REQUEST)], [])

    outcome = await _round(refresher, 2, [], [], lm)

    assert outcome.recited is False
    assert outcome.lm_messages is lm


def test_static_plan_text_never_recited_mid_run_without_provider() -> None:
    config = RuntimeConfig(
        runtime_name="thin",
        native_config={
            "recitation_plan_text": "- [ ] stale plan",
            "recitation_round_cadence": 1,
        },
    )

    assert build_round_context_refresher(config, None) is None


def test_factory_builds_refresher_only_for_opted_in_mechanisms() -> None:
    per_round = _config()
    off = _config(per_round=False)

    async def _provider() -> str:
        return "plan"

    with_provider = RuntimeConfig(
        runtime_name="thin",
        native_config={
            "recitation_plan_provider": _provider,
            "recitation_round_cadence": 3,
        },
    )
    compaction_filter = ConversationCompactionFilter(config=per_round)

    assert (
        build_round_context_refresher(
            RuntimeConfig(runtime_name="thin", compaction=off),
            ConversationCompactionFilter(config=off),
        )
        is None
    )
    assert (
        build_round_context_refresher(
            RuntimeConfig(runtime_name="thin", compaction=per_round), compaction_filter
        )
        is not None
    )
    assert build_round_context_refresher(with_provider, None) is not None
    # A cadence of 0 or a non-callable provider does not opt in.
    for native in (
        {"recitation_plan_provider": _provider, "recitation_round_cadence": 0},
        {"recitation_plan_provider": "plan", "recitation_round_cadence": 2},
    ):
        cfg = RuntimeConfig(runtime_name="thin", native_config=native)
        assert build_round_context_refresher(cfg, None) is None


async def test_recitation_reappended_after_round_compaction() -> None:
    provider, _ = _live_plan(["- [ ] live plan"])
    config = _config()
    refresher = _refresher(config, plan_provider=provider, recitation_cadence=2)
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(3)

    third = await _round(refresher, 3, messages, new)  # cadence round, no compaction
    assert third.recited is True and third.compacted is False

    more = _transcript(12)[6:]
    new.extend(more)
    lm = [*third.lm_messages, *_messages_to_lm(more)]
    fourth = await _round(refresher, 4, messages, new, lm)

    assert fourth.compacted is True
    assert fourth.lm_messages[-1] == third.lm_messages[-1]
    recitations = [
        m for m in fourth.lm_messages if m["content"].startswith("<plan-recitation>")
    ]
    assert len(recitations) == 1


async def test_round_one_is_never_refreshed() -> None:
    provider, state = _live_plan(["plan"])
    refresher = _refresher(_config(), plan_provider=provider, recitation_cadence=1)
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(12)
    lm = _lm(messages, new)

    outcome = await _round(refresher, 1, messages, new, lm)

    assert outcome.lm_messages is lm
    assert state["calls"] == 0


# ---------------------------------------------------------------------------
# 3.0 budget anchored on the provider's prompt_tokens (ref: hermes 2026-09-27)
# ---------------------------------------------------------------------------


def _full_estimate(lm: list[dict]) -> int:
    return estimate_tokens(SYSTEM) + sum(estimate_tokens(m["content"]) for m in lm)


async def test_budget_uses_provider_prompt_tokens_anchor_plus_delta_estimate() -> None:
    refresher = _refresher(_config(threshold_tokens=5_000))
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(2)
    lm = _lm(messages, new)
    request_len = len(lm)
    assert _full_estimate(lm) < 5_000

    # The provider counted tool schemas too: the real prompt was 6 000 tokens.
    refresher.observe_call({"prompt_tokens": 6_000}, request_len)
    tail = _messages_to_lm(_transcript(3)[4:])
    lm = [*lm, *tail]
    delta = sum(estimate_tokens(m["content"]) for m in tail)

    assert refresher.estimate_budget(lm, SYSTEM) == 6_000 + delta
    new = [*new, *_transcript(3)[4:]]
    outcome = await _round(refresher, 2, messages, new, lm)
    assert outcome.compacted is True, "the anchor, not the estimate, crossed"


async def test_anchor_reset_after_round_compaction_and_when_usage_missing() -> None:
    refresher = _refresher(_config())
    messages = [Message(role="user", content=REQUEST)]
    new = _transcript(12)
    lm = _lm(messages, new)
    refresher.observe_call({"prompt_tokens": 50_000}, len(lm))
    assert refresher.estimate_budget(lm, SYSTEM) == 50_000

    outcome = await _round(refresher, 2, messages, new, lm)
    assert outcome.compacted is True
    rebuilt = outcome.lm_messages
    assert refresher.estimate_budget(rebuilt, SYSTEM) == _full_estimate(rebuilt)

    refresher.observe_call({"prompt_tokens": 9_999}, len(rebuilt))
    assert refresher.estimate_budget(rebuilt, SYSTEM) == 9_999
    refresher.observe_call(None, len(rebuilt))
    assert refresher.estimate_budget(rebuilt, SYSTEM) == _full_estimate(rebuilt)
    # An anchor longer than the current projection is stale: full estimate.
    refresher.observe_call({"prompt_tokens": 7}, len(rebuilt) + 5)
    assert refresher.estimate_budget(rebuilt, SYSTEM) == _full_estimate(rebuilt)
