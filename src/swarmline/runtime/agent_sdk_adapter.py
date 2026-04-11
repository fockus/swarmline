"""AgentSDKAdapter — HostAdapter implementation via Claude Agent SDK."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from swarmline.multi_agent.graph_types import LifecycleMode
from swarmline.protocols.host_adapter import AgentAuthority, AgentHandle, AgentHandleStatus
from swarmline.runtime.model_registry import get_registry

_log = structlog.get_logger(component="agent_sdk_adapter")


class AgentSDKAdapter:
    """HostAdapter implementation using Claude Agent SDK (claude-agent-sdk).

    Lazy-imports claude-agent-sdk to avoid hard dependency.
    Uses ModelRegistry for model name resolution.
    """

    def __init__(self, default_model: str = "opus") -> None:
        self._default_model = default_model
        self._sessions: dict[str, Any] = {}  # agent_id -> SDK session
        self._statuses: dict[str, str] = {}  # agent_id -> status

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
        """Spawn a Claude agent via Agent SDK."""
        try:
            from claude_code_sdk import (  # type: ignore[import-not-found,import-untyped]  # noqa: F401
                Agent,
                AgentOptions,
            )
        except ImportError:
            raise RuntimeError(
                "claude-agent-sdk not installed. Run: pip install swarmline[claude]"
            ) from None

        resolved_model = get_registry().resolve(model or self._default_model)
        agent_id = f"claude-{role}-{uuid.uuid4().hex[:8]}"

        # Store session config (actual SDK session created on send_task)
        self._sessions[agent_id] = {
            "model": resolved_model,
            "system_prompt": system_prompt or f"You are a {role} agent. Goal: {goal}",
            "tools": tools,
            "goal": goal,
            "lifecycle": lifecycle,
        }
        self._statuses[agent_id] = AgentHandleStatus.IDLE

        _log.info("agent_spawned", agent_id=agent_id, role=role, model=resolved_model)

        return AgentHandle(
            id=agent_id,
            role=role,
            lifecycle=lifecycle,
            metadata={"model": resolved_model, "goal": goal},
        )

    async def send_task(self, handle: AgentHandle, task: str) -> str:
        """Send a task to a Claude agent and return response."""
        session = self._sessions.get(handle.id)
        if session is None:
            raise ValueError(f"Agent '{handle.id}' not found or already stopped")

        self._statuses[handle.id] = AgentHandleStatus.RUNNING

        try:
            from claude_code_sdk import (  # type: ignore[import-not-found,import-untyped]
                Agent,
                AgentOptions,
            )

            agent = Agent(
                model=session["model"],
                system_prompt=session["system_prompt"],
                options=AgentOptions(max_turns=25),
            )

            # Collect response
            result_parts: list[str] = []
            async for event in agent.run(task):
                if hasattr(event, "text") and event.text:
                    result_parts.append(event.text)

            result = "".join(result_parts) or "(no response)"

        except ImportError:
            raise RuntimeError(
                "claude-agent-sdk not installed. Run: pip install swarmline[claude]"
            ) from None
        except Exception as exc:
            self._statuses[handle.id] = AgentHandleStatus.FAILED
            _log.error("agent_task_failed", agent_id=handle.id, error=str(exc))
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
        """Stop and clean up an agent."""
        self._sessions.pop(handle.id, None)
        self._statuses[handle.id] = AgentHandleStatus.STOPPED
        _log.info("agent_stopped", agent_id=handle.id)

    async def get_status(self, handle: AgentHandle) -> str:
        """Get current agent status."""
        return self._statuses.get(handle.id, AgentHandleStatus.STOPPED)
