"""Integration: ThinRuntime react mode + ToolExecutor + real SandboxProvider. Fake LLM returns tool_call for read_file, ToolExecutor vyzyvaet sandbox.read_file,
zatem LLM returns final with soderzhimym filea.
Verify: tool_call_started event, tool_call_finished event, final result contains file content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, ToolSpec
from swarmline.tools.sandbox_local import LocalSandboxProvider
from swarmline.tools.types import SandboxConfig


def _make_sandbox(tmp_path: Path) -> LocalSandboxProvider:
    """Create real LocalSandboxProvider with workspace in tmp."""
    config = SandboxConfig(
        root_path=str(tmp_path),
        user_id="u1",
        topic_id="t1",
    )
    workspace = Path(config.workspace_path)
    workspace.mkdir(parents=True, exist_ok=True)
    return LocalSandboxProvider(config)


class TestThinRuntimeReactWithRealTools:
    """ThinRuntime react mode + builtin_tools + ToolExecutor + real SandboxProvider."""

    @pytest.mark.asyncio
    async def test_thin_runtime_react_with_real_tools(self, tmp_path: Path) -> None:
        """Fake LLM -> tool_call read_file -> ToolExecutor -> sandbox -> final."""
        sandbox = _make_sandbox(tmp_path)
        workspace = Path(sandbox._config.workspace_path)

        # Podgotovim file in workspace
        test_file = workspace / "hello.txt"
        test_file.write_text("hello from sandbox", encoding="utf-8")

        call_count = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # Pervyy call: LLM hochet prochitat file
                return json.dumps(
                    {
                        "type": "tool_call",
                        "tool": {
                            "name": "read_file",
                            "args": {"path": "hello.txt"},
                        },
                    }
                )
            # Vtoroy call: LLM returns finalnyy response
            return json.dumps(
                {
                    "type": "final",
                    "final_message": "File content: hello from sandbox",
                }
            )

        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin", max_iterations=5),
            llm_call=fake_llm,
            sandbox=sandbox,
        )

        read_file_spec = ToolSpec(
            name="read_file",
            description="Read file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            is_local=True,
        )

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="read hello.txt")],
            system_prompt="You are a file reader",
            active_tools=[read_file_spec],
            mode_hint="react",
        ):
            events.append(event)

        # Verify event types in streame
        event_types = [e.type for e in events]

        assert "tool_call_started" in event_types, "Должен быть tool_call_started event"
        assert "tool_call_finished" in event_types, (
            "Должен быть tool_call_finished event"
        )
        assert "final" in event_types, "Должен быть final event"

        # Verify tool_call_started contains imya toola
        tc_started = [e for e in events if e.type == "tool_call_started"][0]
        assert tc_started.data["name"] == "read_file"

        # Verify tool_call_finished ok=True
        tc_finished = [e for e in events if e.type == "tool_call_finished"][0]
        assert tc_finished.data["ok"] is True
        assert "hello from sandbox" in tc_finished.data["result_summary"]

        # Verify final contains file content
        final_event = [e for e in events if e.type == "final"][0]
        assert "hello from sandbox" in final_event.data["text"]
