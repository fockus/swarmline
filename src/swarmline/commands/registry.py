"""CommandRegistry - command registry for CLI and Telegram."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

# Command handler type
CommandHandler = Callable[..., Awaitable[str]]

_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _validate_params(
    params_schema: dict[str, Any], kwargs: dict[str, Any]
) -> str | None:
    """Validate kwargs against JSON Schema (required + properties.type).

    Uses no external dependencies.
    Returns an error message or None if everything is OK.
    """
    for field_name in params_schema.get("required", []):
        if field_name not in kwargs:
            return f"Error: required parameter '{field_name}' is missing"

    for prop_name, prop_schema in params_schema.get("properties", {}).items():
        if prop_name not in kwargs:
            continue
        expected_type_name: str = prop_schema.get("type", "")
        expected_type = _TYPE_MAP.get(expected_type_name)
        if expected_type is None:
            continue
        # integer is strict: bool is a subclass of int but should not match
        value = kwargs[prop_name]
        if expected_type_name == "integer" and isinstance(value, bool):
            return (
                f"Error: parameter '{prop_name}' must be of type 'integer', "
                f"got '{type(value).__name__}'"
            )
        if not isinstance(value, expected_type):
            return (
                f"Error: parameter '{prop_name}' must be of type '{expected_type_name}', "
                f"got '{type(value).__name__}'"
            )

    return None


@dataclass
class CommandDef:
    """Command definition."""

    name: str
    handler: CommandHandler
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    category: str = ""
    parameters: dict[str, Any] | None = None

    def __getitem__(self, key: str) -> Any:
        """Dict-like access for backward compatibility (cmd['name'])."""
        return getattr(self, key)


@dataclass
class ToolDefinition:
    """Tool definition for the LLM - supports attribute and dict-like access."""

    name: str
    description: str
    parameters: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        """Dict-like access: tool['name'], tool['parameters']."""
        return getattr(self, key)


class CommandRegistry:
    """Command registry with alias support.

    Commands are registered programmatically:
        registry.add("topic.new", aliases=["tn"], handler=create_topic)

    Invocation:
        result = await registry.execute("topic.new", args=["my_topic"], ctx=ctx)
    """

    def __init__(self) -> None:
        self._commands: dict[str, CommandDef] = {}
        self._alias_map: dict[str, str] = {}

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a command name to its canonical form.

        The user-facing format supports `_` (for example `/role_set`),
        while the internal canonical form uses `.` (`role.set`).
        """
        return name.replace("_", ".")

    def add(
        self,
        name: str,
        handler: CommandHandler,
        aliases: list[str] | None = None,
        description: str = "",
        category: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Register a command."""
        canonical_name = self._normalize_name(name)
        cmd = CommandDef(
            name=canonical_name,
            handler=handler,
            aliases=aliases or [],
            description=description,
            category=category,
            parameters=parameters,
        )
        self._commands[canonical_name] = cmd
        for alias in cmd.aliases:
            self._alias_map[alias] = canonical_name
            self._alias_map[self._normalize_name(alias)] = canonical_name

    def resolve(self, name_or_alias: str) -> CommandDef | None:
        """Find a command by name or alias."""
        candidates = [name_or_alias, self._normalize_name(name_or_alias)]
        for candidate in candidates:
            # First exact match
            if candidate in self._commands:
                return self._commands[candidate]
            # Then by alias
            resolved = self._alias_map.get(candidate)
            if resolved:
                return self._commands.get(resolved)
        return None

    async def execute(
        self, name_or_alias: str, args: list[str] | None = None, **kwargs: Any
    ) -> str:
        """Execute a command by name or alias."""
        cmd = self.resolve(name_or_alias)
        if not cmd:
            return f"Неизвестная команда: {name_or_alias}"
        try:
            return await cmd.handler(*(args or []), **kwargs)
        except Exception as e:
            return f"Ошибка выполнения '{cmd.name}': {e}"

    def is_command(self, text: str) -> bool:
        """Check whether the text is a command (starts with /)."""
        return text.startswith("/")

    def parse_command(self, text: str) -> tuple[str, list[str]]:
        """Parse a command string into a name and arguments.

        '/topic.new my_goal' -> ('topic.new', ['my_goal'])
        """
        parts = text.lstrip("/").split(maxsplit=-1)
        name = self._normalize_name(parts[0]) if parts else ""
        # Support both formats:
        # /topic.new -> topic.new
        # /topic_new -> topic.new
        args = parts[1:] if len(parts) > 1 else []
        return name, args

    def list_commands(self, category: str | None = None) -> list[CommandDef]:
        """List all registered commands, optionally filtered by category."""
        commands = list(self._commands.values())
        if category is not None:
            commands = [c for c in commands if c.category == category]
        return commands

    async def execute_validated(
        self, name_or_alias: str, params: dict[str, Any] | None = None
    ) -> str:
        """Execute a command with JSON Schema parameter validation.

        If a command defines JSON Schema (parameters), params are validated
        before invoking the handler. On validation error, returns an error message.
        Uses no external dependencies - built-in validation (required + types).
        """
        cmd = self.resolve(name_or_alias)
        if not cmd:
            return f"Неизвестная команда: {name_or_alias}"
        effective_params = params or {}
        if cmd.parameters:
            error = _validate_params(cmd.parameters, effective_params)
            if error:
                return error
        try:
            return await cmd.handler(**effective_params)
        except Exception as e:
            return f"Ошибка выполнения '{cmd.name}': {e}"

    def to_tool_definitions(self) -> list[ToolDefinition]:
        """Convert registered commands into tool definitions for the LLM."""
        tools: list[ToolDefinition] = []
        for cmd in self._commands.values():
            tools.append(
                ToolDefinition(
                    name=cmd.name,
                    description=cmd.description,
                    parameters=cmd.parameters or {"type": "object", "properties": {}},
                )
            )
        return tools

    def help_text(self) -> str:
        """Generate help text."""
        lines = ["Доступные команды:"]
        for cmd in self._commands.values():
            display_name = cmd.name.replace(".", "_")
            aliases = (
                f" ({', '.join('/' + a.replace('.', '_') for a in cmd.aliases)})"
                if cmd.aliases
                else ""
            )
            desc = f" — {cmd.description}" if cmd.description else ""
            lines.append(f"  /{display_name}{aliases}{desc}")
        return "\n".join(lines)
