"""CodexAdapter — HostAdapter implementation via OpenAI SDK for Codex agents."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from swarmline.multi_agent.graph_types import LifecycleMode
from swarmline.protocols.host_adapter import AgentAuthority, AgentHandle, AgentHandleStatus
from swarmline.runtime.model_registry import get_registry

_log = structlog.get_logger(component="codex_adapter")


class CodexAdapter:
    """HostAdapter implementation using OpenAI SDK for Codex/GPT agents.

    Lazy-imports openai to avoid hard dependency.
    Uses ModelRegistry for model name resolution ("codex" → "codex-mini").
    """

    def __init__(self, default_model: str = "codex", api_key: str | None = None) -> None:
        self._default_model = default_model
        self._api_key = api_key
        self._sessions: dict[str, dict[str, Any]] = {}
        self._statuses: dict[str, str] = {}

    async def spawn_agent(
        self,
        role: str,
        goal: str,
        *,
        system_prompt: str = "",
        model: str | None = None,
        tools: tuple[str, ...] = (),
        skills: tuple[str, ...] = (),
        hooks: tuple[str, ...] = (),
        lifecycle: LifecycleMode = LifecycleMode.SUPERVISED,
        authority: AgentAuthority | None = None,
        timeout: float | None = None,
    ) -> AgentHandle:
        """Spawn a Codex/OpenAI agent."""
        resolved_model = get_registry().resolve(model or self._default_model)
        agent_id = f"codex-{role}-{uuid.uuid4().hex[:8]}"

        self._sessions[agent_id] = {
            "model": resolved_model,
            "system_prompt": system_prompt or f"You are a {role} agent. Goal: {goal}",
            "tools": tools,
            "goal": goal,
            "lifecycle": lifecycle,
            "messages": [],  # conversation history for multi-turn
        }
        self._statuses[agent_id] = AgentHandleStatus.IDLE

        _log.info("agent_spawned", agent_id=agent_id, role=role, model=resolved_model)

        return AgentHandle(
            id=agent_id,
            role=role,
            lifecycle=lifecycle,
            metadata={"model": resolved_model, "goal": goal, "provider": "openai"},
        )

    async def send_task(self, handle: AgentHandle, task: str) -> str:
        """Send a task to a Codex agent via OpenAI API."""
        session = self._sessions.get(handle.id)
        if session is None:
            raise ValueError(f"Agent '{handle.id}' not found or already stopped")

        self._statuses[handle.id] = AgentHandleStatus.RUNNING

        try:
            openai = __import__("openai")
        except ImportError:
            raise RuntimeError(
                "openai not installed. Run: pip install swarmline[openai-agents]"
            ) from None

        try:
            client = openai.AsyncOpenAI(api_key=self._api_key) if self._api_key else openai.AsyncOpenAI()

            messages = [
                {"role": "system", "content": session["system_prompt"]},
                *session["messages"],
                {"role": "user", "content": task},
            ]

            response = await client.chat.completions.create(
                model=session["model"],
                messages=messages,
            )

            result = response.choices[0].message.content or "(no response)"

            # Append to conversation for multi-turn
            session["messages"].append({"role": "user", "content": task})
            session["messages"].append({"role": "assistant", "content": result})

        except Exception as exc:
            self._statuses[handle.id] = AgentHandleStatus.FAILED
            _log.error("codex_task_failed", agent_id=handle.id, error=str(exc))
            raise

        # Lifecycle handling
        if handle.lifecycle == LifecycleMode.EPHEMERAL:
            self._statuses[handle.id] = AgentHandleStatus.COMPLETED
            del self._sessions[handle.id]
            _log.info("agent_self_terminated", agent_id=handle.id)
        else:
            self._statuses[handle.id] = AgentHandleStatus.IDLE

        return result

    async def stop_agent(self, handle: AgentHandle) -> None:
        """Stop and clean up a Codex agent."""
        self._sessions.pop(handle.id, None)
        self._statuses[handle.id] = AgentHandleStatus.STOPPED
        _log.info("agent_stopped", agent_id=handle.id)

    async def get_status(self, handle: AgentHandle) -> str:
        """Get current agent status."""
        return self._statuses.get(handle.id, AgentHandleStatus.STOPPED)
