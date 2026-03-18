"""Portable Memory module."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 10_240  # 10KB per file


def load_agents_md(paths: list[str]) -> str:
    """Load agents md."""
    parts: list[str] = []
    for raw_path in paths:
        p = Path(raw_path).expanduser()
        if not p.is_file():
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            logger.warning("Не удалось прочитать %s", p)
            continue
        if len(content) > _MAX_FILE_SIZE:
            content = content[:_MAX_FILE_SIZE]
        parts.append(content)
    return "\n\n---\n\n".join(parts)


def inject_memory_into_prompt(system_prompt: str, memory_content: str) -> str:
    """Inject memory into prompt."""
    if not memory_content:
        return system_prompt
    return f"{system_prompt}\n\n<agent_memory>\n{memory_content}\n</agent_memory>"
