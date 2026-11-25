"""Pre-edit snapshot capture for the type-aware LSP verify runtime hook (Task 8).

The runtime ``PreToolUse`` hook captures the pre-edit file content as a
:class:`PendingEdit` (baseline diagnostics + the pre-edit line list); the
``PostToolUse`` hook reads the post-edit content and feeds both line lists to
:func:`~swarmline.agent.lsp.range_shift.remap_by_opcodes`, the hunk-based remap
that shifts baseline diagnostics through an edit so a pre-existing diagnostic
pushed up/down is not falsely surfaced as edit-introduced.

Pure logic; the only IO is :func:`read_lines` (a thin, fail-open file read). This
module stays in ``agent/lsp`` and depends on nothing from runtime/infrastructure
(Clean Architecture).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from swarmline.agent.lsp.diagnostics_wire import read_text
from swarmline.agent.lsp.session import DiagnosticSnapshot


@dataclass(frozen=True, slots=True)
class PendingEdit:
    """A captured Pre snapshot: baseline diagnostics + the pre-edit line list."""

    baseline: DiagnosticSnapshot
    pre_lines: tuple[str, ...]


def read_lines(root: str, path: str) -> tuple[str, ...]:
    """Read ``path`` (resolved against ``root``) as a tuple of lines (fail-open).

    A relative ``path`` is resolved against ``root`` exactly as the pyright
    session resolves it for ``diagnostics``; a missing/unreadable file yields an
    empty tuple (so a freshly-created file has an empty pre-image).
    """
    target = Path(path)
    if not target.is_absolute():
        target = Path(root) / target
    return tuple(read_text(str(target)).splitlines())
