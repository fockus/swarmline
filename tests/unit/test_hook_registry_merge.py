"""Tests for HookRegistry.merge() method."""

from __future__ import annotations

from swarmline.hooks.registry import HookRegistry


async def _dummy_hook_a(**kwargs: object) -> None:
    pass


async def _dummy_hook_b(**kwargs: object) -> None:
    pass


async def _dummy_hook_c(**kwargs: object) -> None:
    pass


def test_merge_empty_registries():
    r1, r2 = HookRegistry(), HookRegistry()
    merged = r1.merge(r2)
    assert isinstance(merged, HookRegistry)
    assert merged.list_events() == []


def test_merge_combines_hooks():
    r1 = HookRegistry()
    r1.on_pre_tool_use(_dummy_hook_a, matcher="read")

    r2 = HookRegistry()
    r2.on_post_tool_use(_dummy_hook_b)

    merged = r1.merge(r2)

    pre = merged.get_hooks("PreToolUse")
    post = merged.get_hooks("PostToolUse")
    assert len(pre) == 1
    assert pre[0].callback is _dummy_hook_a
    assert pre[0].matcher == "read"
    assert len(post) == 1
    assert post[0].callback is _dummy_hook_b


def test_merge_combines_same_event_hooks():
    r1 = HookRegistry()
    r1.on_stop(_dummy_hook_a)

    r2 = HookRegistry()
    r2.on_stop(_dummy_hook_b)

    merged = r1.merge(r2)

    stop_hooks = merged.get_hooks("Stop")
    assert len(stop_hooks) == 2
    callbacks = {h.callback for h in stop_hooks}
    assert callbacks == {_dummy_hook_a, _dummy_hook_b}


def test_merge_does_not_mutate_originals():
    r1 = HookRegistry()
    r1.on_pre_tool_use(_dummy_hook_a)

    r2 = HookRegistry()
    r2.on_post_tool_use(_dummy_hook_b)

    merged = r1.merge(r2)
    merged.on_stop(_dummy_hook_c)

    # Originals unchanged
    assert r1.list_events() == ["PreToolUse"]
    assert r2.list_events() == ["PostToolUse"]
    assert len(r1.get_hooks("PreToolUse")) == 1
    assert len(r2.get_hooks("PostToolUse")) == 1
    # Stop only in merged
    assert r1.get_hooks("Stop") == []
    assert r2.get_hooks("Stop") == []
    assert len(merged.get_hooks("Stop")) == 1
