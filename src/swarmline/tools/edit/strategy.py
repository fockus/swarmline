# Attribution: adapted from aider (Apache-2.0)
# Upstream file: aider/coders/editblock_coder.py
# Copyright: (c) Paul Gauthier and contributors
# Changes: refactored the search/replace fuzzy-match cascade (exact, whitespace-
#          normalized, indentation-flexible, block-anchor) into a Protocol-based
#          strategy; added Hunk/HunkResult/EditOutcome value objects; removed all
#          REPL-specific output; integrated with the async SandboxProvider port.
#
# Attribution: adapted from hermes (MIT)
# Upstream file: hermes/patch_parser.py, hermes/fuzzy_match.py
# Copyright: (c) Nous Research and contributors
# Changes: rewritten as async EditStrategy implementations; transactional
#          dry-run-validate-then-apply added for V4APatchStrategy; integrated
#          with PathLock and structured HunkResult failure reporting.
"""Tolerant edit-format engine — pure domain logic.

This module is framework-free: it depends only on the ``SandboxProvider``
*Protocol* for file IO. No infrastructure imports, no SDK types — Clean
Architecture domain layer.

Cascade (``SearchReplaceStrategy``):
    exact → whitespace-normalized → indentation-flexible → block-anchor

Every miss returns a structured :class:`HunkResult` carrying a machine-actionable
``detail`` (e.g. ``"matched 3 times; use a longer/unique anchor"``) and the winning
``match_strategy`` on success — never a bare boolean.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from swarmline.tools.protocols import SandboxProvider

# ---------------------------------------------------------------------------
# Enums / Literal aliases (B4: explicit states)
# ---------------------------------------------------------------------------

EditFailureKind = Literal[
    "not_found",
    "matched_n_times",
    "already_present",
    "ambiguous",
    "rollback_failed",
    "alias_conflict",
    "roundtrip_mismatch",
    "stale_anchor",
]
HunkStatus = Literal["validated", "persisted", "failed"]

# Cascade strategy names, in attempt order.
_MATCH_STRATEGY_NAMES = ("exact", "whitespace", "indent", "block_anchor")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hunk:
    """A single search/replace unit targeting one file."""

    path: str
    old: str
    new: str


@dataclass(frozen=True)
class HunkResult:
    """Outcome for one hunk.

    status:
        ``validated`` — dry-run match succeeded but not yet written;
        ``persisted`` — written to disk;
        ``failed``    — could not be applied.
    failure:
        machine-readable cause when ``status == "failed"`` else ``None``.
    detail:
        machine-actionable hint (e.g. "matched 3 times; use a longer anchor").
    match_strategy:
        winning cascade strategy (exact/whitespace/indent/block_anchor) or ``None``.
    """

    path: str
    status: HunkStatus
    failure: EditFailureKind | None
    detail: str
    match_strategy: str | None


@dataclass(frozen=True)
class EditOutcome:
    """Aggregate outcome of an :class:`EditStrategy` application.

    ``applied`` means PERSISTED on disk (B4).

    Invariants:
        single_file               — ``applied ⟺ any(r.status == "persisted")``
                                     (partial application allowed).
        transactional_multi_file  — ``applied ⟺ all(r.status == "persisted")``;
                                     on ANY failure NO hunk is persisted (dry-run
                                     validate all → only then write).
    """

    mode: Literal["single_file", "transactional_multi_file"]
    applied: bool
    results: tuple[HunkResult, ...]
    message: str


# ---------------------------------------------------------------------------
# Protocols (ISP: ≤5 methods each)
# ---------------------------------------------------------------------------


@runtime_checkable
class FuzzyMatcher(Protocol):
    """Tolerant matcher: exact → whitespace → indentation → block-anchor."""

    def find(self, content: str, old: str) -> tuple[int, int] | None:
        """Return ``(start, end)`` char offsets of a unique match, else ``None``."""
        ...


@runtime_checkable
class EditStrategy(Protocol):
    """Applies hunks to files through a :class:`SandboxProvider`."""

    name: str

    async def apply(
        self,
        hunks: tuple[Hunk, ...],
        sandbox: SandboxProvider,
        *,
        transactional: bool,
    ) -> EditOutcome: ...


@runtime_checkable
class PathLock(Protocol):
    """Sync method returning an async context manager (M6 fix).

    Paths must be normalized (``os.path.realpath``) BEFORE sorting by the caller
    so that ``a/../b`` and ``b`` lock the same key:

        async with path_lock.acquire_all(tuple(sorted(realpath(p) for p in paths))):
            ...
    """

    def acquire_all(
        self, paths: tuple[str, ...]
    ) -> contextlib.AbstractAsyncContextManager[None]: ...


# ---------------------------------------------------------------------------
# Match result (internal)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    strategy: str


@dataclass(frozen=True)
class _MatchFailure:
    failure: EditFailureKind
    detail: str
    count: int


# ---------------------------------------------------------------------------
# Fuzzy cascade
# ---------------------------------------------------------------------------


def _normalize_ws(text: str) -> str:
    """Collapse internal runs of whitespace and strip per-line — for comparison only."""
    return "\n".join(" ".join(line.split()) for line in text.splitlines())


def _normalize_for_roundtrip(text: str) -> str:
    """Normalize CRLF/CR and strip a leading UTF-8 BOM for round-trip comparison.

    Platform-benign differences (``\\r\\n`` / lone ``\\r`` line endings, a leading
    BOM written by some editors) must NOT trip the round-trip verify — only real
    data loss/corruption should. Both the intended and the read-back content are
    normalized through this single helper before comparison (REQ-SCA-061).
    """
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


async def _verify_roundtrip(
    sandbox: SandboxProvider, path: str, intended: str
) -> str | None:
    """Read ``path`` back and compare (normalized) to the intended content.

    Returns an error message on mismatch (the write did NOT persist faithfully —
    truncated/corrupted), else ``None``. This is the one LOUD data-integrity
    boundary in the edit path: a faithful write returns ``None`` and leaves
    behavior byte-identical; a mismatch is surfaced as a failed outcome.
    """
    try:
        actual = await sandbox.read_file(path)
    except Exception as exc:  # noqa: BLE001 - surfaced as a structured failure
        return f"round-trip verify failed for {path!r}: read-back error: {exc}"
    if _normalize_for_roundtrip(actual) != _normalize_for_roundtrip(intended):
        return (
            f"round-trip verify FAILED for {path!r}: the file on disk does not "
            f"match the intended content (truncated or corrupted write) — "
            f"intended {len(intended)} chars, found {len(actual)} chars"
        )
    return None


async def _rollback_writes(
    sandbox: SandboxProvider,
    written: list[tuple[str, str]],
    originals: dict[str, str],
) -> set[str]:
    """Best-effort restore of ``written`` (display_path, canonical) to originals.

    Returns the set of display paths that could NOT be restored. The restore is
    ITSELF round-trip-verified: a silently-corrupting write provider — the same
    failure mode that triggers a rollback (roundtrip_mismatch) — can mangle the
    rollback write too, so a write that raises no exception is not proof of a
    faithful restore. A path whose read-back does not match the original is
    reported unrestored (→ a LOUD ``rollback_failed``), preserving the
    transactional all-or-nothing contract instead of silently leaving a file
    corrupted (REQ-SCA-061).
    """
    unrestored: set[str] = set()
    for disp, canon in written:
        original = originals[canon]
        try:
            await sandbox.write_file(disp, original)
        except Exception:  # noqa: BLE001
            unrestored.add(disp)
            continue
        if await _verify_roundtrip(sandbox, disp, original) is not None:
            unrestored.add(disp)
    return unrestored


def _strip_common_indent(lines: list[str]) -> list[str]:
    """Remove the smallest shared leading-whitespace prefix across non-blank lines."""
    indents = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    if not indents:
        return [line.lstrip() for line in lines]
    common = min(indents)
    return [line[common:] if len(line) >= common else line for line in lines]


class CascadeFuzzyMatcher:
    """Concrete :class:`FuzzyMatcher` implementing the four-stage cascade.

    Adapted from aider's editblock fuzzy strategies + hermes fuzzy_match. Returns
    char offsets of the *first* unique match. When a stage matches the source text
    more than once it is treated as ambiguous and the cascade stops (no guessing —
    risk R2): the caller surfaces ``matched_n_times``.
    """

    name = "cascade"

    def find(self, content: str, old: str) -> tuple[int, int] | None:
        result = self._find_detailed(content, old)
        if isinstance(result, _Match):
            return (result.start, result.end)
        return None

    def find_detailed(self, content: str, old: str) -> _Match | _MatchFailure:
        """Public detailed variant used by strategies for structured failures."""
        return self._find_detailed(content, old)

    # -- internal -----------------------------------------------------------

    def _find_detailed(self, content: str, old: str) -> _Match | _MatchFailure:
        if old == "":
            return _MatchFailure(
                failure="not_found",
                detail="empty old_string is not allowed; provide a unique anchor",
                count=0,
            )

        # Stage 1 — exact.
        exact = self._count_exact(content, old)
        if exact == 1:
            start = content.index(old)
            return _Match(start=start, end=start + len(old), strategy="exact")
        if exact > 1:
            return _MatchFailure(
                failure="matched_n_times",
                detail=(
                    f"matched {exact} times exactly; "
                    "use a longer/unique anchor that appears once"
                ),
                count=exact,
            )

        # Stages 2-4 operate over whole-line windows.
        line_match = self._find_by_lines(content, old)
        if line_match is not None:
            return line_match

        return _MatchFailure(
            failure="not_found",
            detail=(
                "old_string not found (tried exact, whitespace-normalized, "
                "indentation-flexible, block-anchor); verify the snippet exists "
                "and re-read the file"
            ),
            count=0,
        )

    @staticmethod
    def _count_exact(content: str, old: str) -> int:
        count = 0
        idx = content.find(old)
        while idx != -1:
            count += 1
            idx = content.find(old, idx + 1)
        return count

    def _find_by_lines(self, content: str, old: str) -> _Match | _MatchFailure | None:
        """Line-window scan applying whitespace/indent/block-anchor comparisons.

        Returns a :class:`_Match` on a unique hit, a :class:`_MatchFailure` when a
        stage matches multiple windows (ambiguous), or ``None`` when no stage
        matches at all (let the caller fall through to not_found).
        """
        content_lines = content.splitlines(keepends=True)
        old_lines = old.splitlines()
        if not old_lines:
            return None
        n = len(old_lines)
        if n > len(content_lines):
            return None

        # Precompute normalized forms of the needle once per stage.
        old_ws = _normalize_ws(old)
        old_indent = "\n".join(_strip_common_indent(old_lines))

        for strategy in ("whitespace", "indent", "block_anchor"):
            matches = self._windows_matching(
                content_lines, n, old_lines, old_ws, old_indent, strategy
            )
            if len(matches) == 1:
                start_line = matches[0]
                start = sum(len(content_lines[i]) for i in range(start_line))
                end = start + sum(
                    len(content_lines[i]) for i in range(start_line, start_line + n)
                )
                # Trim a trailing newline from the window if the needle had none,
                # so block replacement preserves surrounding structure.
                window_text = content[start:end]
                if not old.endswith("\n") and window_text.endswith("\n"):
                    end -= 1
                return _Match(start=start, end=end, strategy=strategy)
            if len(matches) > 1:
                return _MatchFailure(
                    failure="matched_n_times",
                    detail=(
                        f"matched {len(matches)} times via {strategy} matching; "
                        "use a longer/unique anchor that appears once"
                    ),
                    count=len(matches),
                )
        return None

    def _windows_matching(
        self,
        content_lines: list[str],
        n: int,
        old_lines: list[str],
        old_ws: str,
        old_indent: str,
        strategy: str,
    ) -> list[int]:
        hits: list[int] = []
        for i in range(len(content_lines) - n + 1):
            window = content_lines[i : i + n]
            window_stripped = [line.rstrip("\n") for line in window]
            if self._window_matches(
                window_stripped, old_lines, old_ws, old_indent, strategy
            ):
                hits.append(i)
        return hits

    @staticmethod
    def _window_matches(
        window: list[str],
        old_lines: list[str],
        old_ws: str,
        old_indent: str,
        strategy: str,
    ) -> bool:
        if strategy == "whitespace":
            return _normalize_ws("\n".join(window)) == old_ws
        if strategy == "indent":
            return _strip_common_indent(window) == _strip_common_indent(old_lines)
        # block_anchor: first and last non-blank lines (stripped) must match AND
        # the whitespace-normalized full body must also match (F2 fix: prevents
        # replacing the wrong block when only boundary lines are identical but
        # the interior differs — risk R2 / code corruption).
        win_core = [line.strip() for line in window if line.strip()]
        old_core = [line.strip() for line in old_lines if line.strip()]
        if not win_core or not old_core:
            return False
        if win_core[0] != old_core[0] or win_core[-1] != old_core[-1]:
            return False
        # Boundary anchors match — tighten by requiring whitespace-normalized body
        # equality so a stale middle line is NOT silently accepted.
        return _normalize_ws("\n".join(window)) == _normalize_ws("\n".join(old_lines))


# ---------------------------------------------------------------------------
# Path lock (concrete)
# ---------------------------------------------------------------------------


class AsyncPathLock:
    """Concrete :class:`PathLock`: one :class:`asyncio.Lock` per realpath key.

    Locks are acquired in the order given by the caller (callers MUST pass a
    sorted tuple of realpaths) so overlapping multi-file edits cannot deadlock
    or interleave. The same realpath always maps to the same lock object, so
    ``a/../b`` and ``b`` serialize against each other.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def lock_count(self) -> int:
        """Number of distinct realpath keys currently registered (for tests/observability)."""
        return len(self._locks)

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def acquire_all(
        self, paths: tuple[str, ...]
    ) -> contextlib.AbstractAsyncContextManager[None]:
        # Deduplicate while preserving order (a hunk set may repeat a path).
        ordered_unique = tuple(dict.fromkeys(paths))
        return self._acquire(ordered_unique)

    @contextlib.asynccontextmanager
    async def _acquire(self, keys: tuple[str, ...]) -> AsyncIterator[None]:
        acquired: list[asyncio.Lock] = []
        try:
            for key in keys:
                lock = self._lock_for(key)
                await lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ResolvedHunk:
    """A hunk paired with the intended new content of its file (dry-run result)."""

    hunk: Hunk
    new_content: str
    match_strategy: str


class SearchReplaceStrategy:
    """Tolerant single-file search/replace (REQ-SCA-001/002).

    Non-transactional: each hunk is matched against the *current* file content and
    written independently. ``applied`` is True when at least one hunk persisted
    (single_file invariant). Failed hunks are reported individually so the model
    can retry only those.
    """

    name = "search_replace"

    def __init__(self, matcher: FuzzyMatcher | None = None) -> None:
        self._matcher: FuzzyMatcher = matcher or CascadeFuzzyMatcher()

    async def apply(
        self,
        hunks: tuple[Hunk, ...],
        sandbox: SandboxProvider,
        *,
        transactional: bool,
    ) -> EditOutcome:
        if transactional:
            # Delegate to the transactional engine when asked, reusing the matcher.
            return await V4APatchStrategy(self._matcher).apply(
                hunks, sandbox, transactional=True
            )

        results: list[HunkResult] = []
        any_persisted = False
        # Per-file in-memory content so multiple hunks on one file compose.
        file_cache: dict[str, str] = {}
        for hunk in hunks:
            try:
                if hunk.path not in file_cache:
                    file_cache[hunk.path] = await sandbox.read_file(hunk.path)
            except Exception as exc:  # noqa: BLE001 - surfaced as structured failure
                results.append(
                    HunkResult(
                        path=hunk.path,
                        status="failed",
                        failure="not_found",
                        detail=f"could not read file: {exc}",
                        match_strategy=None,
                    )
                )
                continue

            content = file_cache[hunk.path]
            outcome = _match_and_replace(self._matcher, content, hunk)
            if isinstance(outcome, HunkResult):
                results.append(outcome)
                continue

            new_content, strategy = outcome
            try:
                await sandbox.write_file(hunk.path, new_content)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    HunkResult(
                        path=hunk.path,
                        status="failed",
                        failure="not_found",
                        detail=f"write failed: {exc}",
                        match_strategy=strategy,
                    )
                )
                continue
            # Round-trip verify (REQ-SCA-061): the LOUD data-integrity boundary.
            mismatch = await _verify_roundtrip(sandbox, hunk.path, new_content)
            if mismatch is not None:
                results.append(
                    HunkResult(
                        path=hunk.path,
                        status="failed",
                        failure="roundtrip_mismatch",
                        detail=mismatch,
                        match_strategy=strategy,
                    )
                )
                continue
            file_cache[hunk.path] = new_content
            any_persisted = True
            results.append(
                HunkResult(
                    path=hunk.path,
                    status="persisted",
                    failure=None,
                    detail="applied",
                    match_strategy=strategy,
                )
            )

        return EditOutcome(
            mode="single_file",
            applied=any_persisted,
            results=tuple(results),
            message=_summarize(results, transactional=False),
        )


class V4APatchStrategy:
    """Transactional multi-file patch (REQ-SCA-003/004).

    Two-pass, all-or-nothing:
        1. Dry-run: validate EVERY hunk against the (composed) content of its file.
           If any hunk fails, NOTHING is written.
        2. Apply: only when all hunks validated, write each file's final content.

    Uses an :class:`AsyncPathLock` over the sorted realpaths of the touched files
    so concurrent overlapping multi-file edits serialize deterministically.
    """

    name = "patch"

    def __init__(
        self,
        matcher: FuzzyMatcher | None = None,
        path_lock: PathLock | None = None,
    ) -> None:
        self._matcher: FuzzyMatcher = matcher or CascadeFuzzyMatcher()
        self._path_lock: PathLock = path_lock or AsyncPathLock()

    async def apply(
        self,
        hunks: tuple[Hunk, ...],
        sandbox: SandboxProvider,
        *,
        transactional: bool,
    ) -> EditOutcome:
        import os

        paths = tuple(sorted({os.path.realpath(h.path) for h in hunks}))
        async with self._path_lock.acquire_all(paths):
            return await self._apply_locked(hunks, sandbox)

    async def _apply_locked(
        self, hunks: tuple[Hunk, ...], sandbox: SandboxProvider
    ) -> EditOutcome:
        import os

        # ---- Pass 1: dry-run validate every hunk (compose per-file in memory) ----
        #
        # F4 fix: ALL internal state (file_cache, originals, final_by_path) is keyed
        # by the CANONICAL realpath of each hunk's path so that aliases like `b.txt`
        # and `./b.txt` share one snapshot and compose sequentially against the same
        # evolving content.  The display path stored in HunkResult.path is preserved
        # as the ORIGINAL hunk.path so users never see the realpath in error messages.
        #
        # F1 / F1-residual fix: `originals` is populated on the first read of each
        # canonical key (before composing); rollback restore failures are surfaced
        # as `rollback_failed` HunkResults instead of being swallowed silently.

        originals: dict[str, str] = {}  # canonical_key → on-disk content
        file_cache: dict[str, str] = {}  # canonical_key → composed content
        validated: list[HunkResult] = []
        resolved: list[_ResolvedHunk] = []
        failed = False

        for hunk in hunks:
            # ponytail: host realpath, not sandbox-internal identity; aliased
            # sandbox-symlink writes are detected+failed (not composed) — full
            # composition needs a SandboxProvider path-identity primitive (backlog).
            canonical = os.path.realpath(hunk.path)  # F4: single canonical key
            if canonical not in file_cache:
                try:
                    raw = await sandbox.read_file(hunk.path)
                except Exception as exc:  # noqa: BLE001
                    validated.append(
                        HunkResult(
                            path=hunk.path,
                            status="failed",
                            failure="not_found",
                            detail=f"could not read file: {exc}",
                            match_strategy=None,
                        )
                    )
                    failed = True
                    continue
                originals[canonical] = raw  # snapshot BEFORE composing
                file_cache[canonical] = raw

            content = file_cache[canonical]
            outcome = _match_and_replace(self._matcher, content, hunk)
            if isinstance(outcome, HunkResult):
                validated.append(outcome)
                failed = True
                continue

            new_content, strategy = outcome
            file_cache[canonical] = new_content  # compose subsequent hunks on same key
            resolved.append(
                _ResolvedHunk(
                    hunk=hunk, new_content=new_content, match_strategy=strategy
                )
            )
            validated.append(
                HunkResult(
                    path=hunk.path,  # display path — not realpath
                    status="validated",
                    failure=None,
                    detail="validated (dry-run)",
                    match_strategy=strategy,
                )
            )

        if failed:
            # Validation phase failed: nothing written — return immediately.
            return EditOutcome(
                mode="transactional_multi_file",
                applied=False,
                results=tuple(validated),
                message=_summarize(validated, transactional=True),
            )

        # ---- Pass 2: write final composed content per file ----
        # Deduplicate by canonical key; use hunk.path (original display path) as
        # the write target so the sandbox resolves it the same way as the read did.
        seen_canonical: set[str] = set()
        final_writes: list[
            tuple[str, str, str]
        ] = []  # (display_path, canonical, content)
        for item in resolved:
            canonical = os.path.realpath(item.hunk.path)
            if canonical not in seen_canonical:
                seen_canonical.add(canonical)
                final_writes.append((item.hunk.path, canonical, file_cache[canonical]))

        # Write each file; on any IO failure restore already-written files to their
        # originals (F1 fix: best-effort).  Track restore failures and surface them
        # as `rollback_failed` results so the caller knows which paths need manual
        # recovery (F1-residual fix: no silent swallow of restore errors).
        #
        # F4-deep fix: before writing each canonical target, re-read its CURRENT
        # on-disk content via the sandbox. If it differs from originals[canonical]
        # AND this canonical key has NOT already been written by this transaction,
        # an aliased name changed the file under us — roll back everything written
        # so far and return alias_conflict (loud, safe, transactional failure).
        # For NON-aliased files the guard is a no-op (content unchanged since read).
        written: list[tuple[str, str]] = []  # (display_path, canonical)
        write_error: str | None = None
        failed_write_path: str | None = None
        alias_conflict_path: str | None = None
        alias_conflict_reason: str = ""
        for display_path, canonical, content in final_writes:
            # Stale/alias guard — skip re-read if we already wrote this canonical key
            # (our own prior write changed it; that is expected and correct).
            if canonical not in {c for _, c in written}:
                try:
                    current = await sandbox.read_file(display_path)
                except Exception:  # noqa: BLE001
                    # Cannot verify target before write — fail loudly rather than
                    # assuming "unchanged".  Route into alias-conflict rollback so
                    # already-written files are restored and applied=False.
                    alias_conflict_path = display_path
                    alias_conflict_reason = (
                        f"could not verify target before write (read failed) — "
                        f"transaction aborted to avoid possible alias/stale-write "
                        f"corruption: '{display_path}'"
                    )
                    break
                if current != originals.get(canonical, ""):
                    # Backing content changed via a different name → alias conflict.
                    alias_conflict_path = display_path
                    alias_conflict_reason = (
                        f"path alias/stale-write conflict: "
                        f"'{display_path}' changed under a different "
                        f"name during the transaction; aliased multi-file "
                        f"edits are not composed — retry as separate edits"
                    )
                    break

            try:
                await sandbox.write_file(display_path, content)
                written.append((display_path, canonical))
            except Exception as exc:  # noqa: BLE001
                write_error = str(exc)
                failed_write_path = display_path
                break

        if alias_conflict_path is not None:
            # Roll back every write that succeeded before the conflict was detected.
            # Round-trip-VERIFIED restore (REQ-SCA-061): a silently-corrupting write
            # provider — the same failure mode that can force a rollback — may also
            # mangle the rollback write, so a raised-no-exception write is not proof of
            # a faithful restore. _rollback_writes reads each restore back and reports
            # any path that did not match → a LOUD rollback_failed below.
            unrestored = await _rollback_writes(sandbox, written, originals)

            conflict_results: list[HunkResult] = []
            for r in validated:
                canon = os.path.realpath(r.path)
                if canon in unrestored or r.path in unrestored:
                    conflict_results.append(
                        HunkResult(
                            path=r.path,
                            status="failed",
                            failure="rollback_failed",
                            detail=(
                                f"left MODIFIED on disk — manual recovery needed: "
                                f"{r.path} (alias conflict on '{alias_conflict_path}'; "
                                f"restore also failed)"
                            ),
                            match_strategy=r.match_strategy,
                        )
                    )
                else:
                    conflict_results.append(
                        HunkResult(
                            path=r.path,
                            status="failed",
                            failure="alias_conflict",
                            detail=alias_conflict_reason,
                            match_strategy=r.match_strategy,
                        )
                    )
            msg = _summarize_rollback(
                conflict_results,
                unrestored_paths=list(unrestored),
            )
            return EditOutcome(
                mode="transactional_multi_file",
                applied=False,
                results=tuple(conflict_results),
                message=msg,
            )

        if write_error is not None:
            # Best-effort restore: undo every write that succeeded. Round-trip-VERIFIED
            # (REQ-SCA-061): the corrupting-provider failure mode that forces a rollback
            # can also corrupt the restore write itself, so _rollback_writes reads each
            # restore back and reports any path that did not match → rollback_failed.
            unrestored = await _rollback_writes(sandbox, written, originals)

            # Build per-hunk results, flagging any path that could not be restored.
            fail_results: list[HunkResult] = []
            for r in validated:
                canon = os.path.realpath(r.path)
                if canon in unrestored or r.path in unrestored:
                    fail_results.append(
                        HunkResult(
                            path=r.path,
                            status="failed",
                            failure="rollback_failed",
                            detail=(
                                f"left MODIFIED on disk — manual recovery needed: "
                                f"{r.path} (write error: {write_error}; "
                                f"restore also failed)"
                            ),
                            match_strategy=r.match_strategy,
                        )
                    )
                else:
                    fail_results.append(
                        HunkResult(
                            path=r.path,
                            status="failed",
                            failure="not_found",
                            detail=(
                                f"write failure during transaction "
                                f"(rolled back): {failed_write_path}: {write_error}"
                            ),
                            match_strategy=r.match_strategy,
                        )
                    )

            msg = _summarize_rollback(
                fail_results,
                unrestored_paths=list(unrestored),
            )
            return EditOutcome(
                mode="transactional_multi_file",
                applied=False,
                results=tuple(fail_results),
                message=msg,
            )

        # ---- Pass 3: round-trip verify every written file (REQ-SCA-061) ----
        # All writes succeeded; confirm each one persisted faithfully. On any
        # mismatch the transaction is rolled back (all-or-nothing invariant) and
        # a LOUD roundtrip_mismatch failure is surfaced. A faithful write leaves
        # this path a no-op (byte-identical success output below).
        for display_path, _canonical, content in final_writes:
            mismatch = await _verify_roundtrip(sandbox, display_path, content)
            if mismatch is None:
                continue
            # ponytail: mirrors the alias/write rollback blocks above rather than
            # sharing one generic reporter — keeping each failure path explicit
            # avoids refactoring the existing (test-pinned) rollback messages.
            unrestored = await _rollback_writes(sandbox, written, originals)
            rt_results: list[HunkResult] = []
            for r in validated:
                canon = os.path.realpath(r.path)
                if canon in unrestored or r.path in unrestored:
                    rt_results.append(
                        HunkResult(
                            path=r.path,
                            status="failed",
                            failure="rollback_failed",
                            detail=(
                                f"left MODIFIED on disk — manual recovery needed: "
                                f"{r.path} (round-trip verify failed on "
                                f"'{display_path}'; restore also failed)"
                            ),
                            match_strategy=r.match_strategy,
                        )
                    )
                else:
                    rt_results.append(
                        HunkResult(
                            path=r.path,
                            status="failed",
                            failure="roundtrip_mismatch",
                            detail=mismatch,
                            match_strategy=r.match_strategy,
                        )
                    )
            msg = _summarize_rollback(rt_results, unrestored_paths=list(unrestored))
            return EditOutcome(
                mode="transactional_multi_file",
                applied=False,
                results=tuple(rt_results),
                message=msg,
            )

        persisted = tuple(
            HunkResult(
                path=r.path,
                status="persisted",
                failure=None,
                detail="applied",
                match_strategy=r.match_strategy,
            )
            for r in validated
        )
        return EditOutcome(
            mode="transactional_multi_file",
            applied=True,
            results=persisted,
            message=_summarize(persisted, transactional=True),
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _match_and_replace(
    matcher: FuzzyMatcher, content: str, hunk: Hunk
) -> tuple[str, str] | HunkResult:
    """Resolve a hunk against ``content``.

    Returns ``(new_content, match_strategy)`` on success, or a failed
    :class:`HunkResult` carrying the structured failure.
    """
    detailed = (
        matcher.find_detailed(content, hunk.old)
        if isinstance(matcher, CascadeFuzzyMatcher)
        else _adapt_find(matcher, content, hunk.old)
    )
    if isinstance(detailed, _MatchFailure):
        return HunkResult(
            path=hunk.path,
            status="failed",
            failure=detailed.failure,
            detail=detailed.detail,
            match_strategy=None,
        )
    new_content = content[: detailed.start] + hunk.new + content[detailed.end :]
    return new_content, detailed.strategy


def _adapt_find(
    matcher: FuzzyMatcher, content: str, old: str
) -> _Match | _MatchFailure:
    """Bridge a bare ``FuzzyMatcher.find`` into the detailed result shape."""
    span = matcher.find(content, old)
    if span is None:
        return _MatchFailure(
            failure="not_found",
            detail="old_string not found by the configured matcher",
            count=0,
        )
    return _Match(start=span[0], end=span[1], strategy="custom")


def _summarize(
    results: tuple[HunkResult, ...] | list[HunkResult], *, transactional: bool
) -> str:
    persisted = [r for r in results if r.status == "persisted"]
    validated = [r for r in results if r.status == "validated"]
    failed = [r for r in results if r.status == "failed"]
    if transactional:
        if failed:
            causes = "; ".join(f"{r.path}: {r.detail}" for r in failed)
            return (
                f"transaction rolled back — {len(failed)} hunk(s) failed, "
                f"nothing written. Failures: {causes}"
            )
        return f"transaction applied — {len(persisted)} file edit(s) written"
    parts = [f"{len(persisted)} applied"]
    if validated:
        parts.append(f"{len(validated)} validated")
    if failed:
        causes = "; ".join(f"{r.path}: {r.detail}" for r in failed)
        parts.append(f"{len(failed)} failed ({causes})")
    return ", ".join(parts)


def _summarize_rollback(
    results: list[HunkResult],
    *,
    unrestored_paths: list[str],
) -> str:
    """Summarize a write-phase failure, distinguishing clean rollback from
    partial rollback (some paths left mutated on disk — F1-residual fix).

    When ``unrestored_paths`` is non-empty the message explicitly names them
    and does NOT claim "nothing written".
    """
    if unrestored_paths:
        paths_str = ", ".join(unrestored_paths)
        return (
            f"transaction PARTIALLY rolled back — the following path(s) "
            f"remain MODIFIED on disk and need manual recovery: {paths_str}"
        )
    failed = [r for r in results if r.status == "failed"]
    causes = "; ".join(f"{r.path}: {r.detail}" for r in failed)
    return (
        f"transaction rolled back — {len(failed)} hunk(s) failed, "
        f"nothing written. Failures: {causes}"
    )
