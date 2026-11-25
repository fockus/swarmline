"""FileScratchpadProvider — durable, dependency-free scratchpad backed by a JSON file.

Same semantics as :class:`~swarmline.scratchpad.inmemory_provider.InMemoryScratchpadProvider`,
plus durability: entries survive process restarts, so an agent resuming after a
redeploy still sees its own working notes.

Storage layout: ONE JSON object per ``base_dir`` (``scratchpad.json``), keyed by
entry key. A single file — rather than one file per entry — is deliberate: entry
keys come from the model and never touch the filesystem, so path traversal
(``../../etc/passwd``) is structurally impossible, and every mutation is a single
atomic ``tmp -> replace``.

Isolation is the ``base_dir``: two providers over different directories share
nothing. Callers wanting per-namespace/session isolation pass a distinct
``base_dir`` per namespace/session.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from swarmline.scratchpad.types import ScratchpadEntry

logger = logging.getLogger(__name__)

_STORE_FILENAME = "scratchpad.json"


class FileScratchpadProvider:
    """JSON-file-backed scratchpad. Not thread-safe — intended for a single event loop.

    Concurrent writers across processes are NOT supported: the store is written
    whole, so two processes over one ``base_dir`` give last-writer-wins. Give each
    process its own ``base_dir`` if that matters.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = Path(base_dir)
        self._store_file = self._base_dir / _STORE_FILENAME
        self._entries: dict[str, ScratchpadEntry] = self._load()

    async def write(
        self, key: str, content: str, tags: tuple[str, ...] = ()
    ) -> ScratchpadEntry:
        now = datetime.now(timezone.utc)
        existing = self._entries.get(key)
        created_at = existing.created_at if existing is not None else now
        entry = ScratchpadEntry(
            key=key,
            content=content,
            tags=tuple(tags),
            created_at=created_at,
            updated_at=now,
        )
        previous = self._entries.get(key)
        self._entries[key] = entry
        try:
            self._persist()
        except Exception:
            # Roll back so memory matches the file. Leaving the entry in memory
            # after a failed persist is a phantom write: `read` returns a note
            # that is not on disk and disappears on restart.
            if previous is None:
                self._entries.pop(key, None)
            else:
                self._entries[key] = previous
            raise
        return entry

    async def read(
        self, key: str | None
    ) -> list[ScratchpadEntry] | ScratchpadEntry | None:
        if key is None:
            return list(self._entries.values())
        return self._entries.get(key)

    async def search(self, query: str) -> list[ScratchpadEntry]:
        if not query:
            return []
        needle = query.casefold()
        return [
            entry
            for entry in self._entries.values()
            if needle in entry.key.casefold()
            or needle in entry.content.casefold()
            or any(needle in tag.casefold() for tag in entry.tags)
        ]

    async def delete(self, key: str) -> bool:
        removed = self._entries.pop(key, None)
        if removed is None:
            return False
        try:
            self._persist()
        except Exception:
            # Phantom delete otherwise: gone from memory, still on disk, and back
            # after a restart — while the caller was told it was removed.
            self._entries[key] = removed
            raise
        return True

    def _load(self) -> dict[str, ScratchpadEntry]:
        if not self._store_file.exists():
            return {}
        try:
            raw = json.loads(self._store_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            self._quarantine_corrupt_store()
            return {}
        if not isinstance(raw, dict):
            self._quarantine_corrupt_store()
            return {}
        loaded: dict[str, ScratchpadEntry] = {}
        damaged: dict[str, Any] = {}
        for key, payload in raw.items():
            if not isinstance(key, str) or not isinstance(payload, dict):
                damaged[str(key)] = payload
                continue
            try:
                loaded[key] = _entry_from_json(key, payload)
            except (KeyError, TypeError, ValueError):
                damaged[key] = payload
        if damaged:
            self._quarantine_damaged_entries(damaged)
        return loaded

    def _quarantine_damaged_entries(self, damaged: dict[str, Any]) -> None:
        """Preserve unreadable entries and say so, instead of dropping them.

        Individual bad entries used to be skipped with a bare `continue`: the
        next write rewrote the store WITHOUT them, so a single malformed field
        silently destroyed a note forever, with nothing in the logs. Whole-store
        corruption is already quarantined (`_quarantine_corrupt_store`); this is
        the same guarantee at entry granularity. The good entries are kept —
        discarding them too would turn a small defect into total data loss.
        """
        quarantine_path = self._store_file.with_name(
            f"{_STORE_FILENAME}.damaged-{int(time.time())}"
        )
        try:
            quarantine_path.write_text(
                json.dumps(damaged, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            logger.error(
                "Scratchpad: %d unreadable entries in %s could NOT be quarantined and are being dropped: %s",
                len(damaged),
                self._store_file,
                sorted(damaged),
                exc_info=True,
            )
            return
        logger.error(
            "Scratchpad: %d unreadable entries in %s quarantined to %s (keys: %s); continuing with the %s that loaded",
            len(damaged),
            self._store_file,
            quarantine_path,
            sorted(damaged),
            "others",
        )

    def _quarantine_corrupt_store(self) -> None:
        """Move a damaged store aside before degrading to empty.

        Without this the next write would overwrite the file from scratch and
        destroy bytes from which the notes could still have been recovered.
        """
        quarantine_path = self._store_file.with_name(
            f"{_STORE_FILENAME}.corrupt-{int(time.time())}"
        )
        try:
            self._store_file.replace(quarantine_path)
        except OSError:
            logger.error(
                "Scratchpad store at %s is corrupt and could NOT be quarantined",
                self._store_file,
                exc_info=True,
            )
            return
        logger.error(
            "Scratchpad store at %s is corrupt: quarantined to %s, continuing with an EMPTY scratchpad",
            self._store_file,
            quarantine_path,
        )

    def _persist(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        payload = {key: _entry_to_json(entry) for key, entry in self._entries.items()}
        temp_path = self._store_file.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_path.replace(self._store_file)


def _entry_to_json(entry: ScratchpadEntry) -> dict[str, Any]:
    return {
        "content": entry.content,
        "tags": list(entry.tags),
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _entry_from_json(key: str, payload: dict[str, Any]) -> ScratchpadEntry:
    tags = payload.get("tags", [])
    if not isinstance(tags, list):
        raise TypeError("tags must be a list")
    return ScratchpadEntry(
        key=key,
        content=str(payload["content"]),
        tags=tuple(str(tag) for tag in tags),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        updated_at=datetime.fromisoformat(str(payload["updated_at"])),
    )
