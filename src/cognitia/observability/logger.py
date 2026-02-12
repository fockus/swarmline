"""StructuredLogger — структурированное логирование для агента."""

from __future__ import annotations

from typing import Any

import structlog


def configure_logging(level: str = "info", fmt: str = "json") -> None:
    """Настроить structlog с JSON-форматом в stdout."""
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
        wrapper_class=structlog.make_filtering_bound_logger(_level_to_int(level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class AgentLogger:
    """Логгер событий агента с предопределённой схемой."""

    def __init__(self, component: str = "cognitia") -> None:
        self._log = structlog.get_logger(component=component)

    def session_created(
        self,
        user_id: str,
        topic_id: str,
        role_id: str,
        is_rehydrated: bool = False,
    ) -> None:
        """Создание/восстановление сессии."""
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
        """Начало обработки сообщения."""
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
        """Вызов инструмента."""
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
        """Завершение обработки сообщения (§12.1: включает prompt_hash).

        KISS: latency_ms передаётся вызывающим кодом, а не считается в логгере.
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
        """Событие политики инструментов (§6.2, §12.1)."""
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
        """Событие применения бюджета контекста (§10.3 acceptance)."""
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
        """Событие загрузки настроек (§2.2 acceptance)."""
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
        """Ошибка при обработке."""
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
        """Роль выбрана для turn'а.

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
        """Делегирование начато (orchestrator → доменная роль)."""
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
        """Делегирование завершено (доменная роль → orchestrator).

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
        """Ошибка при делегировании."""
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
        """Сохранение данных в память."""
        self._log.info(
            "memory_persist",
            user_id=user_id,
            topic_id=topic_id,
            facts_saved=facts_saved,
            summary_updated=summary_updated,
        )


def _level_to_int(level: str) -> int:
    """Преобразовать строковый уровень в числовой."""
    levels = {
        "debug": 10,
        "info": 20,
        "warning": 30,
        "error": 40,
        "critical": 50,
    }
    return levels.get(level.lower(), 20)
