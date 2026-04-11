"""Tests for HookRegistry - registratsiya and receiving hookov sobytiy."""

from swarmline.hooks.registry import HookEntry, HookRegistry


async def _dummy_hook(**kwargs):  # type: ignore[no-untyped-def]
    """Fiktivnyy hook for testov."""
    return "ok"


async def _another_hook(**kwargs):  # type: ignore[no-untyped-def]
    return "another"


class TestHookRegistry:
    """Osnovnoy contract: registratsiya and izvlechenie hookov by sobytiyu."""

    def test_empty_registry_returns_no_hooks(self) -> None:
        """Empty reestr - nott hookov."""
        reg = HookRegistry()
        assert reg.get_hooks("PreToolUse") == []

    def test_on_pre_tool_use_registers(self) -> None:
        """on_pre_tool_use sohranyaet hook."""
        reg = HookRegistry()
        reg.on_pre_tool_use(_dummy_hook, matcher="mcp__iss__*")
        hooks = reg.get_hooks("PreToolUse")
        assert len(hooks) == 1
        assert hooks[0].event == "PreToolUse"
        assert hooks[0].callback is _dummy_hook
        assert hooks[0].matcher == "mcp__iss__*"

    def test_on_post_tool_use_registers(self) -> None:
        """on_post_tool_use sohranyaet hook."""
        reg = HookRegistry()
        reg.on_post_tool_use(_dummy_hook)
        hooks = reg.get_hooks("PostToolUse")
        assert len(hooks) == 1
        assert hooks[0].matcher == ""

    def test_on_stop_registers(self) -> None:
        """on_stop sohranyaet hook."""
        reg = HookRegistry()
        reg.on_stop(_dummy_hook)
        assert len(reg.get_hooks("Stop")) == 1

    def test_on_user_prompt_registers(self) -> None:
        """on_user_prompt sohranyaet hook."""
        reg = HookRegistry()
        reg.on_user_prompt(_dummy_hook)
        assert len(reg.get_hooks("UserPromptSubmit")) == 1

    def test_multiple_hooks_same_event(self) -> None:
        """Notskolko hookov on odno event."""
        reg = HookRegistry()
        reg.on_pre_tool_use(_dummy_hook)
        reg.on_pre_tool_use(_another_hook, matcher="iss")
        hooks = reg.get_hooks("PreToolUse")
        assert len(hooks) == 2
        assert hooks[0].callback is _dummy_hook
        assert hooks[1].callback is _another_hook

    def test_list_events_empty(self) -> None:
        """Without hookov - empty list sobytiy."""
        reg = HookRegistry()
        assert reg.list_events() == []

    def test_list_events_returns_registered(self) -> None:
        """list_events returns vse events with hookami."""
        reg = HookRegistry()
        reg.on_pre_tool_use(_dummy_hook)
        reg.on_stop(_another_hook)
        events = reg.list_events()
        assert set(events) == {"PreToolUse", "Stop"}

    def test_get_hooks_unknown_event(self) -> None:
        """Notzaregistrirovannoe event - empty list."""
        reg = HookRegistry()
        reg.on_pre_tool_use(_dummy_hook)
        assert reg.get_hooks("NonExistent") == []


class TestHookEntry:
    """HookEntry - dataclass hooka."""

    def test_defaults(self) -> None:
        entry = HookEntry(event="PreToolUse", callback=_dummy_hook)
        assert entry.matcher == ""

    def test_with_matcher(self) -> None:
        entry = HookEntry(event="PreToolUse", callback=_dummy_hook, matcher="iss*")
        assert entry.matcher == "iss*"
