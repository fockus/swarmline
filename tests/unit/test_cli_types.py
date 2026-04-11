"""Unit tests for CliConfig domain type."""

from __future__ import annotations

import dataclasses

import pytest


class TestCliConfig:
    """CliConfig frozen dataclass tests."""

    def test_cli_config_frozen_cannot_mutate(self) -> None:
        """CliConfig is frozen — mutation raises FrozenInstanceError."""
        from swarmline.runtime.cli.types import CliConfig

        cfg = CliConfig(command=["claude", "--print", "-"])
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.command = ["other"]  # type: ignore[misc]

    def test_cli_config_defaults_timeout(self) -> None:
        """Default timeout is 300 seconds."""
        from swarmline.runtime.cli.types import CliConfig

        cfg = CliConfig(command=["claude"])
        assert cfg.timeout_seconds == 300.0

    def test_cli_config_defaults_max_output(self) -> None:
        """Default max_output_bytes is 4MB."""
        from swarmline.runtime.cli.types import CliConfig

        cfg = CliConfig(command=["claude"])
        assert cfg.max_output_bytes == 4_000_000

    def test_cli_config_defaults_output_format(self) -> None:
        """Default output_format is stream-json."""
        from swarmline.runtime.cli.types import CliConfig

        cfg = CliConfig(command=["claude"])
        assert cfg.output_format == "stream-json"

    def test_cli_config_defaults_env_empty(self) -> None:
        """Default env is empty dict."""
        from swarmline.runtime.cli.types import CliConfig

        cfg = CliConfig(command=["claude"])
        assert cfg.env == {}

    def test_cli_config_defaults_host_env_redacted(self) -> None:
        from swarmline.runtime.cli.types import CliConfig

        cfg = CliConfig(command=["claude"])
        assert cfg.inherit_host_env is False
        assert "PATH" in cfg.env_allowlist

    def test_cli_config_custom_values(self) -> None:
        """CliConfig accepts custom values for all fields."""
        from swarmline.runtime.cli.types import CliConfig

        cfg = CliConfig(
            command=["my-agent", "--json"],
            output_format="json",
            timeout_seconds=60.0,
            max_output_bytes=1_000_000,
            env={"API_KEY": "test"},
            inherit_host_env=True,
            env_allowlist=frozenset({"PATH"}),
        )
        assert cfg.command == ["my-agent", "--json"]
        assert cfg.output_format == "json"
        assert cfg.timeout_seconds == 60.0
        assert cfg.max_output_bytes == 1_000_000
        assert cfg.env == {"API_KEY": "test"}
        assert cfg.inherit_host_env is True
        assert cfg.env_allowlist == frozenset({"PATH"})
