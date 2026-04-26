"""Integration: swarmline serve — HTTP client → agent end-to-end."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx

from swarmline.serve.app import create_app


def _mock_agent(responses: dict[str, str] | None = None) -> MagicMock:
    agent = MagicMock()
    _responses = responses or {"Hello": "Hi there!"}

    async def _query(prompt: str) -> MagicMock:
        result = MagicMock()
        result.text = _responses.get(prompt, "default")
        result.ok = True
        result.error = None
        return result

    agent.query = AsyncMock(side_effect=_query)
    return agent


class TestServeIntegration:
    async def test_health_via_httpx(self) -> None:
        agent = _mock_agent()
        app = create_app(agent)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    async def test_query_via_httpx(self) -> None:
        agent = _mock_agent({"What is 2+2?": "4"})
        app = create_app(agent, allow_unauthenticated_query=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/v1/query", json={"prompt": "What is 2+2?"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["text"] == "4"
            assert data["ok"] is True

    async def test_query_closed_by_default(self) -> None:
        agent = _mock_agent()
        app = create_app(agent)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/v1/query", json={"prompt": "hi"})
            assert resp.status_code == 404

    async def test_auth_flow(self) -> None:
        agent = _mock_agent()
        app = create_app(agent, auth_token="my-token")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Rejected without token
            resp = await client.post("/v1/query", json={"prompt": "hi"})
            assert resp.status_code == 401

            # Health is exempt
            resp = await client.get("/v1/health")
            assert resp.status_code == 200

            # Accepted with token
            resp = await client.post(
                "/v1/query",
                json={"prompt": "hi"},
                headers={"Authorization": "Bearer my-token"},
            )
            assert resp.status_code == 200

    async def test_multiple_queries(self) -> None:
        agent = _mock_agent({"q1": "a1", "q2": "a2"})
        app = create_app(agent, allow_unauthenticated_query=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.post("/v1/query", json={"prompt": "q1"})
            r2 = await client.post("/v1/query", json={"prompt": "q2"})
            assert r1.json()["text"] == "a1"
            assert r2.json()["text"] == "a2"
