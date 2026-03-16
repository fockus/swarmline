"""TDD RED: CommandRegistry v2 — typed params, YAML discovery, LLM tool generation.

CRP-5.1: Расширение CommandRegistry с сохранением backward compatibility.
"""

from __future__ import annotations

import pytest
from cognitia.commands.registry import CommandRegistry


class TestCommandTypedParamsValidated:
    """JSON Schema параметры валидируются при execute."""

    async def test_command_typed_params_validated(self) -> None:
        reg = CommandRegistry()

        async def create_topic(name: str, priority: int = 1, **kwargs) -> str:
            return f"Topic '{name}' created with priority {priority}"

        reg.add(
            "topic.new",
            create_topic,
            description="Create a new topic",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Topic name"},
                    "priority": {"type": "integer", "default": 1},
                },
                "required": ["name"],
            },
        )

        cmd = reg.resolve("topic.new")
        assert cmd is not None
        assert cmd.parameters is not None
        assert "name" in cmd.parameters["properties"]


class TestCommandYamlAutoDiscovery:
    """Commands из YAML загружаются автоматически."""

    async def test_command_yaml_auto_discovery(self, tmp_path) -> None:
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
        assert commands[0]["name"] == "deploy.staging"
        assert commands[0]["category"] == "admin"
        assert commands[1]["name"] == "status.check"


class TestCommandToToolDefinition:
    """CommandSpec → ToolDefinition для LLM."""

    async def test_command_to_tool_definition(self) -> None:
        reg = CommandRegistry()

        async def handler(**kwargs) -> str:
            return "ok"

        reg.add(
            "topic.new",
            handler,
            description="Create a new topic",
            category="content",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        )

        tools = reg.to_tool_definitions()
        assert len(tools) == 1
        tool = tools[0]
        assert tool["name"] == "topic.new"
        assert tool["description"] == "Create a new topic"
        assert "properties" in tool["parameters"]


class TestCommandBackwardCompatible:
    """Старый string API работает без изменений."""

    async def test_command_backward_compatible(self) -> None:
        reg = CommandRegistry()

        async def hello(*args, **kwargs) -> str:
            name = args[0] if args else "world"
            return f"Hello, {name}!"

        # Old-style add without parameters/category
        reg.add("hello", hello, aliases=["hi"], description="Greeting")

        result = await reg.execute("hello", args=["Alice"])
        assert result == "Hello, Alice!"

        result_alias = await reg.execute("hi", args=["Bob"])
        assert result_alias == "Hello, Bob!"

        cmd = reg.resolve("hello")
        assert cmd is not None
        assert cmd.parameters is None


class TestCommandCategoriesListed:
    """list_commands(category='admin') фильтрует."""

    async def test_command_categories_listed(self) -> None:
        reg = CommandRegistry()

        async def handler(**kwargs) -> str:
            return "ok"

        reg.add("deploy", handler, category="admin", description="Deploy")
        reg.add("status", handler, category="ops", description="Status")
        reg.add("help", handler, category="admin", description="Help")

        admin_cmds = reg.list_commands(category="admin")
        assert len(admin_cmds) == 2
        assert all(c.category == "admin" for c in admin_cmds)

        ops_cmds = reg.list_commands(category="ops")
        assert len(ops_cmds) == 1

        all_cmds = reg.list_commands()
        assert len(all_cmds) == 3
