"""Coverage tests: CommandRegistry (validate, execute_validated, help, errors) + loader edge cases. Dopolnyaet test_commands_v2.py - pokryvaet notprotestirovannye puti."""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.commands.registry import CommandRegistry, _validate_params


# --- _validate_params ---


class TestValidateParamsRequired:
    """_validate_params verifies required polya."""

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({"name": "test"}, None),
            ({}, "required parameter 'name' is missing"),
        ],
        ids=["present", "missing"],
    )
    def test_validate_params_required(self, kwargs: dict, expected: str | None) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        result = _validate_params(schema, kwargs)
        if expected is None:
            assert result is None
        else:
            assert result is not None
            assert expected in result


class TestValidateParamsTypeChecks:
    """_validate_params verifies tipy by JSON Schema."""

    @pytest.mark.parametrize(
        "prop_type, value, should_pass",
        [
            ("string", "hello", True),
            ("string", 123, False),
            ("integer", 42, True),
            ("integer", "no", False),
            ("integer", True, False),  # bool is subclass of int but rejected
            ("boolean", True, True),
            ("boolean", "yes", False),
            ("array", [1, 2], True),
            ("array", "not-list", False),
            ("object", {"a": 1}, True),
            ("object", "not-dict", False),
        ],
        ids=[
            "str-ok",
            "str-fail",
            "int-ok",
            "int-fail",
            "int-bool-rejected",
            "bool-ok",
            "bool-fail",
            "array-ok",
            "array-fail",
            "obj-ok",
            "obj-fail",
        ],
    )
    def test_validate_params_type_checks(
        self, prop_type: str, value: Any, should_pass: bool
    ) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"field": {"type": prop_type}},
        }
        result = _validate_params(schema, {"field": value})
        if should_pass:
            assert result is None
        else:
            assert result is not None
            assert "field" in result

    def test_validate_params_unknown_type_skipped(self) -> None:
        schema: dict[str, Any] = {
            "properties": {"x": {"type": "custom_unknown"}},
        }
        assert _validate_params(schema, {"x": "anything"}) is None

    def test_validate_params_missing_optional_ok(self) -> None:
        schema: dict[str, Any] = {
            "properties": {"opt": {"type": "string"}},
        }
        assert _validate_params(schema, {}) is None


# --- execute_validated ---


class TestExecuteValidated:
    """execute_validated validiruet parameters pered vyzovom handler."""

    async def test_execute_validated_success(self) -> None:
        reg = CommandRegistry()

        async def greet(name: str = "world", **kwargs: Any) -> str:
            return f"Hi, {name}!"

        reg.add(
            "greet",
            greet,
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        result = await reg.execute_validated("greet", {"name": "Alice"})
        assert result == "Hi, Alice!"

    async def test_execute_validated_missing_required(self) -> None:
        reg = CommandRegistry()

        async def handler(**kwargs: Any) -> str:
            return "ok"

        reg.add(
            "cmd",
            handler,
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        result = await reg.execute_validated("cmd", {})
        assert "required parameter 'name' is missing" in result

    async def test_execute_validated_wrong_type(self) -> None:
        reg = CommandRegistry()

        async def handler(**kwargs: Any) -> str:
            return "ok"

        reg.add(
            "cmd",
            handler,
            parameters={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
            },
        )
        result = await reg.execute_validated("cmd", {"count": "not_int"})
        assert "must be of type 'integer'" in result

    async def test_execute_validated_unknown_command(self) -> None:
        reg = CommandRegistry()
        result = await reg.execute_validated("nonexistent")
        assert "Неизвестная команда" in result

    async def test_execute_validated_no_params_schema(self) -> None:
        reg = CommandRegistry()

        async def handler(**kwargs: Any) -> str:
            return f"got {kwargs}"

        reg.add("simple", handler)
        result = await reg.execute_validated("simple", {"x": 1})
        assert "got" in result

    async def test_execute_validated_handler_exception(self) -> None:
        reg = CommandRegistry()

        async def broken(**kwargs: Any) -> str:
            raise ValueError("boom")

        reg.add(
            "broken",
            broken,
            parameters={
                "type": "object",
                "properties": {},
            },
        )
        result = await reg.execute_validated("broken")
        assert "Ошибка выполнения" in result
        assert "boom" in result


# --- execute error handling ---


class TestExecuteErrorHandling:
    """execute lovit isklyucheniya handler'a."""

    async def test_execute_handler_exception(self) -> None:
        reg = CommandRegistry()

        async def exploder(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("kaboom")

        reg.add("explode", exploder)
        result = await reg.execute("explode")
        assert "Ошибка выполнения" in result
        assert "kaboom" in result

    async def test_execute_unknown_command(self) -> None:
        reg = CommandRegistry()
        result = await reg.execute("nope")
        assert "Неизвестная команда" in result


# --- help_text, is_command, parse_command, normalize ---


class TestRegistryUtilities:
    """Vspomogatelnye metody registry."""

    def test_is_command_slash(self) -> None:
        reg = CommandRegistry()
        assert reg.is_command("/deploy") is True
        assert reg.is_command("deploy") is False

    def test_parse_command_with_args(self) -> None:
        reg = CommandRegistry()
        name, args = reg.parse_command("/topic_new my_goal extra")
        assert name == "topic.new"
        assert args == ["my_goal", "extra"]

    def test_parse_command_no_args(self) -> None:
        reg = CommandRegistry()
        name, args = reg.parse_command("/status")
        assert name == "status"
        assert args == []

    def test_help_text_includes_commands(self) -> None:
        reg = CommandRegistry()

        async def handler(**kw: Any) -> str:
            return "ok"

        reg.add("deploy", handler, aliases=["d"], description="Deploy app")
        text = reg.help_text()
        assert "deploy" in text
        assert "/d" in text
        assert "Deploy app" in text

    def test_resolve_underscore_alias(self) -> None:
        reg = CommandRegistry()

        async def handler(**kw: Any) -> str:
            return "ok"

        reg.add("topic.new", handler, aliases=["tn"])
        assert reg.resolve("topic_new") is not None
        assert reg.resolve("topic.new") is not None
        assert reg.resolve("tn") is not None

    def test_resolve_nonexistent(self) -> None:
        reg = CommandRegistry()
        assert reg.resolve("ghost") is None


# --- CommandDef / ToolDefinition dict-like access ---


class TestDictLikeAccess:
    """__getitem__ for backward compatibility."""

    def test_command_def_getitem(self) -> None:
        from swarmline.commands.registry import CommandDef

        async def h(**kw: Any) -> str:
            return ""

        cmd = CommandDef(name="test", handler=h, description="desc")
        assert cmd["name"] == "test"
        assert cmd["description"] == "desc"

    def test_tool_definition_getitem(self) -> None:
        from swarmline.commands.registry import ToolDefinition

        tool = ToolDefinition(name="t", description="d", parameters={"type": "object"})
        assert tool["name"] == "t"
        assert tool["parameters"]["type"] == "object"


# --- loader edge cases ---


class TestLoaderEdgeCases:
    """loader.py — directory scan, single-command, errors."""

    async def test_load_from_directory(self, tmp_path: Any) -> None:
        from swarmline.commands.loader import load_commands_from_yaml

        (tmp_path / "a.yaml").write_text("name: cmd_a\ndescription: A\ncategory: ops\n")
        (tmp_path / "b.yml").write_text("name: cmd_b\ndescription: B\n")

        commands = load_commands_from_yaml(tmp_path)
        names = {c.name for c in commands}
        assert "cmd_a" in names
        assert "cmd_b" in names

    async def test_load_single_command_format(self, tmp_path: Any) -> None:
        from swarmline.commands.loader import load_commands_from_yaml

        f = tmp_path / "single.yaml"
        f.write_text("name: solo\ndescription: Single\ncategory: test\n")
        commands = load_commands_from_yaml(str(f))
        assert len(commands) == 1
        assert commands[0].name == "solo"
        assert commands[0].category == "test"

    async def test_load_invalid_yaml_returns_empty(self, tmp_path: Any) -> None:
        from swarmline.commands.loader import load_commands_from_yaml

        f = tmp_path / "bad.yaml"
        f.write_text(":::: not valid yaml {{{{")
        commands = load_commands_from_yaml(str(f))
        assert commands == []

    async def test_load_no_name_entries_skipped(self, tmp_path: Any) -> None:
        from swarmline.commands.loader import load_commands_from_yaml

        f = tmp_path / "noname.yaml"
        f.write_text(
            "commands:\n  - description: no name here\n  - name: valid\n    description: ok\n"
        )
        commands = load_commands_from_yaml(str(f))
        assert len(commands) == 1
        assert commands[0].name == "valid"

    async def test_load_non_dict_data_returns_empty(self, tmp_path: Any) -> None:
        from swarmline.commands.loader import load_commands_from_yaml

        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        commands = load_commands_from_yaml(str(f))
        assert commands == []

    async def test_loaded_command_dict_access(self, tmp_path: Any) -> None:
        from swarmline.commands.loader import LoadedCommand

        cmd = LoadedCommand(name="test", description="d", category="c")
        assert cmd["name"] == "test"
        assert cmd["category"] == "c"


class TestAutoDiscoverCommands:
    """auto_discover_commands - registratsiya YAML in CommandRegistry."""

    async def test_auto_discover_registers_commands(self, tmp_path: Any) -> None:
        from swarmline.commands.loader import auto_discover_commands

        (tmp_path / "deploy.yaml").write_text(
            "name: deploy\ndescription: Deploy\ncategory: admin\n"
        )
        (tmp_path / "status.yml").write_text(
            "name: status\ndescription: Status\ncategory: ops\n"
        )

        reg = CommandRegistry()
        count = auto_discover_commands(reg, tmp_path)
        assert count == 2
        assert reg.resolve("deploy") is not None
        assert reg.resolve("status") is not None

    async def test_auto_discover_with_handler_registry(self, tmp_path: Any) -> None:
        from swarmline.commands.loader import auto_discover_commands

        (tmp_path / "greet.yaml").write_text("name: greet\ndescription: Say hi\n")

        async def greet_handler(**kw: Any) -> str:
            return "hi!"

        reg = CommandRegistry()
        count = auto_discover_commands(
            reg, tmp_path, handler_registry={"greet": greet_handler}
        )
        assert count == 1
        result = await reg.execute("greet")
        assert result == "hi!"

    async def test_auto_discover_noop_handler_when_no_registry(
        self, tmp_path: Any
    ) -> None:
        from swarmline.commands.loader import auto_discover_commands

        (tmp_path / "noop.yaml").write_text("name: noop_cmd\ndescription: No handler\n")

        reg = CommandRegistry()
        auto_discover_commands(reg, tmp_path)
        result = await reg.execute("noop.cmd")
        assert "executed" in result.lower() or "no handler" in result.lower()
