"""Tests for MCP StatefulSession."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.mcp._session import HeadlessModeError, StatefulSession, resolve_mode


class TestStatefulSessionInit:
    """Session initialization tests."""

    def test_headless_mode_creates_providers(self) -> None:
        session = StatefulSession(mode="headless")
        assert session.mode == "headless"
        assert session.memory is not None
        assert session.plan_store is not None
        assert session.agent_registry is not None
        assert session.task_queue is not None

    def test_full_mode_creates_providers(self) -> None:
        session = StatefulSession(mode="full")
        assert session.mode == "full"
        assert session.memory is not None

    def test_no_agents_initially(self) -> None:
        session = StatefulSession(mode="full")
        assert session.list_agents() == []


class TestHeadlessModeGuard:
    """Test headless mode restrictions."""

    def test_require_full_mode_raises_in_headless(self) -> None:
        session = StatefulSession(mode="headless")
        with pytest.raises(HeadlessModeError, match="requires full mode"):
            session.require_full_mode()

    def test_require_full_mode_ok_in_full(self) -> None:
        session = StatefulSession(mode="full")
        session.require_full_mode()  # should not raise

    @pytest.mark.asyncio
    async def test_create_agent_blocked_in_headless(self) -> None:
        session = StatefulSession(mode="headless")
        with pytest.raises(HeadlessModeError):
            await session.create_agent(system_prompt="test")

    @pytest.mark.asyncio
    async def test_query_agent_blocked_in_headless(self) -> None:
        session = StatefulSession(mode="headless")
        with pytest.raises(HeadlessModeError):
            await session.query_agent("fake-id", "test")


class TestAgentLifecycle:
    """Test agent creation and querying in full mode."""

    @pytest.mark.asyncio
    async def test_create_agent_returns_id(self) -> None:
        session = StatefulSession(mode="full")
        with patch("swarmline.agent.Agent") as mock_cls:
            mock_cls.return_value = MagicMock()
            agent_id = await session.create_agent(system_prompt="You are a helper")
            assert agent_id.startswith("agent-")
            assert len(agent_id) == 14  # "agent-" + 8 hex chars

    @pytest.mark.asyncio
    async def test_list_agents_after_create(self) -> None:
        session = StatefulSession(mode="full")
        with patch("swarmline.agent.Agent"):
            await session.create_agent(system_prompt="test", model="sonnet")
            agents = session.list_agents()
            assert len(agents) == 1
            assert agents[0]["model"] == "sonnet"

    @pytest.mark.asyncio
    async def test_query_agent_returns_result(self) -> None:
        session = StatefulSession(mode="full")
        mock_agent = AsyncMock()
        mock_result = MagicMock(ok=True, text="Hello!")
        mock_agent.query = AsyncMock(return_value=mock_result)

        with patch("swarmline.agent.Agent", return_value=mock_agent):
            agent_id = await session.create_agent(system_prompt="test")
            result = await session.query_agent(agent_id, "hi")
            assert result.text == "Hello!"

    @pytest.mark.asyncio
    async def test_query_unknown_agent_raises(self) -> None:
        session = StatefulSession(mode="full")
        with pytest.raises(KeyError, match="Agent not found"):
            await session.query_agent("nonexistent", "hi")


class TestCleanup:
    """Test session cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_clears_agents(self) -> None:
        session = StatefulSession(mode="full")
        mock_agent = AsyncMock()
        mock_agent.cleanup = AsyncMock()

        with patch("swarmline.agent.Agent", return_value=mock_agent):
            await session.create_agent(system_prompt="test")
            assert len(session.list_agents()) == 1

            await session.cleanup()
            assert len(session.list_agents()) == 0
            mock_agent.cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_handles_agent_error(self) -> None:
        session = StatefulSession(mode="full")
        mock_agent = AsyncMock()
        mock_agent.cleanup = AsyncMock(side_effect=RuntimeError("cleanup failed"))

        with patch("swarmline.agent.Agent", return_value=mock_agent):
            await session.create_agent(system_prompt="test")
            await session.cleanup()  # should not raise
            assert len(session.list_agents()) == 0


class TestResolveMode:
    """Test mode resolution logic."""

    def test_explicit_full(self) -> None:
        assert resolve_mode("full") == "full"

    def test_explicit_headless(self) -> None:
        assert resolve_mode("headless") == "headless"

    def test_auto_with_anthropic_key(self) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            assert resolve_mode("auto") == "full"

    def test_auto_with_openai_key(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            assert resolve_mode("auto") == "full"

    def test_auto_without_keys(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert resolve_mode("auto") == "headless"
