"""A2A Client — discover and call remote A2A agents.

Uses httpx for HTTP communication and supports both synchronous
(tasks/send) and streaming (tasks/sendSubscribe via SSE) modes.

Requires: ``pip install swarmline[a2a]`` (httpx)
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from swarmline.a2a.types import (
    AgentCard,
    Message,
    Task,
    TaskStatusUpdateEvent,
    TextPart,
)

logger = logging.getLogger(__name__)


def _try_import_httpx() -> Any:
    """Lazy import httpx."""
    try:
        import httpx

        return httpx
    except ImportError:
        raise ImportError(
            "httpx is required for A2AClient. "
            "Install it with: pip install swarmline[a2a]"
        ) from None


class A2AClient:
    """Client for communicating with remote A2A agents.

    Parameters
    ----------
    url:
        Base URL of the A2A server (e.g. ``"http://localhost:8000"``).
    timeout:
        HTTP request timeout in seconds. Default: 30.
    """

    def __init__(self, url: str, *, timeout: float = 30.0) -> None:
        self._url = url.rstrip("/")
        self._timeout = timeout
        self._httpx: Any = None

    async def discover(self) -> AgentCard:
        """Fetch the agent's AgentCard from /.well-known/agent.json.

        Returns
        -------
        AgentCard
            The remote agent's capabilities and metadata.
        """
        httpx = _try_import_httpx()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(f"{self._url}/.well-known/agent.json")
            response.raise_for_status()
            return AgentCard(**response.json())

    async def send_task(
        self,
        message: str,
        *,
        task_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Send a task to the remote agent (non-streaming).

        Parameters
        ----------
        message:
            User message text.
        task_id:
            Optional task ID. Generated if not provided.
        session_id:
            Optional session ID for conversation continuity.
        metadata:
            Optional metadata dict attached to the task.

        Returns
        -------
        Task
            The completed (or failed) task with agent response.
        """
        httpx = _try_import_httpx()

        task_data: dict[str, Any] = {
            "id": task_id or str(uuid.uuid4()),
            "messages": [
                Message(role="user", parts=[TextPart(text=message)]).model_dump()
            ],
        }
        if session_id:
            task_data["sessionId"] = session_id
        if metadata:
            task_data["metadata"] = metadata

        rpc_request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/send",
            "params": {"task": task_data},
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._url}/", json=rpc_request)
            response.raise_for_status()
            body = response.json()

        if "error" in body and body["error"] is not None:
            error = body["error"]
            raise A2AClientError(
                f"RPC error {error.get('code', '?')}: {error.get('message', '?')}"
            )

        return Task(**body.get("result", {}))

    async def stream_task(
        self,
        message: str,
        *,
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[TaskStatusUpdateEvent]:
        """Send a task with SSE streaming.

        Parameters
        ----------
        message:
            User message text.
        task_id:
            Optional task ID.
        session_id:
            Optional session ID.

        Yields
        ------
        TaskStatusUpdateEvent
            Status updates as the task progresses.
        """
        httpx = _try_import_httpx()

        task_data = {
            "id": task_id or str(uuid.uuid4()),
            "messages": [
                Message(role="user", parts=[TextPart(text=message)]).model_dump()
            ],
        }
        if session_id:
            task_data["sessionId"] = session_id

        rpc_request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/sendSubscribe",
            "params": {"task": task_data},
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST", f"{self._url}/", json=rpc_request
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[len("data: "):]
                        try:
                            data = json.loads(data_str)
                            yield TaskStatusUpdateEvent(**data)
                        except (json.JSONDecodeError, Exception) as exc:
                            logger.warning("Failed to parse SSE event: %s", exc)

    async def get_task(self, task_id: str) -> Task:
        """Retrieve a task by ID.

        Parameters
        ----------
        task_id:
            The task ID to retrieve.

        Returns
        -------
        Task
            The task with current status.
        """
        httpx = _try_import_httpx()

        rpc_request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/get",
            "params": {"id": task_id},
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._url}/", json=rpc_request)
            response.raise_for_status()
            body = response.json()

        if "error" in body and body["error"] is not None:
            error = body["error"]
            raise A2AClientError(
                f"RPC error {error.get('code', '?')}: {error.get('message', '?')}"
            )

        return Task(**body.get("result", {}))

    async def cancel_task(self, task_id: str) -> Task:
        """Cancel a task.

        Parameters
        ----------
        task_id:
            The task ID to cancel.

        Returns
        -------
        Task
            The task with updated (canceled) status.
        """
        httpx = _try_import_httpx()

        rpc_request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/cancel",
            "params": {"id": task_id},
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._url}/", json=rpc_request)
            response.raise_for_status()
            body = response.json()

        if "error" in body and body["error"] is not None:
            error = body["error"]
            raise A2AClientError(
                f"RPC error {error.get('code', '?')}: {error.get('message', '?')}"
            )

        return Task(**body.get("result", {}))


class A2AClientError(Exception):
    """Error from an A2A remote agent."""
