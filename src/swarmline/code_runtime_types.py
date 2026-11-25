"""Pure domain types for Code Runtime — zero external/SDK dependencies.

Code Runtime types form the contract for coding agent runtimes
(Claude Code, Codex, etc.). Clean Architecture: no imports from
runtime/, infrastructure/, or any SDK (anthropic, openai).

Types:
- CodeRuntimeEventType: enum of event kinds
- CODE_RUNTIME_ERROR_KINDS: allowed error categories
- CodeRuntimeErrorData: frozen typed error
- CodeRuntimeEvent: frozen streaming event with factory methods
- CodeRuntimeCapabilities: frozen capability descriptor
- CodeSessionStatus: session lifecycle states
- CodeRuntimeSession: frozen session snapshot
- CodeRuntimeConfig: frozen configuration
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# CodeRuntimeEventType
# ---------------------------------------------------------------------------


class CodeRuntimeEventType(enum.Enum):
    """Event types emitted by a coding runtime."""

    status = "status"
    tool_use = "tool_use"
    tool_result = "tool_result"
    delta = "delta"
    error = "error"
    final = "final"


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------

CODE_RUNTIME_ERROR_KINDS: frozenset[str] = frozenset(
    {
        "provider_unavailable",
        "session_expired",
        "approval_timeout",
        "sandbox_violation",
        "capability_missing",
    }
)

_CODE_RUNTIME_ERROR_FALLBACK = "provider_unavailable"


@dataclass(frozen=True)
class CodeRuntimeErrorData:
    """Typed error from a coding runtime.

    If *kind* is not in CODE_RUNTIME_ERROR_KINDS, it falls back
    to ``provider_unavailable`` (same pattern as RuntimeErrorData).
    """

    kind: str
    message: str
    recoverable: bool = False
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.kind not in CODE_RUNTIME_ERROR_KINDS:
            object.__setattr__(self, "kind", _CODE_RUNTIME_ERROR_FALLBACK)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "message": self.message,
            "recoverable": self.recoverable,
        }
        if self.details is not None:
            d["details"] = self.details
        return d


# ---------------------------------------------------------------------------
# CodeRuntimeEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeRuntimeEvent:
    """Unified streaming event from a coding runtime.

    Factory methods create correctly-typed events.
    ``data`` is always a plain dict — no SDK types leak.
    """

    type: CodeRuntimeEventType
    data: dict[str, Any] = field(default_factory=dict)

    # -- factory methods ---------------------------------------------------

    @staticmethod
    def status(text: str) -> CodeRuntimeEvent:
        return CodeRuntimeEvent(type=CodeRuntimeEventType.status, data={"text": text})

    @staticmethod
    def tool_use(name: str, args: dict[str, Any] | None = None) -> CodeRuntimeEvent:
        return CodeRuntimeEvent(
            type=CodeRuntimeEventType.tool_use,
            data={"name": name, "args": args or {}},
        )

    @staticmethod
    def tool_result(name: str, ok: bool = True, summary: str = "") -> CodeRuntimeEvent:
        return CodeRuntimeEvent(
            type=CodeRuntimeEventType.tool_result,
            data={"name": name, "ok": ok, "summary": summary},
        )

    @staticmethod
    def delta(text: str) -> CodeRuntimeEvent:
        return CodeRuntimeEvent(type=CodeRuntimeEventType.delta, data={"text": text})

    @staticmethod
    def error(error: CodeRuntimeErrorData) -> CodeRuntimeEvent:
        return CodeRuntimeEvent(type=CodeRuntimeEventType.error, data=error.to_dict())

    @staticmethod
    def final(text: str, session_id: str | None = None) -> CodeRuntimeEvent:
        data: dict[str, Any] = {"text": text}
        if session_id is not None:
            data["session_id"] = session_id
        return CodeRuntimeEvent(type=CodeRuntimeEventType.final, data=data)

    # -- convenience properties --------------------------------------------

    @property
    def text(self) -> str:
        return self.data.get("text", "")

    @property
    def is_final(self) -> bool:
        return self.type == CodeRuntimeEventType.final

    @property
    def is_error(self) -> bool:
        return self.type == CodeRuntimeEventType.error

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "data": self.data}


# ---------------------------------------------------------------------------
# CodeRuntimeCapabilities
# ---------------------------------------------------------------------------

_CAPABILITY_FLAGS = frozenset(
    {"approvals", "subagents", "hooks", "worktrees", "session_persistence", "sandbox"}
)


@dataclass(frozen=True)
class CodeRuntimeCapabilities:
    """Describes what a coding runtime can do."""

    provider: str
    mode: str
    approvals: bool = False
    subagents: bool = False
    hooks: bool = False
    worktrees: bool = False
    session_persistence: bool = False
    sandbox: bool = False

    def supports(self, flag_name: str) -> bool:
        if flag_name not in _CAPABILITY_FLAGS:
            return False
        return bool(getattr(self, flag_name))

    def enabled_flags(self) -> frozenset[str]:
        return frozenset(f for f in _CAPABILITY_FLAGS if getattr(self, f))


# ---------------------------------------------------------------------------
# CodeSessionStatus + CodeRuntimeSession
# ---------------------------------------------------------------------------


class CodeSessionStatus(enum.Enum):
    """Lifecycle states of a coding session."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class CodeRuntimeSession:
    """Immutable snapshot of a coding session."""

    session_id: str
    provider: str
    status: CodeSessionStatus
    capabilities: CodeRuntimeCapabilities
    created_at: datetime


# ---------------------------------------------------------------------------
# CodeRuntimeConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeRuntimeConfig:
    """Configuration for creating a coding runtime session."""

    provider: str = "claude_code"
    model: str = "claude-sonnet-4-20250514"
    working_directory: str = "."
    approval_mode: str = "auto"
    sandbox: bool = True
    extra: dict[str, Any] = field(default_factory=dict)
