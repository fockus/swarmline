"""Unit: swarmline serve HTTP routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch

import pytest

from swarmline.serve.app import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_agent(text: str = "Hello!", error: str | None = None) -> MagicMock:
    agent = MagicMock()
    result = MagicMock()
    result.text = text
    result.ok = error is None
    result.error = error
    agent.query = AsyncMock(return_value=result)
    return agent


@pytest.fixture
def client():
    from starlette.testclient import TestClient

    agent = _mock_agent()
    app = create_app(agent)
    return TestClient(app), agent


@pytest.fixture
def open_query_client():
    from starlette.testclient import TestClient

    agent = _mock_agent()
    app = create_app(agent, allow_unauthenticated_query=True)
    return TestClient(app), agent


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:

    def test_health_returns_200(self, client) -> None:
        tc, _ = client
        resp = tc.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_json(self, client) -> None:
        tc, _ = client
        resp = tc.get("/v1/health")
        assert resp.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# Info
# ---------------------------------------------------------------------------


class TestInfo:

    def test_info_returns_200(self, client) -> None:
        tc, _ = client
        resp = tc.get("/v1/info")
        assert resp.status_code == 200

    def test_info_contains_version(self, client) -> None:
        tc, _ = client
        data = tc.get("/v1/info").json()
        assert "version" in data

    def test_info_excludes_query_when_closed(self, client) -> None:
        tc, _ = client
        data = tc.get("/v1/info").json()
        assert "/v1/query" not in data["endpoints"]


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


class TestQuery:

    def test_query_closed_by_default(self, client) -> None:
        tc, _ = client
        with patch("swarmline.serve.app._log") as mock_log:
            resp = tc.post("/v1/query", json={"prompt": "Hello"})
        assert resp.status_code == 404
        mock_log.warning.assert_called_once_with(
            "security_decision",
            event_name="security.http_query_denied",
            component="serve",
            decision="deny",
            reason="query_disabled",
            route="/v1/query",
            target="query",
        )

    def test_query_success(self, open_query_client) -> None:
        tc, agent = open_query_client
        resp = tc.post("/v1/query", json={"prompt": "Hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Hello!"
        assert data["ok"] is True

    def test_query_calls_agent(self, open_query_client) -> None:
        tc, agent = open_query_client
        tc.post("/v1/query", json={"prompt": "test prompt"})
        agent.query.assert_called_once_with("test prompt")

    def test_query_missing_prompt(self, open_query_client) -> None:
        tc, _ = open_query_client
        resp = tc.post("/v1/query", json={})
        assert resp.status_code == 400

    def test_query_empty_prompt(self, open_query_client) -> None:
        tc, _ = open_query_client
        resp = tc.post("/v1/query", json={"prompt": ""})
        assert resp.status_code == 400

    def test_query_agent_error(self) -> None:
        from starlette.testclient import TestClient

        agent = _mock_agent(error="LLM timeout")
        tc = TestClient(create_app(agent, allow_unauthenticated_query=True))
        resp = tc.post("/v1/query", json={"prompt": "Hello"})
        assert resp.status_code == 200  # HTTP 200, error in body
        data = resp.json()
        assert data["ok"] is False
        assert "timeout" in data["error"]

    def test_query_agent_exception(self) -> None:
        from starlette.testclient import TestClient

        agent = MagicMock()
        agent.query = AsyncMock(side_effect=RuntimeError("boom"))
        tc = TestClient(create_app(agent, allow_unauthenticated_query=True))
        resp = tc.post("/v1/query", json={"prompt": "Hello"})
        assert resp.status_code == 500
        assert "boom" in resp.json()["error"]


# ---------------------------------------------------------------------------
# Auth (optional Bearer token)
# ---------------------------------------------------------------------------


class TestAuth:

    def test_no_auth_by_default(self, client) -> None:
        tc, _ = client
        resp = tc.get("/v1/health")
        assert resp.status_code == 200

    def test_auth_required_rejects_no_token(self) -> None:
        from starlette.testclient import TestClient

        agent = _mock_agent()
        tc = TestClient(create_app(agent, auth_token="secret-123"))
        with patch("swarmline.serve.app._log") as mock_log:
            resp = tc.post("/v1/query", json={"prompt": "hi"})
        assert resp.status_code == 401
        mock_log.warning.assert_called_once_with(
            "security_decision",
            event_name="security.http_query_denied",
            component="serve",
            decision="deny",
            reason="missing_or_invalid_bearer_token",
            route="/v1/query",
            target="query",
        )

    def test_auth_accepts_valid_token(self) -> None:
        from starlette.testclient import TestClient

        agent = _mock_agent()
        tc = TestClient(create_app(agent, auth_token="secret-123"))
        resp = tc.post(
            "/v1/query",
            json={"prompt": "hi"},
            headers={"Authorization": "Bearer secret-123"},
        )
        assert resp.status_code == 200

    def test_health_bypasses_auth(self) -> None:
        from starlette.testclient import TestClient

        agent = _mock_agent()
        tc = TestClient(create_app(agent, auth_token="secret-123"))
        resp = tc.get("/v1/health")
        assert resp.status_code == 200
