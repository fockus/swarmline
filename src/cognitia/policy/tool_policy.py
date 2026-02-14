"""ToolPolicy — контроль доступа к инструментам агента.

Жёстко запрещает file/bash tools, разрешает только MCP tools из активных скилов
и явно перечисленные local tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from cognitia.observability.logger import AgentLogger
    from cognitia.protocols import ToolIdCodec

_log = structlog.get_logger(component="tool_policy")


# Инструменты, которые ВСЕГДА запрещены (file-system, shell, etc.)
# Содержит ОБА варианта именования: PascalCase (SDK) и snake_case (builtin)
ALWAYS_DENIED_TOOLS: frozenset[str] = frozenset(
    {
        # PascalCase (Claude SDK naming)
        "Bash", "Read", "Write", "Edit", "MultiEdit",
        "Glob", "Grep", "LS", "TodoRead", "TodoWrite",
        "WebFetch", "WebSearch",
        # snake_case (builtin canonical naming)
        "bash", "read", "write", "edit", "multi_edit",
        "glob", "grep", "ls", "todo_read", "todo_write",
        "web_fetch", "web_search",
    }
)


@dataclass(frozen=True)
class ToolPolicyInput:
    """Контекст для принятия решения о tool-доступе."""

    tool_name: str
    input_data: dict[str, Any]
    active_skill_ids: list[str]
    allowed_local_tools: set[str]


@dataclass(frozen=True)
class PermissionAllow:
    """Разрешение на вызов инструмента."""

    updated_input: dict[str, Any] | None = None


@dataclass(frozen=True)
class PermissionDeny:
    """Отказ в вызове инструмента."""

    message: str = "Инструмент не разрешён текущей политикой"


class DefaultToolPolicy:
    """Политика доступа к инструментам.

    Логика:
    1. Если tool в ALWAYS_DENIED → deny
    2. Если tool в allowed_local_tools → allow (включая mcp__app_tools__*)
    3. Если tool начинается с "mcp__" и MCP-сервер в активных скилах → allow
    4. Иначе → deny
    """

    def __init__(
        self,
        extra_denied: set[str] | None = None,
        codec: ToolIdCodec | None = None,
        agent_logger: AgentLogger | None = None,
        allowed_system_tools: set[str] | None = None,
    ) -> None:
        self._allowed_system_tools = allowed_system_tools or set()
        # Whitelist: убираем из deny-list разрешённые system tools
        base_denied = ALWAYS_DENIED_TOOLS - self._allowed_system_tools
        self._denied = base_denied | (extra_denied or set())
        if codec is None:
            from cognitia.policy.tool_id_codec import DefaultToolIdCodec

            codec = DefaultToolIdCodec()
        self._codec = codec
        self._agent_logger = agent_logger

    def _log_policy(
        self,
        tool_name: str,
        allowed: bool,
        reason: str,
        server_id: str = "",
    ) -> None:
        """Логировать решение политики (§6.2, §12.1)."""
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
        """Проверить, разрешён ли вызов инструмента (§6.2: логируем allow/deny)."""
        # Шаг 1: жёсткий deny-list
        if tool_name in self._denied:
            self._log_policy(tool_name, allowed=False, reason="always_denied")
            return PermissionDeny(
                message=f"Инструмент '{tool_name}' запрещён политикой безопасности",
            )

        # Шаг 2: local tools (проверяем до MCP, т.к. local tools тоже имеют mcp__ префикс)
        if tool_name in state.allowed_local_tools:
            self._log_policy(tool_name, allowed=True, reason="local_tool")
            return PermissionAllow(updated_input=input_data)

        # Шаг 2b: явно разрешённые system tools (например WebSearch/WebFetch в SDK).
        if tool_name in self._allowed_system_tools:
            self._log_policy(tool_name, allowed=True, reason="allowed_system_tool")
            return PermissionAllow(updated_input=input_data)

        # Шаг 3: MCP tools — проверяем через ToolIdCodec
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
            # MCP tool от неактивного скилa
            self._log_policy(
                tool_name,
                allowed=False,
                reason="mcp_inactive_skill",
                server_id=server_name or "",
            )
            return PermissionDeny(
                message=f"MCP сервер '{server_name}' не активен для текущей роли",
            )

        # Шаг 4: всё остальное запрещено
        self._log_policy(tool_name, allowed=False, reason="not_in_allowlist")
        return PermissionDeny(message=f"Инструмент '{tool_name}' не входит в allowlist")
