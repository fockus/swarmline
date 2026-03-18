"""StructuredLogger — structured logging for the agent."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "info", fmt: str = "json") -> None:
    """Configure structlog + standard logging to stdout.

    Standard logging is needed because many modules (adapter, service, session_factory)
    use ``logging.getLogger(__name__)`` instead of structlog.
    Without basicConfig, their output is silently lost.
    """
    numeric_level = _level_to_int(level)

    # --- Standard logging (for logging.getLogger) ---
    logging.basicConfig(
        level=numeric_level,
        stream=sys.stdout,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,  # reconfigure even if basicConfig was already called
    )

    # --- structlog (for AgentLogger) ---
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if fmt == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class AgentLogger:
    """Agent event logger with a predefined schema."""

    def __init__(self, component: str = "cognitia") -> None:
        self._log = structlog.get_logger(component=component)

    def session_created(
        self,
        user_id: str,
        topic_id: str,
        role_id: str,
        is_rehydrated: bool = False,
    ) -> None:
        """Session creation/restoration."""
        self._log.info(
            "session_created",
            user_id=user_id,
            topic_id=topic_id,
            role_id=role_id,
            is_rehydrated=is_rehydrated,
        )

    def turn_start(
        self,
        user_id: str,
        topic_id: str,
        user_text_preview: str = "",
    ) -> None:
        """Start processing a message."""
        self._log.info(
            "turn_start",
            user_id=user_id,
            topic_id=topic_id,
            user_text_preview=user_text_preview[:50],
        )

    def tool_call(
        self,
        tool_name: str,
        latency_ms: int = 0,
        status: str = "ok",
        input_preview: str = "",
    ) -> None:
        """Tool invocation."""
        self._log.info(
            "tool_call",
            tool_name=tool_name,
            latency_ms=latency_ms,
            status=status,
            input_preview=input_preview[:100],
        )

    def turn_complete(
        self,
        user_id: str,
        topic_id: str,
        role_id: str,
        model: str = "",
        prompt_hash: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        context_budget_used: int = 0,
        context_budget_total: int = 8000,
        truncated_packs: list[str] | None = None,
        turn_latency_ms: int = 0,
    ) -> None:
        """Message processing completion (§12.1: includes prompt_hash).

        KISS: latency_ms is passed by the caller instead of being computed in the logger.
        """
        self._log.info(
            "turn_complete",
            user_id=user_id,
            topic_id=topic_id,
            role_id=role_id,
            model=model,
            prompt_hash=prompt_hash,
            turn_latency_ms=turn_latency_ms,
            tool_calls=tool_calls or [],
            context_budget={
                "total": context_budget_total,
                "used": context_budget_used,
                "truncated_packs": truncated_packs or [],
            },
        )

    def tool_policy_event(
        self,
        tool_name: str,
        allowed: bool,
        reason: str = "",
        server_id: str = "",
        user_id: str = "",
        topic_id: str = "",
        role_id: str = "",
    ) -> None:
        """Tool policy event (§6.2, §12.1)."""
        event_type = "tool_allowed" if allowed else "tool_denied"
        self._log.info(
            event_type,
            tool_name=tool_name,
            tool_allowed=allowed,
            reason=reason,
            server_id=server_id,
            user_id=user_id,
            topic_id=topic_id,
            role_id=role_id,
        )

    def context_budget_applied(
        self,
        user_id: str,
        topic_id: str,
        prompt_hash: str,
        total_tokens: int,
        truncated_packs: list[str] | None = None,
    ) -> None:
        """Context budget application event (§10.3 acceptance)."""
        self._log.info(
            "context_budget_applied",
            user_id=user_id,
            topic_id=topic_id,
            prompt_hash=prompt_hash,
            total_tokens=total_tokens,
            truncated_packs=truncated_packs or [],
        )

    def settings_loaded(
        self,
        sources: list[str],
        mcp_servers_count: int = 0,
    ) -> None:
        """Settings load event (§2.2 acceptance)."""
        self._log.info(
            "settings_loaded",
            sources=sources,
            mcp_servers_count=mcp_servers_count,
        )

    def turn_error(
        self,
        user_id: str,
        topic_id: str,
        error_type: str,
        error_message: str,
        recovery_action: str = "",
    ) -> None:
        """Processing error."""
        self._log.error(
            "turn_error",
            user_id=user_id,
            topic_id=topic_id,
            error_type=error_type,
            error_message=error_message,
            recovery_action=recovery_action,
        )

    # --- Delegation events (orchestrator) ---

    def role_selected(
        self,
        user_id: str,
        topic_id: str,
        role_id: str,
        source: str = "",
    ) -> None:
        """Role selected for a turn.

        source: explicit / intent / router / orchestrator / delegation / auto_return.
        """
        self._log.info(
            "role_selected",
            user_id=user_id,
            topic_id=topic_id,
            role_id=role_id,
            source=source,
        )

    def delegation_start(
        self,
        user_id: str,
        topic_id: str,
        from_role: str,
        to_role: str,
        context: str = "",
    ) -> None:
        """Delegation started (orchestrator → domain role)."""
        self._log.info(
            "delegation_start",
            user_id=user_id,
            topic_id=topic_id,
            from_role=from_role,
            to_role=to_role,
            context=context[:200],
        )

    def delegation_done(
        self,
        user_id: str,
        topic_id: str,
        from_role: str,
        to_role: str,
        turns: int = 0,
        trigger: str = "",
    ) -> None:
        """Delegation finished (domain role → orchestrator).

        trigger: return_tool / auto_return / intent_change.
        """
        self._log.info(
            "delegation_done",
            user_id=user_id,
            topic_id=topic_id,
            from_role=from_role,
            to_role=to_role,
            turns=turns,
            trigger=trigger,
        )

    def delegation_failed(
        self,
        user_id: str,
        topic_id: str,
        role_id: str,
        error: str,
    ) -> None:
        """Delegation error."""
        self._log.error(
            "delegation_failed",
            user_id=user_id,
            topic_id=topic_id,
            role_id=role_id,
            error=error,
        )

    def memory_persist(
        self,
        user_id: str,
        topic_id: str,
        facts_saved: int = 0,
        summary_updated: bool = False,
    ) -> None:
        """Persist data to memory."""
        self._log.info(
            "memory_persist",
            user_id=user_id,
            topic_id=topic_id,
            facts_saved=facts_saved,
            summary_updated=summary_updated,
        )


def _level_to_int(level: str) -> int:
    """Convert a string log level to its numeric value."""
    levels = {
        "debug": 10,
        "info": 20,
        "warning": 30,
        "error": 40,
        "critical": 50,
    }
    return levels.get(level.lower(), 20)
