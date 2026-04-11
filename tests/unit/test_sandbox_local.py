"""Tests LocalSandboxProvider - TDD: RED -> GREEN -> REFACTOR. Unit-tests for izolyatsii fileovoy sistemy and vypolnotniya komand.
"""

from __future__ import annotations

import pytest
from cognitia.tools.types import SandboxConfig, SandboxViolation


@pytest.fixture()
def sandbox_config(tmp_path: object) -> SandboxConfig:
    """Konfiguratsiya sandbox for testov."""
    return SandboxConfig(
        root_path=str(tmp_path),
        user_id="user-1",
        topic_id="topic-1",
        max_file_size_bytes=1024,  # 1KB for testov
        timeout_seconds=5,
        denied_commands=frozenset({"rm", "sudo"}),
        allow_host_execution=True,
    )


@pytest.fixture()
async def sandbox(sandbox_config: SandboxConfig):
    """Ekzemplyar LocalSandboxProvider."""
    from cognitia.tools.sandbox_local import LocalSandboxProvider

    return LocalSandboxProvider(sandbox_config)


class TestLocalSandboxReadFile:
    """Tests chteniya fileov."""

    async def test_read_existing_file(self, sandbox, sandbox_config: SandboxConfig) -> None:
        """Reading sushchestvuyushchego filea."""
        import os

        ws = sandbox_config.workspace_path
        os.makedirs(ws, exist_ok=True)
        with open(os.path.join(ws, "hello.txt"), "w") as f:
            f.write("world")

        result = await sandbox.read_file("hello.txt")
        assert result == "world"

    async def test_read_nonexistent_file(self, sandbox) -> None:
        """Reading notsushchestvuyushchego filea -> FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await sandbox.read_file("nonexistent.txt")

    async def test_read_traversal_blocked(self, sandbox) -> None:
        """Path traversal pri chtenii -> SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.read_file("../../etc/passwd")

    async def test_read_absolute_path_blocked(self, sandbox) -> None:
        """Absolyutnyy put pri chtenii -> SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.read_file("/etc/passwd")

    async def test_read_nested_file(self, sandbox, sandbox_config: SandboxConfig) -> None:
        """Reading filea from poddirektorii."""
        import os

        ws = sandbox_config.workspace_path
        sub = os.path.join(ws, "src")
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, "main.py"), "w") as f:
            f.write("print('hi')")

        result = await sandbox.read_file("src/main.py")
        assert result == "print('hi')"


class TestLocalSandboxWriteFile:
    """Tests zapisi fileov."""

    async def test_write_creates_file(self, sandbox, sandbox_config: SandboxConfig) -> None:
        """Writing sozdaet file and promezhutochnye direktorii."""
        await sandbox.write_file("new.txt", "content")

        import os

        path = os.path.join(sandbox_config.workspace_path, "new.txt")
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == "content"

    async def test_write_creates_subdirectories(
        self, sandbox, sandbox_config: SandboxConfig
    ) -> None:
        """Writing sozdaet promezhutochnye direktorii."""
        await sandbox.write_file("a/b/c.txt", "deep")

        import os

        path = os.path.join(sandbox_config.workspace_path, "a", "b", "c.txt")
        assert os.path.exists(path)

    async def test_write_overwrites_existing(self, sandbox) -> None:
        """Perewriting sushchestvuyushchego filea."""
        await sandbox.write_file("f.txt", "old")
        await sandbox.write_file("f.txt", "new")

        result = await sandbox.read_file("f.txt")
        assert result == "new"

    async def test_write_traversal_blocked(self, sandbox) -> None:
        """Path traversal pri zapisi -> SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.write_file("../../../tmp/hack", "evil")

    async def test_write_size_limit(self, sandbox) -> None:
        """Writing filea bolshe max_file_size_bytes -> SandboxViolation."""
        big_content = "x" * 2048  # > 1KB limita
        with pytest.raises(SandboxViolation):
            await sandbox.write_file("big.txt", big_content)


class TestLocalSandboxExecute:
    """Tests vypolnotniya komand."""

    async def test_execute_echo(self, sandbox) -> None:
        """Execution simple commands."""
        result = await sandbox.execute("echo hello")
        assert result.stdout.strip() == "hello"
        assert result.exit_code == 0
        assert result.timed_out is False

    async def test_execute_without_host_opt_in_blocks(self, tmp_path) -> None:
        """Host execution без opt-in must fail fast."""
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        provider = LocalSandboxProvider(
            SandboxConfig(root_path=str(tmp_path), user_id="u", topic_id="t")
        )

        with pytest.raises(SandboxViolation, match="allow_host_execution=True"):
            await provider.execute("echo hello")

    async def test_execute_failing_command(self, sandbox) -> None:
        """Command with notnulevym exit code."""
        result = await sandbox.execute("false")
        assert result.exit_code != 0
        assert result.timed_out is False

    async def test_execute_denied_command(self, sandbox) -> None:
        """Zapreshchennaya command -> SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.execute("rm -rf /")

    async def test_execute_denied_sudo(self, sandbox) -> None:
        """sudo → SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.execute("sudo ls")

    async def test_execute_denied_via_shell_wrapper_sh(self, sandbox) -> None:
        """Obhod denylist cherez sh -c blokiruetsya."""
        with pytest.raises(SandboxViolation):
            await sandbox.execute("sh -c 'rm -rf /'")

    async def test_execute_denied_via_shell_wrapper_bash(self, sandbox) -> None:
        """Obhod denylist cherez bash -lc blokiruetsya."""
        with pytest.raises(SandboxViolation):
            await sandbox.execute('bash -lc "rm -rf /"')

    async def test_execute_timeout(self, sandbox_config, tmp_path) -> None:
        """Command with timeout -> timed_out=True."""
        config = SandboxConfig(
            root_path=str(tmp_path),
            user_id="u",
            topic_id="t",
            timeout_seconds=1,  # 1 sekunda
            allow_host_execution=True,
        )
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        sb = LocalSandboxProvider(config)
        result = await sb.execute("sleep 10")
        assert result.timed_out is True

    async def test_execute_cwd_is_workspace(self, sandbox, sandbox_config: SandboxConfig) -> None:
        """cwd commands = workspace path."""
        result = await sandbox.execute("pwd")
        assert result.stdout.strip() == sandbox_config.workspace_path

    async def test_execute_stderr(self, sandbox) -> None:
        """Stderr correctly zahvatyvaetsya."""
        result = await sandbox.execute("cat missing_file")
        assert "missing_file" in result.stderr


class TestLocalSandboxListDir:
    """Tests list_dir."""

    async def test_list_empty_workspace(self, sandbox) -> None:
        """Empty workspace -> empty list."""
        result = await sandbox.list_dir(".")
        assert result == []

    async def test_list_with_files(self, sandbox) -> None:
        """Workspace with fileami."""
        await sandbox.write_file("a.txt", "a")
        await sandbox.write_file("b.py", "b")

        result = await sandbox.list_dir(".")
        assert sorted(result) == ["a.txt", "b.py"]

    async def test_list_subdirectory(self, sandbox) -> None:
        """List fileov in poddirektorii."""
        await sandbox.write_file("src/main.py", "x")
        await sandbox.write_file("src/utils.py", "y")

        result = await sandbox.list_dir("src")
        assert sorted(result) == ["main.py", "utils.py"]

    async def test_list_traversal_blocked(self, sandbox) -> None:
        """Path traversal in list_dir -> SandboxViolation."""
        with pytest.raises(SandboxViolation):
            await sandbox.list_dir("../../")


class TestLocalSandboxGlob:
    """Tests glob_files."""

    async def test_glob_py_files(self, sandbox) -> None:
        """Glob *.py nahodit Python-files."""
        await sandbox.write_file("main.py", "x")
        await sandbox.write_file("test.py", "y")
        await sandbox.write_file("readme.md", "z")

        result = await sandbox.glob_files("*.py")
        assert sorted(result) == ["main.py", "test.py"]

    async def test_glob_recursive(self, sandbox) -> None:
        """Recursive glob **/*.py."""
        await sandbox.write_file("main.py", "x")
        await sandbox.write_file("src/utils.py", "y")

        result = await sandbox.glob_files("**/*.py")
        assert sorted(result) == ["main.py", "src/utils.py"]

    async def test_glob_no_matches(self, sandbox) -> None:
        """Glob without matches -> empty list."""
        result = await sandbox.glob_files("*.rs")
        assert result == []

    async def test_glob_traversal_blocked(self, sandbox) -> None:
        """Traversal in glob-patternot blokiruetsya."""
        with pytest.raises(SandboxViolation):
            await sandbox.glob_files("../../*.txt")


class TestLocalSandboxIsolation:
    """Tests izolyatsii mezhdu usermi/topikami."""

    async def test_cross_user_isolation(self, tmp_path) -> None:
        """User A not vidit files user B."""
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
        """Topic X not vidit files topic Y togo zhe user."""
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
        """LocalSandboxProvider prohodit isinstance check for SandboxProvider."""
        from cognitia.tools.protocols import SandboxProvider

        assert isinstance(sandbox, SandboxProvider)
