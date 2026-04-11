"""Nano Claw: a simple Claude Code-like CLI agent.

Demonstrates: Agent, @tool, Conversation, streaming, middleware -- full CLI agent.
Requires ``ANTHROPIC_API_KEY`` or ``OPENROUTER_API_KEY`` for live mode;
demo mode runs without it.
"""

from __future__ import annotations

import asyncio
import os
import re
import textwrap
from collections.abc import AsyncIterator
from typing import Any

from swarmline.agent.config import AgentConfig
from swarmline.agent.middleware import CostTracker, Middleware
from swarmline.agent.result import Result
from swarmline.agent.tool import tool
from swarmline.runtime.capabilities import RuntimeCapabilities
from swarmline.runtime.registry import get_default_registry
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec

# ---------------------------------------------------------------------------
# Mock filesystem tools (safe, no disk side-effects in demo)
# ---------------------------------------------------------------------------

_MOCK_FS: dict[str, str] = {
    "/project/main.py": "def hello():\n    print('Hello, world!')\n",
    "/project/README.md": "# My Project\n\nA sample project.\n",
}


@tool("read_file", description="Read the contents of a file.")
async def read_file(path: str) -> str:
    """Read a file from the mock filesystem.

    Args:
        path: Absolute path to the file.
    """
    if path in _MOCK_FS:
        return _MOCK_FS[path]
    return f"[Error] File not found: {path}"


@tool("write_file", description="Write content to a file.")
async def write_file(path: str, content: str) -> str:
    """Write content to a file in the mock filesystem.

    Args:
        path: Absolute path to the file.
        content: Text content to write.
    """
    _MOCK_FS[path] = content
    return f"[OK] Written {len(content)} bytes to {path}"


@tool("list_directory", description="List files in a directory.")
async def list_directory(path: str) -> str:
    """List all files under a directory in the mock filesystem.

    Args:
        path: Directory path prefix.
    """
    files = [f for f in _MOCK_FS if f.startswith(path)]
    if not files:
        return f"[Empty] No files found under {path}"
    return "\n".join(sorted(files))


@tool("execute_command", description="Execute a shell command (mocked, safe).")
async def execute_command(command: str) -> str:
    """Execute a shell command (returns a mock response for safety).

    Args:
        command: Shell command to run.
    """
    return f"[Mock] Would execute: {command}\n[stdout] (mocked output)"


# ---------------------------------------------------------------------------
# Turn logger: print per-turn cost to stderr
# ---------------------------------------------------------------------------


class TurnLogger(Middleware):
    """Prints token usage and cost after every turn."""

    async def after_result(self, result: Result) -> Result:
        usage = result.usage or {}
        cost = result.total_cost_usd
        parts: list[str] = []
        if usage.get("input_tokens") is not None:
            parts.append(f"in={usage['input_tokens']}")
        if usage.get("output_tokens") is not None:
            parts.append(f"out={usage['output_tokens']}")
        if cost is not None:
            parts.append(f"cost=${cost:.6f}")
        if parts:
            print(f"\n  [usage] {' | '.join(parts)}", flush=True)
        return result


# ---------------------------------------------------------------------------
# Mock LLM runtime (no API key needed)
# ---------------------------------------------------------------------------

_CANNED: list[tuple[str, str]] = [
    (
        "list",
        "Sure! Here are your project files:\n\n/project/main.py\n/project/README.md",
    ),
    (
        "read",
        "I'll read main.py for you.\n\n```python\ndef hello():\n    print('Hello, world!')\n```\n\nLooks good!",
    ),
    (
        "write",
        "I've written the new file to /project/utils.py with the helper functions.",
    ),
    (
        "help",
        textwrap.dedent("""\
            I can help you with:
            • list_directory — browse your project files
            • read_file      — read any file
            • write_file     — create or update files
            • execute_command — run shell commands (mocked)

            Just ask in plain English!
        """),
    ),
]


def _extract_path(user_input: str, default: str) -> str:
    match = re.search(r"(/\S+)", user_input)
    if not match:
        return default
    return match.group(1).rstrip(".,)")


def _helper_file_content(path: str) -> str:
    stem = path.rsplit("/", 1)[-1].split(".", 1)[0] or "helper"
    fn_name = stem.replace("-", "_")
    return textwrap.dedent(
        f"""\
        def {fn_name}_helper(name: str) -> str:
            return f"Hello, {{name}}!"
        """
    )


async def _demo_tool_turn(
    user_input: str,
) -> tuple[str, str, dict[str, Any], str, bool] | None:
    lower = user_input.lower()

    if "list" in lower and ("file" in lower or "/project" in lower):
        path = _extract_path(user_input, "/project")
        result = await list_directory(path=path)
        text = f"Sure! Here are your project files:\n\n{result}"
        return ("list_directory", text, {"path": path}, result, True)

    if "read" in lower:
        path = _extract_path(user_input, "/project/main.py")
        result = await read_file(path=path)
        ok = not result.startswith("[Error]")
        if ok:
            language = "python" if path.endswith(".py") else ""
            fence = f"```{language}\n{result}\n```" if language else f"```\n{result}\n```"
            text = f"I'll read {path} for you.\n\n{fence}\n\nLooks good!"
        else:
            text = result
        return ("read_file", text, {"path": path}, result, ok)

    if "write" in lower:
        path = _extract_path(user_input, "/project/utils.py")
        content = _helper_file_content(path)
        result = await write_file(path=path, content=content)
        text = f"I've written the new file to {path} with the helper functions."
        return (
            "write_file",
            text,
            {"path": path, "content": content},
            result,
            result.startswith("[OK]"),
        )

    if "execute" in lower or lower.startswith("run "):
        command = user_input.split(" ", 1)[-1].strip()
        result = await execute_command(command=command)
        return ("execute_command", result, {"command": command}, result, True)

    return None


def _pick_response(user_input: str) -> str:
    lower = user_input.lower()
    for keyword, response in _CANNED:
        if keyword in lower:
            return response
    return (
        f'Got your message: "{user_input}"\n\n'
        "I'm running in demo mode (no API key). "
        "Attach ANTHROPIC_API_KEY and call live() for the real experience."
    )


class MockRuntime:
    """Keyword-based mock runtime — no network calls."""

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        _ = (system_prompt, active_tools, config, mode_hint)
        last = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "",
        )

        tool_turn = await _demo_tool_turn(last)
        if tool_turn is not None:
            tool_name, text, tool_input, tool_result, ok = tool_turn
            started = RuntimeEvent.tool_call_started(tool_name, args=tool_input)
            correlation_id = started.data["correlation_id"]
            yield started
            await asyncio.sleep(0.01)
            yield RuntimeEvent.tool_call_finished(
                tool_name,
                correlation_id=correlation_id,
                ok=ok,
                result_summary=tool_result,
            )
        else:
            text = _pick_response(last)

        # Stream word-by-word to show streaming path
        for word in text.split():
            yield RuntimeEvent.assistant_delta(text=word + " ")
            await asyncio.sleep(0.015)  # simulate token latency

        yield RuntimeEvent.final(
            text=text,
            new_messages=[],
            total_cost_usd=0.0,
            usage={"input_tokens": 0, "output_tokens": 0},
        )

    def cancel(self) -> None:
        pass

    async def cleanup(self) -> None:
        pass


def _mock_factory(config: RuntimeConfig | None = None, **_: Any) -> MockRuntime:
    return MockRuntime()


_MOCK_CAPS = RuntimeCapabilities(
    runtime_name="mock",
    tier="light",
    supports_mcp=False,
    supports_provider_override=False,
)

# Register into the global default registry so AgentConfig validation passes.
get_default_registry().register("mock", _mock_factory, capabilities=_MOCK_CAPS)


# ---------------------------------------------------------------------------
# NanoClaw — the agent wrapper
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = textwrap.dedent("""\
    You are Nano Claw, a CLI coding assistant similar to Claude Code.
    You have access to tools for reading, writing, and listing files,
    and for executing shell commands. Always be concise and helpful.
    When asked to perform a file operation, use the appropriate tool.
""")

_HELP_TEXT = textwrap.dedent("""\
    Nano Claw — CLI coding agent
    ─────────────────────────────
    Commands:
      /help   — show this help
      /clear  — clear conversation history
      /quit   — exit
      /cost   — show accumulated spend

    Otherwise, type any request and press Enter.
""")

_AGENT_TOOLS = (
    read_file.__tool_definition__,  # type: ignore[attr-defined]
    write_file.__tool_definition__,  # type: ignore[attr-defined]
    list_directory.__tool_definition__,  # type: ignore[attr-defined]
    execute_command.__tool_definition__,  # type: ignore[attr-defined]
)


class NanoClaw:
    """Nano Claw agent: multi-turn conversation with streaming and cost tracking."""

    def __init__(self, runtime: str = "mock", model: str = "sonnet") -> None:
        self._cost_tracker = CostTracker(budget_usd=10.0)
        self._turn_logger = TurnLogger()
        self._config = AgentConfig(
            system_prompt=_SYSTEM_PROMPT,
            runtime=runtime,
            model=model,
            tools=_AGENT_TOOLS,
            middleware=(self._cost_tracker, self._turn_logger),
        )
        from swarmline.agent.agent import Agent

        self._agent = Agent(self._config)
        self._conv = self._agent.conversation(session_id="nano-claw-session")
        self._turn = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_turn(self, user_input: str) -> str:
        """Process one user turn; return the assistant's reply text."""
        stripped = user_input.strip()
        if not stripped:
            return ""

        # Handle special commands before sending to LLM
        if stripped == "/help":
            return _HELP_TEXT
        if stripped == "/clear":
            self._conv = self._agent.conversation()
            return "[History cleared]"
        if stripped == "/quit":
            return "/quit"
        if stripped == "/cost":
            return f"Accumulated cost: ${self._cost_tracker.total_cost_usd:.6f}"

        self._turn += 1
        print(f"\n[turn {self._turn}] assistant: ", end="", flush=True)

        # Stream the reply token-by-token
        full_text = ""
        raw_stream_text = ""
        final_text = ""
        pending_chunks: list[str] = []
        render_mode = "unknown"
        total_cost_usd: float | None = None
        usage: dict[str, Any] | None = None
        async for event in self._conv.stream(stripped):
            if event.type == "text_delta":
                chunk = event.text
                raw_stream_text += chunk
                if render_mode == "unknown":
                    pending_chunks.append(chunk)
                    probe = "".join(pending_chunks).lstrip()
                    if not probe:
                        continue
                    if probe.startswith("{"):
                        render_mode = "json"
                        continue
                    render_mode = "text"
                    buffered = "".join(pending_chunks)
                    print(buffered, end="", flush=True)
                    full_text += buffered
                    pending_chunks.clear()
                    continue

                if render_mode == "text":
                    print(chunk, end="", flush=True)
                    full_text += chunk
            elif event.type == "tool_use_start":
                # _RuntimeEventAdapter always has tool_name and tool_input
                print(f"\n  [tool] {event.tool_name}({event.tool_input})", flush=True)
            elif event.type == "tool_use_result":
                # _RuntimeEventAdapter always has tool_result (default "")
                print(f"  [result] {event.tool_result[:120]}", flush=True)
            elif event.type == "error":
                # _RuntimeEventAdapter always has text (default "")
                print(f"\n  [error] {event.text}", flush=True)
            elif event.type in {"done", "final"}:
                final_text = getattr(event, "text", "") or ""
                total_cost_usd = getattr(event, "total_cost_usd", None)
                usage = getattr(event, "usage", None)

        if render_mode != "text" and final_text:
            print(final_text, end="", flush=True)
            full_text = final_text
        elif not full_text and final_text:
            full_text = final_text
        elif not full_text and raw_stream_text:
            full_text = raw_stream_text

        print()  # newline after streamed response

        # Manually trigger after_result on streaming path (middleware)
        mock_result = Result(
            text=full_text,
            session_id=self._conv.session_id,
            total_cost_usd=total_cost_usd,
            usage=usage,
        )
        for mw in self._config.middleware:
            mock_result = await mw.after_result(mock_result)

        return full_text

    async def close(self) -> None:
        await self._conv.close()
        await self._agent.cleanup()


# ---------------------------------------------------------------------------
# Demo: simulated turns (runs without ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------


async def demo() -> None:
    """Run 4 simulated turns with the mock runtime to showcase the agent."""
    print("=" * 60)
    print("  Nano Claw — Demo Mode (mock LLM, no API key needed)")
    print("=" * 60)

    agent = NanoClaw(runtime="mock")

    turns = [
        "/help",
        "List the files in /project",
        "Read the file /project/main.py",
        "Write a new file /project/utils.py with a helper function",
    ]

    for user_input in turns:
        print(f"\n[user] {user_input}")
        reply = await agent.run_turn(user_input)
        if reply == "/quit":
            break

    print("\n" + "=" * 60)
    print(f"  Demo complete. Total cost: ${agent._cost_tracker.total_cost_usd:.6f}")
    print("=" * 60)

    await agent.close()


# ---------------------------------------------------------------------------
# Live REPL: real LLM via ANTHROPIC_API_KEY or OPENROUTER_API_KEY
# ---------------------------------------------------------------------------


def _resolve_live_model() -> str:
    """Select live model/provider based on available credentials."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "sonnet"

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        os.environ["OPENAI_API_KEY"] = openrouter_key
        return "openrouter:anthropic/claude-3.5-haiku"

    raise SystemExit("Either ANTHROPIC_API_KEY or OPENROUTER_API_KEY is required for --live mode")


async def live() -> None:
    """Interactive REPL with a real model via Anthropic or OpenRouter."""
    model = _resolve_live_model()

    print("=" * 60)
    print(f"  Nano Claw — Live Mode ({model})")
    print("  Type /help for commands, /quit to exit.")
    print("=" * 60)

    agent = NanoClaw(runtime="thin", model=model)

    try:
        while True:
            try:
                user_input = input("\n[user] ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nInterrupted.")
                break

            if not user_input:
                continue

            reply = await agent.run_turn(user_input)
            if reply == "/quit":
                print("Goodbye!")
                break
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Default: demo mode (no API key required).
    # To run live:
    #   ANTHROPIC_API_KEY=sk-... python 27_nano_claw.py --live
    #   OPENROUTER_API_KEY=sk-or-... python 27_nano_claw.py --live
    import sys

    if "--live" in sys.argv:
        asyncio.run(live())
    else:
        asyncio.run(demo())
