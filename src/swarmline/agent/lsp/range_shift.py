"""Baseline diagnostic remapping for the edit-introduced subtraction (Task 8).

Two pure, in-memory, zero-IO remaps over an edited file's baseline diagnostics,
both feeding the ``diagnostics(after) − remap(diagnostics(before))`` computation
that keeps the subtraction line-accurate (REQ-SCA-070):

* :class:`LineDeltaRangeShifter` — the design-§7 ``RangeShifter`` Protocol impl:
  a single ``(edit_line, line_delta)`` span. Kept as the documented contract.
* :func:`remap_by_opcodes` — the hunk-based remap the runtime coordinator uses:
  a per-hunk shift driven by :func:`difflib.SequenceMatcher`, correct at the
  insertion/deletion boundary and across multi-region edits where one total
  delta would over-shift a diagnostic sitting between two edits. Everything is
  0-based to match the raw LSP diagnostic coordinates (no 1-based/0-based mix).
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from dataclasses import replace

from swarmline.agent.lsp.session import Diagnostic, DiagnosticSnapshot, Range


class LineDeltaRangeShifter:
    """Shifts baseline diagnostics through a single line-delta edit.

    Invariant (REQ-SCA-070): a diagnostic on a line ``L > edit_line`` shifts by
    ``line_delta`` (both range endpoints); a diagnostic on ``L <= edit_line`` is
    unchanged. Diagnostics in files other than ``edited_file`` are never touched.
    """

    def remap(
        self,
        baseline: DiagnosticSnapshot,
        edited_file: str,
        edit_line: int,
        line_delta: int,
    ) -> DiagnosticSnapshot:
        """Return a new snapshot with ``edited_file``'s diagnostics shifted."""
        new_by_file: dict[str, tuple[Diagnostic, ...]] = {}
        for file_path, diagnostics in baseline.by_file.items():
            if file_path != edited_file or line_delta == 0:
                new_by_file[file_path] = tuple(diagnostics)
                continue
            new_by_file[file_path] = tuple(
                self._shift(diag, edit_line, line_delta) for diag in diagnostics
            )
        return DiagnosticSnapshot(by_file=new_by_file)

    @staticmethod
    def _shift(diagnostic: Diagnostic, edit_line: int, line_delta: int) -> Diagnostic:
        """Shift a diagnostic's range if it begins strictly after ``edit_line``."""
        if diagnostic.range.start_line <= edit_line:
            return diagnostic
        shifted = Range(
            start_line=diagnostic.range.start_line + line_delta,
            start_char=diagnostic.range.start_char,
            end_line=diagnostic.range.end_line + line_delta,
            end_char=diagnostic.range.end_char,
        )
        return replace(diagnostic, range=shifted)


def remap_by_opcodes(
    baseline: DiagnosticSnapshot,
    edited_file: str,
    pre_lines: Sequence[str],
    post_lines: Sequence[str],
) -> DiagnosticSnapshot:
    """Hunk-based remap of ``edited_file``'s baseline diagnostics (0-based).

    Computes :func:`difflib.SequenceMatcher` opcodes between the pre- and
    post-edit line lists and shifts each baseline diagnostic by the *cumulative*
    line-delta of the hunks whose pre-image lies strictly ABOVE it — fixing both
    the single-span boundary off-by-one and the multi-region over-shift. Both
    range endpoints move by the same amount; diagnostics in other files are left
    untouched.
    """
    opcodes = difflib.SequenceMatcher(
        a=pre_lines, b=post_lines, autojunk=False
    ).get_opcodes()
    new_by_file: dict[str, tuple[Diagnostic, ...]] = {}
    for file_path, diagnostics in baseline.by_file.items():
        if file_path != edited_file:
            new_by_file[file_path] = tuple(diagnostics)
            continue
        new_by_file[file_path] = tuple(
            _shift_by_opcodes(diag, opcodes) for diag in diagnostics
        )
    return DiagnosticSnapshot(by_file=new_by_file)


def _shift_by_opcodes(
    diagnostic: Diagnostic, opcodes: Sequence[tuple[str, int, int, int, int]]
) -> Diagnostic:
    """Shift one diagnostic by the cumulative delta of the hunks above it."""
    shift = _cumulative_shift(diagnostic.range.start_line, opcodes)
    if shift == 0:
        return diagnostic
    old = diagnostic.range
    return replace(
        diagnostic,
        range=Range(
            start_line=old.start_line + shift,
            start_char=old.start_char,
            end_line=old.end_line + shift,
            end_char=old.end_char,
        ),
    )


def _cumulative_shift(
    line: int, opcodes: Sequence[tuple[str, int, int, int, int]]
) -> int:
    """Cumulative line-delta of every hunk whose pre-image is strictly above ``line``.

    For a hunk on pre-lines ``[i1, i2)`` mapping to post-lines ``[j1, j2)`` the
    delta is ``(j2 - j1) - (i2 - i1)``. A diagnostic fully below the hunk
    (``i2 <= line``) accumulates that delta; a diagnostic INSIDE an edited hunk
    (``i1 <= line < i2``) sits on changed code and is intentionally NOT shifted,
    so a genuinely changed line surfaces as edit-introduced; ``equal`` hunks and
    hunks entirely below the diagnostic contribute nothing.
    """
    shift = 0
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        if i2 <= line:
            shift += (j2 - j1) - (i2 - i1)
    return shift
