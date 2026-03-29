"""Unit: A2A protocol types — serialization roundtrip, defaults, validation."""

from __future__ import annotations

import json


from cognitia.a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentProvider,
    AgentSkill,
    Artifact,
    DataPart,
    FileContent,
    FilePart,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    Message,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)


# ---------------------------------------------------------------------------
# TextPart / DataPart / FilePart
# ---------------------------------------------------------------------------


class TestParts:
    """Part types serialize and deserialize correctly."""

    def test_text_part_roundtrip(self) -> None:
        part = TextPart(text="Hello world")
        data = part.model_dump()
        assert data["type"] == "text"
        assert data["text"] == "Hello world"
        restored = TextPart(**data)
        assert restored.text == "Hello world"

    def test_data_part_roundtrip(self) -> None:
        part = DataPart(data={"key": "value"}, metadata={"source": "test"})
        data = part.model_dump()
        assert data["type"] == "data"
        assert data["data"] == {"key": "value"}
        restored = DataPart(**data)
        assert restored.data == {"key": "value"}

    def test_file_part_with_uri(self) -> None:
        part = FilePart(file=FileContent(name="doc.pdf", uri="https://example.com/doc.pdf"))
        data = part.model_dump()
        assert data["type"] == "file"
        assert data["file"]["name"] == "doc.pdf"
        assert data["file"]["uri"] == "https://example.com/doc.pdf"

    def test_file_part_with_bytes(self) -> None:
        part = FilePart(file=FileContent(name="img.png", bytes="aGVsbG8=", mime_type="image/png"))
        data = part.model_dump(by_alias=True)
        assert data["file"]["mimeType"] == "image/png"


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class TestMessage:
    """Message serialization and role handling."""

    def test_user_message(self) -> None:
        msg = Message(role="user", parts=[TextPart(text="Hi")])
        data = msg.model_dump()
        assert data["role"] == "user"
        assert len(data["parts"]) == 1

    def test_agent_message_with_metadata(self) -> None:
        msg = Message(
            role="agent",
            parts=[TextPart(text="Hello!")],
            metadata={"model": "sonnet"},
        )
        assert msg.metadata["model"] == "sonnet"

    def test_message_json_roundtrip(self) -> None:
        msg = Message(role="user", parts=[TextPart(text="Test")])
        json_str = msg.model_dump_json()
        restored = Message.model_validate_json(json_str)
        assert restored.role == "user"
        assert restored.parts[0].text == "Test"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Task and TaskStatus
# ---------------------------------------------------------------------------


class TestTask:
    """Task lifecycle and serialization."""

    def test_task_default_state(self) -> None:
        task = Task()
        assert task.status.state == TaskState.SUBMITTED
        assert task.id  # auto-generated UUID

    def test_task_state_transitions(self) -> None:
        task = Task()
        assert task.status.state == TaskState.SUBMITTED

        task.status = TaskStatus(state=TaskState.WORKING)
        assert task.status.state == TaskState.WORKING

        task.status = TaskStatus(state=TaskState.COMPLETED)
        assert task.status.state == TaskState.COMPLETED

    def test_task_with_messages_and_artifacts(self) -> None:
        task = Task(
            messages=[Message(role="user", parts=[TextPart(text="Hello")])],
            artifacts=[Artifact(name="output", parts=[TextPart(text="Result")])],
        )
        assert len(task.messages) == 1
        assert len(task.artifacts) == 1
        assert task.artifacts[0].name == "output"

    def test_task_json_roundtrip(self) -> None:
        task = Task(
            id="task-123",
            status=TaskStatus(state=TaskState.COMPLETED),
            messages=[Message(role="user", parts=[TextPart(text="Hi")])],
        )
        json_str = task.model_dump_json(by_alias=True)
        data = json.loads(json_str)
        assert data["id"] == "task-123"
        assert data["status"]["state"] == "completed"

    def test_task_all_states_are_strings(self) -> None:
        for state in TaskState:
            assert isinstance(state.value, str)

    def test_task_session_id_alias(self) -> None:
        task = Task(session_id="sess-1")
        data = task.model_dump(by_alias=True)
        assert data["sessionId"] == "sess-1"


# ---------------------------------------------------------------------------
# AgentCard
# ---------------------------------------------------------------------------


class TestAgentCard:
    """AgentCard serialization and discovery format."""

    def test_minimal_agent_card(self) -> None:
        card = AgentCard(name="TestAgent", url="http://localhost:8000")
        data = card.model_dump(by_alias=True, exclude_none=True)
        assert data["name"] == "TestAgent"
        assert data["url"] == "http://localhost:8000"
        assert data["version"] == "1.0"

    def test_agent_card_with_skills(self) -> None:
        card = AgentCard(
            name="ResearchBot",
            url="http://localhost:8000",
            skills=[
                AgentSkill(id="search", name="Web Search", description="Search the web"),
                AgentSkill(id="summarize", name="Summarize", tags=["nlp"]),
            ],
        )
        assert len(card.skills) == 2
        assert card.skills[0].id == "search"

    def test_agent_card_capabilities(self) -> None:
        card = AgentCard(
            name="StreamBot",
            url="http://localhost:8000",
            capabilities=AgentCapabilities(streaming=True),
        )
        data = card.model_dump(by_alias=True)
        assert data["capabilities"]["streaming"] is True

    def test_agent_card_with_provider(self) -> None:
        card = AgentCard(
            name="Bot",
            url="http://localhost:8000",
            provider=AgentProvider(organization="Cognitia Labs"),
        )
        data = card.model_dump(by_alias=True, exclude_none=True)
        assert data["provider"]["organization"] == "Cognitia Labs"

    def test_agent_card_json_roundtrip(self) -> None:
        card = AgentCard(
            name="Bot",
            url="http://localhost:8000",
            description="A helpful bot",
        )
        json_str = card.model_dump_json(by_alias=True, exclude_none=True)
        restored = AgentCard.model_validate_json(json_str)
        assert restored.name == "Bot"
        assert restored.url == "http://localhost:8000"


# ---------------------------------------------------------------------------
# JSON-RPC wrappers
# ---------------------------------------------------------------------------


class TestJsonRpc:
    """JSON-RPC 2.0 message types."""

    def test_request(self) -> None:
        req = JsonRpcRequest(method="tasks/send", params={"task": {"id": "1"}})
        data = req.model_dump()
        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "tasks/send"

    def test_response_success(self) -> None:
        resp = JsonRpcResponse(id="1", result={"status": "ok"})
        data = resp.model_dump()
        assert data["result"] == {"status": "ok"}
        assert data["error"] is None

    def test_response_error(self) -> None:
        resp = JsonRpcResponse(
            id="1", error=JsonRpcError(code=-32601, message="Method not found")
        )
        data = resp.model_dump()
        assert data["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# TaskStatusUpdateEvent (SSE)
# ---------------------------------------------------------------------------


class TestTaskStatusUpdateEvent:
    """SSE event serialization."""

    def test_working_event(self) -> None:
        event = TaskStatusUpdateEvent(
            id="task-1",
            status=TaskStatus(state=TaskState.WORKING),
            final=False,
        )
        data = event.model_dump()
        assert data["id"] == "task-1"
        assert data["status"]["state"] == "working"
        assert data["final"] is False

    def test_completed_event(self) -> None:
        event = TaskStatusUpdateEvent(
            id="task-1",
            status=TaskStatus(state=TaskState.COMPLETED),
            final=True,
        )
        assert event.final is True
