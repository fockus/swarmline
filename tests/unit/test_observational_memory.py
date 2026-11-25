"""TDD tests for Stage C2.3 — ``LlmFactExtractor`` + ``ObservationLog``.

``LlmFactExtractor`` covered with fakes (LLM seam mirrors
``LlmSummaryGenerator``'s tests). ``ObservationLog`` covered against
``InMemoryMemoryProvider`` directly (Testing Trophy: integration over
unit-with-mocks for a thin wrapper), matching ``test_working_memory.py``'s
precedent. Covers the 8 plan-mandated tests plus the plan's "Edge cases"
(short-output fallback, prose parse, limit=0, limit > stored).
"""

from __future__ import annotations

import asyncio

import pytest
from swarmline.memory import InMemoryMemoryProvider
from swarmline.memory.consolidation import KeywordFactExtractor
from swarmline.memory.episodic_types import Episode
from swarmline.memory.observational import (
    LlmFactExtractor,
    ObservationLog,
    _parse_observations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ep(id: str, summary: str = "task") -> Episode:  # noqa: A002
    return Episode(id=id, summary=summary)


# ---------------------------------------------------------------------------
# Plan-mandated tests (8, incl. the consolidation.py extension)
# ---------------------------------------------------------------------------


async def test_llm_fact_extractor_without_llm_uses_fallback() -> None:
    episodes = [_ep("e1", "research task"), _ep("e2", "research task")]
    extractor = LlmFactExtractor()

    got = await extractor.extract(episodes)
    expected = await KeywordFactExtractor().extract(episodes)

    assert got == expected


async def test_llm_fact_extractor_uses_llm_when_provided() -> None:
    async def fake_llm(prompt: str, text: str) -> str:
        return "- obs A\n- obs B"

    extractor = LlmFactExtractor(fake_llm)

    facts = await extractor.extract([_ep("e1")])

    assert facts == ["obs A", "obs B"]


async def test_llm_fact_extractor_falls_back_on_llm_error() -> None:
    async def raising_llm(prompt: str, text: str) -> str:
        raise RuntimeError("boom")

    episodes = [_ep("e1", "research task"), _ep("e2", "research task")]
    extractor = LlmFactExtractor(raising_llm)

    got = await extractor.extract(episodes)
    expected = await KeywordFactExtractor().extract(episodes)

    assert got == expected


async def test_llm_fact_extractor_falls_back_on_empty_episodes() -> None:
    async def fake_llm(prompt: str, text: str) -> str:
        return "- should never be reached"

    extractor = LlmFactExtractor(fake_llm)

    assert await extractor.extract([]) == []


async def test_observation_log_record_then_get() -> None:
    store = InMemoryMemoryProvider()
    log = ObservationLog(store, scope_id="u1")

    await log.arecord("x")
    await log.arecord("y")

    assert await log.aget() == ["x", "y"]


async def test_observation_log_is_scope_isolated() -> None:
    store = InMemoryMemoryProvider()
    log_a = ObservationLog(store, scope_id="u1")
    log_b = ObservationLog(store, scope_id="u2")

    await log_a.arecord("a-only")
    await log_b.arecord("b-only")

    assert await log_a.aget() == ["a-only"]
    assert await log_b.aget() == ["b-only"]


async def test_observation_log_clear() -> None:
    store = InMemoryMemoryProvider()
    log = ObservationLog(store, scope_id="u1")
    await log.arecord("x")
    await log.arecord("y")

    await log.aclear()

    assert await log.aget() == []


# ---------------------------------------------------------------------------
# Edge cases (plan "Edge cases" section, C2.3)
# ---------------------------------------------------------------------------


async def test_llm_fact_extractor_falls_back_on_short_output() -> None:
    async def short_llm(prompt: str, text: str) -> str:
        return "ok"

    episodes = [_ep("e1", "research task"), _ep("e2", "research task")]
    extractor = LlmFactExtractor(short_llm)

    got = await extractor.extract(episodes)
    expected = await KeywordFactExtractor().extract(episodes)

    assert got == expected


async def test_llm_fact_extractor_parses_prose_best_effort() -> None:
    async def prose_llm(prompt: str, text: str) -> str:
        return "Users often ask about deposits\nRates matter most to them"

    extractor = LlmFactExtractor(prose_llm)

    facts = await extractor.extract([_ep("e1")])

    assert facts == ["Users often ask about deposits", "Rates matter most to them"]


def test_parse_observations_returns_empty_when_nothing_parseable() -> None:
    """Unit-level: ``_parse_observations`` (bullets-then-prose) returns []
    for all-whitespace input -- the "nothing parseable" contract itself.

    Note: at the ``extract()`` level this case is always caught earlier by
    the short-output guard (any text that ``.strip()``s to all-blank lines
    also ``.strip()``s to length 0), so ``extract()``'s own ``if not facts``
    branch is an untestable-in-isolation defensive backstop for a future
    parser change, not a reachable path today -- tested directly here instead
    of via a redundant ``extract()``-level scenario.
    """
    assert _parse_observations("     \n     ") == []


async def test_llm_fact_extractor_falls_back_on_unparseable_output() -> None:
    async def blank_llm(prompt: str, text: str) -> str:
        return "     \n     "

    episodes = [_ep("e1", "research task"), _ep("e2", "research task")]
    extractor = LlmFactExtractor(blank_llm)

    got = await extractor.extract(episodes)
    expected = await KeywordFactExtractor().extract(episodes)

    assert got == expected


async def test_observation_log_get_limit_zero_returns_empty() -> None:
    store = InMemoryMemoryProvider()
    log = ObservationLog(store, scope_id="u1")
    await log.arecord("x")

    assert await log.aget(limit=0) == []


async def test_observation_log_get_limit_larger_than_stored_returns_all() -> None:
    store = InMemoryMemoryProvider()
    log = ObservationLog(store, scope_id="u1")
    await log.arecord("x")
    await log.arecord("y")

    assert await log.aget(limit=100) == ["x", "y"]


async def test_observation_log_record_after_clear_continues_monotonically() -> None:
    """A new arecord after aclear must never reuse an old (now-hidden)
    index -- the visible log only ever shows post-clear entries."""
    store = InMemoryMemoryProvider()
    log = ObservationLog(store, scope_id="u1")
    await log.arecord("x")
    await log.arecord("y")
    await log.aclear()

    await log.arecord("z")

    assert await log.aget() == ["z"]


async def test_observation_log_custom_key_prefix() -> None:
    store = InMemoryMemoryProvider()
    log = ObservationLog(store, scope_id="u1", key_prefix="notes")

    await log.arecord("first note")

    facts = await store.get_facts("u1", topic_id=None)
    assert "notes.0" in facts
    assert await log.aget() == ["first note"]


# ---------------------------------------------------------------------------
# r1 fix-cycle regressions (concurrent write race, NEVER-raises overclaim,
# bullet-marker coverage)
# ---------------------------------------------------------------------------


class _YieldingFactStore:
    """Wraps a real ``FactStore``, inserting a genuine ``asyncio`` suspension
    point in ``get_facts`` (``InMemoryMemoryProvider``'s own methods never
    actually suspend, so ``asyncio.gather`` over them never truly
    interleaves -- there would be nothing for a lock to protect against in
    a test). This forces real task interleaving between the read-next-index
    and the upsert, reproducing the read-modify-write race the lock guards."""

    def __init__(self, inner: InMemoryMemoryProvider) -> None:
        self._inner = inner

    async def get_facts(self, user_id: str, topic_id: str | None = None) -> dict:
        result = await self._inner.get_facts(user_id, topic_id=topic_id)
        await asyncio.sleep(0)  # yield control -- lets other tasks run here
        return result

    async def upsert_fact(
        self,
        user_id: str,
        key: str,
        value: object,
        topic_id: str | None = None,
        source: str = "user",
    ) -> None:
        await self._inner.upsert_fact(
            user_id, key, value, topic_id=topic_id, source=source
        )


async def test_observation_log_concurrent_arecord_no_data_loss() -> None:
    """MAJOR: 10 concurrent arecord calls on ONE instance must all land --
    no index collision silently overwrites another observation."""
    store = _YieldingFactStore(InMemoryMemoryProvider())
    log = ObservationLog(store, scope_id="u1")

    await asyncio.gather(*(log.arecord(f"obs-{i}") for i in range(10)))

    result = await log.aget(limit=100)
    assert len(result) == 10
    assert set(result) == {f"obs-{i}" for i in range(10)}


async def test_llm_fact_extractor_propagates_broken_fallback_error() -> None:
    """MINOR 1: a broken fallback extractor's own error is a configuration
    error and must propagate, not be swallowed as an "LLM failure"."""

    class _BrokenFallback:
        async def extract(self, episodes: list) -> list[str]:
            raise RuntimeError("fallback is broken")

    extractor = LlmFactExtractor(fallback=_BrokenFallback())

    with pytest.raises(RuntimeError, match="fallback is broken"):
        await extractor.extract([_ep("e1")])


async def test_llm_fact_extractor_parses_asterisk_bullets() -> None:
    """MINOR 2: "*" bullets are accepted, not just "-"."""

    async def fake_llm(prompt: str, text: str) -> str:
        return "* obs A\n* obs B"

    extractor = LlmFactExtractor(fake_llm)

    facts = await extractor.extract([_ep("e1")])

    assert facts == ["obs A", "obs B"]


async def test_llm_fact_extractor_parses_numbered_bullets() -> None:
    """MINOR 2: numbered markers ("1.", "2)") are accepted too."""

    async def fake_llm(prompt: str, text: str) -> str:
        return "1. first\n2) second"

    extractor = LlmFactExtractor(fake_llm)

    facts = await extractor.extract([_ep("e1")])

    assert facts == ["first", "second"]


async def test_llm_fact_extractor_decimal_prefix_is_not_a_bullet() -> None:
    """r2 minor: "1.2 release notes" is prose (decimal/version token), not a
    numbered-list marker — must not be corrupted into "2 release notes"."""

    async def llm(prompt: str, summaries: str) -> str:
        return "1.2 release notes shipped\n3.11 is the minimum python"

    extractor = LlmFactExtractor(llm)
    result = await extractor.extract([_ep("e1")])

    assert result == [
        "1.2 release notes shipped",
        "3.11 is the minimum python",
    ]
