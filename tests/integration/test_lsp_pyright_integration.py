"""Integration: real pyright-langserver type-aware verify (Task 8, REQ-SCA-070/072).

SKIPPED when ``pyright-langserver`` is not on PATH so unit CI without pyright stays
green (pyright is PATH-discovered, never a mandatory dependency).

With pyright installed these tests are the ones that would have caught the two
protocol bugs the fake-transport unit tests cannot:

* the before/after ``edit_introduced`` flow runs TWO ``diagnostics()`` calls on a
  SINGLE persistent session — exercising the ``didOpen`` → ``didChange`` document
  lifecycle (a second ``didOpen`` makes real pyright drop the after-edit diags);
* two distinct ``(tenant, workspace)`` scopes spawn isolated processes that
  ``close_all`` reaps at run end.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from swarmline.agent.lsp import (
    LineDeltaRangeShifter,
    PyrightSessionFactory,
    SnapshotLspVerifier,
)
from swarmline.agent.lsp.session import DiagnosticSnapshot
from swarmline.workspace.types import WorkspaceSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("pyright-langserver") is None,
        reason="pyright-langserver not on PATH (PATH-discovered, optional dep)",
    ),
]


_CLEAN_SOURCE = """\
def greet(name: str) -> str:
    return "hello " + name


VALUE: int = 1
"""

# A real type error: assign a str literal to an int-annotated module constant.
_BROKEN_SOURCE = """\
def greet(name: str) -> str:
    return "hello " + name


VALUE: int = "not an int"
"""


def _ws(repo_root: str) -> WorkspaceSession:
    return WorkspaceSession.create(
        session_id="lsp-int", repo_root=repo_root, branch="main"
    )


def _pid(server: object) -> int | None:
    """Best-effort OS pid of a started pyright session (integration introspection)."""
    transport = getattr(server, "_transport", None)
    proc = getattr(transport, "_proc", None)
    return getattr(proc, "pid", None)


@pytest.mark.asyncio
async def test_edit_introducing_type_error_surfaces_exactly_one_diagnostic(
    tmp_path: Path,
) -> None:
    """A clean baseline, then an edit introducing a type error, yields EXACTLY one
    edit-introduced diagnostic — on a single persistent session (baseline then
    after-edit), which only works if the document lifecycle is didOpen→didChange.
    """
    mod = tmp_path / "mod.py"
    mod.write_text(_CLEAN_SOURCE, encoding="utf-8")

    factory = PyrightSessionFactory()
    server = factory.for_workspace(
        _ws(str(tmp_path)), tenant_id="t1", workspace_id="w1"
    )
    try:
        assert await server.ensure_started("python") is True

        # Baseline diagnostics on the clean file (first diagnostics() → didOpen).
        baseline_diags = await server.diagnostics(str(mod))
        baseline = DiagnosticSnapshot(by_file={str(mod): baseline_diags})

        # Edit in a real type error, then re-read on the SAME session (didChange).
        mod.write_text(_BROKEN_SOURCE, encoding="utf-8")

        verifier = SnapshotLspVerifier(
            session=server,
            range_shifter=LineDeltaRangeShifter(),
            baseline=baseline,
        )
        introduced = await verifier.edit_introduced(str(mod), edit_line=0, line_delta=0)

        errors = [d for d in introduced if d.severity == "error"]
        assert len(errors) == 1, (
            "exactly one edit-introduced type error expected; "
            f"got {[d.message for d in introduced]}"
        )
    finally:
        await factory.close_all()


@pytest.mark.asyncio
async def test_two_scopes_get_isolated_server_processes(tmp_path: Path) -> None:
    """Two distinct (tenant, workspace) scopes spawn isolated pyright processes;
    close_all reaps both at run end."""
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "m.py").write_text(_CLEAN_SOURCE, encoding="utf-8")
    (repo_b / "m.py").write_text(_CLEAN_SOURCE, encoding="utf-8")

    factory = PyrightSessionFactory()
    try:
        s1 = factory.for_workspace(_ws(str(repo_a)), tenant_id="t1", workspace_id="w1")
        s2 = factory.for_workspace(_ws(str(repo_b)), tenant_id="t2", workspace_id="w2")

        # Distinct session objects (one process per scope, never shared).
        assert s1 is not s2
        assert await s1.ensure_started("python") is True
        assert await s2.ensure_started("python") is True

        # Distinct underlying OS processes → real isolation, not a shared server.
        pid1, pid2 = _pid(s1), _pid(s2)
        assert pid1 is not None and pid2 is not None
        assert pid1 != pid2
    finally:
        await factory.close_all()
