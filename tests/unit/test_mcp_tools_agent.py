"""Tests for MCP agent tools (full mode)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.mcp._session import StatefulSession
from swarmline.mcp._tools_agent import agent_create, agent_list, agent_query


@pytest.fixture
def headless_session():
    return StatefulSession(mode="headless")


@pytest.fixture
def full_session():
    return StatefulSession(mode="full")


class TestAgentCreate:
    @pytest.mark.asyncio
    async def test_create_in_headless_returns_error(self, headless_session):
        result = await agent_create(headless_session, system_prompt="test")
        assert result["ok"] is False
        assert "full mode" in result["error"]

    @pytest.mark.asyncio
    async def test_create_in_full_returns_agent_id(self, full_session):
        with patch("swarmline.agent.Agent"):
            result = await agent_create(full_session, system_prompt="You are a helper")
            assert result["ok"] is True
            assert result["data"]["agent_id"].startswith("agent-")
            assert result["data"]["model"] == "sonnet"

    @pytest.mark.asyncio
    async def test_create_with_custom_model(self, full_session):
        with patch("swarmline.agent.Agent"):
            result = await agent_create(
                full_session, system_prompt="test", model="haiku"
            )
            assert result["data"]["model"] == "haiku"


class TestAgentQuery:
    @pytest.mark.asyncio
    async def test_query_in_headless_returns_error(self, headless_session):
        result = await agent_query(headless_session, "fake-id", "hi")
        assert result["ok"] is False
        assert "full mode" in result["error"]

    @pytest.mark.asyncio
    async def test_query_existing_agent(self, full_session):
        mock_agent = AsyncMock()
        mock_agent.query = AsyncMock(
            return_value=MagicMock(ok=True, text="Hello!", error=None)
        )
        with patch("swarmline.agent.Agent", return_value=mock_agent):
            aid = await agent_create(full_session, system_prompt="test")
            agent_id = aid["data"]["agent_id"]
            result = await agent_query(full_session, agent_id, "hi")
            assert result["ok"] is True
            assert result["data"]["text"] == "Hello!"

    @pytest.mark.asyncio
    async def test_query_nonexistent_agent(self, full_session):
        result = await agent_query(full_session, "nonexistent", "hi")
        assert result["ok"] is False
        assert "not found" in result["error"]


class TestAgentList:
    @pytest.mark.asyncio
    async def test_list_empty(self, full_session):
        result = await agent_list(full_session)
        assert result["ok"] is True
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_list_after_create(self, full_session):
        with patch("swarmline.agent.Agent"):
            await agent_create(full_session, system_prompt="test1")
            await agent_create(full_session, system_prompt="test2")
            result = await agent_list(full_session)
            assert result["ok"] is True
            assert len(result["data"]) == 2
