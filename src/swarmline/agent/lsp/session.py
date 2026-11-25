# Attribution: adapted from hermes (MIT)
# Upstream file: hermes/language_server.py (H1 LSP session + diagnostics model)
# Copyright: (c) Nous Research and contributors
# Changes: re-expressed as ISP Protocols over the existing Phase-62
#          WorkspaceSession (B5 — no new session abstraction); diagnostics
#          modelled as frozen value objects with a full Range for line-delta
#          remap; fail-open ``ensure_started`` contract added (REQ-SCA-072).
"""Type-aware LSP verify — contracts (Task 8, REQ-SCA-070/071/072).

This module holds only the *contract* surface: the diagnostic value objects and
the four ISP-compliant Protocols. Concrete implementations live in sibling
modules (``range_shift``, ``verifier``, ``pyright``) so each file stays focused
and under the SRP line budget.

Design (B5 fix): there is no new session abstraction. A language-server process
is scoped to one ``(tenant, workspace)`` pair via
:class:`LanguageServerSessionFactory.for_workspace`, which composes over the
existing :class:`~swarmline.workspace.types.WorkspaceSession`. The process is
reaped at ``close()`` and is never shared across tenants.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from swarmline.workspace.types import WorkspaceSession

Severity = Literal["error", "warning", "info"]


# ---------------------------------------------------------------------------
# Value objects (frozen — immutable diagnostics)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Range:
    """A source range (LSP-style, zero-based lines/characters)."""

    start_line: int
    start_char: int
    end_line: int
    end_char: int


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A single language-server diagnostic.

    Carries the *full* range (not only the line) so a baseline diagnostic can be
    remapped through a line-delta edit and subtracted exactly.
    """

    file_path: str
    range: Range
    severity: Severity
    code: str | None
    message: str


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    """An immutable per-file snapshot of diagnostics."""

    by_file: Mapping[str, tuple[Diagnostic, ...]]


# ---------------------------------------------------------------------------
# Protocols (ISP — ≤5 methods each, @runtime_checkable)
# ---------------------------------------------------------------------------


@runtime_checkable
class LanguageServerSession(Protocol):
    """A language-server process living across tool-calls in one WorkspaceSession.

    Reaped at :meth:`close`. ``ensure_started`` is fail-open: it returns ``False``
    (rather than raising) when no server is available so verification is skipped
    (REQ-SCA-072).
    """

    async def ensure_started(self, language: str) -> bool:
        """Start the server for ``language``; return ``False`` if unavailable."""
        ...

    async def diagnostics(self, file_path: str) -> tuple[Diagnostic, ...]:
        """Return current diagnostics for ``file_path`` (empty when not started)."""
        ...

    async def close(self) -> None:
        """Reap the underlying process and release resources."""
        ...


@runtime_checkable
class LanguageServerSessionFactory(Protocol):
    """Builds a language-server session scoped to one ``(tenant, workspace)``.

    B5 fix: composes over the existing :class:`WorkspaceSession`; one process per
    scope, never shared between tenants (REQ-SCA-072).
    """

    def for_workspace(
        self, session: WorkspaceSession, *, tenant_id: str, workspace_id: str
    ) -> LanguageServerSession:
        """Return the session for the given scope (one process per scope)."""
        ...


@runtime_checkable
class RangeShifter(Protocol):
    """Shifts baseline diagnostics through a line-delta edit.

    Invariant: a diagnostic on a line ``L > edit_line`` shifts by ``line_delta``;
    a diagnostic on ``L <= edit_line`` is unchanged.
    """

    def remap(
        self,
        baseline: DiagnosticSnapshot,
        edited_file: str,
        edit_line: int,
        line_delta: int,
    ) -> DiagnosticSnapshot:
        """Return a new snapshot with the edited file's diagnostics shifted."""
        ...


@runtime_checkable
class LspVerifier(Protocol):
    """Reports ONLY edit-introduced diagnostics.

    ``edit_introduced = diagnostics(after) − remap(diagnostics(before))`` — the
    pre-existing baseline (shifted through the edit) is subtracted so only the
    diagnostics the edit actually introduced remain.
    """

    async def edit_introduced(
        self, file_path: str, edit_line: int, line_delta: int
    ) -> tuple[Diagnostic, ...]:
        """Return diagnostics newly introduced by an edit to ``file_path``."""
        ...
