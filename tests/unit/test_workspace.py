"""Unit tests for ExecutionWorkspace — LocalWorkspace implementation."""

from __future__ import annotations

import asyncio
import os
import shutil
import time

import pytest

from swarmline.multi_agent.workspace import ExecutionWorkspace, LocalWorkspace
from swarmline.multi_agent.workspace_types import (
    WorkspaceHandle,
    WorkspaceSpec,
    WorkspaceStrategy,
)


async def _run(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode())


async def _configure_git_identity(repo: str) -> None:
    await _run("git", "-C", repo, "config", "user.email", "test@example.com")
    await _run("git", "-C", repo, "config", "user.name", "Test User")


@pytest.fixture
def workspace() -> LocalWorkspace:
    return LocalWorkspace()


# --- TEMP_DIR strategy ---


async def test_create_temp_dir_exists(workspace: LocalWorkspace) -> None:
    spec = WorkspaceSpec(strategy=WorkspaceStrategy.TEMP_DIR, base_path="/tmp")
    handle = await workspace.create(spec, "agent1", "task1")
    try:
        assert os.path.isdir(handle.path)
        assert handle.agent_id == "agent1"
        assert handle.task_id == "task1"
        assert handle.strategy == WorkspaceStrategy.TEMP_DIR
        assert len(handle.workspace_id) == 12
    finally:
        await workspace.cleanup(handle)


async def test_cleanup_temp_dir_removes(workspace: LocalWorkspace) -> None:
    spec = WorkspaceSpec(strategy=WorkspaceStrategy.TEMP_DIR, base_path="/tmp")
    handle = await workspace.create(spec, "agent1", "task1")
    path = handle.path
    assert os.path.isdir(path)

    result = await workspace.cleanup(handle)

    assert result is True
    assert not os.path.exists(path)


async def test_cleanup_returns_false_for_unknown(workspace: LocalWorkspace) -> None:
    fake_handle = WorkspaceHandle(
        workspace_id="nonexistent",
        agent_id="a",
        task_id="t",
        path="/tmp/nonexistent_ws",
        strategy=WorkspaceStrategy.TEMP_DIR,
        created_at=time.time(),
    )
    result = await workspace.cleanup(fake_handle)
    assert result is False


async def test_list_active_tracks_handles(workspace: LocalWorkspace) -> None:
    spec = WorkspaceSpec(strategy=WorkspaceStrategy.TEMP_DIR, base_path="/tmp")
    h1 = await workspace.create(spec, "agent1", "task1")
    h2 = await workspace.create(spec, "agent2", "task2")
    try:
        active = await workspace.list_active()
        assert len(active) == 2
        ids = {h.workspace_id for h in active}
        assert h1.workspace_id in ids
        assert h2.workspace_id in ids
    finally:
        await workspace.cleanup(h1)
        await workspace.cleanup(h2)


async def test_list_active_after_cleanup_excluded(workspace: LocalWorkspace) -> None:
    spec = WorkspaceSpec(strategy=WorkspaceStrategy.TEMP_DIR, base_path="/tmp")
    h1 = await workspace.create(spec, "agent1", "task1")
    h2 = await workspace.create(spec, "agent2", "task2")
    try:
        await workspace.cleanup(h1)
        active = await workspace.list_active()
        assert len(active) == 1
        assert active[0].workspace_id == h2.workspace_id
    finally:
        await workspace.cleanup(h2)


async def test_concurrent_creates_independent_paths(workspace: LocalWorkspace) -> None:
    spec = WorkspaceSpec(strategy=WorkspaceStrategy.TEMP_DIR, base_path="/tmp")
    handles = await asyncio.gather(
        workspace.create(spec, "a1", "t1"),
        workspace.create(spec, "a2", "t2"),
        workspace.create(spec, "a3", "t3"),
    )
    try:
        paths = [h.path for h in handles]
        assert len(set(paths)) == 3
        for p in paths:
            assert os.path.isdir(p)
    finally:
        for h in handles:
            await workspace.cleanup(h)


# --- COPY strategy ---


async def test_create_copy_strategy(tmp_path: object) -> None:
    """Create a temp source dir with a file, use COPY, verify file exists in workspace."""
    import pathlib

    source = pathlib.Path(str(tmp_path)) / "source_project"
    source.mkdir()
    (source / "main.py").write_text("print('hello')")

    ws = LocalWorkspace()
    spec = WorkspaceSpec(strategy=WorkspaceStrategy.COPY, base_path=str(source))
    handle = await ws.create(spec, "agent_copy", "task_copy")
    try:
        assert os.path.isdir(handle.path)
        copied_file = os.path.join(handle.path, "main.py")
        assert os.path.isfile(copied_file)
        with open(copied_file) as f:
            assert f.read() == "print('hello')"
    finally:
        await ws.cleanup(handle)


# --- Protocol shape ---


async def test_protocol_shape(workspace: LocalWorkspace) -> None:
    assert isinstance(workspace, ExecutionWorkspace)


# --- GIT_WORKTREE strategy (conditional) ---


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
async def test_create_git_worktree(tmp_path: object) -> None:
    """Create a git repo, add worktree via workspace, verify."""
    import pathlib

    repo = pathlib.Path(str(tmp_path)) / "repo"
    repo.mkdir()
    await _run("git", "init", str(repo))
    await _configure_git_identity(str(repo))
    (repo / "README.md").write_text("hello")
    await _run("git", "-C", str(repo), "add", ".")
    await _run("git", "-C", str(repo), "commit", "-m", "init")

    ws = LocalWorkspace()
    spec = WorkspaceSpec(strategy=WorkspaceStrategy.GIT_WORKTREE, base_path=str(repo))
    handle = await ws.create(spec, "agent1", "task1")
    assert os.path.isdir(handle.path)
    assert handle.strategy == WorkspaceStrategy.GIT_WORKTREE

    result = await ws.cleanup(handle)
    assert result is True
    assert not os.path.isdir(handle.path)


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
async def test_create_git_worktree_failure_raises(tmp_path: object) -> None:
    """Worktree on non-git directory raises RuntimeError."""
    import pathlib

    not_a_repo = pathlib.Path(str(tmp_path)) / "not_a_repo"
    not_a_repo.mkdir()

    ws = LocalWorkspace()
    spec = WorkspaceSpec(
        strategy=WorkspaceStrategy.GIT_WORKTREE, base_path=str(not_a_repo)
    )
    with pytest.raises(RuntimeError):
        await ws.create(spec, "agent1", "task1")


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
async def test_cleanup_git_worktree_deletes_custom_branch(tmp_path: object) -> None:
    import pathlib

    repo = pathlib.Path(str(tmp_path)) / "repo"
    repo.mkdir()
    await _run("git", "init", str(repo))
    await _configure_git_identity(str(repo))
    (repo / "README.md").write_text("hello")
    await _run("git", "-C", str(repo), "add", ".")
    await _run("git", "-C", str(repo), "commit", "-m", "init")

    ws = LocalWorkspace()
    spec = WorkspaceSpec(
        strategy=WorkspaceStrategy.GIT_WORKTREE,
        base_path=str(repo),
        branch_template="feature/{agent_name}-{task_id}",
    )
    handle = await ws.create(spec, "agent1", "task1")
    assert handle.branch_name == "feature/agent1-task1"

    try:
        assert os.path.isdir(handle.path)
    finally:
        result = await ws.cleanup(handle)

    assert result is True
    assert not os.path.isdir(handle.path)

    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        "branch",
        "--list",
        "feature/agent1-task1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()
    assert stdout.decode().strip() == ""
