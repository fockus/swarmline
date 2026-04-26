"""Типы для Memory Bank — долгосрочная файловая память.

MemoryBankConfig — конфигурация банка памяти.
MemoryEntry — запись в банке памяти.
MemoryBankViolation — нарушение правил банка.
validate_memory_path — валидация пути (depth, traversal).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class MemoryBankConfig:
    """Конфигурация Memory Bank.

    Включается независимо от sandbox и todo.
    """

    enabled: bool = False
    backend: Literal["filesystem", "database"] = "filesystem"
    root_path: Path | None = None
    prompt_path: Path | None = None
    max_file_size_bytes: int = 100 * 1024  # 100 KB
    max_total_size_bytes: int = 1024 * 1024  # 1 MB
    max_entries: int = 200
    max_depth: int = 2  # root/subfolder/file
    retention_days: int | None = None
    auto_load_on_turn: bool = True
    auto_load_max_lines: int = 200
    default_folders: list[str] = field(
        default_factory=lambda: ["plans", "reports", "notes"]
    )
    tiered_enabled: bool = False


@dataclass(frozen=True)
class MemoryEntry:
    """Запись в банке памяти."""

    path: str  # e.g. "MEMORY.md", "plans/2026-02-12_feature.md"
    content: str
    created_at: datetime
    updated_at: datetime


ContextTier = Literal["L0", "L1", "L2"]


@dataclass(frozen=True)
class TieredEntry:
    """Memory bank entry with a specific context tier.

    L0 (~100 tokens): abstract/title for fast recall.
    L1 (~2000 tokens): overview for decision-making.
    L2 (unlimited): full original content.
    """

    path: str
    tier: ContextTier
    content: str
    token_count: int = 0


class MemoryBankViolation(Exception):
    """Нарушение правил банка памяти (path depth, traversal, size)."""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


def validate_memory_path(path: str, *, max_depth: int = 2) -> None:
    """Валидация пути в банке памяти.

    - Не пустой
    - Не абсолютный
    - Нет traversal (..)
    - Глубина ≤ max_depth

    Raises:
        MemoryBankViolation: Невалидный путь.
    """
    if not path:
        raise MemoryBankViolation("Путь не может быть пустым", path=path)

    if os.path.isabs(path):
        raise MemoryBankViolation(f"Запрещён абсолютный путь: {path}", path=path)

    if ".." in path.split("/"):
        raise MemoryBankViolation(f"Path traversal запрещён: {path}", path=path)

    # Глубина: количество частей пути
    parts = Path(path).parts
    if len(parts) > max_depth:
        msg = f"Превышена depth ({len(parts)} > {max_depth}): {path}"
        raise MemoryBankViolation(msg, path=path)
