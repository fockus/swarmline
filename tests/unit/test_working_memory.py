"""TDD tests for Stage C2.1 — ``WorkingMemory`` (resource-scoped structured
profile over an existing ``FactStore``).

Uses ``InMemoryMemoryProvider`` (which implements ``FactStore``) directly —
no mocks of our own storage (Testing Trophy: integration over unit-with-mocks
for a thin wrapper like this). Covers the 7 plan-mandated tests plus the
plan-mandated edge case (field name containing the prefix delimiter fails
loud) and a couple of small render/prefix-isolation edge cases.
"""

from __future__ import annotations

import pytest

from swarmline.memory import InMemoryMemoryProvider, WorkingMemory

# ---------------------------------------------------------------------------
# Plan-mandated tests (7)
# ---------------------------------------------------------------------------


async def test_working_memory_set_then_get_round_trips() -> None:
    store = InMemoryMemoryProvider()
    wm = WorkingMemory(store, resource_id="u1")

    await wm.aset("name", "Ann")

    assert await wm.aget() == {"name": "Ann"}


async def test_working_memory_update_bulk() -> None:
    store = InMemoryMemoryProvider()
    wm = WorkingMemory(store, resource_id="u1")

    await wm.aupdate({"name": "Ann", "goal": "save"})

    result = await wm.aget()
    assert result["name"] == "Ann"
    assert result["goal"] == "save"


async def test_working_memory_is_resource_scoped() -> None:
    store = InMemoryMemoryProvider()
    wm_a = WorkingMemory(store, resource_id="u1")
    wm_b = WorkingMemory(store, resource_id="u2")

    await wm_a.aset("name", "Ann")
    await wm_b.aset("name", "Bob")

    assert await wm_a.aget() == {"name": "Ann"}
    assert await wm_b.aget() == {"name": "Bob"}


async def test_working_memory_ignores_non_prefixed_facts() -> None:
    store = InMemoryMemoryProvider()
    await store.upsert_fact("u1", "business_fact", "x")
    wm = WorkingMemory(store, resource_id="u1")
    await wm.aset("name", "Ann")

    result = await wm.aget()

    assert result == {"name": "Ann"}
    assert "business_fact" not in result


async def test_working_memory_render_includes_template_fields_in_order() -> None:
    store = InMemoryMemoryProvider()
    wm = WorkingMemory(
        store,
        resource_id="u1",
        template={"name": "user's name", "goal": "user's goal"},
    )
    await wm.aset("name", "Ann")

    rendered = await wm.arender()

    assert rendered.index("name:") < rendered.index("goal:")
    assert "name: Ann" in rendered
    assert "goal: " in rendered  # unset template field renders blank


async def test_working_memory_render_empty_is_safe() -> None:
    store = InMemoryMemoryProvider()
    wm = WorkingMemory(store, resource_id="u1")

    rendered = await wm.arender()

    assert rendered == "<working_memory></working_memory>"


def test_working_memory_export_importable() -> None:
    from swarmline.memory import WorkingMemory as ImportedWorkingMemory

    assert ImportedWorkingMemory is WorkingMemory


# ---------------------------------------------------------------------------
# Edge cases (plan "Edge cases" section, C2.1)
# ---------------------------------------------------------------------------


async def test_working_memory_field_with_dot_raises_value_error() -> None:
    store = InMemoryMemoryProvider()
    wm = WorkingMemory(store, resource_id="u1")

    with pytest.raises(ValueError, match=r"\."):
        await wm.aset("a.b", "x")


async def test_working_memory_render_wraps_set_non_template_fields() -> None:
    store = InMemoryMemoryProvider()
    wm = WorkingMemory(store, resource_id="u1")
    await wm.aset("nickname", "Annie")

    rendered = await wm.arender()

    assert rendered.startswith("<working_memory>")
    assert rendered.endswith("</working_memory>")
    assert "nickname: Annie" in rendered


async def test_working_memory_is_thread_independent_topic_id_ignored() -> None:
    """WorkingMemory uses topic_id=None (resource-level) -- verified by
    writing directly to a topic-scoped fact under the wm prefix and
    confirming aget() does NOT pick it up (global/resource scope only)."""
    store = InMemoryMemoryProvider()
    await store.upsert_fact("u1", "wm.name", "TopicScoped", topic_id="some-topic")
    wm = WorkingMemory(store, resource_id="u1")

    assert await wm.aget() == {}


# ---------------------------------------------------------------------------
# Fix-cycle r1 — cheap InMemory guards for the default provider (the
# real source-priority-CASE regression lives in tests/unit/test_sqlite_memory.py,
# since InMemory has no priority guard to trigger the bug at all).
# ---------------------------------------------------------------------------


async def test_working_memory_aset_overwrites_preexisting_user_sourced_fact() -> None:
    """Mirrors the SQLite/Postgres provider regression (r1 MAJOR): a
    pre-existing row under a wm.* key, written with source="user", must
    still be overwritten by a subsequent WorkingMemory.aset (source=
    "working_memory")."""
    store = InMemoryMemoryProvider()
    await store.upsert_fact("u1", "wm.name", "old", source="user")
    wm = WorkingMemory(store, resource_id="u1")

    await wm.aset("name", "new")

    assert (await wm.aget())["name"] == "new"


async def test_working_memory_render_sorts_non_template_extras() -> None:
    """Non-template extras render sorted by name (r1 MINOR 1) --
    deterministic regardless of the store's return order."""
    store = InMemoryMemoryProvider()
    wm = WorkingMemory(store, resource_id="u1")
    await wm.aupdate({"zebra": "1", "apple": "2"})

    rendered = await wm.arender()

    assert rendered.index("apple:") < rendered.index("zebra:")


async def test_working_memory_aupdate_rejects_all_on_one_invalid_field() -> None:
    """aupdate validates EVERY field name before any write (r1 MINOR 2) --
    an invalid field must not leave an earlier field partially persisted."""
    store = InMemoryMemoryProvider()
    wm = WorkingMemory(store, resource_id="u1")

    with pytest.raises(ValueError, match=r"\."):
        await wm.aupdate({"name": "Ann", "bad.field": "x"})

    assert await wm.aget() == {}
