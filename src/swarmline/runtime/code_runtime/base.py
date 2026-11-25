"""BaseCodeRuntimeAdapter — shared logic for all CodeRuntimePort adapters.

Subclasses override: _sdk_module_name, _session_prefix, _provider_name,
_sdk_capabilities, and _execute_sdk_impl.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from swarmline.code_runtime_types import (
    CodeRuntimeCapabilities,
    CodeRuntimeConfig,
    CodeRuntimeEvent,
    CodeRuntimeSession,
    CodeSessionStatus,
)

logger = logging.getLogger(__name__)


class BaseCodeRuntimeAdapter:
    """Base adapter implementing CodeRuntimePort common logic.

    Handles: session lifecycle, validation, terminate idempotency,
    SDK detection, CLI fallback stub. Subclasses provide provider-specific
    capability profiles and SDK execution.
    """

    _sdk_module_name: str = ""
    _session_prefix: str = "runtime"
    _provider_name: str = "unknown"
    _sdk_caps: dict[str, bool] = {}

    def __init__(self) -> None:
        self._sdk_available = self._detect_sdk()
        self._sessions: dict[str, CodeRuntimeSession] = {}
        self._terminated: set[str] = set()
        self._configs: dict[str, CodeRuntimeConfig] = {}

    def _detect_sdk(self) -> bool:
        """Check if provider SDK is importable."""
        if not self._sdk_module_name:
            return False
        try:
            __import__(self._sdk_module_name)
            return True
        except ImportError:
            return False

    async def create_session(self, config: CodeRuntimeConfig) -> CodeRuntimeSession:
        """Create a coding session. Returns frozen session snapshot."""
        sid = f"{self._session_prefix}-{uuid.uuid4().hex[:12]}"
        caps = self._build_capabilities(config)
        session = CodeRuntimeSession(
            session_id=sid,
            provider=config.provider,
            status=CodeSessionStatus.CREATED,
            capabilities=caps,
            created_at=datetime.now(UTC),
        )
        self._sessions[sid] = session
        self._configs[sid] = config
        logger.info(
            "%s session created: %s (mode=%s)", self._provider_name, sid, caps.mode
        )
        return session

    async def execute(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[CodeRuntimeEvent]:
        """Execute a coding task, yielding CodeRuntimeEvent stream."""
        if session_id in self._terminated:
            raise RuntimeError(f"Session {session_id} is terminated")
        if session_id not in self._sessions:
            raise ValueError(f"Unknown session: {session_id}")
        if not prompt.strip():
            raise ValueError("Prompt must not be empty")

        if self._sdk_available:
            async for event in self._execute_sdk_stub(session_id, prompt):
                yield event
        else:
            async for event in self._execute_cli_stub(session_id, prompt):
                yield event

    def get_capabilities(self) -> CodeRuntimeCapabilities:
        """Return capabilities based on current mode (sdk/cli)."""
        return self._make_capabilities(
            provider=self._provider_name,
            config_sandbox=True,
        )

    async def terminate_session(self, session_id: str) -> None:
        """Terminate a coding session. Idempotent for already-terminated sessions."""
        if session_id not in self._sessions and session_id not in self._terminated:
            raise ValueError(f"Unknown session: {session_id}")
        self._sessions.pop(session_id, None)
        self._configs.pop(session_id, None)
        self._terminated.add(session_id)
        logger.info("%s session terminated: %s", self._provider_name, session_id)

    # -- private helpers --------------------------------------------------

    def _build_capabilities(self, config: CodeRuntimeConfig) -> CodeRuntimeCapabilities:
        """Build session-level capabilities from config and mode."""
        return self._make_capabilities(
            provider=config.provider,
            config_sandbox=config.sandbox,
        )

    def _make_capabilities(
        self, provider: str, config_sandbox: bool
    ) -> CodeRuntimeCapabilities:
        """Build capabilities from mode and provider-specific flags."""
        if self._sdk_available:
            return CodeRuntimeCapabilities(
                provider=provider,
                mode="sdk",
                approvals=self._sdk_caps.get("approvals", False),
                subagents=self._sdk_caps.get("subagents", False),
                hooks=self._sdk_caps.get("hooks", False),
                worktrees=self._sdk_caps.get("worktrees", False),
                session_persistence=self._sdk_caps.get("session_persistence", False),
                sandbox=config_sandbox,
            )
        return CodeRuntimeCapabilities(
            provider=provider,
            mode="cli",
            approvals=False,
            subagents=False,
            hooks=False,
            worktrees=False,
            session_persistence=False,
            sandbox=config_sandbox,
        )

    async def _execute_sdk_stub(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[CodeRuntimeEvent]:
        """SDK stub: yields deterministic events. Real SDK integration in future phase."""
        yield CodeRuntimeEvent.status(f"Connecting to {self._provider_name} SDK")
        yield CodeRuntimeEvent.delta(f"Processing: {prompt[:50]}")
        yield CodeRuntimeEvent.tool_use("write_file", {"path": "main.py"})
        yield CodeRuntimeEvent.tool_result(
            "write_file", ok=True, summary="File written"
        )
        yield CodeRuntimeEvent.final(text="Done", session_id=session_id)

    async def _execute_cli_stub(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[CodeRuntimeEvent]:
        """CLI fallback: deterministic stub events for testing."""
        yield CodeRuntimeEvent.status("CLI mode: executing task")
        yield CodeRuntimeEvent.delta(f"Processing: {prompt[:50]}")
        yield CodeRuntimeEvent.final(
            text="CLI execution complete", session_id=session_id
        )
