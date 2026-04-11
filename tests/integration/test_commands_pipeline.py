"""Integration: CommandRegistry + YamlCommandLoader - load, discover, execute. CommandRegistry + load_commands_from_yaml: load from real YAML string (tmp file).
Register -> discover -> execute_validated -> check result.
Without mock'ov -- real YAML, real validation, real execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swarmline.commands import CommandRegistry, auto_discover_commands, load_commands_from_yaml


class TestCommandRegistryYamlDiscoveryExecute:
    """CommandRegistry + YamlCommandLoader: real YAML, real validation, real execution."""

    @pytest.mark.asyncio
    async def test_command_registry_yaml_discovery_execute(self, tmp_path: Path) -> None:
        """Load YAML -> register -> discover -> execute_validated."""
        # Create YAML file with multi-command formatom
        yaml_content = """\
commands:
  - name: greet
    description: Greet a person by name
    category: social
    aliases:
      - hello
      - hi
    parameters:
      type: object
      properties:
        name:
          type: string
          description: Person name
      required:
        - name

  - name: calc.add
    description: Add two numbers
    category: math
    parameters:
      type: object
      properties:
        a:
          type: integer
        b:
          type: integer
      required:
        - a
        - b
"""
        yaml_file = tmp_path / "commands.yaml"
        yaml_file.write_text(yaml_content)

        # --- Load from YAML ---
        loaded = load_commands_from_yaml(yaml_file)
        assert len(loaded) == 2
        assert loaded[0].name == "greet"
        assert loaded[1].name == "calc.add"
        assert loaded[0].aliases == ["hello", "hi"]
        assert loaded[0].category == "social"

        # --- Register with real handlers ---
        registry = CommandRegistry()

        async def greet_handler(name: str = "World") -> str:
            return f"Hello, {name}!"

        async def calc_add_handler(a: int = 0, b: int = 0) -> str:
            return str(a + b)

        handler_map = {
            "greet": greet_handler,
            "calc.add": calc_add_handler,
        }

        for cmd in loaded:
            handler = handler_map.get(cmd.name)
            if handler:
                registry.add(
                    cmd.name,
                    handler,
                    aliases=cmd.aliases,
                    description=cmd.description,
                    category=cmd.category,
                    parameters=cmd.parameters,
                )

        # --- Discover ---
        all_commands = registry.list_commands()
        assert len(all_commands) == 2
        social_commands = registry.list_commands(category="social")
        assert len(social_commands) == 1
        assert social_commands[0].name == "greet"

        # --- Resolve by alias ---
        resolved = registry.resolve("hello")
        assert resolved is not None
        assert resolved.name == "greet"

        # --- Execute validated (success) ---
        result = await registry.execute_validated("greet", {"name": "Alice"})
        assert result == "Hello, Alice!"

        result = await registry.execute_validated("calc.add", {"a": 3, "b": 7})
        assert result == "10"

        # --- Execute validated (validation error: missing required param) ---
        result = await registry.execute_validated("greet", {})
        assert "required" in result.lower() and "name" in result.lower()

        # --- Execute validated (validation error: wrong type) ---
        result = await registry.execute_validated("calc.add", {"a": "not_int", "b": 5})
        assert "type" in result.lower()

        # --- Execute unknown command ---
        result = await registry.execute_validated("nonexistent", {})
        assert "неизвестная" in result.lower()

    @pytest.mark.asyncio
    async def test_auto_discover_commands_from_directory(self, tmp_path: Path) -> None:
        """auto_discover_commands: scan directory -> register all commands."""
        # Create otdelnye YAML files (single-command format)
        (tmp_path / "deploy.yaml").write_text(
            "name: deploy\ndescription: Deploy to prod\ncategory: devops\n"
        )
        (tmp_path / "rollback.yaml").write_text(
            "name: rollback\ndescription: Rollback deploy\ncategory: devops\n"
            "aliases:\n  - rb\n"
        )

        registry = CommandRegistry()
        count = auto_discover_commands(registry, tmp_path)

        assert count == 2
        all_cmds = registry.list_commands()
        assert len(all_cmds) == 2

        cmd_names = [c.name for c in all_cmds]
        assert "deploy" in cmd_names
        assert "rollback" in cmd_names

        # auto_discover sozdaet noop handler
        result = await registry.execute("deploy")
        assert "deploy" in result.lower()

        # Alias works
        resolved = registry.resolve("rb")
        assert resolved is not None
        assert resolved.name == "rollback"

    @pytest.mark.asyncio
    async def test_to_tool_definitions(self, tmp_path: Path) -> None:
        """Commands are converted in ToolDefinition for LLM."""
        registry = CommandRegistry()

        async def noop(**kwargs: Any) -> str:
            return "ok"

        registry.add(
            "analyze",
            noop,
            description="Analyze data",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )

        tools = registry.to_tool_definitions()
        assert len(tools) == 1
        assert tools[0].name == "analyze"
        assert tools[0].description == "Analyze data"
        assert "query" in tools[0].parameters["properties"]
