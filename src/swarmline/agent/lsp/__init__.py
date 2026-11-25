"""Type-aware LSP verify (Task 8, REQ-SCA-070/071/072).

Public API for the language-server verification surface:

* value objects — :class:`Range`, :class:`Diagnostic`, :class:`DiagnosticSnapshot`
* protocols — :class:`LanguageServerSession`, :class:`LanguageServerSessionFactory`,
  :class:`RangeShifter`, :class:`LspVerifier`
* concrete impls — :class:`LineDeltaRangeShifter`, :class:`SnapshotLspVerifier`,
  :class:`PyrightLanguageServer`, :class:`PyrightSessionFactory`
* DoD wiring — :func:`lsp_criterion`, :func:`register_lsp_criterion`
"""

from __future__ import annotations

from swarmline.agent.lsp.pyright import PyrightLanguageServer, PyrightSessionFactory
from swarmline.agent.lsp.range_shift import LineDeltaRangeShifter
from swarmline.agent.lsp.session import (
    Diagnostic,
    DiagnosticSnapshot,
    LanguageServerSession,
    LanguageServerSessionFactory,
    LspVerifier,
    Range,
    RangeShifter,
    Severity,
)
from swarmline.agent.lsp.verifier import (
    SnapshotLspVerifier,
    lsp_criterion,
    register_lsp_criterion,
)

__all__ = [
    "Diagnostic",
    "DiagnosticSnapshot",
    "LanguageServerSession",
    "LanguageServerSessionFactory",
    "LineDeltaRangeShifter",
    "LspVerifier",
    "PyrightLanguageServer",
    "PyrightSessionFactory",
    "Range",
    "RangeShifter",
    "Severity",
    "SnapshotLspVerifier",
    "lsp_criterion",
    "register_lsp_criterion",
]
