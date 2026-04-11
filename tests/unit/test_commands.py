"""Tests for CommandRegistry."""

import pytest
from swarmline.commands import CommandRegistry


@pytest.fixture
def registry() -> CommandRegistry:
    reg = CommandRegistry()

    async def hello(*args, **kwargs):
        name = args[0] if args else "world"
        return f"Hello, {name}!"

    async def goodbye(**kwargs):
        return "Goodbye!"

    reg.add("hello", hello, aliases=["hi", "h"], description="Приветствие")
    reg.add("goodbye", goodbye, aliases=["bye"], description="Прощание")
    return reg


class TestCommandRegistry:
    """Tests reestra komand."""

    def test_resolve_by_name(self, registry: CommandRegistry) -> None:
        """Nahodit komandu by imeni."""
        cmd = registry.resolve("hello")
        assert cmd is not None
        assert cmd.name == "hello"

    def test_resolve_by_alias(self, registry: CommandRegistry) -> None:
        """Nahodit komandu by aliasu."""
        cmd = registry.resolve("hi")
        assert cmd is not None
        assert cmd.name == "hello"

    def test_resolve_nonexistent(self, registry: CommandRegistry) -> None:
        """Notsushchestvuyushchaya command returns None."""
        assert registry.resolve("nonexistent") is None

    @pytest.mark.asyncio
    async def test_execute_with_args(self, registry: CommandRegistry) -> None:
        """Execution commands with argumentami."""
        result = await registry.execute("hello", args=["Freedom"])
        assert result == "Hello, Freedom!"

    @pytest.mark.asyncio
    async def test_execute_by_alias(self, registry: CommandRegistry) -> None:
        """Execution by aliasu."""
        result = await registry.execute("bye")
        assert result == "Goodbye!"

    @pytest.mark.asyncio
    async def test_execute_nonexistent(self, registry: CommandRegistry) -> None:
        """Notsushchestvuyushchaya command -> message ob oshibke."""
        result = await registry.execute("nonexistent")
        assert "Неизвестная" in result

    def test_is_command(self, registry: CommandRegistry) -> None:
        """Tekst, nachinayushchiysya with /, yavlyaetsya komandoy."""
        assert registry.is_command("/hello")
        assert not registry.is_command("hello")
        assert not registry.is_command("привет")

    def test_parse_command(self, registry: CommandRegistry) -> None:
        """Parsing commands on imya and argumenty."""
        name, args = registry.parse_command("/topic.new my_goal")
        assert name == "topic.new"
        assert args == ["my_goal"]

    def test_parse_command_with_underscore(self, registry: CommandRegistry) -> None:
        """Parsing underscore-formata commands in canonical dotted-name."""
        name, args = registry.parse_command("/topic_new my_goal")
        assert name == "topic.new"
        assert args == ["my_goal"]

    @pytest.mark.asyncio
    async def test_execute_dotted_command_via_underscore_name(self) -> None:
        """`/role_set`-podobnye imena should rezolvitsya in `role.set`."""
        reg = CommandRegistry()

        async def _handler(*args, **kwargs):
            return "ok"

        reg.add("role.set", _handler, aliases=["r"])
        result = await reg.execute("role_set")
        assert result == "ok"

    def test_parse_command_no_args(self, registry: CommandRegistry) -> None:
        """Parsing commands without argumentov."""
        name, args = registry.parse_command("/help")
        assert name == "help"
        assert args == []

    def test_list_commands(self, registry: CommandRegistry) -> None:
        """List vseh komand."""
        commands = registry.list_commands()
        assert len(commands) == 2

    def test_help_text(self, registry: CommandRegistry) -> None:
        """Genotratsiya help teksta."""
        text = registry.help_text()
        assert "/hello" in text
        assert "/goodbye" in text
        assert "Приветствие" in text
