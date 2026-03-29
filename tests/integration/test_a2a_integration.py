"""Integration: A2A server ↔ client full task lifecycle (in-process)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

starlette = pytest.importorskip("starlette")
httpx = pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from cognitia.a2a.adapter import CognitiaA2AAdapter  # noqa: E402
from cognitia.a2a.server import A2AServer  # noqa: E402
from cognitia.a2a.types import AgentSkill  # noqa: E402
from cognitia.agent.result import Result  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_agent(text: str = "I'm a helpful agent") -> MagicMock:
    agent = MagicMock()
    agent.query = AsyncMock(return_value=Result(text=text))
    return agent


def _make_stack(agent: Any = None) -> tuple[A2AServer, Any]:
    """Create A2A server with in-process ASGI transport for httpx."""
    if agent is None:
        agent = _mock_agent()
    adapter = CognitiaA2AAdapter(
        agent,
        name="IntegrationBot",
        url="http://testserver",
        skills=[AgentSkill(id="chat", name="Chat", description="General chat")],
    )
    server = A2AServer(adapter)
    transport = ASGITransport(app=server.app)
    return server, transport


# ---------------------------------------------------------------------------
# Full lifecycle: discover → send → get
# ---------------------------------------------------------------------------


class TestA2AFullLifecycle:
    """Full A2A lifecycle with in-process server and httpx client."""

    async def test_discover_returns_agent_card(self) -> None:
        """Client.discover() returns AgentCard from server."""
        _, transport = _make_stack()

        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            resp = await http.get("/.well-known/agent.json")
            assert resp.status_code == 200
            card = resp.json()
            assert card["name"] == "IntegrationBot"
            assert card["capabilities"]["streaming"] is True
            assert len(card["skills"]) == 1

    async def test_send_task_full_cycle(self) -> None:
        """Send a task via JSON-RPC → get completed result."""
        _, transport = _make_stack()

        rpc_send = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tasks/send",
            "params": {
                "task": {
                    "id": "integration-1",
                    "messages": [
                        {"role": "user", "parts": [{"type": "text", "text": "Hello A2A!"}]}
                    ],
                }
            },
        }

        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            # Send task
            resp = await http.post("/", json=rpc_send)
            assert resp.status_code == 200
            body = resp.json()
            assert body["result"]["status"]["state"] == "completed"
            assert body["result"]["id"] == "integration-1"

            # Get task by ID
            rpc_get = {
                "jsonrpc": "2.0",
                "id": "2",
                "method": "tasks/get",
                "params": {"id": "integration-1"},
            }
            resp2 = await http.post("/", json=rpc_get)
            assert resp2.status_code == 200
            assert resp2.json()["result"]["id"] == "integration-1"

    async def test_agent_query_called_with_user_text(self) -> None:
        """Server extracts user text and calls agent.query() with it."""
        agent = _mock_agent()
        _, transport = _make_stack(agent)

        rpc = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tasks/send",
            "params": {"task": {"id": "t1", "message": "What is A2A?"}},
        }

        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            await http.post("/", json=rpc)

        agent.query.assert_called_once_with("What is A2A?")

    async def test_failed_agent_returns_failed_task(self) -> None:
        """Agent error propagates as failed task status."""
        agent = MagicMock()
        agent.query = AsyncMock(return_value=Result(text="", error="LLM timeout"))
        _, transport = _make_stack(agent)

        rpc = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tasks/send",
            "params": {"task": {"id": "fail-1", "message": "Test"}},
        }

        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            resp = await http.post("/", json=rpc)
            body = resp.json()
            assert body["result"]["status"]["state"] == "failed"

    async def test_cancel_nonexistent_returns_error(self) -> None:
        """Cancel for unknown task returns JSON-RPC error."""
        _, transport = _make_stack()

        rpc = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tasks/cancel",
            "params": {"id": "no-such-task"},
        }

        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            resp = await http.post("/", json=rpc)
            body = resp.json()
            assert body["error"]["code"] == -32602


class TestA2ANoCoreDependencies:
    """A2A module doesn't modify core agent/ — pure adapter pattern."""

    def test_adapter_has_no_agent_import(self) -> None:
        """CognitiaA2AAdapter doesn't import from cognitia.agent.agent."""
        import inspect
        import cognitia.a2a.adapter as mod

        source = inspect.getsource(mod)
        assert "from cognitia.agent.agent import" not in source
        assert "from cognitia.agent import Agent" not in source

    def test_types_module_is_standalone(self) -> None:
        """a2a.types has no dependencies on cognitia.agent."""
        import inspect
        import cognitia.a2a.types as mod

        source = inspect.getsource(mod)
        assert "cognitia.agent" not in source
