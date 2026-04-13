"""Shared test fixtures for cognitive tests."""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.tools.sandbox_local import LocalSandboxProvider
from swarmline.tools.types import SandboxConfig


@pytest.fixture()
def coding_sandbox(tmp_path: Any) -> LocalSandboxProvider:
    """Create a real LocalSandboxProvider in a temp directory for coding tests."""
    config = SandboxConfig(
        root_path=str(tmp_path),
        user_id="test",
        topic_id="coding",
        max_file_size_bytes=1024,
        timeout_seconds=5,
        allow_host_execution=True,
    )
    return LocalSandboxProvider(config)


class FakeStreamEvent:
    """Minimal StreamEvent-like mock for unit/integration/e2e tests of Agent Facade."""

    def __init__(self, type: str = "done", text: str = "", **kwargs: Any) -> None:
        self.type = type
        self.text = text
        self.is_final = kwargs.get("is_final", False)
        self.session_id = kwargs.get("session_id")
        self.total_cost_usd = kwargs.get("total_cost_usd")
        self.usage = kwargs.get("usage")
        self.structured_output = kwargs.get("structured_output")
        self.native_metadata = kwargs.get("native_metadata")
        self.tool_name = kwargs.get("tool_name", "")
        self.tool_input = kwargs.get("tool_input")
        self.tool_result = kwargs.get("tool_result", "")
        self.allowed_decisions = kwargs.get("allowed_decisions")
        self.interrupt_id = kwargs.get("interrupt_id")
