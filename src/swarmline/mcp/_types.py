"""Pydantic models for MCP tool input/output validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Generic output
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    """Standard response from all Swarmline MCP tools."""

    ok: bool = True
    data: Any = None
    error: str | None = None

    @classmethod
    def success(cls, data: Any = None) -> ToolResult:
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error: str) -> ToolResult:
        return cls(ok=False, error=error)


# ---------------------------------------------------------------------------
# Memory tool inputs
# ---------------------------------------------------------------------------


class UpsertFactInput(BaseModel):
    """Input for memory_upsert_fact tool."""

    user_id: str = Field(description="User/namespace identifier")
    key: str = Field(description="Fact key (unique within user)")
    value: str = Field(description="Fact value")
    topic_id: str | None = Field(default=None, description="Optional topic scope")


class GetFactsInput(BaseModel):
    """Input for memory_get_facts tool."""

    user_id: str = Field(description="User/namespace identifier")
    topic_id: str | None = Field(default=None, description="Optional topic scope")


class SaveMessageInput(BaseModel):
    """Input for memory_save_message tool."""

    user_id: str = Field(description="User/namespace identifier")
    topic_id: str = Field(description="Conversation topic ID")
    role: str = Field(description="Message role: user/assistant/system")
    content: str = Field(description="Message content")


class GetMessagesInput(BaseModel):
    """Input for memory_get_messages tool."""

    user_id: str = Field(description="User/namespace identifier")
    topic_id: str = Field(description="Conversation topic ID")
    limit: int = Field(default=10, description="Max messages to return", ge=1, le=100)


class SaveSummaryInput(BaseModel):
    """Input for memory_save_summary tool."""

    user_id: str = Field(description="User/namespace identifier")
    topic_id: str = Field(description="Conversation topic ID")
    summary: str = Field(description="Summary text")
    messages_covered: int = Field(default=0, description="Number of messages covered")


class GetSummaryInput(BaseModel):
    """Input for memory_get_summary tool."""

    user_id: str = Field(description="User/namespace identifier")
    topic_id: str = Field(description="Conversation topic ID")


# ---------------------------------------------------------------------------
# Plan tool inputs
# ---------------------------------------------------------------------------


class CreatePlanInput(BaseModel):
    """Input for plan_create tool."""

    goal: str = Field(description="Plan goal/objective")
    steps: list[str] = Field(description="List of step descriptions")
    user_id: str = Field(default="default", description="Namespace user ID")
    topic_id: str = Field(default="default", description="Namespace topic ID")


class GetPlanInput(BaseModel):
    """Input for plan_get tool."""

    plan_id: str = Field(description="Plan identifier")


class ListPlansInput(BaseModel):
    """Input for plan_list tool."""

    user_id: str = Field(default="default", description="Namespace user ID")
    topic_id: str = Field(default="default", description="Namespace topic ID")


class ApprovePlanInput(BaseModel):
    """Input for plan_approve tool."""

    plan_id: str = Field(description="Plan identifier")
    approved_by: str = Field(default="user", description="Approval source: user/system/agent")


class UpdateStepInput(BaseModel):
    """Input for plan_update_step tool."""

    plan_id: str = Field(description="Plan identifier")
    step_id: str = Field(description="Step identifier")
    status: str = Field(description="New status: pending/in_progress/completed/failed/skipped")
    result: str | None = Field(default=None, description="Step result or failure reason")


# ---------------------------------------------------------------------------
# Team tool inputs
# ---------------------------------------------------------------------------


class RegisterAgentInput(BaseModel):
    """Input for team_register_agent tool."""

    id: str = Field(description="Unique agent identifier")
    name: str = Field(description="Human-readable agent name")
    role: str = Field(description="Agent role (e.g., researcher, reviewer)")
    parent_id: str | None = Field(default=None, description="Parent agent ID for hierarchy")
    runtime_name: str = Field(default="thin", description="Runtime to use")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extra metadata")


class ListAgentsInput(BaseModel):
    """Input for team_list_agents tool."""

    role: str | None = Field(default=None, description="Filter by role")
    status: str | None = Field(default=None, description="Filter by status")


class CreateTaskInput(BaseModel):
    """Input for team_create_task tool."""

    id: str = Field(description="Unique task identifier")
    title: str = Field(description="Task title")
    description: str = Field(default="", description="Task description")
    priority: str = Field(default="MEDIUM", description="Priority: LOW/MEDIUM/HIGH/CRITICAL")
    assignee_agent_id: str | None = Field(default=None, description="Assign to specific agent")


class ClaimTaskInput(BaseModel):
    """Input for team_claim_task tool."""

    assignee_agent_id: str | None = Field(
        default=None, description="Agent claiming the task"
    )


class ListTasksInput(BaseModel):
    """Input for team_list_tasks tool."""

    status: str | None = Field(default=None, description="Filter by status")
    priority: str | None = Field(default=None, description="Filter by priority")
    assignee_agent_id: str | None = Field(default=None, description="Filter by assignee")


# ---------------------------------------------------------------------------
# Agent tool inputs (full mode only)
# ---------------------------------------------------------------------------


class CreateAgentInput(BaseModel):
    """Input for agent_create tool."""

    system_prompt: str = Field(description="Agent system prompt")
    model: str = Field(default="sonnet", description="Model alias")
    runtime: str = Field(default="thin", description="Runtime name")
    max_turns: int | None = Field(default=None, description="Max conversation turns")


class QueryAgentInput(BaseModel):
    """Input for agent_query tool."""

    agent_id: str = Field(description="Agent identifier")
    prompt: str = Field(description="User prompt to send")


class ListCreatedAgentsInput(BaseModel):
    """Input for agent_list tool."""

    pass


# ---------------------------------------------------------------------------
# Code execution input
# ---------------------------------------------------------------------------


class ExecCodeInput(BaseModel):
    """Input for exec_code tool."""

    code: str = Field(description="Python code to execute")
    timeout_seconds: int = Field(default=30, description="Execution timeout", ge=1, le=300)
