"""FilesystemMemoryBankProvider — банк памяти на файловой системе.

Структура: {root}/{user_id}/{topic_id}/memory/
Поддерживает 2-уровневую вложенность: root/subfolder/file.
"""

from __future__ import annotations

import os
from pathlib import Path

from cognitia.memory_bank.types import MemoryBankConfig, MemoryBankViolation, validate_memory_path


class FilesystemMemoryBankProvider:
    """MemoryBankProvider через файловую систему.

    SRP: только FS persistence + path isolation.
    """

    def __init__(self, config: MemoryBankConfig, user_id: str, topic_id: str) -> None:
        self._config = config
        root = config.root_path or Path(".")
        self._base = Path(root) / user_id / topic_id / "memory"

    def _resolve(self, path: str) -> Path:
        """Разрешить путь внутри memory bank."""
        validate_memory_path(path, max_depth=self._config.max_depth)
        resolved = (self._base / path).resolve()
        base_resolved = self._base.resolve()
        # is_relative_to безопасен от prefix-bypass (/tmp/mem2 vs /tmp/mem)
        if not resolved.is_relative_to(base_resolved):
            raise MemoryBankViolation(f"Path traversal: {path}", path=path)
        return resolved

    async def read_file(self, path: str) -> str | None:
        """Прочитать файл. None если не существует."""
        safe = self._resolve(path)
        if not safe.exists():
            return None
        return safe.read_text(encoding="utf-8")

    async def write_file(self, path: str, content: str) -> None:
        """Записать файл. Атомарная запись."""
        if len(content.encode("utf-8")) > self._config.max_file_size_bytes:
            raise MemoryBankViolation(
                f"Файл превышает лимит {self._config.max_file_size_bytes} байт", path=path,
            )
        safe = self._resolve(path)
        safe.parent.mkdir(parents=True, exist_ok=True)
        tmp = safe.with_suffix(safe.suffix + ".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(str(tmp), str(safe))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    async def append_to_file(self, path: str, content: str) -> None:
        """Дописать в конец файла."""
        existing = await self.read_file(path)
        new_content = f"{existing}\n{content}" if existing else content
        await self.write_file(path, new_content)

    async def list_files(self, prefix: str = "") -> list[str]:
        """Список файлов (рекурсивно, max 2 уровня)."""
        base_resolved = self._base.resolve()
        if not base_resolved.exists():
            return []

        results: list[str] = []
        for root_dir, _dirs, files in os.walk(base_resolved):
            for f in files:
                if f.endswith(".tmp"):
                    continue
                full = Path(root_dir) / f
                rel = str(full.relative_to(base_resolved))
                if prefix and not rel.startswith(prefix):
                    continue
                results.append(rel)
        return sorted(results)

    async def delete_file(self, path: str) -> None:
        """Удалить файл. Graceful если не существует."""
        try:
            safe = self._resolve(path)
            safe.unlink(missing_ok=True)
        except MemoryBankViolation:
            pass
