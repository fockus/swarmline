"""E2E: Commands - YAML to execution. Full pipeline: YAML definition -> load -> register -> validate -> execute.
CommandRegistry + load_commands_from_yaml with realnym YAML.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from swarmline.commands.loader import load_commands_from_yaml
from swarmline.commands.registry import CommandRegistry


# ---------------------------------------------------------------------------
# 1. YAML load -> validate -> execute
# ---------------------------------------------------------------------------


class TestCommandYamlToExecutionE2E:
    """Full pipeline: YAML file -> load -> register -> validate -> execute."""

    @pytest.mark.asyncio
    async def test_command_yaml_load_validate_execute(self) -> None:
        """Write YAML to tmpfile -> load_commands_from_yaml -> register -> execute_validated. Full E2E: ot filea do vypolnotniya with validatsiey parameterov."""
        yaml_content = """\
commands:
  - name: topic.new
    description: Create a new research topic
    category: research
    aliases:
      - tn
    parameters:
      type: object
      properties:
        name:
          type: string
          description: Topic name
        priority:
          type: integer
          description: Priority level (1-5)
      required:
        - name
  - name: topic.list
    description: List all research topics
    category: research
    aliases:
      - tl
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            # Step 1: Load from YAML
            commands = load_commands_from_yaml(yaml_path)
            assert len(commands) == 2, "Должно загрузиться 2 команды"

            topic_new = next(c for c in commands if c.name == "topic.new")
            assert topic_new.description == "Create a new research topic"
            assert topic_new.category == "research"
            assert "tn" in topic_new.aliases

            topic_list = next(c for c in commands if c.name == "topic.list")
            assert topic_list.description == "List all research topics"

            # Step 2: Register in CommandRegistry
            registry = CommandRegistry()
            execution_log: list[str] = []

            async def handle_topic_new(**kwargs: Any) -> str:
                name = kwargs.get("name", "unnamed")
                priority = kwargs.get("priority", 3)
                execution_log.append(f"created:{name}:{priority}")
                return f"Topic '{name}' created with priority {priority}"

            async def handle_topic_list(**kwargs: Any) -> str:
                execution_log.append("listed")
                return "Topics: AI, ML, NLP"

            registry.add(
                "topic.new",
                handle_topic_new,
                aliases=topic_new.aliases,
                description=topic_new.description,
                category=topic_new.category,
                parameters=topic_new.parameters,
            )
            registry.add(
                "topic.list",
                handle_topic_list,
                aliases=topic_list.aliases,
                description=topic_list.description,
                category=topic_list.category,
                parameters=topic_list.parameters,
            )

            # Step 3: Execute with validation
            result = await registry.execute_validated(
                "topic.new", {"name": "Deep Learning", "priority": 1}
            )
            assert "Deep Learning" in result
            assert "priority 1" in result
            assert execution_log[-1] == "created:Deep Learning:1"

            # Step 4: Execute via alias
            result_alias = await registry.execute(
                "tn", args=[], name="NLP Research", priority=2
            )
            assert "NLP Research" in result_alias

            # Step 5: Validation error — missing required param
            error_result = await registry.execute_validated(
                "topic.new", {"priority": 5}
            )
            assert "Error" in error_result
            assert "name" in error_result

            # Step 6: List commands
            result_list = await registry.execute_validated("topic.list", {})
            assert "Topics" in result_list
            assert execution_log[-1] == "listed"
        finally:
            Path(yaml_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_command_single_yaml_format(self) -> None:
        """Single-command YAML format: {name: ..., description: ...}."""
        yaml_content = """\
name: agent.status
description: Get agent status
category: agent
aliases:
  - as
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            commands = load_commands_from_yaml(yaml_path)
            assert len(commands) == 1
            assert commands[0].name == "agent.status"
            assert commands[0].category == "agent"
        finally:
            Path(yaml_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_command_directory_scan(self) -> None:
        """load_commands_from_yaml with direktoriey: scans vse .yaml files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 2 YAML filea
            (Path(tmpdir) / "cmd1.yaml").write_text(
                "name: cmd1\ndescription: First command\n"
            )
            (Path(tmpdir) / "cmd2.yaml").write_text(
                "name: cmd2\ndescription: Second command\n"
            )
            # Not-YAML file - should be ignored
            (Path(tmpdir) / "readme.txt").write_text("Not a command")

            commands = load_commands_from_yaml(tmpdir)
            assert len(commands) == 2
            names = {c.name for c in commands}
            assert names == {"cmd1", "cmd2"}


# ---------------------------------------------------------------------------
# 2. Command as LLM tool
# ---------------------------------------------------------------------------


class TestCommandAsLLMToolE2E:
    """CommandRegistry.to_tool_definitions() -> ToolDefinition list."""

    @pytest.mark.asyncio
    async def test_command_as_llm_tool(self) -> None:
        """Commands are registered and are converted in ToolDefinition for LLM."""
        registry = CommandRegistry()

        async def noop(**kwargs: Any) -> str:
            return "ok"

        registry.add(
            "analyze.data",
            noop,
            description="Analyze dataset",
            parameters={
                "type": "object",
                "properties": {
                    "dataset": {"type": "string"},
                    "depth": {"type": "integer"},
                },
                "required": ["dataset"],
            },
        )
        registry.add(
            "export.report",
            noop,
            description="Export report to file",
            parameters={
                "type": "object",
                "properties": {
                    "format": {"type": "string"},
                },
            },
        )

        tools = registry.to_tool_definitions()
        assert len(tools) == 2, "Должно быть 2 tool definitions"

        tool_names = {t.name for t in tools}
        assert "analyze.data" in tool_names
        assert "export.report" in tool_names

        analyze_tool = next(t for t in tools if t.name == "analyze.data")
        assert analyze_tool.description == "Analyze dataset"
        assert "dataset" in analyze_tool.parameters.get("properties", {})
        assert "dataset" in analyze_tool.parameters.get("required", [])

        # Dict-like dostup works
        assert analyze_tool["name"] == "analyze.data"
        assert analyze_tool["description"] == "Analyze dataset"

    @pytest.mark.asyncio
    async def test_command_help_text(self) -> None:
        """help_text() genotriruet correct tekst spravki."""
        registry = CommandRegistry()

        async def noop(**kwargs: Any) -> str:
            return "ok"

        registry.add("topic.new", noop, aliases=["tn"], description="Create topic")
        registry.add("topic.list", noop, aliases=["tl"], description="List topics")

        help_text = registry.help_text()
        assert "topic_new" in help_text, "Имя команды в user-friendly формате"
        assert "/tn" in help_text, "Alias в справке"
        assert "Create topic" in help_text
        assert "List topics" in help_text

    @pytest.mark.asyncio
    async def test_command_resolve_by_alias(self) -> None:
        """resolve() nahodit komandu by alias."""
        registry = CommandRegistry()

        async def handler(**kwargs: Any) -> str:
            return "found"

        registry.add("workflow.start", handler, aliases=["ws", "wf_start"])

        # Po imeni
        cmd = registry.resolve("workflow.start")
        assert cmd is not None
        assert cmd.name == "workflow.start"

        # Po alias
        cmd_alias = registry.resolve("ws")
        assert cmd_alias is not None
        assert cmd_alias.name == "workflow.start"

        # Po alias with underscore
        cmd_alias2 = registry.resolve("wf_start")
        assert cmd_alias2 is not None
        assert cmd_alias2.name == "workflow.start"

        # Notizvestnaya command
        assert registry.resolve("unknown") is None
