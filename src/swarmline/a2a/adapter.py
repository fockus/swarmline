"""SwarmlineA2AAdapter — wraps a Swarmline Agent as an A2A-compatible service.

Zero changes to core agent/ — pure adapter pattern.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from swarmline.a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Artifact,
    Message,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

logger = logging.getLogger(__name__)


class SwarmlineA2AAdapter:
    """Adapts a Swarmline Agent to the A2A protocol.

    Parameters
    ----------
    agent:
        A Swarmline Agent instance.
    name:
        Agent name for the AgentCard.
    description:
        Agent description for the AgentCard.
    url:
        Base URL where this agent's A2A server will be hosted.
    skills:
        List of AgentSkill objects to advertise.
    version:
        A2A card version string.
    """

    def __init__(
        self,
        agent: Any,
        *,
        name: str = "Swarmline Agent",
        description: str | None = None,
        url: str,
        skills: list[AgentSkill] | None = None,
        version: str = "1.0",
    ) -> None:
        self._agent = agent
        self._name = name
        self._description = description
        self._url = url.rstrip("/")
        self._skills = skills or []
        self._version = version
        self._tasks: dict[str, Task] = {}

    @property
    def agent_card(self) -> AgentCard:
        """Generate the AgentCard for discovery."""
        return AgentCard(
            name=self._name,
            description=self._description,
            url=self._url,
            version=self._version,
            capabilities=AgentCapabilities(streaming=True),
            skills=self._skills,
        )

    async def handle_task(self, task: Task) -> Task:
        """Process a task synchronously (non-streaming).

        1. Extracts user message text from task.messages
        2. Runs agent.query()
        3. Returns updated task with agent response
        """
        user_text = _extract_user_text(task)
        if not user_text:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role="agent",
                    parts=[TextPart(text="No user message found in task")],
                ),
            )
            return task

        self._tasks[task.id] = task
        task.status = TaskStatus(state=TaskState.WORKING)

        try:
            result = await self._agent.query(user_text)

            if result.ok:
                agent_message = Message(
                    role="agent",
                    parts=[TextPart(text=result.text)],
                )
                task.messages.append(agent_message)
                task.status = TaskStatus(
                    state=TaskState.COMPLETED,
                    message=agent_message,
                )

                if result.structured_output is not None:
                    task.artifacts.append(
                        Artifact(
                            name="structured_output",
                            parts=[TextPart(text=str(result.structured_output))],
                            metadata={"type": type(result.structured_output).__name__},
                        )
                    )
            else:
                task.status = TaskStatus(
                    state=TaskState.FAILED,
                    message=Message(
                        role="agent",
                        parts=[TextPart(text=result.error or "Unknown error")],
                    ),
                )
        except Exception as exc:
            logger.exception("A2A task processing failed")
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role="agent",
                    parts=[TextPart(text=f"Agent error: {exc}")],
                ),
            )

        return task

    async def handle_task_streaming(
        self, task: Task
    ) -> AsyncIterator[TaskStatusUpdateEvent]:
        """Process a task with SSE streaming.

        Yields TaskStatusUpdateEvent as the task progresses.
        """
        user_text = _extract_user_text(task)
        if not user_text:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role="agent",
                    parts=[TextPart(text="No user message found in task")],
                ),
            )
            yield TaskStatusUpdateEvent(id=task.id, status=task.status, final=True)
            return

        self._tasks[task.id] = task
        task.status = TaskStatus(state=TaskState.WORKING)
        yield TaskStatusUpdateEvent(id=task.id, status=task.status, final=False)

        try:
            collected_text = ""
            async for event in self._agent.stream(user_text):
                event_type = getattr(event, "type", "")
                if event_type == "text_delta":
                    collected_text += getattr(event, "text", "")
                elif event_type == "done" or getattr(event, "is_final", False):
                    final_text = (
                        getattr(event, "text", collected_text) or collected_text
                    )
                    agent_message = Message(
                        role="agent",
                        parts=[TextPart(text=final_text)],
                    )
                    task.messages.append(agent_message)
                    task.status = TaskStatus(
                        state=TaskState.COMPLETED,
                        message=agent_message,
                    )
                    yield TaskStatusUpdateEvent(
                        id=task.id, status=task.status, final=True
                    )
                    return

            # If stream ended without a final event
            if collected_text:
                agent_message = Message(
                    role="agent",
                    parts=[TextPart(text=collected_text)],
                )
                task.messages.append(agent_message)
                task.status = TaskStatus(
                    state=TaskState.COMPLETED,
                    message=agent_message,
                )
            else:
                task.status = TaskStatus(
                    state=TaskState.FAILED,
                    message=Message(
                        role="agent",
                        parts=[TextPart(text="No response from agent")],
                    ),
                )

            yield TaskStatusUpdateEvent(id=task.id, status=task.status, final=True)

        except Exception as exc:
            logger.exception("A2A streaming task failed")
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role="agent",
                    parts=[TextPart(text=f"Agent error: {exc}")],
                ),
            )
            yield TaskStatusUpdateEvent(id=task.id, status=task.status, final=True)

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a task by ID."""
        return self._tasks.get(task_id)

    async def cancel_task(self, task_id: str) -> Task | None:
        """Cancel a task."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.status.state in (
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELED,
        ):
            return task
        task.status = TaskStatus(state=TaskState.CANCELED)
        return task


def _extract_user_text(task: Task) -> str:
    """Extract text from the last user message in a task."""
    for msg in reversed(task.messages):
        if msg.role == "user":
            texts = [p.text for p in msg.parts if isinstance(p, TextPart)]
            if texts:
                return " ".join(texts)
    return ""
