"""File-backed, append-only JSONL event journal.

Durable counterpart to ``journal.InMemoryEventJournal``. Kept in its own
module (rather than in ``journal.py``) because it pulls in heavier
dependencies -- ``structlog`` for structured warnings and the redaction
pipeline from ``jsonl_sink.py`` -- mirroring how this package splits
``event_bus.py`` (stdlib-only port) from ``event_bus_redis.py`` /
``event_bus_nats.py`` (heavy infra impls).

ADR -- durable seq across restart: ``JsonlEventJournal`` recovers its next seq
by reading the file tail on construction.

- Tail cleanup happens at the BYTE level, before any UTF-8 decode. If the
  file does not end with ``b"\\n"``, the last line is a partial write from a
  crash mid-append; the incomplete tail is truncated back to the end of the
  last complete line (or to empty, if there is no complete line at all) and
  rewritten to disk so appends never concatenate onto a dangling,
  unterminated line. Doing this at the byte level (not after ``read_text``)
  matters because appends use ``ensure_ascii=False``: a crash mid-append can
  leave an incomplete multi-byte UTF-8 sequence at EOF, and decoding first
  would raise ``UnicodeDecodeError`` on reopen instead of recovering.
- Only once the on-disk bytes are clean (end on a complete line boundary) is
  the clean prefix decoded for seq recovery. If a (now newline-terminated)
  line still fails to parse as JSON, it is dropped and seq recovery falls
  back to the maximum valid seq found among the well-formed lines; a
  structured warning is emitted so operators can see the gap was noticed.
- Empty/absent file -- seq starts at 1.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from swarmline.observability.journal import EventJournal, JournalEntry, ReplayReader
from swarmline.observability.jsonl_sink import (
    DEFAULT_REDACT_KEYS,
    DEFAULT_REDACT_VALUE_PATTERNS,
    _make_json_safe,
    _redact,
)

_logger = structlog.get_logger(component="event_journal")


class JsonlEventJournal:
    """File-backed, append-only JSONL event journal.

    Implements both ``EventJournal`` and ``ReplayReader``. One JSON object
    per line: ``{seq, schema_version, timestamp, event_type, data}``. Reuses
    ``JsonlTelemetrySink``'s default redaction keys/patterns and
    ``schema_version`` convention (DRY -- see jsonl_sink.py:53-122).
    """

    def __init__(
        self,
        path: str | Path,
        *,
        redact_keys: Iterable[str] = DEFAULT_REDACT_KEYS,
        redact_value_patterns: tuple[
            re.Pattern[str], ...
        ] = DEFAULT_REDACT_VALUE_PATTERNS,
        schema_version: int = 1,
    ) -> None:
        self._path = Path(path)
        self._redact_keys = frozenset(key.lower() for key in redact_keys)
        self._redact_value_patterns = tuple(redact_value_patterns)
        self._schema_version = schema_version
        self._lock = asyncio.Lock()
        self._next_seq = self._recover_next_seq()

    @property
    def path(self) -> Path:
        """JSONL journal file path."""
        return self._path

    def _truncate_unterminated_tail(self) -> bytes:
        """Drop a dangling, unterminated tail left by a crash mid-append.

        Operates at the BYTE level, before any UTF-8 decode -- a crash
        mid-append can leave an incomplete multi-byte UTF-8 sequence at EOF
        (appends use ``ensure_ascii=False``), so decoding the file first
        would raise ``UnicodeDecodeError`` and defeat recovery entirely.

        Reads the raw bytes; if the file is non-empty and does not end with
        ``b"\\n"``, the bytes after the last ``b"\\n"`` are a partial write
        and are rewritten out of the file (via ``write_bytes``) so the next
        append always starts on a clean line boundary. If there is no
        ``b"\\n"`` at all, the whole file is one incomplete line and is
        truncated to empty. Returns the clean, newline-terminated bytes.
        """
        raw_bytes = self._path.read_bytes()
        if not raw_bytes or raw_bytes.endswith(b"\n"):
            return raw_bytes
        last_newline = raw_bytes.rfind(b"\n")
        clean_bytes = raw_bytes[: last_newline + 1] if last_newline != -1 else b""
        if clean_bytes != raw_bytes:
            self._path.write_bytes(clean_bytes)
            _logger.warning(
                "jsonl_event_journal.unterminated_tail_truncated",
                path=str(self._path),
                dropped_bytes=len(raw_bytes) - len(clean_bytes),
            )
        return clean_bytes

    def _recover_next_seq(self) -> int:
        """Read the file tail to recover the next seq to assign.

        First truncates any dangling unterminated tail at the byte level
        (see ``_truncate_unterminated_tail``) -- only the resulting clean,
        newline-terminated bytes are decoded as UTF-8. Then skips blank
        lines; if a (terminated) line still fails to parse, it is dropped --
        and if it was the last line in the file, a structured warning is
        emitted.
        """
        if not self._path.exists():
            return 1
        clean_bytes = self._truncate_unterminated_tail()
        raw = clean_bytes.decode("utf-8")
        lines = raw.splitlines()
        last_non_blank_index = -1
        for index, line in enumerate(lines):
            if line.strip():
                last_non_blank_index = index

        max_seq = 0
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                seq = int(record["seq"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                if index == last_non_blank_index:
                    _logger.warning(
                        "jsonl_event_journal.corrupt_last_line_recovered",
                        path=str(self._path),
                        line_number=index + 1,
                        recovered_max_seq=max_seq,
                    )
                continue
            if seq > max_seq:
                max_seq = seq
        return max_seq + 1

    async def append(self, event_type: str, data: dict[str, object]) -> int:
        """Append one event; assigns the next durable seq under lock."""
        async with self._lock:
            seq = self._next_seq
            timestamp = datetime.now(tz=UTC).isoformat()
            record = {
                "seq": seq,
                "schema_version": self._schema_version,
                "timestamp": timestamp,
                "event_type": event_type,
                "data": _make_json_safe(
                    _redact(data, self._redact_keys, self._redact_value_patterns)
                ),
            }
            line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            await asyncio.to_thread(self._append_line, line)
            self._next_seq += 1
            return seq

    def _append_line(self, line: str) -> None:
        """Sync filesystem append; called via asyncio.to_thread() from append()."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    async def last_seq(self) -> int:
        """Return the highest assigned seq (0 if the journal is empty)."""
        async with self._lock:
            return self._next_seq - 1

    async def read(
        self, *, since: int = 0, until: int | None = None
    ) -> AsyncIterator[JournalEntry]:
        """Stream the file and yield entries in ``[since, until]``.

        Does not need its own byte-level torn-tail cleanup: on-disk bytes
        are cleaned once, at construction time (``_recover_next_seq`` ->
        ``_truncate_unterminated_tail``), and every subsequent ``append()``
        writes one complete, newline-terminated line under ``self._lock``.
        So for the lifetime of this instance the file can only end in a
        dangling partial line at the single moment right after an external
        process crashes mid-append -- which requires re-constructing a new
        ``JsonlEventJournal`` (and thus re-running recovery) before this
        instance's ``read()``/``append()`` would touch the file again.
        """
        if not self._path.exists():
            return
        text = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                seq = int(record["seq"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if seq < since:
                continue
            if until is not None and seq > until:
                continue
            yield JournalEntry(
                seq=seq,
                schema_version=record.get("schema_version", self._schema_version),
                timestamp=record.get("timestamp", ""),
                event_type=record.get("event_type", ""),
                data=record.get("data", {}),
            )


if TYPE_CHECKING:
    # Static-only self-check: JsonlEventJournal must structurally satisfy
    # both ports it claims to implement (no runtime cost, no import cycle).
    _conforms_to_event_journal: type[EventJournal] = JsonlEventJournal
    _conforms_to_replay_reader: type[ReplayReader] = JsonlEventJournal
