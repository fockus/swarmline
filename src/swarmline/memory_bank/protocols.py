"""MemoryBankProvider Protocol — ISP ≤5 методов.

Storage-agnostic интерфейс для банка памяти.
Backend: filesystem или database.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryBankProvider(Protocol):
    """Провайдер банка памяти — ISP: ≤5 методов.

    Multi-tenant: изоляция по user_id + topic_id.
    """

    async def read_file(self, path: str) -> str | None:
        """Прочитать файл из банка. None если не существует."""
        ...

    async def write_file(self, path: str, content: str) -> None:
        """Записать/перезаписать файл в банке."""
        ...

    async def append_to_file(self, path: str, content: str) -> None:
        """Дописать содержимое в конец файла."""
        ...

    async def list_files(self, prefix: str = "") -> list[str]:
        """Список файлов (опционально по prefix/subfolder)."""
        ...

    async def delete_file(self, path: str) -> None:
        """Удалить файл. Graceful если не существует."""
        ...
