"""Tests for MemoryBank types, config, and path validation - TDD."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


class TestMemoryBankConfig:
    def test_defaults(self) -> None:
        from swarmline.memory_bank.types import MemoryBankConfig

        cfg = MemoryBankConfig()
        assert cfg.enabled is False
        assert cfg.backend == "filesystem"
        assert cfg.max_file_size_bytes == 100 * 1024
        assert cfg.max_depth == 2
        assert cfg.auto_load_on_turn is True
        assert cfg.default_folders == ["plans", "reports", "notes"]

    def test_custom(self) -> None:
        from swarmline.memory_bank.types import MemoryBankConfig

        cfg = MemoryBankConfig(
            enabled=True,
            backend="database",
            max_entries=50,
            max_depth=1,
            default_folders=["custom"],
        )
        assert cfg.enabled is True
        assert cfg.backend == "database"
        assert cfg.default_folders == ["custom"]


class TestMemoryEntry:
    def test_create(self) -> None:
        from swarmline.memory_bank.types import MemoryEntry

        entry = MemoryEntry(
            path="plans/2026-02-12_feature.md",
            content="# Plan",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        assert entry.path == "plans/2026-02-12_feature.md"
        assert entry.content == "# Plan"


class TestPathValidation:
    def test_valid_root_file(self) -> None:
        from swarmline.memory_bank.types import validate_memory_path

        validate_memory_path("MEMORY.md", max_depth=2)  # Does not raise

    def test_valid_subfolder_file(self) -> None:
        from swarmline.memory_bank.types import validate_memory_path

        validate_memory_path("plans/2026-02-12_feature.md", max_depth=2)

    def test_depth_exceeded(self) -> None:
        from swarmline.memory_bank.types import MemoryBankViolation, validate_memory_path

        with pytest.raises(MemoryBankViolation, match="depth"):
            validate_memory_path("a/b/c/file.md", max_depth=2)

    def test_traversal_blocked(self) -> None:
        from swarmline.memory_bank.types import MemoryBankViolation, validate_memory_path

        with pytest.raises(MemoryBankViolation, match="traversal"):
            validate_memory_path("../etc/passwd", max_depth=2)

    def test_absolute_path_blocked(self) -> None:
        from swarmline.memory_bank.types import MemoryBankViolation, validate_memory_path

        with pytest.raises(MemoryBankViolation, match="абсолютный"):
            validate_memory_path("/etc/passwd", max_depth=2)

    def test_empty_path_blocked(self) -> None:
        from swarmline.memory_bank.types import MemoryBankViolation, validate_memory_path

        with pytest.raises(MemoryBankViolation):
            validate_memory_path("", max_depth=2)


class TestMemoryBankProviderProtocol:
    def test_runtime_checkable(self) -> None:
        from swarmline.memory_bank.protocols import MemoryBankProvider

        class FakeMB:
            async def read_file(self, path: str) -> str | None:
                return None

            async def write_file(self, path: str, content: str) -> None:
                pass

            async def append_to_file(self, path: str, content: str) -> None:
                pass

            async def list_files(self, prefix: str = "") -> list[str]:
                return []

            async def delete_file(self, path: str) -> None:
                pass

        assert isinstance(FakeMB(), MemoryBankProvider)

    def test_incomplete_not_instance(self) -> None:
        from swarmline.memory_bank.protocols import MemoryBankProvider

        class Incomplete:
            async def read_file(self, path: str) -> str | None:
                return None

        assert not isinstance(Incomplete(), MemoryBankProvider)

    def test_isp_max_5(self) -> None:
        from swarmline.memory_bank.protocols import MemoryBankProvider

        methods = [
            n
            for n in dir(MemoryBankProvider)
            if not n.startswith("_") and callable(getattr(MemoryBankProvider, n, None))
        ]
        assert len(methods) <= 5

    def test_no_freedom_imports(self) -> None:
        import inspect

        import swarmline.memory_bank.protocols as p
        import swarmline.memory_bank.types as t

        assert "freedom_agent" not in inspect.getsource(t)
        assert "freedom_agent" not in inspect.getsource(p)
