"""Tests for Swarmline CLI commands."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from swarmline.cli._app import cli
from swarmline.cli._output import format_output


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Help output
# ---------------------------------------------------------------------------


class TestCLIHelp:
    def test_main_help_shows_group_name(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Swarmline" in result.output

    def test_memory_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["memory", "--help"])
        assert result.exit_code == 0
        assert "memory" in result.output.lower()

    def test_plan_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["plan", "--help"])
        assert result.exit_code == 0
        assert "plan" in result.output.lower()

    def test_team_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["team", "--help"])
        assert result.exit_code == 0
        assert "team" in result.output.lower()

    def test_agent_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "--help"])
        assert result.exit_code == 0
        assert "agent" in result.output.lower()

    def test_run_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "timeout" in result.output.lower()

    def test_mcp_serve_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["mcp-serve", "--help"])
        assert result.exit_code == 0
        assert "mode" in result.output.lower()


# ---------------------------------------------------------------------------
# Memory commands
# ---------------------------------------------------------------------------


class TestMemoryCommands:
    def test_upsert_fact_returns_ok(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["memory", "upsert", "user1", "key1", "value1"])
        assert result.exit_code == 0
        assert "upserted" in result.output or "key1" in result.output

    def test_get_facts_empty_returns_ok(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["memory", "get", "user1"])
        assert result.exit_code == 0

    def test_messages_empty_returns_ok(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["memory", "messages", "user1", "topic1"])
        assert result.exit_code == 0

    def test_upsert_with_topic(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["memory", "upsert", "user1", "k", "v", "--topic-id", "t1"]
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Plan commands
# ---------------------------------------------------------------------------


class TestPlanCommands:
    def test_create_plan_with_steps(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["plan", "create", "Test goal", "--steps", "Step 1", "--steps", "Step 2"],
        )
        assert result.exit_code == 0
        assert "Test goal" in result.output or "plan-" in result.output

    def test_list_plans_empty(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["plan", "list"])
        assert result.exit_code == 0

    def test_get_plan_not_found(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["plan", "get", "plan-nonexistent"])
        assert (
            result.exit_code != 0
            or "not found" in result.output.lower()
            or "Error" in result.output
        )

    def test_approve_plan_not_found(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["plan", "approve", "plan-nonexistent"])
        assert "not found" in result.output.lower() or "Error" in result.output

    def test_step_requires_status(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["plan", "step", "plan-1", "step-1"])
        assert result.exit_code != 0  # missing --status


# ---------------------------------------------------------------------------
# Team commands
# ---------------------------------------------------------------------------


class TestTeamCommands:
    def test_register_agent_returns_ok(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["team", "register", "agent-1", "Test Agent", "researcher"]
        )
        assert result.exit_code == 0
        assert "agent-1" in result.output

    def test_list_agents_empty(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["team", "agents"])
        assert result.exit_code == 0

    def test_create_task_returns_ok(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["team", "task", "task-1", "Do something"])
        assert result.exit_code == 0
        assert "task-1" in result.output

    def test_claim_no_tasks(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["team", "claim"])
        # No tasks to claim -- should report error
        assert "No tasks" in result.output or "Error" in result.output

    def test_list_tasks_empty(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["team", "tasks"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Run command
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_run_simple_code(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["run", "print(42)"])
        assert result.exit_code == 0
        assert "42" in result.output

    def test_run_with_timeout_option(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["run", "--timeout", "5", "print('hello')"])
        assert result.exit_code == 0
        assert "hello" in result.output


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_json_format_memory_upsert(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["--format", "json", "memory", "upsert", "u1", "k1", "v1"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True

    def test_json_format_team_agents(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--format", "json", "team", "agents"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert isinstance(data["data"], list)

    def test_json_format_plan_list(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--format", "json", "plan", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True


# ---------------------------------------------------------------------------
# Output formatter unit tests
# ---------------------------------------------------------------------------


class TestFormatOutput:
    def test_format_json_explicit(self) -> None:
        data = {"ok": True, "data": {"key": "val"}}
        out = format_output(data, "json")
        parsed = json.loads(out)
        assert parsed["ok"] is True

    def test_format_error_text(self) -> None:
        data = {"ok": False, "error": "boom"}
        out = format_output(data, "text")
        assert "Error: boom" in out

    def test_format_none_data(self) -> None:
        out = format_output({"ok": True}, "text")
        assert out == "OK"

    def test_format_string_data(self) -> None:
        out = format_output({"ok": True, "data": "hello"}, "text")
        assert out == "hello"

    def test_format_empty_list(self) -> None:
        out = format_output({"ok": True, "data": []}, "text")
        assert out == "(empty)"

    def test_format_list_of_dicts(self) -> None:
        out = format_output({"ok": True, "data": [{"a": 1}, {"b": 2}]}, "text")
        assert '"a": 1' in out
        assert '"b": 2' in out
