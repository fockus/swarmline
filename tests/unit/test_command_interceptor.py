"""Tests for command interception in ThinRuntime.

Verifies that /commands are intercepted BEFORE LLM call, executed via
CommandRegistry, and result returned as RuntimeEvent.final. Non-command
input passes through to LLM as before.
"""

from __future__ import annotations

import json
from typing import Any

from swarmline.commands.registry import CommandRegistry
from swarmline.hooks.registry import HookRegistry
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_final(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


class MockLLM:
    """Tracks whether LLM was called and returns pre-set responses."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses or [make_final("llm response")])
        self._call_count = 0
        self.called = False

    async def __call__(
        self, messages: list[dict[str, Any]], system_prompt: str, **kwargs: Any
    ) -> str:
        self.called = True
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        return make_final("fallback")


def _make_registry() -> CommandRegistry:
    """Create a CommandRegistry with a /help command."""
    registry = CommandRegistry()

    async def help_handler(*args: Any, **kwargs: Any) -> str:
        return "Available commands: /help"

    registry.add("help", handler=help_handler, description="Show help")
    return registry


def _make_registry_with_topic() -> CommandRegistry:
    """Create a CommandRegistry with /help and /topic.new commands."""
    registry = _make_registry()

    async def topic_handler(*args: Any, **kwargs: Any) -> str:
        return f"Topic created: {args[0] if args else 'default'}"

    registry.add("topic.new", handler=topic_handler, description="Create topic")
    return registry


async def _collect(
    runtime: ThinRuntime,
    text: str = "test",
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="System",
        active_tools=[],
    ):
        events.append(ev)
    return events


# ===========================================================================
# Tests
# ===========================================================================


class TestCommandInterceptor:
    """Command interception in ThinRuntime."""

    async def test_command_intercepted_skips_llm(self) -> None:
        """/help detected -> RuntimeEvent.final returned, LLM NOT called."""
        llm = MockLLM()
        registry = _make_registry()
        runtime = ThinRuntime(llm_call=llm, command_registry=registry)

        events = await _collect(runtime, "/help")

        assert not llm.called, "LLM should not be called when command is intercepted"
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert "Available commands: /help" in finals[0].data["text"]

    async def test_noncommand_passes_through(self) -> None:
        """Regular text -> LLM is called normally."""
        llm = MockLLM()
        registry = _make_registry()
        runtime = ThinRuntime(llm_call=llm, command_registry=registry)

        events = await _collect(runtime, "hello")

        assert llm.called, "LLM should be called for non-command input"
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert finals[0].data["text"] == "llm response"

    async def test_no_registry_passes_through(self) -> None:
        """No registry (None) -> everything passes to LLM as before."""
        llm = MockLLM()
        runtime = ThinRuntime(llm_call=llm)

        events = await _collect(runtime, "/help")

        assert llm.called, "LLM should be called when no registry is set"
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1

    async def test_unknown_command_falls_through_to_llm(self) -> None:
        """/unknown -> not intercepted, passes to LLM."""
        llm = MockLLM()
        registry = _make_registry()
        runtime = ThinRuntime(llm_call=llm, command_registry=registry)

        events = await _collect(runtime, "/unknown")

        assert llm.called, "Unregistered /command should pass through to LLM"
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1

    async def test_command_after_hook_transform(self) -> None:
        """UserPromptSubmit hook transforms 'hello' -> '/help', command intercepted."""

        async def transform_to_command(**kwargs: Any) -> str:
            prompt = kwargs.get("prompt", "")
            if prompt == "hello":
                return "/help"
            return prompt

        reg = HookRegistry()
        reg.on_user_prompt(transform_to_command)

        llm = MockLLM()
        registry = _make_registry()
        runtime = ThinRuntime(
            llm_call=llm, command_registry=registry, hook_registry=reg
        )

        events = await _collect(runtime, "hello")

        assert not llm.called, "LLM should not be called when hook transforms to command"
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert "Available commands: /help" in finals[0].data["text"]

    async def test_command_fires_stop_hook(self) -> None:
        """/help -> Stop hook fires with result text."""
        stop_results: list[str] = []

        async def on_stop(**kwargs: Any) -> None:
            stop_results.append(kwargs.get("result_text", ""))

        reg = HookRegistry()
        reg.on_stop(on_stop)

        registry = _make_registry()
        llm = MockLLM()
        runtime = ThinRuntime(
            llm_call=llm, command_registry=registry, hook_registry=reg
        )

        await _collect(runtime, "/help")

        assert len(stop_results) == 1
        assert "Available commands: /help" in stop_results[0]

    async def test_command_with_args(self) -> None:
        """/topic.new my_goal -> args=["my_goal"] passed to handler."""
        registry = _make_registry_with_topic()
        llm = MockLLM()
        runtime = ThinRuntime(llm_call=llm, command_registry=registry)

        events = await _collect(runtime, "/topic.new my_goal")

        assert not llm.called
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert "Topic created: my_goal" in finals[0].data["text"]

    async def test_command_result_in_final_event(self) -> None:
        """Result text appears in RuntimeEvent.final data['text']."""
        registry = _make_registry()
        llm = MockLLM()
        runtime = ThinRuntime(llm_call=llm, command_registry=registry)

        events = await _collect(runtime, "/help")

        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert finals[0].type == "final"
        assert finals[0].data["text"] == "Available commands: /help"

    async def test_unknown_command_passes_to_llm(self) -> None:
        """Unregistered /command passes through to LLM (not intercepted)."""
        llm = MockLLM()
        registry = _make_registry()
        runtime = ThinRuntime(llm_call=llm, command_registry=registry)

        events = await _collect(runtime, "/unknown_cmd")

        assert llm.called, "LLM should be called for unregistered /command"
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1

    async def test_url_like_input_passes_to_llm(self) -> None:
        """Text starting with / but looking like a URL passes to LLM."""
        llm = MockLLM()
        registry = _make_registry()
        runtime = ThinRuntime(llm_call=llm, command_registry=registry)

        await _collect(runtime, "Use /etc/passwd to check permissions")

        assert llm.called, "LLM should be called for non-command /path text"

    async def test_multiline_with_slash_prefix_passes_to_llm(self) -> None:
        """Multiline input starting with / passes to LLM (not a command)."""
        llm = MockLLM()
        registry = _make_registry()
        runtime = ThinRuntime(llm_call=llm, command_registry=registry)

        await _collect(runtime, "/help\nplus more text on next line")

        assert llm.called, "LLM should be called for multiline input even if starts with /"
