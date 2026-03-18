"""Tests CommandRegistry v2 - typed params, YAML discovery, LLM tools. CRP-5.1: rasshirenie CommandRegistry with backward compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cognitia.commands.registry import CommandRegistry


class TestCommandTypedParams:
    """JSON Schema parameters validiruyutsya pri execute."""

    async def test_command_typed_params_stored_in_command_def(self) -> None:
        """JSON Schema is preserved in CommandDef.parameters and dostupna cherez resolve."""
        reg = CommandRegistry()

        async def create_topic(name: str, **kwargs: Any) -> str:
            return f"Created: {name}"

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Topic name"},
            },
            "required": ["name"],
        }
        reg.add(
            "topic.new",
            create_topic,
            description="Create topic",
            parameters=schema,
            category="agent",
        )

        cmd = reg.resolve("topic.new")
        assert cmd is not None
        # Shema sohranotna without izmenotniy for peredachi LLM
        assert cmd.parameters is not None
        assert cmd.parameters["type"] == "object"
        assert "name" in cmd.parameters["properties"]
        assert cmd.category == "agent"

    async def test_command_typed_params_validated(self) -> None:
        """Command with typed params runs with validnymi argumentami."""
        reg = CommandRegistry()

        async def create_topic(name: str, **kwargs: Any) -> str:
            return f"Created topic: {name}"

        reg.add(
            "topic.new",
            handler=create_topic,
            description="Create new topic",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Topic name"},
                },
                "required": ["name"],
            },
            category="topics",
        )

        result = await reg.execute("topic.new", args=["my_topic"])
        assert "my_topic" in result


class TestCommandYamlAutoDiscovery:
    """Commands from YAML zagruzhayutsya avtomaticheski."""

    async def test_command_yaml_auto_discovery(self, tmp_path: Path) -> None:
        """load_commands_from_yaml chitaet YAML-file and returns list[LoadedCommand]."""
        from cognitia.commands.loader import load_commands_from_yaml

        yaml_content = """
commands:
  - name: deploy.staging
    description: Deploy to staging environment
    category: admin
    parameters:
      type: object
      properties:
        version:
          type: string
          description: Version to deploy
      required:
        - version
  - name: status.check
    description: Check system status
    category: ops
"""
        yaml_file = tmp_path / "commands.yaml"
        yaml_file.write_text(yaml_content)

        commands = load_commands_from_yaml(str(yaml_file))

        assert len(commands) == 2
        # load_commands_from_yaml returns list[LoadedCommand] - dataclass with atributami
        assert commands[0].name == "deploy.staging"
        assert commands[0].category == "admin"
        assert commands[0].description == "Deploy to staging environment"
        assert commands[1].name == "status.check"

    async def test_command_yaml_with_parameters_loaded_correctly(
        self, tmp_path: Path
    ) -> None:
        """YAML-parameters (JSON Schema) correctly deserializuyutsya in LoadedCommand.parameters."""
        from cognitia.commands.loader import load_commands_from_yaml

        yaml_content = """
commands:
  - name: test.cmd
    description: A test command
    category: test
    parameters:
      type: object
      properties:
        arg1:
          type: string
      required:
        - arg1
"""
        yaml_file = tmp_path / "test_cmd.yaml"
        yaml_file.write_text(yaml_content)

        commands = load_commands_from_yaml(str(yaml_file))
        assert len(commands) == 1

        cmd = commands[0]
        # LoadedCommand - dataclass, dostup cherez atributy
        assert cmd.name == "test.cmd"
        assert cmd.parameters is not None
        assert "arg1" in cmd.parameters.get("properties", {})


class TestCommandToToolDefinition:
    """CommandSpec -> ToolDefinition for LLM."""

    def test_command_to_tool_definition(self) -> None:
        """to_tool_definitions() returns list[dict] with name, description, parameters."""
        reg = CommandRegistry()

        async def handler(**kwargs: Any) -> str:
            return "ok"

        reg.add(
            "data.query",
            handler,
            description="Query data from database",
            parameters={
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                },
                "required": ["sql"],
            },
            category="data",
        )

        tool_defs = reg.to_tool_definitions()
        assert len(tool_defs) == 1

        tool = tool_defs[0]
        # to_tool_definitions returns list[dict], not obekty with atributami
        assert tool["name"] == "data.query"
        assert tool["description"] == "Query data from database"
        assert "sql" in json.dumps(tool["parameters"])

    def test_command_to_tool_definition_multiple_commands(self) -> None:
        """to_tool_definitions() returns tool definition for kazhdoy commands."""
        reg = CommandRegistry()

        async def h(**kwargs: Any) -> str:
            return "ok"

        reg.add("cmd.one", h, description="First command")
        reg.add("cmd.two", h, description="Second command")

        tools = reg.to_tool_definitions()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert "cmd.one" in names
        assert "cmd.two" in names


class TestCommandBackwardCompatible:
    """Legacy string API works without izmenotniy."""

    async def test_command_backward_compatible(self) -> None:
        """Legacy API (without parameters/category) runs and returns result."""
        reg = CommandRegistry()

        async def old_handler(*args: Any, **kwargs: Any) -> str:
            return f"Old handler: {args}"

        reg.add("legacy.cmd", handler=old_handler, description="Legacy command")

        result = await reg.execute("legacy.cmd", args=["arg1"])
        assert "Old handler" in result

    async def test_command_alias_resolution(self) -> None:
        """Aliasy work - execute('tn') vyzyvaet komandu 'topic.new'."""
        reg = CommandRegistry()

        async def handler(**kwargs: Any) -> str:
            return "aliased"

        reg.add("topic.new", handler=handler, aliases=["tn"])

        result = await reg.execute("tn")
        assert result == "aliased"

    def test_command_parameters_none_by_default(self) -> None:
        """Command without parameters imeet parameters=None (backward compat)."""
        reg = CommandRegistry()

        async def h(**kwargs: Any) -> str:
            return "ok"

        reg.add("legacy", h, description="Legacy command")

        cmd = reg.resolve("legacy")
        assert cmd is not None
        assert cmd.parameters is None


class TestCommandCategoriesListed:
    """list_commands(category='admin') filtruet."""

    def test_command_categories_listed(self) -> None:
        """list_commands(category='admin') returns tolko commands with category='admin'."""
        reg = CommandRegistry()

        async def h(**kw: Any) -> str:
            return "ok"

        reg.add("admin.reset", handler=h, category="admin")
        reg.add("admin.backup", handler=h, category="admin")
        reg.add("user.profile", handler=h, category="user")

        admin_cmds = reg.list_commands(category="admin")
        assert len(admin_cmds) == 2
        assert all(c.category == "admin" for c in admin_cmds)

        all_cmds = reg.list_commands()
        assert len(all_cmds) == 3

    def test_command_list_without_filter_returns_all(self) -> None:
        """list_commands() without argumentov returns vse zaregistrirovannye commands."""
        reg = CommandRegistry()

        async def h(**kw: Any) -> str:
            return "ok"

        reg.add("cmd1", h)
        reg.add("cmd2", h)
        reg.add("cmd3", h)

        assert len(reg.list_commands()) == 3

    def test_command_nonexistent_category_returns_empty(self) -> None:
        """list_commands(category='unknown') returns empty list."""
        reg = CommandRegistry()

        async def h(**kw: Any) -> str:
            return "ok"

        reg.add("cmd.a", h, category="admin")

        result = reg.list_commands(category="unknown")
        assert result == []
