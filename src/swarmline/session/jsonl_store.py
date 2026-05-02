"""JsonlMessageStore — file-based MessageStore using JSONL format.

One JSON line per message, one file per (user_id, topic_id) session.
Uses asyncio.to_thread for non-blocking file I/O.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from swarmline.memory.types import MemoryMessage


def _safe_filename(user_id: str, topic_id: str) -> str:
    """Generate collision-free filename from user_id + topic_id.

    Uses SHA-256 hash to avoid filesystem-unsafe characters and
    prevent collisions between similar IDs (e.g. 'user:1' vs 'user_1').
    """
    key = f"{user_id}\x00{topic_id}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


class JsonlMessageStore:
    """File-based MessageStore using JSONL format (one JSON line per message).

    Implements the MessageStore protocol from swarmline.protocols.memory.
    Each (user_id, topic_id) pair maps to a separate .jsonl file.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, user_id: str, topic_id: str) -> Path:
        return self._base_dir / f"{_safe_filename(user_id, topic_id)}.jsonl"

    async def save_message(
        self,
        user_id: str,
        topic_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        content_blocks: list[dict[str, Any]] | None = None,
    ) -> None:
        """Append a message as a JSON line to the session file."""
        record = {
            "role": role,
            "content": content,
            "name": name,
            "tool_calls": tool_calls,
            "metadata": metadata,
            "content_blocks": content_blocks,
            "ts": time.time(),
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        path = self._session_path(user_id, topic_id)

        await asyncio.to_thread(self._append_line, path, line)

    async def get_messages(
        self,
        user_id: str,
        topic_id: str,
        limit: int = 10,
    ) -> list[MemoryMessage]:
        """Read the last N messages from the session file."""
        path = self._session_path(user_id, topic_id)
        lines = await asyncio.to_thread(self._read_lines, path)
        if limit <= 0:
            return []
        if not lines:
            return []

        tail = lines[-limit:]
        result: list[MemoryMessage] = []
        for raw in tail:
            try:
                record = json.loads(raw)
            except (json.JSONDecodeError, KeyError):
                continue  # skip corrupted lines
            result.append(
                MemoryMessage(
                    role=record.get("role", "user"),
                    content=record.get("content", ""),
                    name=record.get("name"),
                    tool_calls=record.get("tool_calls"),
                    metadata=record.get("metadata"),
                    content_blocks=record.get("content_blocks"),
                )
            )
        return result

    async def count_messages(self, user_id: str, topic_id: str) -> int:
        """Count messages in the session file."""
        path = self._session_path(user_id, topic_id)
        lines = await asyncio.to_thread(self._read_lines, path)
        return len(lines)

    async def delete_messages_before(
        self,
        user_id: str,
        topic_id: str,
        keep_last: int = 10,
    ) -> int:
        """Delete old messages, keeping only the last keep_last. Returns count deleted."""
        path = self._session_path(user_id, topic_id)
        lines = await asyncio.to_thread(self._read_lines, path)
        total = len(lines)
        if keep_last <= 0:
            if total > 0:
                await asyncio.to_thread(self._write_lines, path, [])
            return total
        to_delete = max(0, total - keep_last)
        if to_delete > 0:
            kept = lines[-keep_last:]
            await asyncio.to_thread(self._write_lines, path, kept)
        return to_delete

    # --- Sync file helpers (run via asyncio.to_thread) ---

    @staticmethod
    def _append_line(path: Path, line: str) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        return [line for line in text.split("\n") if line.strip()]

    @staticmethod
    def _write_lines(path: Path, lines: list[str]) -> None:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
