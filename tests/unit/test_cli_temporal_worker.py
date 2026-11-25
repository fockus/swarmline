"""Tests for the ``swarmline temporal-worker`` CLI command.

Only validation paths — actually serving requires a Temporal server.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from swarmline.cli._app import cli
from swarmline.cli._commands_temporal import _build_event_bus, _load_object


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestHelpers:
    def test_load_object_imports_module_attribute(self) -> None:
        assert _load_object("json:loads") is json.loads

    def test_load_object_rejects_malformed_path(self) -> None:
        import click

        with pytest.raises(click.BadParameter, match="package.module:attribute"):
            _load_object("no_colon_here")

    def test_load_object_rejects_missing_attribute(self) -> None:
        import click

        with pytest.raises(click.BadParameter, match="has no attribute"):
            _load_object("json:nope")

    def test_event_bus_rejects_unknown_scheme(self) -> None:
        import click

        with pytest.raises(click.BadParameter, match="redis:// or nats://"):
            _build_event_bus("http://not-a-bus")


class TestCommand:
    def test_listed_in_main_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "temporal-worker" in result.output

    def test_help_documents_options(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["temporal-worker", "--help"])
        assert result.exit_code == 0
        assert "--task-queue" in result.output
        assert "--require-approval" in result.output
        assert "--history-store" in result.output
        assert "--compaction-threshold" in result.output

    def test_unset_api_key_env_fails_fast(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["temporal-worker", "--api-key-env", "SWARMLINE_TEST_MISSING_KEY"],
            env={"SWARMLINE_TEST_MISSING_KEY": None},
        )
        assert result.exit_code != 0
        assert "SWARMLINE_TEST_MISSING_KEY" in result.output

    def test_non_dict_tools_fails_fast(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["temporal-worker", "--tools", "json:loads"])
        assert result.exit_code != 0
        assert "dict" in result.output
