"""Unit-tests for load_mcp_from_settings (§4.3, R-401)."""

from __future__ import annotations

import json
from pathlib import Path

from swarmline.skills.loader import load_mcp_from_settings


class TestLoadMcpFromSettings:
    """Tests zagruzki MCP from .claude/settings.json."""

    def test_no_settings_file(self, tmp_path: Path) -> None:
        """Nott filea -> empty result."""
        servers = load_mcp_from_settings(tmp_path)
        assert servers == {}

    def test_loads_from_project_settings(self, tmp_path: Path) -> None:
        """Loads servery from project-level settings."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {
            "mcpServers": {
                "iss": {"type": "url", "url": "https://example.com/iss/mcp"},
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(settings))

        servers = load_mcp_from_settings(tmp_path)
        assert "iss" in servers
        assert servers["iss"].url == "https://example.com/iss/mcp"
        assert servers["iss"].transport == "url"

    def test_local_overrides_project(self, tmp_path: Path) -> None:
        """settings.local.json overwrites settings.json."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        # project settings
        (claude_dir / "settings.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "iss": {"type": "url", "url": "https://prod.com/iss/mcp"},
                    }
                }
            )
        )
        # local overrides
        (claude_dir / "settings.local.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "iss": {"type": "url", "url": "https://dev.com/iss/mcp"},
                    }
                }
            )
        )

        servers = load_mcp_from_settings(tmp_path)
        assert servers["iss"].url == "https://dev.com/iss/mcp"

    def test_invalid_json_skipped(self, tmp_path: Path) -> None:
        """Invalid JSON is skipped without errors."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("NOT VALID JSON")

        servers = load_mcp_from_settings(tmp_path)
        assert servers == {}

    def test_no_mcp_servers_key(self, tmp_path: Path) -> None:
        """Nott klyucha mcpServers -> empty result."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(json.dumps({"other": "config"}))

        servers = load_mcp_from_settings(tmp_path)
        assert servers == {}

    def test_stdio_transport(self, tmp_path: Path) -> None:
        """Support stdio transport."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {
            "mcpServers": {
                "local": {
                    "type": "stdio",
                    "command": "python",
                    "args": ["-m", "my_server"],
                    "env": {"KEY": "val"},
                },
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(settings))

        servers = load_mcp_from_settings(tmp_path)
        assert "local" in servers
        assert servers["local"].transport == "stdio"
        assert servers["local"].command == "python"
        assert servers["local"].args == ["-m", "my_server"]
        assert servers["local"].env == {"KEY": "val"}
