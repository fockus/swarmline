# Attribution: adapted from aider (Apache-2.0)
# Upstream file: aider/linter.py, aider/coders/base_coder.py
# Copyright: (c) Paul Gauthier and contributors
# Changes: reimplemented for swarmline as AutoVerifyLoop bounded-budget
#          lint/test re-inject convergence loop. Design adapted from
#          aider's Linter.lint tree-context formatting and run_one re-inject
#          pattern. No aider code is copied verbatim.
"""AutoVerifyLoop — REQ-RCA-001/002/003 bounded-budget lint/test re-inject loop.

After an edit tool completes (when ``enable_auto_lint_test`` is True), runs the
configured lint/test command via :class:`WorkspaceVerificationRunner`, and:

* **PASS** → resets the reflection budget; returns ``None`` (no injection).
* **FAIL, budget remaining** → records the failure, builds a :class:`VerifyFeedback`,
  and returns it for re-injection as the next agent turn.
* **FAIL, budget exhausted** → returns ``None``; stops the re-inject loop
  (REQ-RCA-002).
* **No command configured** OR **non-code session** → returns ``None`` fail-open
  with no side effects (REQ-RCA-003).

OFF path (``enable_auto_lint_test=False``):
    :func:`wire_auto_verify_loop` returns ``None``, no
    :class:`AutoVerifyLoop` is ever constructed, and the turn loop is
    byte-identical to the pre-Task-1 behaviour.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from swarmline.runtime.thin.reflection import ReflectionState
from swarmline.workspace.verification import WorkspaceVerificationRunner

if TYPE_CHECKING:
    from swarmline.orchestration.code_verifier import CommandRunner
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig
    from swarmline.workspace.types import WorkspaceSession

_logger = logging.getLogger(__name__)

# Regex to extract file paths from lint/test output.
# Matches:
#   - ruff/flake8/mypy style: "path/to/file.py:line..."
#   - pytest FAILED style:    "FAILED tests/foo.py::test_name..."
#   - pytest ERROR style:     "ERROR tests/foo.py"
_FILE_PATH_RE = re.compile(
    r"(?:FAILED\s+|ERROR\s+)?"  # optional pytest prefix
    r"((?:[\w.\-]+/)*[\w.\-]+\.py)"  # capture: relative path ending in .py
    r"(?:::|:\d|\s+-)",  # followed by :: (pytest), :digit (lint), or " -" separator
)


# ---------------------------------------------------------------------------
# VerifyFeedback — pure value object (stdlib only, no framework deps)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifyFeedback:
    """Re-inject payload describing a lint/test failure.

    Attributes:
        summary:      One-line human-readable summary from the verification
                      runner (e.g. "tests failed (exit code 1)").
        detail:       Truncated stdout+stderr from the command; suitable for
                      inclusion in the agent's next user turn message.
        failing_files: File paths extracted from the output, deduplicated and
                      ordered by first appearance.
    """

    summary: str
    detail: str
    failing_files: tuple[str, ...]

    def to_turn_message(self) -> str:
        """Compose the full re-inject text for the agent's next user turn.

        Includes summary, the failing-file list (when non-empty) so the LLM
        knows exactly which files to look at, and the raw command output detail.
        This ensures ``failing_files`` actually reaches the model turn rather
        than being extracted and discarded (REQ-RCA-001).

        Format::

            [auto-verify] <summary>
            Failing files: a.py, b.py       ← omitted when failing_files is ()

            <detail>
        """
        parts: list[str] = [f"[auto-verify] {self.summary}"]
        if self.failing_files:
            parts.append(f"Failing files: {', '.join(self.failing_files)}")
        parts.append(self.detail)
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_failing_files(output: str) -> tuple[str, ...]:
    """Extract deduplicated file paths from lint/test command output.

    Parses ruff/flake8/mypy ("path.py:line:col: ...") and pytest ("FAILED
    tests/foo.py::..." or "ERROR tests/foo.py") patterns.  Returns paths in
    order of first appearance, deduplicated.
    """
    seen: list[str] = []
    for m in _FILE_PATH_RE.finditer(output):
        path = m.group(1)
        if path and path not in seen:
            seen.append(path)
    return tuple(seen)


# ---------------------------------------------------------------------------
# AutoVerifyLoop
# ---------------------------------------------------------------------------


class AutoVerifyLoop:
    """Bounded-budget lint/test re-inject convergence loop.

    Composes :class:`~swarmline.workspace.verification.WorkspaceVerificationRunner`
    and :class:`~swarmline.runtime.thin.reflection.ReflectionState`.

    * Fail-open: if ``session`` is ``None`` or ``command`` is ``None``,
      :meth:`run` returns ``None`` with no error and no side effects.
    * Budget-bounded: after ``reflection.max_reflections`` consecutive
      failures, :meth:`run` returns ``None`` and stops re-injecting
      (REQ-RCA-002).
    * Reset on success: a passing run calls ``reflection.reset_on_success()``
      so a later failure can still reflect (mirrors the
      ``EditSnapshotCoordinator`` success-reset behaviour).
    """

    def __init__(
        self,
        runner: WorkspaceVerificationRunner,
        reflection: ReflectionState,
        *,
        session: WorkspaceSession | None = None,
        command: str | None = None,
    ) -> None:
        self._runner = runner
        self._reflection = reflection
        self._session = session
        self._command = command

    async def run(self) -> VerifyFeedback | None:
        """Run the configured command; return feedback for re-injection or None.

        Returns:
            :class:`VerifyFeedback` when the command fails and the budget
            permits another reflection, ``None`` otherwise.
        """
        # --- REQ-RCA-003 fail-open checks ---
        if self._session is None:
            return None  # non-code session: no workspace
        if not self._command:
            return None  # no command configured

        try:
            result = await self._runner.run_tests(self._session, command=self._command)
        except Exception:
            _logger.warning(
                "AutoVerifyLoop.run: verification runner raised (fail-open)",
                exc_info=True,
            )
            return None

        if result.passed:
            # Clean run → reset the budget (REQ-SCA-041 / mirrors EditSnapshotCoordinator)
            self._reflection.reset_on_success()
            return None

        # Failure path.
        if not self._reflection.should_reflect():
            # REQ-RCA-002: budget exhausted → stop re-injecting
            return None

        self._reflection.record_failure()

        # Build VerifyFeedback from the first CheckDetail's message (truncated output).
        detail = result.checks[0].message if result.checks else result.summary
        failing_files = _extract_failing_files(detail)

        return VerifyFeedback(
            summary=result.summary,
            detail=detail,
            failing_files=failing_files,
        )


# ---------------------------------------------------------------------------
# Wiring helper
# ---------------------------------------------------------------------------


def wire_auto_verify_loop(
    config: CodingProfileConfig,
    command_runner: CommandRunner,
    *,
    session: WorkspaceSession | None = None,
) -> AutoVerifyLoop | None:
    """Build an :class:`AutoVerifyLoop` from config, or ``None`` when OFF.

    When ``config.enable_auto_lint_test`` is ``False`` (the default), this
    function returns ``None`` immediately — no :class:`AutoVerifyLoop` is
    constructed, and the turn loop remains byte-identical.

    Args:
        config:         ``CodingProfileConfig`` carrying the feature flags and
                        ``auto_verify_command`` / ``max_reflections`` values.
        command_runner: Sandbox-agnostic :class:`CommandRunner` for process
                        execution.
        session:        Optional :class:`WorkspaceSession`; when ``None`` the
                        loop will fail-open on every :meth:`~AutoVerifyLoop.run`
                        call (REQ-RCA-003).

    Returns:
        :class:`AutoVerifyLoop` if the flag is on, ``None`` otherwise.
    """
    if not config.enable_auto_lint_test:
        return None  # OFF path: byte-identical; no loop constructed

    reflection = ReflectionState(max_reflections=config.max_reflections)
    runner = WorkspaceVerificationRunner(command_runner)
    return AutoVerifyLoop(
        runner,
        reflection,
        session=session,
        command=config.auto_verify_command,
    )
