"""A2A protocol core types — AgentCard, Task, Message, Artifact, Part.

Follows the A2A specification (Google, 2024-2025).
All types are Pydantic models for JSON serialization/deserialization.

Reference: https://google.github.io/A2A/
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskState(str, enum.Enum):
    """A2A Task lifecycle states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class PartType(str, enum.Enum):
    """A2A Message Part types."""

    TEXT = "text"
    DATA = "data"
    FILE = "file"


# ---------------------------------------------------------------------------
# Parts (message content blocks)
# ---------------------------------------------------------------------------


class TextPart(BaseModel):
    """Plain text content."""

    type: str = Field(default="text", frozen=True)
    text: str


class DataPart(BaseModel):
    """Structured data content (JSON-serializable)."""

    type: str = Field(default="data", frozen=True)
    data: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class FilePart(BaseModel):
    """File reference or inline content."""

    type: str = Field(default="file", frozen=True)
    file: FileContent


class FileContent(BaseModel):
    """File content — either inline bytes or URI reference."""

    name: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    bytes: str | None = None  # base64-encoded
    uri: str | None = None

    model_config = {"populate_by_name": True}


# Union type for parts
Part = TextPart | DataPart | FilePart


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class Message(BaseModel):
    """A2A Message — a single turn in a conversation.

    role: "user" (caller) or "agent" (callee)
    parts: list of TextPart, DataPart, or FilePart
    """

    role: str = Field(description="Message role: 'user' or 'agent'")
    parts: list[Part] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


class Artifact(BaseModel):
    """A2A Artifact — output produced by an agent task.

    Artifacts are distinct from messages: messages are conversational,
    artifacts are deliverables (files, data, generated content).
    """

    name: str | None = None
    description: str | None = None
    parts: list[Part] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    index: int = 0


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class TaskStatus(BaseModel):
    """Current status of a task with optional message."""

    state: TaskState = TaskState.SUBMITTED
    message: Message | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class Task(BaseModel):
    """A2A Task — unit of work between agents.

    Lifecycle: submitted → working → completed/failed/canceled
    May transition to input-required if agent needs more info.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = Field(default_factory=TaskStatus)
    messages: list[Message] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = Field(default=None, alias="sessionId")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# AgentCard
# ---------------------------------------------------------------------------


class AgentSkill(BaseModel):
    """A skill advertised by an A2A agent."""

    id: str
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class AgentCapabilities(BaseModel):
    """Capabilities advertised by an A2A agent."""

    streaming: bool = False
    push_notifications: bool = Field(default=False, alias="pushNotifications")
    state_transition_history: bool = Field(
        default=False, alias="stateTransitionHistory"
    )

    model_config = {"populate_by_name": True}


class AgentCard(BaseModel):
    """A2A Agent Card — discoverable at /.well-known/agent.json.

    Describes an agent's identity, capabilities, and skills.
    """

    name: str
    description: str | None = None
    url: str  # base URL of the A2A server
    version: str = "1.0"
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = Field(default_factory=list)
    default_input_modes: list[str] = Field(
        default_factory=lambda: ["text"], alias="defaultInputModes"
    )
    default_output_modes: list[str] = Field(
        default_factory=lambda: ["text"], alias="defaultOutputModes"
    )
    provider: AgentProvider | None = None
    documentation_url: str | None = Field(default=None, alias="documentationUrl")
    authentication: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class AgentProvider(BaseModel):
    """Provider information for an A2A agent."""

    organization: str
    url: str | None = None


# ---------------------------------------------------------------------------
# JSON-RPC wrappers (A2A uses JSON-RPC 2.0 over HTTP)
# ---------------------------------------------------------------------------


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request."""

    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response."""

    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: Any = None
    error: JsonRpcError | None = None


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 error."""

    code: int
    message: str
    data: Any = None


# ---------------------------------------------------------------------------
# Task event (for SSE streaming)
# ---------------------------------------------------------------------------


class TaskStatusUpdateEvent(BaseModel):
    """SSE event: task status changed."""

    id: str  # task id
    status: TaskStatus
    final: bool = False


class TaskArtifactUpdateEvent(BaseModel):
    """SSE event: new artifact produced."""

    id: str  # task id
    artifact: Artifact
