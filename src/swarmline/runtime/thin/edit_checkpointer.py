"""EditCheckpointer — git checkpoints after accepted edits (Task 7, REQ-SCA-060).

Composes the EXISTING workspace ports — :class:`GitOperationsPort` and
:class:`OwnChangesTrackerPort` — over a :class:`WorkspaceSession` to create a
per-edit git checkpoint and to undo only the agent's OWN checkpoints (never a
user commit). **No new Protocol/port is introduced** (design.md §6, M2 — adding
a checkpoint method to a port would be a breaking ISP change).

Design notes
------------
* **Staging + path-scoped commit (NEW-ISSUE-3).** ``GitOperationsPort.commit``
  runs a pathspec-less ``git commit -m`` *without* staging, and there is no
  ``add``/``stage`` method on the port. So :meth:`checkpoint` FIRST stages the
  edited paths in the worktree via ``SandboxProvider.execute``
  (``git -C <worktree> add -- ...``), and then commits ONLY those paths via a
  path-scoped ``git -C <worktree> commit -m <msg> -- <paths>`` (also through the
  sandbox). The explicit pathspec is an OWNERSHIP guarantee: the bare port commit
  would sweep ANY unrelated pre-staged user changes into this OWN checkpoint —
  which :meth:`undo_last_own` could then revert, destroying user work. The scoped
  commit excludes them. (The port is still composed — :meth:`undo_last_own` uses
  ``GitOperationsPort.revert``.)

* **Why ``sandbox`` in ``__init__``.** The class needs a way to run ``git add``
  (and ``git rev-parse``) scoped to ``session.worktree_path``. Injecting the
  already-composed, policy-enforced ``SandboxProvider`` (preferred per the spec)
  reuses existing infrastructure instead of spawning git out-of-band. Commands
  are built with ``git -C <worktree>`` so they are correctly scoped regardless of
  the sandbox's own working directory, and every argument is ``shlex.quote``-d.

* **SHA canonicalization.** ``GitOperationsPort.commit`` returns git's
  *abbreviated* hash, which would not exact-match a later full-SHA lookup in
  ``OwnChangesTrackerPort.is_own_commit``. :meth:`checkpoint` therefore resolves
  the canonical 40-char SHA via ``git rev-parse HEAD`` and records/returns THAT,
  so :meth:`undo_last_own` recognizes its own checkpoints reliably.

Fail-open vs loud
-----------------
Checkpoints are a safety net, never a correctness boundary: a non-git session,
empty paths, "nothing to commit", or a git failure all return ``None`` silently.
(The one LOUD boundary in the edit path — the round-trip write verify — lives in
``tools/edit/strategy.py``, not here.)

Clean Architecture: infrastructure/application glue in ``runtime/thin`` that
depends only on the workspace Protocols (DIP). No new abstraction, ≤400 lines.
"""

from __future__ import annotations

import json
import logging
import shlex
from typing import TYPE_CHECKING

from swarmline.runtime.thin.edit_guards import _paths_for
from swarmline.runtime.thin.edit_verify_coordinator import EDIT_TOOL_NAMES

if TYPE_CHECKING:
    from swarmline.hooks.registry import HookRegistry
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig
    from swarmline.tools.protocols import SandboxProvider
    from swarmline.workspace.protocols import GitOperationsPort, OwnChangesTrackerPort
    from swarmline.workspace.types import WorkspaceSession

logger = logging.getLogger(__name__)


class EditCheckpointer:
    """Create/undo git checkpoints by composing existing workspace ports."""

    def __init__(
        self,
        git: GitOperationsPort,
        own: OwnChangesTrackerPort,
        sandbox: SandboxProvider,
    ) -> None:
        self._git = git
        self._own = own
        self._sandbox = sandbox

    async def checkpoint(
        self,
        session: WorkspaceSession,
        paths: tuple[str, ...],
        message: str,
    ) -> str | None:
        """Stage ``paths`` and commit them as an OWN checkpoint.

        Returns the canonical 40-char commit SHA on success, or ``None`` when
        skipped: a non-git session (``worktree_path`` is ``None``), empty
        ``paths``, nothing staged ("nothing to commit"), or any git failure.
        Fail-open — a checkpoint never breaks the edit flow.
        """
        worktree = session.worktree_path
        if not worktree:
            return None  # non-git session → skip silently (gate)
        if not paths:
            return None  # nothing to checkpoint

        try:
            # NEW-ISSUE-3: stage the edited paths in the worktree BEFORE committing
            # (GitOperationsPort.commit does not stage).
            add = await self._sandbox.execute(self._git_add_command(worktree, paths))
            if add.exit_code != 0:
                return None  # staging failed → no checkpoint

            # OWNERSHIP ISOLATION: commit ONLY the staged edit paths via an explicit
            # ``-- <pathspec>``. GitOperationsPort.commit runs a pathspec-less
            # ``git commit -m`` that would sweep ANY unrelated pre-staged user changes
            # into this OWN checkpoint — which undo_last_own could then revert,
            # destroying user work. A path-scoped commit makes git build the commit
            # from HEAD + only these paths' content, so user changes are never
            # included. Same NEW-ISSUE-3 sandbox accommodation as staging.
            commit = await self._sandbox.execute(
                self._git_commit_command(worktree, message, paths)
            )
            if commit.exit_code != 0:
                return None  # e.g. "nothing to commit" → skip

            # Record the CANONICAL full SHA only. ``commit.output`` is git's
            # ABBREVIATED hash, but undo_last_own resolves HEAD via rev-parse to the
            # full SHA and OwnChangesTrackerPort.is_own_commit is an exact match —
            # recording an abbreviated hash here would make the checkpoint
            # un-undoable. If the canonical SHA cannot be resolved, do NOT record the
            # checkpoint (conservative: a commit we cannot identify is left untracked
            # rather than recorded un-undoably; the commit itself still stands).
            sha = await self._head_sha(worktree)
            if not sha:
                return None

            self._own.record_commit(session.session_id, sha)
            return sha
        except Exception:  # noqa: BLE001 — checkpoints are fail-open, never break edits
            logger.warning(
                "EditCheckpointer.checkpoint failed (fail-open)", exc_info=True
            )
            return None

    async def undo_last_own(self, session: WorkspaceSession) -> str | None:
        """Revert HEAD iff it is one of THIS session's own checkpoints.

        Never touches a user commit. Returns the reverted SHA, or ``None`` when
        there is nothing to undo: a non-git session, HEAD is not an own commit,
        or the revert failed.
        """
        worktree = session.worktree_path
        if not worktree:
            return None
        try:
            sha = await self._head_sha(worktree)
            if sha is None:
                return None
            if not self._own.is_own_commit(session.session_id, sha):
                # ponytail: HEAD-if-own only — we deliberately do NOT dig past a user
                # commit to find an older own checkpoint (reverting a non-HEAD commit
                # risks conflicts). Ceiling: single-level undo of the latest own
                # checkpoint, which is exactly the per-edit checkpoint contract.
                return None
            result = await self._git.revert(session, sha)
            if not result.success:
                return None
            return sha
        except Exception:  # noqa: BLE001 — fail-open, never break the edit flow
            logger.warning(
                "EditCheckpointer.undo_last_own failed (fail-open)", exc_info=True
            )
            return None

    @staticmethod
    def _git_add_command(worktree: str, paths: tuple[str, ...]) -> str:
        """Build a ``git add`` scoped to ``worktree`` with quoted, ``--``-guarded paths."""
        quoted_paths = " ".join(shlex.quote(p) for p in paths)
        return f"git -C {shlex.quote(worktree)} add -- {quoted_paths}"

    @staticmethod
    def _git_commit_command(worktree: str, message: str, paths: tuple[str, ...]) -> str:
        """Build a path-scoped ``git commit`` so ONLY ``paths`` are committed.

        The explicit ``-- <pathspec>`` makes git build the commit from HEAD plus the
        named paths' working-tree content, EXCLUDING any unrelated pre-staged user
        changes — they can never be swept into an OWN checkpoint (which
        :meth:`undo_last_own` could otherwise revert). ``message`` and every path are
        ``shlex.quote``-d.
        """
        quoted_paths = " ".join(shlex.quote(p) for p in paths)
        return (
            f"git -C {shlex.quote(worktree)} commit -m {shlex.quote(message)} "
            f"-- {quoted_paths}"
        )

    async def _head_sha(self, worktree: str) -> str | None:
        """Resolve the canonical 40-char SHA of HEAD via ``git rev-parse``."""
        result = await self._sandbox.execute(
            f"git -C {shlex.quote(worktree)} rev-parse HEAD"
        )
        if result.exit_code != 0:
            return None
        return result.stdout.strip() or None


def _edit_succeeded(tool_output: str) -> bool:
    """Decide whether an edit/write tool_output reports SUCCESS.

    Handles BOTH output shapes:
    * the new EditOutcome JSON (Task 1) — ``applied`` true, or any
      ``results[*].status == "persisted"``;
    * the LEGACY executor JSON (``edit_strategy="legacy"``, the default) —
      ``{"status": "ok", "path": ...}`` with no ``applied``/``results``.

    Returns False for an explicit failure / unparseable / non-dict output.
    Never raises. (Paths come from ``tool_input``, the authoritative request —
    so this only has to answer "did the write land?".)

    Trailing annotations are tolerated: a PostToolUse hook registered before this
    one (e.g. the anti-flailing guard's churn hint, or a host-supplied post hook)
    may APPEND text after the edit-executor JSON. ``raw_decode`` parses the LEADING
    JSON object and ignores any trailing annotation, so a successful edit is still
    recognized even when a prior hook decorated the output. (The edit executors
    always emit their JSON as the leading content.)
    """
    try:
        payload, _ = json.JSONDecoder().raw_decode(tool_output.lstrip())
    except (ValueError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    applied = payload.get("applied")
    if isinstance(applied, bool):
        return applied
    results = payload.get("results")
    if isinstance(results, list):
        return any(
            isinstance(r, dict) and r.get("status") == "persisted" for r in results
        )
    return payload.get("status") == "ok"


class CheckpointPostHook:
    """PostToolUse: create a git checkpoint after a SUCCESSFUL edit/write.

    On a successful edit (new EditOutcome OR legacy ``status="ok"`` — see
    :func:`_edit_succeeded`) it checkpoints the edited path(s) taken from
    ``tool_input`` (the authoritative request, present for both output shapes).
    NEVER modifies ``tool_output`` (returns ``None``) and NEVER raises — a
    checkpoint is a safety net, not a gate. A non-git session / "nothing to
    commit" / git failure is absorbed by ``checkpoint`` itself (returns None).
    Reads the RAW tool_output, so it must be registered BEFORE the verify-loop
    hook (which annotates the output).
    """

    def __init__(
        self, checkpointer: EditCheckpointer, session: WorkspaceSession
    ) -> None:
        self._checkpointer = checkpointer
        self._session = session

    async def __call__(
        self, *, tool_name: str, tool_input: dict, tool_output: str
    ) -> None:
        try:
            if not _edit_succeeded(tool_output):
                return None
            # Paths from tool_input — the shared edit-path extractor (reused, not a
            # 3rd copy). git add of an unchanged path is a harmless no-op, and an
            # empty diff makes checkpoint() return None ("nothing to commit").
            paths = tuple(_paths_for(tool_name, tool_input))
            if not paths:
                return None
            await self._checkpointer.checkpoint(
                self._session, paths, f"swarmline checkpoint: {tool_name}"
            )
        except Exception:  # noqa: BLE001 — checkpoints never break the edit flow
            logger.warning("CheckpointPostHook failed (fail-open)", exc_info=True)
        return None


def register_edit_checkpoint_hooks(
    registry: HookRegistry,
    *,
    checkpointer: EditCheckpointer,
    session: WorkspaceSession,
    config: CodingProfileConfig,
) -> None:
    """Register one PostToolUse checkpoint hook per exact edit/write tool name.

    Gated on ``config.enable_git_checkpoints``: when False, nothing is registered
    (default path stays byte-identical). One ``PostToolUse`` entry per name in
    :data:`EDIT_TOOL_NAMES` (fnmatch has no ``|`` alternation).
    """
    if not config.enable_git_checkpoints:
        return
    hook = CheckpointPostHook(checkpointer, session)
    for name in EDIT_TOOL_NAMES:
        registry.on_post_tool_use(hook, matcher=name)
