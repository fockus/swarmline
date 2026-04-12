"""ToolPolicy - access control for agent tools.

Strictly denies file/bash tools, allows only MCP tools from active skills
and explicitly listed local tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from swarmline.observability.logger import AgentLogger
    from swarmline.protocols import ToolIdCodec

_log = structlog.get_logger(component="tool_policy")


# Tools that are ALWAYS denied (file-system, shell, etc.)
# Includes BOTH naming variants: PascalCase (SDK) and snake_case (builtin)
ALWAYS_DENIED_TOOLS: frozenset[str] = frozenset(
    {
        # PascalCase (Claude SDK naming)
        "Bash",
        "Read",
        "Write",
        "Edit",
        "MultiEdit",
        "Glob",
        "Grep",
        "LS",
        "TodoRead",
        "TodoWrite",
        "WebFetch",
        "WebSearch",
        # snake_case (builtin canonical naming)
        "bash",
        "read",
        "write",
        "edit",
        "multi_edit",
        "glob",
        "grep",
        "ls",
        "todo_read",
        "todo_write",
        "web_fetch",
        "web_search",
    }
)


@dataclass(frozen=True)
class ToolPolicyInput:
    """Context used to decide tool access."""

    tool_name: str
    input_data: dict[str, Any]
    active_skill_ids: list[str]
    allowed_local_tools: set[str]


@dataclass(frozen=True)
class PermissionAllow:
    """Permission to invoke a tool."""

    updated_input: dict[str, Any] | None = None


@dataclass(frozen=True)
class PermissionDeny:
    """Permission denial for a tool call."""

    message: str = "Инструмент не разрешён текущей политикой"


class DefaultToolPolicy:
    """Tool access policy.

    Logic:
    1. If tool is in ALWAYS_DENIED -> deny
    2. If tool is in allowed_local_tools -> allow (including mcp__app_tools__*)
    3. If tool starts with "mcp__" and the MCP server is in active skills -> allow
    4. Otherwise -> deny
    """

    def __init__(
        self,
        extra_denied: set[str] | None = None,
        codec: ToolIdCodec | None = None,
        agent_logger: AgentLogger | None = None,
        allowed_system_tools: set[str] | None = None,
    ) -> None:
        self._allowed_system_tools = allowed_system_tools or set()
        # Whitelist: remove allowed system tools from the deny list
        base_denied = ALWAYS_DENIED_TOOLS - self._allowed_system_tools
        self._denied = base_denied | (extra_denied or set())
        if codec is None:
            from swarmline.policy.tool_id_codec import DefaultToolIdCodec

            codec = DefaultToolIdCodec()
        self._codec = codec
        self._agent_logger = agent_logger

    @property
    def allowed_system_tools(self) -> frozenset[str]:
        """Return the allowed system tools as an immutable set."""
        return frozenset(self._allowed_system_tools)

    def _log_policy(
        self,
        tool_name: str,
        allowed: bool,
        reason: str,
        server_id: str = "",
    ) -> None:
        """Log the policy decision (§6.2, §12.1)."""
        event = "tool_allowed" if allowed else "tool_denied"
        _log.info(event, tool_name=tool_name, reason=reason, server_id=server_id)
        if self._agent_logger:
            self._agent_logger.tool_policy_event(
                tool_name=tool_name,
                allowed=allowed,
                reason=reason,
                server_id=server_id,
            )

    def can_use_tool(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        state: ToolPolicyInput,
    ) -> PermissionAllow | PermissionDeny:
        """Check whether a tool call is allowed (§6.2: log allow/deny)."""
        # Step 1: hard deny list
        if tool_name in self._denied:
            self._log_policy(tool_name, allowed=False, reason="always_denied")
            return PermissionDeny(
                message=f"Инструмент '{tool_name}' запрещён политикой безопасности",
            )

        # Step 2: local tools (checked before MCP because local tools also use the mcp__ prefix)
        if tool_name in state.allowed_local_tools:
            self._log_policy(tool_name, allowed=True, reason="local_tool")
            return PermissionAllow(updated_input=input_data)

        # Step 2b: explicitly allowed system tools (for example WebSearch/WebFetch in the SDK).
        if tool_name in self._allowed_system_tools:
            self._log_policy(tool_name, allowed=True, reason="allowed_system_tool")
            return PermissionAllow(updated_input=input_data)

        # Step 3: MCP tools - check via ToolIdCodec
        if tool_name.startswith("mcp__"):
            server_name = self._codec.extract_server(tool_name)
            if server_name and server_name in state.active_skill_ids:
                self._log_policy(
                    tool_name,
                    allowed=True,
                    reason="mcp_active_skill",
                    server_id=server_name,
                )
                return PermissionAllow(updated_input=input_data)
            # MCP tool from an inactive skill
            self._log_policy(
                tool_name,
                allowed=False,
                reason="mcp_inactive_skill",
                server_id=server_name or "",
            )
            return PermissionDeny(
                message=f"MCP сервер '{server_name}' не активен для текущей роли",
            )

        # Step 4: everything else is denied
        self._log_policy(tool_name, allowed=False, reason="not_in_allowlist")
        return PermissionDeny(message=f"Инструмент '{tool_name}' не входит в allowlist")
