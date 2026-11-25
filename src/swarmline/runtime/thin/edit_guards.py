"""Anti-flailing edit guards + provenance trust-labels (Task 6).

REQ-SCA-050/051/052. Three concerns, each fail-open:

* :class:`PreEditGuardHook` — a hard-cap REFUSAL. A refusal cannot live in
  PostToolUse because the mutation has already happened by then (M3), so the
  cap is enforced in PreToolUse: once a path has failed ``hard_cap`` times in a
  row, the next edit on it is blocked with an actionable hint BEFORE any write.
* :class:`PostEditGuardHook` — records per-path edit OUTCOMES, escalates a hint
  after ``escalate_threshold`` consecutive failures, resets the streak on
  success, and flags summary/doc-write churn.
* :class:`ProvenancePostHook` — annotates a read/bash whose path was written by
  THIS agent (per the shared :class:`OwnChangesTrackerPort`, M2 — no new
  tracker type) with a trust-label so the model does not mistake its own output
  for an independent measurement.

Outcome detection: the edit executors serialize an ``EditOutcome`` to JSON
(Task 1) with an ``applied`` boolean and/or a ``status`` of ``"ok"``/``"error"``.
This module parses that JSON conservatively: ``applied`` (when present) is
authoritative; otherwise ``status`` decides; anything unparseable carries no
outcome info and is a silent no-op (never a recorded failure, never a raise).

These guards are registered ONLY when ``coding_profile.enable_edit_guards`` is
True. The default path registers nothing and stays byte-identical.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from swarmline.hooks.dispatcher import HookResult
from swarmline.runtime.thin.edit_verify_coordinator import EDIT_TOOL_NAMES

if TYPE_CHECKING:
    from swarmline.hooks.registry import HookRegistry
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig
    from swarmline.workspace.protocols import OwnChangesTrackerPort

logger = logging.getLogger(__name__)

# Tool names that receive a provenance trust-label on their PostToolUse output.
_PROVENANCE_TOOL_NAMES: tuple[str, ...] = ("read", "bash")

# Substrings/suffixes that mark a written artifact as a summary/notes/doc file.
_DOC_SUFFIXES: tuple[str, ...] = (".md", ".rst", ".txt")
_DOC_PATH_MARKERS: tuple[str, ...] = ("summary", "notes", "changelog")


@dataclass
class EditGuardState:
    """Mutable per-run anti-flailing accounting.

    Counters are populated by :class:`PostEditGuardHook` and read by
    :class:`PreEditGuardHook`. Thresholds are overridable; sensible defaults are
    provided by :meth:`with_defaults`.

    Attributes:
        consecutive_failures: path → number of back-to-back failed edits (reset
            to 0 on a successful edit of that path).
        edits_per_path: path → total edit attempts (successes + failures).
        summary_doc_writes: count of summary/notes/doc artifacts written.
        escalate_threshold: consecutive failures at which a hint is appended.
        hard_cap: consecutive failures at which Pre refuses the next edit.
        churn_threshold: summary/doc writes at which a churn hint is appended.
    """

    consecutive_failures: dict[str, int] = field(default_factory=dict)
    edits_per_path: dict[str, int] = field(default_factory=dict)
    summary_doc_writes: int = 0
    escalate_threshold: int = 3
    hard_cap: int = 5
    churn_threshold: int = 5

    @classmethod
    def with_defaults(
        cls,
        *,
        escalate_threshold: int = 3,
        hard_cap: int = 5,
        churn_threshold: int = 5,
    ) -> EditGuardState:
        """Build a fresh state with documented, overridable thresholds."""
        return cls(
            escalate_threshold=escalate_threshold,
            hard_cap=hard_cap,
            churn_threshold=churn_threshold,
        )


def _paths_for(tool_name: str, tool_input: dict) -> list[str]:
    """Extract mutated path(s) from an edit/write tool's input.

    Mirrors ``EditSnapshotCoordinator._paths_for``: edit/write/multi_edit use a
    single ``path`` key; multi_file_edit carries ``edits: [{path, ...}]``.
    """
    if tool_name == "multi_file_edit":
        edits = tool_input.get("edits") or []
        seen: list[str] = []
        for edit in edits:
            path = edit.get("path") if isinstance(edit, dict) else None
            if isinstance(path, str) and path and path not in seen:
                seen.append(path)
        return seen
    path = tool_input.get("path")
    return [path] if isinstance(path, str) and path else []


def _outcome_succeeded(tool_output: str) -> bool | None:
    """Decide whether an edit tool_output reports success, failure, or nothing.

    Returns ``True`` (applied/persisted), ``False`` (failed/not applied), or
    ``None`` when the output carries no recognizable outcome (unparseable JSON,
    non-object JSON, or a payload without ``applied``/``status``). Never raises.
    """
    try:
        payload = json.loads(tool_output)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    applied = payload.get("applied")
    if isinstance(applied, bool):
        return applied
    status = payload.get("status")
    if status == "ok":
        return True
    if status == "error":
        return False
    return None


def _looks_like_doc(path: str) -> bool:
    """True when a written path resembles a summary/notes/doc artifact.

    Either a doc-ish suffix (``.md``/``.rst``/``.txt``) OR a doc-ish path marker
    (``summary``/``notes``/``changelog``) is enough — code files (e.g. ``.py``)
    without such a marker never count toward churn.
    """
    lowered = path.lower()
    if lowered.endswith(_DOC_SUFFIXES):
        return True
    return any(marker in lowered for marker in _DOC_PATH_MARKERS)


class PreEditGuardHook:
    """PreToolUse guard: refuse an edit once its path hit the hard-cap (M3).

    The mutation has NOT happened yet at PreToolUse, so this is the only place a
    hard refusal can prevent further flailing on a path that keeps failing.
    """

    def __init__(self, state: EditGuardState) -> None:
        self._state = state

    async def __call__(self, *, tool_name: str, tool_input: dict) -> HookResult:
        try:
            if tool_name not in EDIT_TOOL_NAMES:
                return HookResult.allow()
            for path in _paths_for(tool_name, tool_input):
                failures = self._state.consecutive_failures.get(path, 0)
                if failures >= self._state.hard_cap:
                    return HookResult.block(
                        f"refusing to edit {path}: {failures} consecutive failed "
                        f"edits on this file (hard cap {self._state.hard_cap}). "
                        "Stop retrying the same edit — re-read the file, choose a "
                        "different, unique anchor, or take another approach before "
                        "editing it again."
                    )
            return HookResult.allow()
        except Exception:
            logger.warning(
                "PreEditGuardHook failed for %r (fail-open, allowing)",
                tool_name,
                exc_info=True,
            )
            return HookResult.allow()


class PostEditGuardHook:
    """PostToolUse guard: record edit outcomes, escalate hints, flag churn.

    Records OUTCOMES only — it never blocks (a Post hook cannot, M3). On failure
    it grows the per-path consecutive-failure streak and, at/after
    ``escalate_threshold``, appends an actionable hint. On success it zeroes the
    streak. Summary/doc writes are counted and, at/after ``churn_threshold``, a
    churn hint is appended. Returns the augmented output, or ``None`` when there
    is nothing to add. Fail-open: any exception → ``None``.
    """

    def __init__(self, state: EditGuardState) -> None:
        self._state = state

    async def __call__(
        self, *, tool_name: str, tool_input: dict, tool_output: str
    ) -> str | None:
        try:
            if tool_name not in EDIT_TOOL_NAMES:
                return None
            succeeded = _outcome_succeeded(tool_output)
            if succeeded is None:
                return None  # no recognizable outcome → record nothing

            hints: list[str] = []
            for path in _paths_for(tool_name, tool_input):
                self._state.edits_per_path[path] = (
                    self._state.edits_per_path.get(path, 0) + 1
                )
                if succeeded:
                    self._state.consecutive_failures[path] = 0
                    if _looks_like_doc(path):
                        churn_hint = self._record_doc_write()
                        if churn_hint is not None:
                            hints.append(churn_hint)
                else:
                    streak = self._state.consecutive_failures.get(path, 0) + 1
                    self._state.consecutive_failures[path] = streak
                    if streak >= self._state.escalate_threshold:
                        hints.append(self._escalation_hint(path, streak))

            if not hints:
                return None
            return tool_output + "\n\n" + "\n".join(hints)
        except Exception:
            logger.warning(
                "PostEditGuardHook failed for %r (fail-open)",
                tool_name,
                exc_info=True,
            )
            return None

    def _record_doc_write(self) -> str | None:
        """Increment the doc-write counter; return a churn hint at the threshold."""
        self._state.summary_doc_writes += 1
        count = self._state.summary_doc_writes
        if count >= self._state.churn_threshold:
            return (
                f"[churn_flag] you've written {count} summary/doc files this run — "
                "focus on the actual task and its code/tests, not status documents."
            )
        return None

    def _escalation_hint(self, path: str, streak: int) -> str:
        return (
            f"[edit_guard] you've failed to edit {path} {streak} times in a row — "
            "re-read the current file content, use a longer/unique anchor, or try a "
            "different approach instead of repeating the same edit."
        )


class ProvenancePostHook:
    """PostToolUse provenance: label reads/bash of THIS agent's own writes.

    Reuses the shared :class:`OwnChangesTrackerPort` (M2). When the path being
    read — or a path named in a bash command — is among the session's own
    mutations, the tool_output is annotated so the model treats it as its own
    artifact, not an independent ground-truth measurement. Fail-open: no
    tracker / no session / any error → ``None`` (no annotation).
    """

    def __init__(
        self,
        *,
        tracker: OwnChangesTrackerPort | None,
        session_id: str | None,
    ) -> None:
        self._tracker = tracker
        self._session_id = session_id

    async def __call__(
        self, *, tool_name: str, tool_input: dict, tool_output: str
    ) -> str | None:
        try:
            if self._tracker is None or not self._session_id:
                return None
            own_paths = self._own_paths()
            if not own_paths:
                return None
            matched = self._match_paths(tool_name, tool_input, own_paths)
            if not matched:
                return None
            labels = [self._label(path) for path in matched]
            return tool_output + "\n\n" + "\n".join(labels)
        except Exception:
            logger.warning(
                "ProvenancePostHook failed for %r (fail-open)",
                tool_name,
                exc_info=True,
            )
            return None

    def _own_paths(self) -> list[str]:
        assert self._session_id is not None  # guarded by caller
        assert self._tracker is not None  # guarded by caller
        records = self._tracker.get_mutations(self._session_id)
        return [r.file_path for r in records if r.file_path]

    @staticmethod
    def _match_paths(
        tool_name: str, tool_input: dict, own_paths: list[str]
    ) -> list[str]:
        """Return own_paths referenced by this tool call, preserving order."""
        if tool_name == "bash":
            command = tool_input.get("command")
            if not isinstance(command, str) or not command:
                return []
            seen: list[str] = []
            for path in own_paths:
                if path not in seen and ProvenancePostHook._command_names(
                    command, path
                ):
                    seen.append(path)
            return seen
        path = tool_input.get("path")
        if isinstance(path, str) and path and path in own_paths:
            return [path]
        return []

    @staticmethod
    def _command_names(command: str, path: str) -> bool:
        """True when a bash command references ``path`` as a whole token.

        Whitespace-tokenized and matched as an exact token or path-suffix. A raw
        substring match would over-label — own ``a.py`` would wrongly flag a
        command that only touches ``data.py``.
        """
        # ponytail: whitespace split; switch to shlex if quoted-path provenance matters.
        base = os.path.basename(path)
        for token in command.split():
            if token == path or (base and token == base):
                return True
            if token.endswith("/" + path) or (base and token.endswith("/" + base)):
                return True
        return False

    @staticmethod
    def _label(path: str) -> str:
        return (
            f"[provenance] {path} was written by THIS agent — not an independent "
            "measurement; verify with an external source if you need ground truth."
        )


def register_edit_guard_hooks(
    registry: HookRegistry,
    *,
    state: EditGuardState,
    tracker: OwnChangesTrackerPort | None,
    session_id: str | None,
    config: CodingProfileConfig,
) -> None:
    """Register anti-flailing guard + provenance hooks (mirrors verify wiring).

    Gated on ``config.enable_edit_guards``: when False, nothing is registered
    (default path stays byte-identical). Registers one ``PreToolUse`` + one
    ``PostToolUse`` guard entry per exact name in :data:`EDIT_TOOL_NAMES` (fnmatch
    has no ``|`` alternation), plus one ``PostToolUse`` provenance entry on each
    of ``read`` and ``bash``.
    """
    if not config.enable_edit_guards:
        return
    pre_guard = PreEditGuardHook(state)
    post_guard = PostEditGuardHook(state)
    for name in EDIT_TOOL_NAMES:
        registry.on_pre_tool_use(pre_guard, matcher=name)
        registry.on_post_tool_use(post_guard, matcher=name)
    provenance = ProvenancePostHook(tracker=tracker, session_id=session_id)
    for name in _PROVENANCE_TOOL_NAMES:
        registry.on_post_tool_use(provenance, matcher=name)
