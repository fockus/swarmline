"""Модуль памяти — провайдеры хранения данных агента.

ISP: монолитный MemoryProvider удалён. Используйте мелкие протоколы
из cognitia.protocols (MessageStore, FactStore, etc.).

PostgresMemoryProvider перенесён в infrastructure layer
приложения. Здесь только InMemory + types.
"""

# Backward-compatible re-export (deprecated — используйте провайдер из app layer)
import contextlib

from cognitia.memory.inmemory import InMemoryMemoryProvider
from cognitia.memory.types import (
    GoalState,
    MemoryMessage,
    PhaseState,
    ToolEvent,
    UserProfile,
)

with contextlib.suppress(ImportError):
    from cognitia.memory.postgres import PostgresMemoryProvider

with contextlib.suppress(ImportError):
    from cognitia.memory.sqlite import SQLiteMemoryProvider

__all__ = [
    "GoalState",
    "InMemoryMemoryProvider",
    "MemoryMessage",
    "PhaseState",
    "SQLiteMemoryProvider",
    "ToolEvent",
    "UserProfile",
]
