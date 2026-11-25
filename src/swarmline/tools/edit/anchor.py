"""Hash-anchored edit strategy (REQ-RCA-070, opt-in).

Anchor format: sha256 hexdigest (64 hex chars) of the exact matched slice
``file_content[start:end]`` at model-read time.  Before writing, the strategy
recomputes sha256 of the located slice and rejects (``stale_anchor``) if it
differs.  All-or-nothing: any failure leaves every file untouched.

Opt-in: only activated when ``CodingProfileConfig.edit_strategy == "anchor"``.
Default ``"legacy"`` path never imports this module — byte-identical.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from swarmline.tools.edit.strategy import (
    AsyncPathLock,
    CascadeFuzzyMatcher,
    EditFailureKind,
    EditOutcome,
    Hunk,
    HunkResult,
    PathLock,
    _Match,
    _MatchFailure,
    _ResolvedHunk,
    _adapt_find,
    _rollback_writes,
    _summarize,
    _summarize_rollback,
    _verify_roundtrip,
)

if TYPE_CHECKING:
    from swarmline.tools.protocols import SandboxProvider


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class AnchoredHunk(Hunk):
    """Hunk with sha256 anchor of the target slice (``file_content[start:end]``).

    Compute: ``hashlib.sha256(matched_slice.encode()).hexdigest()``.
    AnchorEditStrategy rejects with ``stale_anchor`` when the recomputed hash
    does not match.
    """

    anchor: str


async def _rollback_outcome(
    sandbox: SandboxProvider,
    written: list[tuple[str, str]],
    originals: dict[str, str],
    validated: list[HunkResult],
    *,
    restored_failure: EditFailureKind,
    restored_detail: str,
    unrestored_suffix: str,
) -> EditOutcome:
    """Roll back *written* files; unrestored paths → ``rollback_failed``."""
    unrestored = await _rollback_writes(sandbox, written, originals)
    results: list[HunkResult] = []
    for r in validated:
        canon = os.path.realpath(r.path)
        if canon in unrestored or r.path in unrestored:
            results.append(
                HunkResult(
                    path=r.path,
                    status="failed",
                    failure="rollback_failed",
                    detail=(
                        f"left MODIFIED on disk — manual recovery needed: "
                        f"{r.path} ({unrestored_suffix})"
                    ),
                    match_strategy=r.match_strategy,
                )
            )
        else:
            results.append(
                HunkResult(
                    path=r.path,
                    status="failed",
                    failure=restored_failure,
                    detail=restored_detail,
                    match_strategy=r.match_strategy,
                )
            )
    return EditOutcome(
        mode="transactional_multi_file",
        applied=False,
        results=tuple(results),
        message=_summarize_rollback(results, unrestored_paths=list(unrestored)),
    )


class AnchorEditStrategy:
    """Content-hash anchored, transactional edit strategy (REQ-RCA-070).

    Dry-run / anchor-check → write (all-or-nothing) → rollback on error →
    round-trip verify (REQ-SCA-061).  Plain :class:`Hunk` objects (no anchor)
    pass through without a hash check.  Opt-in: only constructed when
    ``edit_strategy="anchor"``; default path is byte-identical.
    """

    name = "anchor"

    def __init__(
        self,
        matcher: CascadeFuzzyMatcher | None = None,
        path_lock: PathLock | None = None,
    ) -> None:
        self._matcher: CascadeFuzzyMatcher = matcher or CascadeFuzzyMatcher()
        self._path_lock: PathLock = path_lock or AsyncPathLock()

    async def apply(
        self,
        hunks: tuple[Hunk, ...],
        sandbox: SandboxProvider,
        *,
        transactional: bool,
    ) -> EditOutcome:
        paths = tuple(sorted({os.path.realpath(h.path) for h in hunks}))
        async with self._path_lock.acquire_all(paths):
            return await self._apply_locked(hunks, sandbox)

    async def _apply_locked(
        self, hunks: tuple[Hunk, ...], sandbox: SandboxProvider
    ) -> EditOutcome:
        originals: dict[str, str] = {}
        file_cache: dict[str, str] = {}
        validated: list[HunkResult] = []
        resolved: list[_ResolvedHunk] = []
        failed = False

        for hunk in hunks:
            canonical = os.path.realpath(hunk.path)
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
                originals[canonical] = raw
                file_cache[canonical] = raw

            content = file_cache[canonical]
            match_result: _Match | _MatchFailure = (
                self._matcher.find_detailed(content, hunk.old)
                if isinstance(self._matcher, CascadeFuzzyMatcher)
                else _adapt_find(self._matcher, content, hunk.old)
            )
            if isinstance(match_result, _MatchFailure):
                validated.append(
                    HunkResult(
                        path=hunk.path,
                        status="failed",
                        failure=match_result.failure,
                        detail=match_result.detail,
                        match_strategy=None,
                    )
                )
                failed = True
                continue

            if isinstance(hunk, AnchoredHunk):
                matched_slice = content[match_result.start : match_result.end]
                actual_hash = _sha256(matched_slice)
                if actual_hash != hunk.anchor:
                    validated.append(
                        HunkResult(
                            path=hunk.path,
                            status="failed",
                            failure="stale_anchor",
                            detail=(
                                f"anchor mismatch on '{hunk.path}': "
                                f"expected sha256={hunk.anchor[:16]}…, "
                                f"actual sha256={actual_hash[:16]}… — "
                                f"file changed since anchor was computed"
                            ),
                            match_strategy=match_result.strategy,
                        )
                    )
                    failed = True
                    continue

            new_content = (
                content[: match_result.start] + hunk.new + content[match_result.end :]
            )
            file_cache[canonical] = new_content
            resolved.append(
                _ResolvedHunk(
                    hunk=hunk,
                    new_content=new_content,
                    match_strategy=match_result.strategy,
                )
            )
            validated.append(
                HunkResult(
                    path=hunk.path,
                    status="validated",
                    failure=None,
                    detail="validated (dry-run, anchor ok)",
                    match_strategy=match_result.strategy,
                )
            )

        if failed:
            return EditOutcome(
                mode="transactional_multi_file",
                applied=False,
                results=tuple(validated),
                message=_summarize(validated, transactional=True),
            )

        seen_canonical: set[str] = set()
        final_writes: list[tuple[str, str, str]] = []
        for item in resolved:
            canonical = os.path.realpath(item.hunk.path)
            if canonical not in seen_canonical:
                seen_canonical.add(canonical)
                final_writes.append((item.hunk.path, canonical, file_cache[canonical]))

        written: list[tuple[str, str]] = []
        write_error: str | None = None
        failed_write_path: str | None = None

        for display_path, canonical, content in final_writes:
            try:
                await sandbox.write_file(display_path, content)
                written.append((display_path, canonical))
            except Exception as exc:  # noqa: BLE001
                write_error = str(exc)
                failed_write_path = display_path
                break

        if write_error is not None:
            return await _rollback_outcome(
                sandbox,
                written,
                originals,
                validated,
                restored_failure="not_found",
                restored_detail=(
                    f"write failure during transaction "
                    f"(rolled back): {failed_write_path}: {write_error}"
                ),
                unrestored_suffix=f"write error: {write_error}; restore also failed",
            )

        for display_path, _canonical, content in final_writes:
            mismatch = await _verify_roundtrip(sandbox, display_path, content)
            if mismatch is not None:
                return await _rollback_outcome(
                    sandbox,
                    written,
                    originals,
                    validated,
                    restored_failure="roundtrip_mismatch",
                    restored_detail=mismatch,
                    unrestored_suffix=(
                        f"round-trip verify failed on '{display_path}'; "
                        f"restore also failed"
                    ),
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
