"""Unit: A2AServer — HTTP endpoints, routing, JSON-RPC dispatch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

starlette = pytest.importorskip("starlette")

from starlette.testclient import TestClient  # noqa: E402

from swarmline.a2a.adapter import SwarmlineA2AAdapter  # noqa: E402
from swarmline.a2a.server import A2AServer  # noqa: E402
from swarmline.a2a.types import (  # noqa: E402
    AgentSkill,
)
from swarmline.agent.result import Result  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_agent(text: str = "Hello from agent") -> MagicMock:
    agent = MagicMock()
    agent.query = AsyncMock(return_value=Result(text=text))
    return agent


def _make_server(agent: Any = None) -> tuple[A2AServer, TestClient]:
    if agent is None:
        agent = _mock_agent()
    adapter = SwarmlineA2AAdapter(
        agent,
        name="TestBot",
        url="http://localhost:8000",
        skills=[AgentSkill(id="test", name="Test Skill")],
    )
    server = A2AServer(adapter, allow_unauthenticated_local=True)
    client = TestClient(server.app)
    return server, client


def _rpc(method: str, params: dict[str, Any] | None = None, rpc_id: str = "1") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": method,
        "params": params or {},
    }


# ---------------------------------------------------------------------------
# Discovery: /.well-known/agent.json
# ---------------------------------------------------------------------------


class TestAgentCardEndpoint:

    def test_returns_agent_card(self) -> None:
        _, client = _make_server()
        resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "TestBot"
        assert data["url"] == "http://localhost:8000"

    def test_card_includes_skills(self) -> None:
        _, client = _make_server()
        data = client.get("/.well-known/agent.json").json()
        assert len(data["skills"]) == 1
        assert data["skills"][0]["id"] == "test"

    def test_card_includes_capabilities(self) -> None:
        _, client = _make_server()
        data = client.get("/.well-known/agent.json").json()
        assert data["capabilities"]["streaming"] is True


# ---------------------------------------------------------------------------
# tasks/send
# ---------------------------------------------------------------------------


class TestTasksSend:

    def test_send_task_returns_completed(self) -> None:
        _, client = _make_server()
        resp = client.post("/", json=_rpc("tasks/send", {
            "task": {
                "id": "t1",
                "messages": [{"role": "user", "parts": [{"type": "text", "text": "Hello"}]}],
            }
        }))
        assert resp.status_code == 200
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["result"]["status"]["state"] == "completed"

    def test_send_task_shorthand_message(self) -> None:
        _, client = _make_server()
        resp = client.post("/", json=_rpc("tasks/send", {
            "task": {"id": "t2", "message": "Hi there"}
        }))
        assert resp.status_code == 200
        assert resp.json()["result"]["status"]["state"] == "completed"

    def test_send_task_error_response(self) -> None:
        agent = MagicMock()
        agent.query = AsyncMock(return_value=Result(text="", error="Agent failed"))
        _, client = _make_server(agent)

        resp = client.post("/", json=_rpc("tasks/send", {
            "task": {"id": "t3", "message": "Hi"}
        }))
        assert resp.json()["result"]["status"]["state"] == "failed"


# ---------------------------------------------------------------------------
# tasks/get
# ---------------------------------------------------------------------------


class TestTasksGet:

    def test_get_existing_task(self) -> None:
        _, client = _make_server()
        # First send a task
        client.post("/", json=_rpc("tasks/send", {
            "task": {"id": "get-1", "message": "Hello"}
        }))
        # Then get it
        resp = client.post("/", json=_rpc("tasks/get", {"id": "get-1"}))
        assert resp.status_code == 200
        assert resp.json()["result"]["id"] == "get-1"

    def test_get_nonexistent_task(self) -> None:
        _, client = _make_server()
        resp = client.post("/", json=_rpc("tasks/get", {"id": "nope"}))
        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# tasks/cancel
# ---------------------------------------------------------------------------


class TestTasksCancel:

    def test_cancel_nonexistent_task(self) -> None:
        _, client = _make_server()
        resp = client.post("/", json=_rpc("tasks/cancel", {"id": "nope"}))
        assert resp.json()["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# Unknown method
# ---------------------------------------------------------------------------


class TestUnknownMethod:

    def test_unknown_method_returns_error(self) -> None:
        _, client = _make_server()
        resp = client.post("/", json=_rpc("unknown/method"))
        body = resp.json()
        assert body["error"]["code"] == -32601
        assert "not found" in body["error"]["message"].lower()

    def test_invalid_json_returns_parse_error(self) -> None:
        _, client = _make_server()
        resp = client.post("/", content=b"not json", headers={"content-type": "application/json"})
        body = resp.json()
        assert body["error"]["code"] == -32700
