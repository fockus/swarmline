"""Tests for AutoVerifyLoop — REQ-RCA-001/002/003 bounded-budget re-inject loop.

TDD: tests written before implementation.

Naming convention: test_<what>_<condition>_<result>
Arrangement: Arrange-Act-Assert, @parametrize over copy-paste.
"""

from __future__ import annotations

import pytest
from swarmline.orchestration.code_verifier import CommandResult
from swarmline.runtime.thin.auto_verify_loop import (
    AutoVerifyLoop,
    VerifyFeedback,
    wire_auto_verify_loop,
)
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.runtime.thin.reflection import ReflectionState
from swarmline.workspace.types import WorkspaceSession
from swarmline.workspace.verification import WorkspaceVerificationRunner


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeCommandRunner:
    """Deterministic stub: returns a preset CommandResult for any command."""

    def __init__(self, *, exit_code: int, stdout: str = "", stderr: str = "") -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[str] = []

    async def run(self, command: str) -> CommandResult:
        self.calls.append(command)
        return CommandResult(
            exit_code=self.exit_code, stdout=self.stdout, stderr=self.stderr
        )


def make_session(
    repo_root: str = "/repo", worktree_path: str | None = None
) -> WorkspaceSession:
    """Build a minimal WorkspaceSession for tests."""
    return WorkspaceSession.create(
        session_id="test-session",
        repo_root=repo_root,
        branch="main",
        worktree_path=worktree_path,
    )


def make_loop(
    runner: FakeCommandRunner,
    *,
    max_reflections: int = 3,
    session: WorkspaceSession | None = None,
    command: str | None = "ruff check .",
) -> AutoVerifyLoop:
    reflection = ReflectionState(max_reflections=max_reflections)
    verification_runner = WorkspaceVerificationRunner(runner)
    return AutoVerifyLoop(
        verification_runner, reflection, session=session, command=command
    )


# ---------------------------------------------------------------------------
# Core behaviour: pass / fail / budget
# ---------------------------------------------------------------------------


class TestAutoVerifyLoopCoreLogic:
    @pytest.mark.asyncio
    async def test_failing_command_returns_feedback_with_output_and_failing_file(
        self,
    ) -> None:
        """REQ-RCA-001: failing command → VerifyFeedback with output + file path."""
        output = "src/foo.py:1:1: E001 some error\nsrc/foo.py:5:3: E002 another"
        runner = FakeCommandRunner(exit_code=1, stdout=output)
        reflection = ReflectionState(max_reflections=3)
        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            reflection,
            session=make_session("/repo"),
            command="ruff check .",
        )

        feedback = await loop.run()

        assert feedback is not None
        assert isinstance(feedback, VerifyFeedback)
        # summary comes from VerificationResult.summary
        assert "fail" in feedback.summary.lower()
        # detail holds (truncated) output
        assert "E001" in feedback.detail
        # failing_files extracted from output
        assert "src/foo.py" in feedback.failing_files
        # reflection budget consumed
        assert reflection.count == 1

    @pytest.mark.asyncio
    async def test_passing_command_returns_none_and_resets_reflection_budget(
        self,
    ) -> None:
        """REQ-RCA-001: passing command → None + reset_on_success."""
        runner = FakeCommandRunner(exit_code=0, stdout="All checks passed.")
        reflection = ReflectionState(max_reflections=3)
        reflection.record_failure()  # pre-existing failure
        assert reflection.count == 1

        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            reflection,
            session=make_session("/repo"),
            command="ruff check .",
        )

        feedback = await loop.run()

        assert feedback is None
        assert reflection.count == 0  # reset_on_success called

    @pytest.mark.asyncio
    async def test_budget_exhausted_returns_none_without_looping_further(
        self,
    ) -> None:
        """REQ-RCA-002: budget exhausted (should_reflect=False) → None, no increment."""
        output = "src/bar.py:10:1: E100 bad"
        runner = FakeCommandRunner(exit_code=1, stdout=output)
        reflection = ReflectionState(max_reflections=2)
        reflection.record_failure()
        reflection.record_failure()  # at cap
        assert reflection.should_reflect() is False

        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            reflection,
            session=make_session("/repo"),
            command="pytest",
        )

        feedback = await loop.run()

        assert feedback is None
        assert reflection.count == 2  # NOT incremented further

    @pytest.mark.asyncio
    async def test_multiple_reflections_bounded_to_max(self) -> None:
        """Feedback returned exactly max_reflections times, then suppressed."""
        output = "src/x.py:1: E999 err"
        runner = FakeCommandRunner(exit_code=1, stdout=output)
        reflection = ReflectionState(max_reflections=2)
        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            reflection,
            session=make_session("/repo"),
            command="ruff check .",
        )

        results = [await loop.run() for _ in range(4)]

        # First 2 → VerifyFeedback; 3rd and 4th → None (budget exhausted)
        assert results[0] is not None
        assert results[1] is not None
        assert results[2] is None
        assert results[3] is None
        assert reflection.count == 2  # cap not exceeded


# ---------------------------------------------------------------------------
# Fail-open cases: REQ-RCA-003
# ---------------------------------------------------------------------------


class TestAutoVerifyLoopFailOpen:
    @pytest.mark.asyncio
    async def test_no_command_configured_returns_none_no_side_effects(self) -> None:
        """REQ-RCA-003: no command configured → None, no runner called, no error."""
        runner = FakeCommandRunner(exit_code=1, stdout="error")
        reflection = ReflectionState(max_reflections=3)

        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            reflection,
            session=make_session("/repo"),
            command=None,  # no command
        )

        feedback = await loop.run()

        assert feedback is None
        assert reflection.count == 0
        assert runner.calls == []  # CommandRunner never invoked

    @pytest.mark.asyncio
    async def test_non_code_session_returns_none_no_side_effects(self) -> None:
        """REQ-RCA-003: non-code session (session=None) → None, no runner, no error."""
        runner = FakeCommandRunner(exit_code=1, stdout="error")
        reflection = ReflectionState(max_reflections=3)

        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            reflection,
            session=None,  # no session
            command="pytest",
        )

        feedback = await loop.run()

        assert feedback is None
        assert reflection.count == 0
        assert runner.calls == []

    @pytest.mark.parametrize(
        "exit_code,stdout",
        [
            (0, ""),  # pass, no command
            (1, "errors here"),  # fail, no command
        ],
    )
    @pytest.mark.asyncio
    async def test_no_command_failopen_regardless_of_exit_code(
        self, exit_code: int, stdout: str
    ) -> None:
        """Fail-open on no command regardless of what the runner would return."""
        runner = FakeCommandRunner(exit_code=exit_code, stdout=stdout)
        reflection = ReflectionState(max_reflections=3)
        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            reflection,
            session=make_session("/repo"),
            command=None,
        )

        result = await loop.run()

        assert result is None
        assert runner.calls == []


# ---------------------------------------------------------------------------
# VerifyFeedback content: failing_files extraction
# ---------------------------------------------------------------------------


class TestVerifyFeedbackContent:
    @pytest.mark.asyncio
    async def test_feedback_failing_files_extracted_from_ruff_output(self) -> None:
        """Failing files are parsed from ruff-style 'file.py:line:col:' output."""
        output = "src/alpha.py:1:1: E001 error\nsrc/beta.py:5:3: E002 another"
        runner = FakeCommandRunner(exit_code=1, stdout=output)
        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            ReflectionState(max_reflections=3),
            session=make_session("/repo"),
            command="ruff check .",
        )

        feedback = await loop.run()

        assert feedback is not None
        assert "src/alpha.py" in feedback.failing_files
        assert "src/beta.py" in feedback.failing_files

    @pytest.mark.asyncio
    async def test_feedback_failing_files_extracted_from_pytest_failed_output(
        self,
    ) -> None:
        """Failing files are parsed from pytest 'FAILED tests/foo.py::...' output."""
        output = "FAILED tests/test_foo.py::test_bar - AssertionError"
        runner = FakeCommandRunner(exit_code=1, stdout=output)
        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            ReflectionState(max_reflections=3),
            session=make_session("/repo"),
            command="pytest",
        )

        feedback = await loop.run()

        assert feedback is not None
        assert "tests/test_foo.py" in feedback.failing_files

    @pytest.mark.asyncio
    async def test_feedback_detail_contains_truncated_output(self) -> None:
        """VerifyFeedback.detail contains the (possibly truncated) command output."""
        output = "src/x.py:1: E001 some lint error"
        runner = FakeCommandRunner(exit_code=1, stdout=output)
        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            ReflectionState(max_reflections=3),
            session=make_session("/repo"),
            command="ruff check .",
        )

        feedback = await loop.run()

        assert feedback is not None
        assert "E001" in feedback.detail

    @pytest.mark.asyncio
    async def test_feedback_no_failing_files_when_output_has_no_paths(self) -> None:
        """failing_files is empty tuple when output has no parseable file paths."""
        output = "some generic error with no file paths"
        runner = FakeCommandRunner(exit_code=1, stdout=output)
        loop = AutoVerifyLoop(
            WorkspaceVerificationRunner(runner),
            ReflectionState(max_reflections=3),
            session=make_session("/repo"),
            command="pytest",
        )

        feedback = await loop.run()

        assert feedback is not None
        assert isinstance(feedback.failing_files, tuple)


# ---------------------------------------------------------------------------
# VerifyFeedback value object
# ---------------------------------------------------------------------------


class TestVerifyFeedbackDataclass:
    def test_verify_feedback_is_frozen(self) -> None:
        """VerifyFeedback is a frozen dataclass (immutable value object)."""
        import dataclasses

        fb = VerifyFeedback(summary="s", detail="d", failing_files=())
        assert dataclasses.is_dataclass(fb)
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            fb.summary = "other"  # type: ignore[misc]

    def test_verify_feedback_equality(self) -> None:
        """Value-based equality."""
        a = VerifyFeedback(summary="s", detail="d", failing_files=("f.py",))
        b = VerifyFeedback(summary="s", detail="d", failing_files=("f.py",))
        assert a == b


# ---------------------------------------------------------------------------
# OFF-path regression: wire_auto_verify_loop with flag=False (REQ-RCA-003)
# ---------------------------------------------------------------------------


class TestWireAutoVerifyLoop:
    def test_enable_auto_lint_test_off_no_loop_constructed(self) -> None:
        """REQ-RCA-003 / OFF-path regression: default config (flag=False) →
        wire_auto_verify_loop returns None; no AutoVerifyLoop is constructed.

        Mirrors TestRegistration.test_not_registered_when_flag_off from
        test_edit_verify_coordinator.py which asserts that no hooks are
        registered when enable_post_edit_verify=False.
        """
        config = CodingProfileConfig()  # enable_auto_lint_test defaults to False
        fake_runner = FakeCommandRunner(exit_code=0, stdout="")

        loop = wire_auto_verify_loop(config, fake_runner)

        assert loop is None, (
            "OFF path (enable_auto_lint_test=False) must not construct AutoVerifyLoop"
        )

    def test_enable_auto_lint_test_on_constructs_loop(self) -> None:
        """ON path: wire_auto_verify_loop returns an AutoVerifyLoop instance."""
        config = CodingProfileConfig(
            enable_auto_lint_test=True, auto_verify_command="pytest"
        )
        fake_runner = FakeCommandRunner(exit_code=0, stdout="")

        loop = wire_auto_verify_loop(config, fake_runner)

        assert loop is not None
        assert isinstance(loop, AutoVerifyLoop)

    def test_wire_respects_max_reflections_from_config(self) -> None:
        """wire_auto_verify_loop builds ReflectionState from config.max_reflections."""
        config = CodingProfileConfig(
            enable_auto_lint_test=True,
            max_reflections=7,
            auto_verify_command="ruff check .",
        )
        fake_runner = FakeCommandRunner(exit_code=0, stdout="")

        loop = wire_auto_verify_loop(config, fake_runner)

        assert loop is not None
        # Expose internal state for white-box assertion
        assert loop._reflection.max_reflections == 7


# ---------------------------------------------------------------------------
# VerifyFeedback.to_turn_message — REQ-RCA-001 (code context reaches the LLM)
# ---------------------------------------------------------------------------


class TestVerifyFeedbackToTurnMessage:
    """VerifyFeedback.to_turn_message() composes the re-inject text so that the
    failing-files list ACTUALLY reaches the agent turn (F1 fix).

    Without this method, failing_files was extracted but never included in the
    text sent to the LLM — a dead-field / requirement-gap.
    """

    def test_to_turn_message_contains_summary(self) -> None:
        """The composed message begins with the '[auto-verify]' summary line."""
        fb = VerifyFeedback(
            summary="tests failed (exit code 1)",
            detail="src/foo.py:1: E001 error",
            failing_files=(),
        )
        msg = fb.to_turn_message()
        assert "[auto-verify]" in msg
        assert "tests failed (exit code 1)" in msg

    def test_to_turn_message_contains_detail(self) -> None:
        """The composed message includes the detail (truncated command output)."""
        fb = VerifyFeedback(
            summary="tests failed (exit code 1)",
            detail="src/foo.py:1: E001 some lint error",
            failing_files=(),
        )
        msg = fb.to_turn_message()
        assert "E001 some lint error" in msg

    def test_to_turn_message_includes_failing_files_when_present(self) -> None:
        """When failing_files is non-empty, each path appears in the message."""
        fb = VerifyFeedback(
            summary="tests failed (exit code 1)",
            detail="src/alpha.py:1: E001\nsrc/beta.py:5: E002",
            failing_files=("src/alpha.py", "src/beta.py"),
        )
        msg = fb.to_turn_message()
        assert "src/alpha.py" in msg
        assert "src/beta.py" in msg

    def test_to_turn_message_includes_failing_files_label_when_present(self) -> None:
        """The 'Failing files:' label is present when failing_files is non-empty."""
        fb = VerifyFeedback(
            summary="s",
            detail="d",
            failing_files=("tests/test_x.py",),
        )
        msg = fb.to_turn_message()
        assert "Failing files:" in msg
        assert "tests/test_x.py" in msg

    def test_to_turn_message_omits_failing_files_label_when_empty(self) -> None:
        """No dangling 'Failing files:' label when failing_files is empty."""
        fb = VerifyFeedback(
            summary="lint failed",
            detail="some generic error with no parseable paths",
            failing_files=(),
        )
        msg = fb.to_turn_message()
        assert "Failing files:" not in msg

    @pytest.mark.parametrize(
        "files,expected_in_msg",
        [
            (("a.py", "b.py", "c.py"), "a.py"),
            (("a.py", "b.py", "c.py"), "b.py"),
            (("a.py", "b.py", "c.py"), "c.py"),
            ((), None),  # no paths → no "Failing files:" label
        ],
    )
    def test_to_turn_message_parametrized_files_coverage(
        self, files: tuple[str, ...], expected_in_msg: str | None
    ) -> None:
        """Parametrized: each file path appears; absent list → no label."""
        fb = VerifyFeedback(summary="s", detail="d", failing_files=files)
        msg = fb.to_turn_message()
        if expected_in_msg is not None:
            assert expected_in_msg in msg
        else:
            assert "Failing files:" not in msg
