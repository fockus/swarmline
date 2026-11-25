"""Tests for EditCheckpointer (Task 7, REQ-SCA-060) and round-trip write verify
(REQ-SCA-061).

EditCheckpointer composes the EXISTING workspace ports (GitOperationsPort +
OwnChangesTrackerPort) over a WorkspaceSession — no new Protocol. The git
integration tests build a real tmp git repo. The round-trip tests exercise the
always-on verify inside the edit strategies (strategy.py persist paths).
"""

from __future__ import annotations

import asyncio
import json
import shlex
from typing import Any

import pytest

from swarmline.tools.types import ExecutionResult
from swarmline.workspace.git_local import LocalGitOperations
from swarmline.workspace.mutation import OwnChangesTracker
from swarmline.workspace.types import MutationMode, WorkspaceSession

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Test sandboxes
# ---------------------------------------------------------------------------


class _HostSandbox:
    """Minimal SandboxProvider that runs commands on the host (test-only).

    Only ``execute`` is exercised by EditCheckpointer. The constructed commands
    are ``git -C <worktree> ...`` so the host cwd is irrelevant.
    """

    async def read_file(self, path: str) -> str:  # pragma: no cover - unused
        raise NotImplementedError

    async def write_file(self, path: str, content: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def execute(self, command: str) -> ExecutionResult:
        argv = shlex.split(command)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return ExecutionResult(
            stdout=out.decode("utf-8", errors="replace"),
            stderr=err.decode("utf-8", errors="replace"),
            exit_code=proc.returncode if proc.returncode is not None else 0,
            timed_out=False,
        )

    async def list_dir(self, path: str = ".") -> list[str]:  # pragma: no cover
        raise NotImplementedError

    async def glob_files(self, pattern: str) -> list[str]:  # pragma: no cover
        raise NotImplementedError


async def _run(cwd: str, *args: str) -> tuple[int, str, str]:
    """Run a host command, returning (exit_code, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return (
        proc.returncode if proc.returncode is not None else 0,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )


async def _make_repo_with_user_commit(repo: str) -> str:
    """Init a git repo, configure identity, and create one USER commit.

    Returns the full SHA of the user commit.
    """
    await _run(repo, "git", "init")
    await _run(repo, "git", "config", "user.email", "user@example.com")
    await _run(repo, "git", "config", "user.name", "Real User")
    await _run(repo, "git", "config", "commit.gpgsign", "false")
    file_path = f"{repo}/file.txt"
    with open(file_path, "w", encoding="utf-8") as fh:
        fh.write("original\n")
    await _run(repo, "git", "add", "file.txt")
    await _run(repo, "git", "commit", "-m", "user commit")
    code, sha, _ = await _run(repo, "git", "rev-parse", "HEAD")
    assert code == 0
    return sha.strip()


def _session(repo: str) -> WorkspaceSession:
    return WorkspaceSession.create(
        session_id="sess-1",
        repo_root=repo,
        branch="main",
        worktree_path=repo,
        mutation_mode=MutationMode.AUTO_APPLY,
    )


# ---------------------------------------------------------------------------
# EditCheckpointer — git integration
# ---------------------------------------------------------------------------


class TestEditCheckpointerGit:
    async def test_edit_checkpointer_stages_fresh_edit(self, tmp_path: Any) -> None:
        """A FRESHLY-edited file is STAGED then committed (a non-empty
        checkpoint, NOT "nothing to commit") and recorded as own."""
        from swarmline.runtime.thin.edit_checkpointer import EditCheckpointer

        repo = str(tmp_path)
        await _make_repo_with_user_commit(repo)
        # One commit exists so far (the user commit).
        _, count_before, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")

        # Fresh edit on disk (editor already wrote it) — not yet staged.
        with open(f"{repo}/file.txt", "w", encoding="utf-8") as fh:
            fh.write("edited content\n")

        session = _session(repo)
        own = OwnChangesTracker()
        cp = EditCheckpointer(LocalGitOperations(), own, _HostSandbox())

        sha = await cp.checkpoint(session, ("file.txt",), "checkpoint: edit file")

        assert sha, "checkpoint must return a non-empty SHA for a fresh edit"
        assert own.is_own_commit("sess-1", sha) is True
        # A real (non-empty) checkpoint: commit count increased by exactly one.
        _, count_after, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")
        assert int(count_after) == int(count_before) + 1
        # The edit is committed → working tree clean, content persisted.
        _, status, _ = await _run(repo, "git", "status", "--porcelain")
        assert status.strip() == ""
        _, show, _ = await _run(repo, "git", "show", "HEAD:file.txt")
        assert show == "edited content\n"

    async def test_edit_checkpointer_own_only(self, tmp_path: Any) -> None:
        """undo_last_own reverts an OWN checkpoint but NOT a preceding USER
        commit (is_own_commit is False for the user commit)."""
        from swarmline.runtime.thin.edit_checkpointer import EditCheckpointer

        repo = str(tmp_path)
        user_sha = await _make_repo_with_user_commit(repo)

        session = _session(repo)
        own = OwnChangesTracker()
        cp = EditCheckpointer(LocalGitOperations(), own, _HostSandbox())

        # The user commit is NOT owned by the session.
        assert own.is_own_commit("sess-1", user_sha) is False

        # Agent makes a fresh edit and checkpoints it.
        with open(f"{repo}/file.txt", "w", encoding="utf-8") as fh:
            fh.write("agent edit\n")
        own_sha = await cp.checkpoint(session, ("file.txt",), "agent checkpoint")
        assert own_sha
        assert own.is_own_commit("sess-1", own_sha) is True
        assert own.is_own_commit("sess-1", user_sha) is False

        # undo_last_own reverts ONLY the own checkpoint (HEAD).
        reverted = await cp.undo_last_own(session)
        assert reverted == own_sha
        # File content is back to the user's version — the user commit's effect.
        with open(f"{repo}/file.txt", encoding="utf-8") as fh:
            assert fh.read() == "original\n"

        # A second undo must NOT touch the user commit: HEAD is now the revert
        # commit (not own) → no-op.
        again = await cp.undo_last_own(session)
        assert again is None
        with open(f"{repo}/file.txt", encoding="utf-8") as fh:
            assert fh.read() == "original\n"

    async def test_checkpoint_non_git_session_returns_none(self) -> None:
        """A non-git session (worktree_path None) → checkpoint returns None,
        no commit, no error; undo_last_own also returns None."""
        from swarmline.runtime.thin.edit_checkpointer import EditCheckpointer

        executed: list[str] = []

        class _NoExecSandbox:
            async def read_file(self, path: str) -> str:
                raise NotImplementedError

            async def write_file(self, path: str, content: str) -> None:
                raise NotImplementedError

            async def execute(self, command: str) -> ExecutionResult:
                executed.append(command)
                raise AssertionError("execute must not run for a non-git session")

            async def list_dir(self, path: str = ".") -> list[str]:
                raise NotImplementedError

            async def glob_files(self, pattern: str) -> list[str]:
                raise NotImplementedError

        session = WorkspaceSession.create(
            session_id="s",
            repo_root="/tmp/no-such-repo",
            branch="main",
            worktree_path=None,
            mutation_mode=MutationMode.AUTO_APPLY,
        )
        cp = EditCheckpointer(
            LocalGitOperations(), OwnChangesTracker(), _NoExecSandbox()
        )

        assert await cp.checkpoint(session, ("file.txt",), "msg") is None
        assert await cp.undo_last_own(session) is None
        assert executed == []

    async def test_checkpoint_no_paths_returns_none(self, tmp_path: Any) -> None:
        """Empty paths → nothing to checkpoint → None (no commit)."""
        from swarmline.runtime.thin.edit_checkpointer import EditCheckpointer

        repo = str(tmp_path)
        await _make_repo_with_user_commit(repo)
        _, count_before, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")

        cp = EditCheckpointer(LocalGitOperations(), OwnChangesTracker(), _HostSandbox())
        sha = await cp.checkpoint(_session(repo), (), "no paths")
        assert sha is None
        _, count_after, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")
        assert int(count_after) == int(count_before)

    async def test_checkpoint_fail_open_when_sandbox_execute_raises(
        self, tmp_path: Any
    ) -> None:
        """A sandbox whose execute raises (e.g. host execution denied) must NOT
        propagate into the edit flow — checkpoint/undo are fail-open → None."""
        from swarmline.runtime.thin.edit_checkpointer import EditCheckpointer

        class _RaisingSandbox:
            async def read_file(self, path: str) -> str:
                raise NotImplementedError

            async def write_file(self, path: str, content: str) -> None:
                raise NotImplementedError

            async def execute(self, command: str) -> ExecutionResult:
                raise RuntimeError("host execution denied")

            async def list_dir(self, path: str = ".") -> list[str]:
                raise NotImplementedError

            async def glob_files(self, pattern: str) -> list[str]:
                raise NotImplementedError

        # Git-backed session (worktree set) so the gate passes and execute IS hit.
        session = WorkspaceSession.create(
            session_id="s",
            repo_root=str(tmp_path),
            branch="main",
            worktree_path=str(tmp_path),
            mutation_mode=MutationMode.AUTO_APPLY,
        )
        cp = EditCheckpointer(
            LocalGitOperations(), OwnChangesTracker(), _RaisingSandbox()
        )
        assert await cp.checkpoint(session, ("file.txt",), "msg") is None
        assert await cp.undo_last_own(session) is None


# ---------------------------------------------------------------------------
# Round-trip write verify (REQ-SCA-061) — strategy.py persist paths
# ---------------------------------------------------------------------------


class _DictSandbox:
    """In-memory sandbox; an optional ``mangle`` transforms content on write."""

    def __init__(self, initial: dict[str, str], mangle=None) -> None:
        self._store = dict(initial)
        self._mangle = mangle

    async def read_file(self, path: str) -> str:
        return self._store[path]

    async def write_file(self, path: str, content: str) -> None:
        self._store[path] = self._mangle(content) if self._mangle else content

    async def execute(self, command: str) -> ExecutionResult:  # pragma: no cover
        raise NotImplementedError

    async def list_dir(self, path: str = ".") -> list[str]:  # pragma: no cover
        raise NotImplementedError

    async def glob_files(self, pattern: str) -> list[str]:  # pragma: no cover
        raise NotImplementedError


class TestRoundtripWriteVerify:
    async def test_roundtrip_write_verify(self) -> None:
        """Round-trip detects a truncated write and surfaces a LOUD failed
        HunkResult; a faithful CRLF/BOM-mangled write is NOT a false positive."""
        from swarmline.tools.edit.strategy import Hunk, SearchReplaceStrategy

        # (1) Truncating sandbox drops the last 3 chars on every write → data loss.
        sandbox = _DictSandbox({"f.txt": "hello world\n"}, mangle=lambda c: c[:-3])
        outcome = await SearchReplaceStrategy().apply(
            (Hunk(path="f.txt", old="hello", new="HELLO"),),
            sandbox,  # type: ignore[arg-type]
            transactional=False,
        )
        assert outcome.applied is False
        mismatches = [r for r in outcome.results if r.failure == "roundtrip_mismatch"]
        assert mismatches, (
            f"expected roundtrip_mismatch; got {[r.failure for r in outcome.results]}"
        )
        assert "round-trip" in mismatches[0].detail.lower()

        # (2) CRLF + BOM mangling is BENIGN: normalization makes it equal → no
        #     false positive, the edit persists exactly as before (byte-identical
        #     success path).
        faithful = _DictSandbox(
            {"g.txt": "alpha\nbeta\n"},
            mangle=lambda c: "﻿" + c.replace("\n", "\r\n"),
        )
        ok = await SearchReplaceStrategy().apply(
            (Hunk(path="g.txt", old="alpha", new="ALPHA"),),
            faithful,  # type: ignore[arg-type]
            transactional=False,
        )
        assert ok.applied is True
        assert all(r.status == "persisted" for r in ok.results)

    async def test_roundtrip_write_verify_transactional(self) -> None:
        """The V4A transactional persist path also round-trip verifies and rolls
        back the whole transaction on a corrupted write."""
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy

        sandbox = _DictSandbox(
            {"a.txt": "alpha beta\n", "b.txt": "gamma delta\n"},
            # Corrupt only b.txt's write (truncate); a.txt writes faithfully.
            mangle=lambda c: c[:-4] if c.startswith("gamma") or "GAMMA" in c else c,
        )
        outcome = await V4APatchStrategy().apply(
            (
                Hunk(path="a.txt", old="alpha", new="ALPHA"),
                Hunk(path="b.txt", old="gamma", new="GAMMA"),
            ),
            sandbox,  # type: ignore[arg-type]
            transactional=True,
        )
        assert outcome.applied is False
        assert any(r.failure == "roundtrip_mismatch" for r in outcome.results)
        # a.txt writes faithfully → its rollback restores cleanly.
        assert await sandbox.read_file("a.txt") == "alpha beta\n"
        # b.txt's provider corrupts EVERY write, so even the rollback write of the
        # original is mangled — the transaction CANNOT truly restore it. It must be
        # surfaced LOUDLY as rollback_failed (manual recovery), never silently
        # reported as a clean rollback while left corrupted (all-or-nothing).
        assert any(
            r.path == "b.txt" and r.failure == "rollback_failed"
            for r in outcome.results
        )

    async def test_roundtrip_faithful_write_is_byte_identical(self) -> None:
        """A faithful sandbox: the round-trip verify changes nothing on success
        (same persisted results, applied=True)."""
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy

        sandbox = _DictSandbox({"x.txt": "one two three\n"})
        outcome = await V4APatchStrategy().apply(
            (Hunk(path="x.txt", old="two", new="TWO"),),
            sandbox,  # type: ignore[arg-type]
            transactional=True,
        )
        assert outcome.applied is True
        assert all(r.status == "persisted" for r in outcome.results)
        assert await sandbox.read_file("x.txt") == "one TWO three\n"


# ---------------------------------------------------------------------------
# CheckpointPostHook — wires checkpoint() into the edit flow (Task 7 wiring)
# ---------------------------------------------------------------------------


def _edit_outcome_json(path: str, *, applied: bool) -> str:
    """A minimal EditOutcome JSON as the edit executors serialize it."""
    return json.dumps(
        {
            "status": "ok" if applied else "error",
            "applied": applied,
            "mode": "single_file",
            "results": [{"path": path, "status": "persisted" if applied else "failed"}],
        }
    )


class TestEditSucceeded:
    @pytest.mark.parametrize(
        "out",
        [
            '{"applied": true, "results": [{"path": "a.py", "status": "persisted"}]}',
            '{"results": [{"path": "a.py", "status": "persisted"}]}',
            '{"status": "ok", "path": "a.py"}',  # LEGACY write/edit shape
            '{"status": "ok", "path": "a.py", "edits_applied": 2}',  # legacy multi_edit
            # Trailing annotation from a PRIOR post hook (guard churn / verify) — the
            # leading JSON must still be recognized (raw_decode tolerates the suffix).
            '{"status": "ok", "path": "a.py"}\n\n[churn] you edited docs repeatedly',
            '{"applied": true, "results": [{"path": "a.py", "status": "persisted"}]}'
            "\n\n[verify] lint clean",
        ],
    )
    def test_true_for_new_and_legacy_success(self, out: str) -> None:
        from swarmline.runtime.thin.edit_checkpointer import _edit_succeeded

        assert _edit_succeeded(out) is True

    @pytest.mark.parametrize(
        "out",
        [
            "not json",
            "",
            "12345",
            '{"applied": false, "results": [{"path": "a.py", "status": "persisted"}]}',
            '{"status": "error", "path": "a.py"}',
            '{"results": [{"path": "a.py", "status": "failed"}]}',
        ],
    )
    def test_false_for_failure_or_unparseable(self, out: str) -> None:
        from swarmline.runtime.thin.edit_checkpointer import _edit_succeeded

        assert _edit_succeeded(out) is False


class TestCheckpointPostHook:
    async def test_successful_edit_creates_checkpoint(self, tmp_path: Any) -> None:
        """A successful EditOutcome → the hook stages+commits an OWN checkpoint."""
        from swarmline.runtime.thin.edit_checkpointer import (
            CheckpointPostHook,
            EditCheckpointer,
        )

        repo = str(tmp_path)
        await _make_repo_with_user_commit(repo)
        # A fresh edit on disk so there is something to checkpoint.
        with open(f"{repo}/file.txt", "w", encoding="utf-8") as fh:
            fh.write("edited by agent\n")
        _, count_before, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")

        own = OwnChangesTracker()
        cp = EditCheckpointer(LocalGitOperations(), own, _HostSandbox())
        hook = CheckpointPostHook(cp, _session(repo))

        result = await hook(
            tool_name="write",
            tool_input={"path": "file.txt"},
            tool_output=_edit_outcome_json("file.txt", applied=True),
        )
        assert result is None  # the hook never modifies tool_output
        _, count_after, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")
        assert int(count_after) == int(count_before) + 1
        _, head, _ = await _run(repo, "git", "rev-parse", "HEAD")
        assert own.is_own_commit("sess-1", head.strip()) is True

    async def test_failed_edit_creates_no_checkpoint(self, tmp_path: Any) -> None:
        """An unapplied EditOutcome → no persisted paths → no checkpoint, no commit."""
        from swarmline.runtime.thin.edit_checkpointer import (
            CheckpointPostHook,
            EditCheckpointer,
        )

        repo = str(tmp_path)
        await _make_repo_with_user_commit(repo)
        with open(f"{repo}/file.txt", "w", encoding="utf-8") as fh:
            fh.write("edited but reported failed\n")
        _, count_before, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")

        cp = EditCheckpointer(LocalGitOperations(), OwnChangesTracker(), _HostSandbox())
        hook = CheckpointPostHook(cp, _session(repo))
        await hook(
            tool_name="write",
            tool_input={"path": "file.txt"},
            tool_output=_edit_outcome_json("file.txt", applied=False),
        )
        _, count_after, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")
        assert int(count_after) == int(count_before)

    async def test_legacy_write_output_creates_checkpoint_via_dispatcher(
        self, tmp_path: Any
    ) -> None:
        """E2E: the DEFAULT legacy executor's {"status":"ok","path":...} output —
        dispatched through the real registry's PostToolUse chain — still creates an
        own checkpoint (the path comes from tool_input, not the EditOutcome shape)."""
        from swarmline.hooks.dispatcher import DefaultHookDispatcher
        from swarmline.hooks.registry import HookRegistry
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig
        from swarmline.runtime.thin.edit_checkpointer import (
            EditCheckpointer,
            register_edit_checkpoint_hooks,
        )

        repo = str(tmp_path)
        await _make_repo_with_user_commit(repo)
        with open(f"{repo}/file.txt", "w", encoding="utf-8") as fh:
            fh.write("agent edit via legacy executor\n")
        _, count_before, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")

        own = OwnChangesTracker()
        cp = EditCheckpointer(LocalGitOperations(), own, _HostSandbox())
        registry = HookRegistry()
        register_edit_checkpoint_hooks(
            registry,
            checkpointer=cp,
            session=_session(repo),
            config=CodingProfileConfig(enabled=True, enable_git_checkpoints=True),
        )
        dispatcher = DefaultHookDispatcher(registry)

        # Legacy executor success shape — NO `applied`, NO `results`.
        out = await dispatcher.dispatch_post_tool(
            "write", {"path": "file.txt"}, '{"status": "ok", "path": "file.txt"}'
        )
        assert out is None  # checkpoint hook does not modify output
        _, count_after, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")
        assert int(count_after) == int(count_before) + 1
        _, head, _ = await _run(repo, "git", "rev-parse", "HEAD")
        assert own.is_own_commit("sess-1", head.strip()) is True

    async def test_checkpoint_fires_when_prior_post_hook_appends_annotation(
        self, tmp_path: Any
    ) -> None:
        """A PostToolUse hook registered BEFORE the checkpoint hook may APPEND text
        (e.g. the anti-flailing guard's churn hint), making the output non-JSON for a
        naive ``json.loads``. The checkpoint must STILL fire — ``_edit_succeeded``
        tolerates a trailing annotation (raw_decode). Regression for the cycle-4
        hook_ordering finding (an earlier modifier silently suppressed checkpoints).
        """
        from swarmline.hooks.dispatcher import DefaultHookDispatcher
        from swarmline.hooks.registry import HookRegistry
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig
        from swarmline.runtime.thin.edit_checkpointer import (
            EditCheckpointer,
            register_edit_checkpoint_hooks,
        )

        repo = str(tmp_path)
        await _make_repo_with_user_commit(repo)
        with open(f"{repo}/file.txt", "w", encoding="utf-8") as fh:
            fh.write("agent edit needing a checkpoint\n")
        _, count_before, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")

        own = OwnChangesTracker()
        cp = EditCheckpointer(LocalGitOperations(), own, _HostSandbox())
        registry = HookRegistry()

        # Prior post hook that APPENDS a churn-style annotation → output is no longer
        # bare JSON. Registered first so the dispatcher runs it BEFORE the checkpoint.
        async def churn_annotator(
            *, tool_name: str, tool_input: dict, tool_output: str
        ) -> str:
            return tool_output + "\n\n[churn] you have edited docs repeatedly"

        registry.on_post_tool_use(churn_annotator, matcher="write")
        register_edit_checkpoint_hooks(
            registry,
            checkpointer=cp,
            session=_session(repo),
            config=CodingProfileConfig(enabled=True, enable_git_checkpoints=True),
        )
        dispatcher = DefaultHookDispatcher(registry)

        out = await dispatcher.dispatch_post_tool(
            "write", {"path": "file.txt"}, '{"status": "ok", "path": "file.txt"}'
        )
        # The annotator's text survives in the final output...
        assert out is not None and "[churn]" in out
        # ...and the checkpoint STILL fired despite the preceding modification.
        _, count_after, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")
        assert int(count_after) == int(count_before) + 1
        _, head, _ = await _run(repo, "git", "rev-parse", "HEAD")
        assert own.is_own_commit("sess-1", head.strip()) is True


# ---------------------------------------------------------------------------
# Ownership isolation (cycle-4 fix) — scoped commit excludes pre-staged user work
# ---------------------------------------------------------------------------


class TestCheckpointOwnershipIsolation:
    async def test_checkpoint_excludes_pre_staged_unrelated_file(
        self, tmp_path: Any
    ) -> None:
        """A path-scoped commit must NOT sweep an unrelated PRE-STAGED user change
        into the OWN checkpoint — otherwise undo_last_own could revert user work.
        Regression for the cycle-4 ownership finding (the port's pathspec-less commit
        committed the whole index)."""
        from swarmline.runtime.thin.edit_checkpointer import EditCheckpointer

        repo = str(tmp_path)
        await _make_repo_with_user_commit(repo)
        # The user stages an UNRELATED change (not part of the agent's edit).
        with open(f"{repo}/user_wip.txt", "w", encoding="utf-8") as fh:
            fh.write("user work in progress\n")
        await _run(repo, "git", "add", "user_wip.txt")
        # The agent edits a DIFFERENT file and checkpoints only that path.
        with open(f"{repo}/file.txt", "w", encoding="utf-8") as fh:
            fh.write("agent edit\n")

        own = OwnChangesTracker()
        cp = EditCheckpointer(LocalGitOperations(), own, _HostSandbox())
        sha = await cp.checkpoint(_session(repo), ("file.txt",), "agent checkpoint")
        assert sha

        # The checkpoint commit contains ONLY file.txt — never the user's staged file.
        _, names, _ = await _run(
            repo, "git", "show", "--name-only", "--format=", "HEAD"
        )
        committed = [n for n in names.split() if n]
        assert committed == ["file.txt"], f"checkpoint swept extra paths: {committed}"
        # The user's staged change is still present and uncommitted (index preserved).
        _, status, _ = await _run(repo, "git", "status", "--porcelain")
        assert "user_wip.txt" in status

    async def test_checkpoint_fail_open_when_commit_fails(self, tmp_path: Any) -> None:
        """If the scoped commit fails (exit != 0) AFTER staging, checkpoint is
        fail-open: returns None and records NO own commit (no new commit created)."""
        from swarmline.runtime.thin.edit_checkpointer import EditCheckpointer

        repo = str(tmp_path)
        await _make_repo_with_user_commit(repo)
        with open(f"{repo}/file.txt", "w", encoding="utf-8") as fh:
            fh.write("agent edit\n")

        host = _HostSandbox()

        class _CommitFailsSandbox:
            async def read_file(self, path: str) -> str:
                raise NotImplementedError

            async def write_file(self, path: str, content: str) -> None:
                raise NotImplementedError

            async def execute(self, command: str) -> ExecutionResult:
                if " commit " in f" {command} ":
                    return ExecutionResult(
                        stdout="",
                        stderr="simulated commit failure",
                        exit_code=1,
                        timed_out=False,
                    )
                return await host.execute(command)

            async def list_dir(self, path: str = ".") -> list[str]:
                raise NotImplementedError

            async def glob_files(self, pattern: str) -> list[str]:
                raise NotImplementedError

        own = OwnChangesTracker()
        cp = EditCheckpointer(LocalGitOperations(), own, _CommitFailsSandbox())
        _, count_before, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")
        sha = await cp.checkpoint(_session(repo), ("file.txt",), "agent checkpoint")
        assert sha is None
        _, count_after, _ = await _run(repo, "git", "rev-list", "--count", "HEAD")
        assert int(count_after) == int(count_before)
