"""Тесты LocalSandboxProvider — TDD: RED → GREEN → REFACTOR.

Unit-тесты для изоляции файловой системы и выполнения команд.
"""

from __future__ import annotations

import pytest

from cognitia.tools.types import SandboxConfig, SandboxViolation


@pytest.fixture()
def sandbox_config(tmp_path: object) -> SandboxConfig:
    """Конфигурация sandbox для тестов."""
    return SandboxConfig(
        root_path=str(tmp_path),
        user_id="user-1",
        topic_id="topic-1",
        max_file_size_bytes=1024,  # 1KB для тестов
        timeout_seconds=5,
        denied_commands=frozenset({"rm", "sudo"}),
    )


@pytest.fixture()
async def sandbox(sandbox_config: SandboxConfig):
    """Экземпляр LocalSandboxProvider."""
    from cognitia.tools.sandbox_local import LocalSandboxProvider

    return LocalSandboxProvider(sandbox_config)


class TestLocalSandboxReadFile:
    """Тесты чтения файлов."""

    async def test_read_existing_file(self, sandbox, sandbox_config: SandboxConfig) -> None:
        """Чтение существующего файла."""
        import os

        ws = sandbox_config.workspace_path
        os.makedirs(ws, exist_ok=True)
        with open(os.path.join(ws, "hello.txt"), "w") as f:
            f.write("world")

        result = await sandbox.read_file("hello.txt")
        assert result == "world"

    async def test_read_nonexistent_file(self, sandbox) -> None:
        """Чтение несуществующего файла → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await sandbox.read_file("nonexistent.txt")

    async def test_read_traversal_blocked(self, sandbox) -> None:
        """Path traversal при чтении → SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.read_file("../../etc/passwd")

    async def test_read_absolute_path_blocked(self, sandbox) -> None:
        """Абсолютный путь при чтении → SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.read_file("/etc/passwd")

    async def test_read_nested_file(self, sandbox, sandbox_config: SandboxConfig) -> None:
        """Чтение файла из поддиректории."""
        import os

        ws = sandbox_config.workspace_path
        sub = os.path.join(ws, "src")
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, "main.py"), "w") as f:
            f.write("print('hi')")

        result = await sandbox.read_file("src/main.py")
        assert result == "print('hi')"


class TestLocalSandboxWriteFile:
    """Тесты записи файлов."""

    async def test_write_creates_file(self, sandbox, sandbox_config: SandboxConfig) -> None:
        """Запись создаёт файл и промежуточные директории."""
        await sandbox.write_file("new.txt", "content")

        import os

        path = os.path.join(sandbox_config.workspace_path, "new.txt")
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == "content"

    async def test_write_creates_subdirectories(self, sandbox, sandbox_config: SandboxConfig) -> None:
        """Запись создаёт промежуточные директории."""
        await sandbox.write_file("a/b/c.txt", "deep")

        import os

        path = os.path.join(sandbox_config.workspace_path, "a", "b", "c.txt")
        assert os.path.exists(path)

    async def test_write_overwrites_existing(self, sandbox) -> None:
        """Перезапись существующего файла."""
        await sandbox.write_file("f.txt", "old")
        await sandbox.write_file("f.txt", "new")

        result = await sandbox.read_file("f.txt")
        assert result == "new"

    async def test_write_traversal_blocked(self, sandbox) -> None:
        """Path traversal при записи → SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.write_file("../../../tmp/hack", "evil")

    async def test_write_size_limit(self, sandbox) -> None:
        """Запись файла больше max_file_size_bytes → SandboxViolation."""
        big_content = "x" * 2048  # > 1KB лимита
        with pytest.raises(SandboxViolation):
            await sandbox.write_file("big.txt", big_content)


class TestLocalSandboxExecute:
    """Тесты выполнения команд."""

    async def test_execute_echo(self, sandbox) -> None:
        """Выполнение простой команды."""
        result = await sandbox.execute("echo hello")
        assert result.stdout.strip() == "hello"
        assert result.exit_code == 0
        assert result.timed_out is False

    async def test_execute_failing_command(self, sandbox) -> None:
        """Команда с ненулевым exit code."""
        result = await sandbox.execute("false")
        assert result.exit_code != 0
        assert result.timed_out is False

    async def test_execute_denied_command(self, sandbox) -> None:
        """Запрещённая команда → SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.execute("rm -rf /")

    async def test_execute_denied_sudo(self, sandbox) -> None:
        """sudo → SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.execute("sudo ls")

    async def test_execute_timeout(self, sandbox_config, tmp_path) -> None:
        """Команда с timeout → timed_out=True."""
        config = SandboxConfig(
            root_path=str(tmp_path),
            user_id="u",
            topic_id="t",
            timeout_seconds=1,  # 1 секунда
        )
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        sb = LocalSandboxProvider(config)
        result = await sb.execute("sleep 10")
        assert result.timed_out is True

    async def test_execute_cwd_is_workspace(self, sandbox, sandbox_config: SandboxConfig) -> None:
        """cwd команды = workspace path."""
        result = await sandbox.execute("pwd")
        assert result.stdout.strip() == sandbox_config.workspace_path

    async def test_execute_stderr(self, sandbox) -> None:
        """Stderr корректно захватывается."""
        result = await sandbox.execute("echo err >&2")
        assert "err" in result.stderr


class TestLocalSandboxListDir:
    """Тесты list_dir."""

    async def test_list_empty_workspace(self, sandbox) -> None:
        """Пустой workspace → пустой список."""
        result = await sandbox.list_dir(".")
        assert result == []

    async def test_list_with_files(self, sandbox) -> None:
        """Workspace с файлами."""
        await sandbox.write_file("a.txt", "a")
        await sandbox.write_file("b.py", "b")

        result = await sandbox.list_dir(".")
        assert sorted(result) == ["a.txt", "b.py"]

    async def test_list_subdirectory(self, sandbox) -> None:
        """Список файлов в поддиректории."""
        await sandbox.write_file("src/main.py", "x")
        await sandbox.write_file("src/utils.py", "y")

        result = await sandbox.list_dir("src")
        assert sorted(result) == ["main.py", "utils.py"]

    async def test_list_traversal_blocked(self, sandbox) -> None:
        """Path traversal в list_dir → SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.list_dir("../../")


class TestLocalSandboxGlob:
    """Тесты glob_files."""

    async def test_glob_py_files(self, sandbox) -> None:
        """Glob *.py находит Python-файлы."""
        await sandbox.write_file("main.py", "x")
        await sandbox.write_file("test.py", "y")
        await sandbox.write_file("readme.md", "z")

        result = await sandbox.glob_files("*.py")
        assert sorted(result) == ["main.py", "test.py"]

    async def test_glob_recursive(self, sandbox) -> None:
        """Рекурсивный glob **/*.py."""
        await sandbox.write_file("main.py", "x")
        await sandbox.write_file("src/utils.py", "y")

        result = await sandbox.glob_files("**/*.py")
        assert sorted(result) == ["main.py", "src/utils.py"]

    async def test_glob_no_matches(self, sandbox) -> None:
        """Glob без совпадений → пустой список."""
        result = await sandbox.glob_files("*.rs")
        assert result == []


class TestLocalSandboxIsolation:
    """Тесты изоляции между пользователями/топиками."""

    async def test_cross_user_isolation(self, tmp_path) -> None:
        """Пользователь A не видит файлы пользователя B."""
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        sb_a = LocalSandboxProvider(
            SandboxConfig(root_path=str(tmp_path), user_id="alice", topic_id="t1")
        )
        sb_b = LocalSandboxProvider(
            SandboxConfig(root_path=str(tmp_path), user_id="bob", topic_id="t1")
        )

        await sb_a.write_file("secret.txt", "alice-data")

        with pytest.raises(FileNotFoundError):
            await sb_b.read_file("secret.txt")

    async def test_cross_topic_isolation(self, tmp_path) -> None:
        """Topic X не видит файлы topic Y того же пользователя."""
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        sb_x = LocalSandboxProvider(
            SandboxConfig(root_path=str(tmp_path), user_id="alice", topic_id="topic-x")
        )
        sb_y = LocalSandboxProvider(
            SandboxConfig(root_path=str(tmp_path), user_id="alice", topic_id="topic-y")
        )

        await sb_x.write_file("data.txt", "topic-x-data")

        with pytest.raises(FileNotFoundError):
            await sb_y.read_file("data.txt")

    async def test_isinstance_sandbox_provider(self, sandbox) -> None:
        """LocalSandboxProvider проходит isinstance check для SandboxProvider."""
        from cognitia.tools.protocols import SandboxProvider

        assert isinstance(sandbox, SandboxProvider)
