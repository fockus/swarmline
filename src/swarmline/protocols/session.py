"""Session protocols -- session lifecycle and management interfaces."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol

from swarmline.types import TurnContext


class SessionFactory(Protocol):
    """Port: SDK session creation (DIP for application AgentService)."""

    @property
    def last_prompt_hash(self) -> str: ...

    async def create(
        self,
        user_id: str,
        topic_id: str,
        role_id: str,
    ) -> Any | None: ...


class SessionLifecycle(Protocol):
    """Port: session lifecycle management (close/close_all).

    Extracted from SessionManager for ISP compliance (<=5 methods per Protocol).
    """

    async def close(self, key: Any) -> None: ...

    async def close_all(self) -> None: ...


class SessionManager(SessionLifecycle, Protocol):
    """Port: active session management.

    Inherits SessionLifecycle (close/close_all).
    Total: 4 own + 2 from SessionLifecycle = backward compatible.
    """

    def get(self, key: Any) -> Any | None: ...

    def register(self, state: Any) -> None: ...

    def stream_reply(
        self,
        key: Any,
        user_text: str,
    ) -> AsyncIterator[Any]: ...

    def run_turn(
        self,
        key: Any,
        *,
        messages: list[Any],
        system_prompt: str,
        active_tools: list[Any],
        mode_hint: str | None = None,
    ) -> AsyncIterator[Any]: ...


class SessionRehydrator(Protocol):
    """Port: session state rehydration."""

    async def build_rehydration_payload(
        self,
        ctx: TurnContext,
    ) -> Mapping[str, Any]: ...
