"""Concrete LSP verifier + DoD registry wiring (Task 8, REQ-SCA-070/071).

* :class:`SnapshotLspVerifier` implements ``edit_introduced`` as
  ``diagnostics(after) − remap(diagnostics(before))`` — only the diagnostics an
  edit actually introduced survive the subtraction.
* :func:`lsp_criterion` adapts a per-edit :class:`LspVerifier` into the zero-arg
  ``VerifierFn`` the :class:`VerifierRegistry` expects.
* :func:`register_lsp_criterion` is the *gated* wiring seam: with
  ``enable_lsp_verify=False`` (default) it returns the registry UNCHANGED, so the
  ``lsp`` criterion is ABSENT and behaviour is byte-identical (the plan GATE).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from swarmline.agent.lsp.session import (
    Diagnostic,
    DiagnosticSnapshot,
    LanguageServerSession,
    LspVerifier,
    RangeShifter,
)
from swarmline.orchestration.verification_types import (
    CheckDetail,
    VerificationResult,
    VerificationStatus,
)

if TYPE_CHECKING:
    from swarmline.orchestration.verifier_registry import VerifierFn, VerifierRegistry
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig


class SnapshotLspVerifier:
    """Reports only edit-introduced diagnostics for a single edited file.

    Holds a baseline snapshot (diagnostics *before* the edit). On
    :meth:`edit_introduced` it fetches the *after* diagnostics from the session,
    remaps the baseline through the edit's line-delta, and subtracts — leaving
    exactly the diagnostics the edit introduced (REQ-SCA-070).
    """

    def __init__(
        self,
        *,
        session: LanguageServerSession,
        range_shifter: RangeShifter,
        baseline: DiagnosticSnapshot,
    ) -> None:
        self._session = session
        self._range_shifter = range_shifter
        self._baseline = baseline

    async def edit_introduced(
        self, file_path: str, edit_line: int, line_delta: int
    ) -> tuple[Diagnostic, ...]:
        """Return diagnostics newly introduced by an edit to ``file_path``."""
        after = await self._session.diagnostics(file_path)
        remapped = self._range_shifter.remap(
            self._baseline, file_path, edit_line, line_delta
        )
        baseline_for_file = set(remapped.by_file.get(file_path, ()))
        return tuple(diag for diag in after if diag not in baseline_for_file)


def lsp_criterion(
    verifier: LspVerifier,
    *,
    file_path: str,
    edit_line: int,
    line_delta: int,
) -> VerifierFn:
    """Adapt an :class:`LspVerifier` into a zero-arg ``VerifierFn``.

    PASS when no edit-introduced *error* diagnostics exist; FAIL otherwise, with
    each error message surfaced as a :class:`CheckDetail`. Non-error diagnostics
    (warnings/info) never fail the criterion.
    """

    async def _run() -> VerificationResult:
        introduced = await verifier.edit_introduced(file_path, edit_line, line_delta)
        errors = tuple(d for d in introduced if d.severity == "error")
        if not errors:
            return VerificationResult(
                status=VerificationStatus.PASS,
                summary="lsp: no edit-introduced type errors",
            )
        checks = tuple(
            CheckDetail(
                name="lsp",
                status=VerificationStatus.FAIL,
                message=f"{d.file_path}:{d.range.start_line}: {d.message}",
            )
            for d in errors
        )
        plural = "error" if len(errors) == 1 else "errors"
        return VerificationResult(
            status=VerificationStatus.FAIL,
            checks=checks,
            summary=f"lsp: {len(errors)} edit-introduced type {plural}",
        )

    return _run


def register_lsp_criterion(
    registry: VerifierRegistry,
    criterion: VerifierFn,
    config: CodingProfileConfig,
) -> VerifierRegistry:
    """Register the ``lsp`` DoD criterion, gated on ``enable_lsp_verify``.

    GATE (REQ-SCA-071): with ``enable_lsp_verify=False`` (the default) the input
    registry is returned UNCHANGED — the ``lsp`` criterion is absent and the DoD
    verification path is byte-identical to before. When enabled, a NEW registry
    with the extra criterion is returned (the base is never mutated).
    """
    if not config.enable_lsp_verify:
        return registry
    return registry.with_check("lsp", criterion)
