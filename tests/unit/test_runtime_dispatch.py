"""Tests for shared agent runtime dispatch helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_dispatch import stream_claude_one_shot


class _Factory:
    def validate_agent_config(self, config: AgentConfig) -> None:
        _ = config

    def resolve_agent_model(self, config: AgentConfig) -> str:
        return config.model


async def _failing_stream(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
    _ = (args, kwargs)
    raise RuntimeError(
        "upstream failed Authorization: Bearer claude-dispatch-secret-1234567890"
    )
    yield object()


class TestStreamClaudeOneShot:
    async def test_stream_error_redacts_secret_in_event_and_logs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        secret = "claude-dispatch-secret-1234567890"
        monkeypatch.setattr(
            "swarmline.runtime.sdk_query.stream_one_shot_query",
            _failing_stream,
        )

        caplog.set_level("ERROR", logger="swarmline.agent.runtime_dispatch")
        events = [
            event
            async for event in stream_claude_one_shot(
                "hi",
                AgentConfig(system_prompt="test", model="sonnet"),
                runtime_factory=_Factory(),
            )
        ]

        assert len(events) == 1
        assert events[0].type == "error"
        assert secret not in events[0].text
        assert "RuntimeError" in events[0].text
        assert secret not in caplog.text
