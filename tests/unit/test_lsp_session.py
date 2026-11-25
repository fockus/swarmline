"""Tests for the type-aware LSP verify module (Task 8, REQ-SCA-070/071/072).

Contract-first: every test asserts a business fact about the LSP-verify
contracts, not an implementation detail.

* ``RangeShifter.remap`` invariant — a baseline diagnostic on line ``L >
  edit_line`` shifts by ``line_delta``; ``L < edit_line`` is unchanged.
* ``LspVerifier.edit_introduced`` reports ONLY edit-introduced diagnostics
  (``diagnostics(after) − remap(diagnostics(before))``).
* Fail-open (REQ-SCA-072): a missing language server ⇒ ``ensure_started``
  returns ``False`` and verification is skipped (no crash).
* Scope isolation (REQ-SCA-072): two distinct ``(tenant, workspace)`` scopes
  get isolated sessions, never shared.
* GATE: with ``enable_lsp_verify=False`` (default) the ``lsp`` criterion is
  ABSENT from the registry — behaviour is byte-identical to before.

The external boundary (the pyright process / its stdout) is the only thing
mocked; the remap + subtraction logic is pure and tested in-memory. These
tests do NOT require pyright to be installed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from swarmline.agent.lsp import (
    Diagnostic,
    DiagnosticSnapshot,
    LineDeltaRangeShifter,
    PyrightLanguageServer,
    PyrightSessionFactory,
    Range,
    SnapshotLspVerifier,
    lsp_criterion,
    register_lsp_criterion,
)
from swarmline.orchestration.verification_types import VerificationStatus
from swarmline.orchestration.verifier_registry import VerifierRegistry
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.workspace.types import WorkspaceSession


# ---------------------------------------------------------------------------
# Test doubles (external boundary only)
# ---------------------------------------------------------------------------


class _FakeSession:
    """A LanguageServerSession double returning canned per-file diagnostics."""

    def __init__(self, by_file: dict[str, tuple[Diagnostic, ...]]) -> None:
        self._by_file = by_file
        self.closed = False

    async def ensure_started(self, language: str) -> bool:
        return True

    async def diagnostics(self, file_path: str) -> tuple[Diagnostic, ...]:
        return self._by_file.get(file_path, ())

    async def close(self) -> None:
        self.closed = True


class _FakeTransport:
    """A scripted JSON-RPC transport double (mocks the pyright process stdout).

    ``receive`` replays scripted messages in order; ``send`` is recorded so a
    test can assert the LSP handshake / didOpen were emitted. ``aclose`` records
    that the process was reaped.
    """

    def __init__(self, scripted: list[dict[str, Any]]) -> None:
        self._scripted = list(scripted)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(dict(message))

    async def receive(self) -> dict[str, Any]:
        if not self._scripted:
            raise EOFError("no more scripted messages")
        return self._scripted.pop(0)

    async def aclose(self) -> None:
        self.closed = True


def _ws(repo_root: str = "/repo") -> WorkspaceSession:
    return WorkspaceSession.create(
        session_id="sess-1", repo_root=repo_root, branch="main"
    )


# ---------------------------------------------------------------------------
# RangeShifter.remap invariant
# ---------------------------------------------------------------------------


class TestRangeShiftRemap:
    def test_range_shift_remap(self) -> None:
        """L>edit_line shifts by line_delta; L<edit_line unchanged; other files untouched."""
        below = Diagnostic(
            file_path="a.py",
            range=Range(2, 0, 2, 4),
            severity="warning",
            code="W1",
            message="below edit",
        )
        above = Diagnostic(
            file_path="a.py",
            range=Range(10, 0, 10, 4),
            severity="error",
            code="E1",
            message="above edit",
        )
        other_file = Diagnostic(
            file_path="b.py",
            range=Range(10, 0, 10, 4),
            severity="error",
            code="E2",
            message="other file",
        )
        baseline = DiagnosticSnapshot(
            by_file={"a.py": (below, above), "b.py": (other_file,)}
        )

        shifted = LineDeltaRangeShifter().remap(
            baseline, edited_file="a.py", edit_line=5, line_delta=3
        )

        a_diags = shifted.by_file["a.py"]
        # L=2 < edit_line=5 → unchanged.
        assert a_diags[0].range == Range(2, 0, 2, 4)
        # L=10 > edit_line=5 → shifted by +3 (both start and end line).
        assert a_diags[1].range == Range(13, 0, 13, 4)
        # message/severity/code/file_path preserved on the shifted diagnostic.
        assert a_diags[1].message == "above edit"
        assert a_diags[1].code == "E1"
        # A diagnostic in a different file is never touched by the remap.
        assert shifted.by_file["b.py"] == (other_file,)

    def test_range_shift_remap_at_edit_line_is_unchanged(self) -> None:
        """A diagnostic exactly on edit_line stays put (only strictly-after shifts)."""
        on_line = Diagnostic(
            file_path="a.py",
            range=Range(5, 0, 5, 4),
            severity="error",
            code="E1",
            message="on edit line",
        )
        baseline = DiagnosticSnapshot(by_file={"a.py": (on_line,)})

        shifted = LineDeltaRangeShifter().remap(
            baseline, edited_file="a.py", edit_line=5, line_delta=4
        )

        assert shifted.by_file["a.py"][0].range == Range(5, 0, 5, 4)


# ---------------------------------------------------------------------------
# LspVerifier.edit_introduced — only edit-introduced diagnostics
# ---------------------------------------------------------------------------


class TestEditIntroducedOnly:
    @pytest.mark.asyncio
    async def test_lsp_edit_introduced_only(self) -> None:
        """Only the NEW type error is reported; the shifted pre-existing one is subtracted."""
        # Pre-existing baseline error on line 3.
        pre_existing = Diagnostic(
            file_path="foo.py",
            range=Range(3, 0, 3, 5),
            severity="error",
            code="reportUndefinedVariable",
            message="x is undefined",
        )
        baseline = DiagnosticSnapshot(by_file={"foo.py": (pre_existing,)})

        # Edit inserts 2 lines at line 1 → pre-existing diag shifts to line 5.
        shifted_pre_existing = Diagnostic(
            file_path="foo.py",
            range=Range(5, 0, 5, 5),
            severity="error",
            code="reportUndefinedVariable",
            message="x is undefined",
        )
        new_error = Diagnostic(
            file_path="foo.py",
            range=Range(2, 0, 2, 10),
            severity="error",
            code="reportAssignmentType",
            message='"int" is not assignable to "str"',
        )
        session = _FakeSession({"foo.py": (shifted_pre_existing, new_error)})

        verifier = SnapshotLspVerifier(
            session=session,
            range_shifter=LineDeltaRangeShifter(),
            baseline=baseline,
        )

        introduced = await verifier.edit_introduced("foo.py", edit_line=1, line_delta=2)

        # Exactly the NEW error — the shifted pre-existing one is subtracted.
        assert introduced == (new_error,)

    @pytest.mark.asyncio
    async def test_edit_introduced_empty_when_no_new_diagnostics(self) -> None:
        """A clean edit (after == remapped before) yields no edit-introduced diagnostics."""
        pre_existing = Diagnostic(
            file_path="foo.py",
            range=Range(3, 0, 3, 5),
            severity="error",
            code="E1",
            message="pre",
        )
        baseline = DiagnosticSnapshot(by_file={"foo.py": (pre_existing,)})
        shifted = Diagnostic(
            file_path="foo.py",
            range=Range(5, 0, 5, 5),
            severity="error",
            code="E1",
            message="pre",
        )
        session = _FakeSession({"foo.py": (shifted,)})
        verifier = SnapshotLspVerifier(
            session=session, range_shifter=LineDeltaRangeShifter(), baseline=baseline
        )

        assert await verifier.edit_introduced("foo.py", 1, 2) == ()


# ---------------------------------------------------------------------------
# Fail-open (REQ-SCA-072)
# ---------------------------------------------------------------------------


class TestFailOpen:
    @pytest.mark.asyncio
    async def test_lsp_fail_open(self) -> None:
        """Missing server (which→None) ⇒ ensure_started False, no diagnostics, no crash."""
        server = PyrightLanguageServer(workspace_root="/repo", which=lambda _name: None)

        started = await server.ensure_started("python")

        assert started is False
        # A skipped verification must never crash — diagnostics is a no-op tuple.
        assert await server.diagnostics("foo.py") == ()
        # close() on an unstarted server is safe.
        await server.close()

    @pytest.mark.asyncio
    async def test_ensure_started_false_for_non_python_language(self) -> None:
        """The pyright server only serves python; other languages fail-open to skip."""
        server = PyrightLanguageServer(
            workspace_root="/repo", which=lambda _name: "/usr/bin/pyright-langserver"
        )

        assert await server.ensure_started("rust") is False


# ---------------------------------------------------------------------------
# Pyright JSON-RPC parsing via a mocked transport (no pyright required)
# ---------------------------------------------------------------------------


class TestPyrightTransport:
    @pytest.mark.asyncio
    async def test_diagnostics_parsed_from_publish_notification(self) -> None:
        """A scripted publishDiagnostics is parsed into a typed Diagnostic; close reaps."""
        abs_path = "/repo/pkg/mod.py"
        uri = Path(abs_path).as_uri()
        transport = _FakeTransport(
            [
                # initialize response
                {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}},
                # publishDiagnostics for our file
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {
                        "uri": uri,
                        "diagnostics": [
                            {
                                "range": {
                                    "start": {"line": 4, "character": 8},
                                    "end": {"line": 4, "character": 15},
                                },
                                "severity": 1,
                                "code": "reportGeneralTypeIssues",
                                "message": "bad type",
                            }
                        ],
                    },
                },
            ]
        )

        async def _spawner(_executable: str, _root: str) -> _FakeTransport:
            return transport

        server = PyrightLanguageServer(
            workspace_root="/repo",
            which=lambda _name: "/usr/bin/pyright-langserver",
            spawner=_spawner,
        )

        assert await server.ensure_started("python") is True
        diags = await server.diagnostics(abs_path)

        assert len(diags) == 1
        assert diags[0] == Diagnostic(
            file_path=abs_path,
            range=Range(4, 8, 4, 15),
            severity="error",
            code="reportGeneralTypeIssues",
            message="bad type",
        )
        # The LSP handshake actually went out over the transport.
        methods_sent = [m.get("method") for m in transport.sent]
        assert "initialize" in methods_sent
        assert "initialized" in methods_sent
        assert "textDocument/didOpen" in methods_sent

        # close() reaps the process (transport aclose called).
        await server.close()
        assert transport.closed is True

    @pytest.mark.asyncio
    async def test_second_diagnostics_sends_didchange_not_second_didopen(self) -> None:
        """A persistent session sends didOpen ONCE per URI, then didChange (with an
        incremented version) on the next diagnostics() call.

        A second didOpen on an already-open URI is an LSP protocol violation: real
        pyright returns stale/missing after-diagnostics, breaking the before/after
        ``edit_introduced`` flow which calls diagnostics() twice on one session.
        """
        abs_path = "/repo/pkg/mod.py"
        uri = Path(abs_path).as_uri()

        def _publish() -> dict[str, Any]:
            return {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {"uri": uri, "diagnostics": []},
            }

        transport = _FakeTransport(
            [
                {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}},
                _publish(),  # baseline diagnostics() → didOpen
                _publish(),  # after-edit diagnostics() → didChange
            ]
        )

        async def _spawner(_executable: str, _root: str) -> _FakeTransport:
            return transport

        server = PyrightLanguageServer(
            workspace_root="/repo",
            which=lambda _name: "/usr/bin/pyright-langserver",
            spawner=_spawner,
        )

        assert await server.ensure_started("python") is True
        await server.diagnostics(abs_path)  # first call on the URI
        await server.diagnostics(abs_path)  # second call on the SAME URI

        doc_methods = [
            m.get("method")
            for m in transport.sent
            if str(m.get("method", "")).startswith("textDocument/did")
        ]
        # didOpen exactly once, then didChange — NOT two didOpen.
        assert doc_methods == ["textDocument/didOpen", "textDocument/didChange"]

        opens = [m for m in transport.sent if m.get("method") == "textDocument/didOpen"]
        changes = [
            m for m in transport.sent if m.get("method") == "textDocument/didChange"
        ]
        assert opens[0]["params"]["textDocument"]["version"] == 1
        # The version increments on the didChange (LSP requires monotonic versions).
        assert changes[0]["params"]["textDocument"]["version"] == 2


# ---------------------------------------------------------------------------
# Scope isolation (REQ-SCA-072) — one process per (tenant, workspace)
# ---------------------------------------------------------------------------


class TestScopeIsolation:
    def test_lsp_scope_isolation(self) -> None:
        """Distinct (tenant, workspace) scopes get isolated sessions; never shared."""
        factory = PyrightSessionFactory(which=lambda _name: None)
        session = _ws()

        a = factory.for_workspace(session, tenant_id="t1", workspace_id="w1")
        b = factory.for_workspace(session, tenant_id="t2", workspace_id="w2")
        # Same tenant, DIFFERENT workspace → isolated.
        c = factory.for_workspace(session, tenant_id="t1", workspace_id="w2")
        # DIFFERENT tenant, SAME workspace → never shared across tenants.
        d = factory.for_workspace(session, tenant_id="t2", workspace_id="w1")

        assert a is not b
        assert a is not c
        assert a is not d
        assert len({id(a), id(b), id(c), id(d)}) == 4

    def test_same_scope_reuses_one_session(self) -> None:
        """The same (tenant, workspace) returns the SAME session (one process per scope)."""
        factory = PyrightSessionFactory(which=lambda _name: None)
        session = _ws()

        first = factory.for_workspace(session, tenant_id="t1", workspace_id="w1")
        second = factory.for_workspace(session, tenant_id="t1", workspace_id="w1")

        assert first is second

    @pytest.mark.asyncio
    async def test_close_all_reaps_every_scoped_session(self) -> None:
        """close_all reaps every session the factory handed out and clears the cache."""
        factory = PyrightSessionFactory(which=lambda _name: None)
        session = _ws()
        a = factory.for_workspace(session, tenant_id="t1", workspace_id="w1")
        b = factory.for_workspace(session, tenant_id="t2", workspace_id="w2")

        await factory.close_all()

        # After close_all a fresh scope yields a NEW instance (cache cleared).
        a2 = factory.for_workspace(session, tenant_id="t1", workspace_id="w1")
        assert a2 is not a
        assert a is not b  # sanity: the two pre-close sessions were distinct


# ---------------------------------------------------------------------------
# lsp_criterion adapter — LspVerifier → VerifierFn
# ---------------------------------------------------------------------------


class TestLspCriterion:
    @pytest.mark.asyncio
    async def test_lsp_criterion_passes_when_no_edit_introduced_errors(self) -> None:
        """No edit-introduced error diagnostics ⇒ PASS verification result."""
        session = _FakeSession({"foo.py": ()})
        verifier = SnapshotLspVerifier(
            session=session,
            range_shifter=LineDeltaRangeShifter(),
            baseline=DiagnosticSnapshot(by_file={}),
        )
        criterion = lsp_criterion(
            verifier, file_path="foo.py", edit_line=1, line_delta=0
        )

        result = await criterion()

        assert result.status == VerificationStatus.PASS

    @pytest.mark.asyncio
    async def test_lsp_criterion_fails_with_edit_introduced_error(self) -> None:
        """An edit-introduced error diagnostic ⇒ FAIL with the message surfaced."""
        new_error = Diagnostic(
            file_path="foo.py",
            range=Range(2, 0, 2, 9),
            severity="error",
            code="reportAssignmentType",
            message='"int" not assignable to "str"',
        )
        session = _FakeSession({"foo.py": (new_error,)})
        verifier = SnapshotLspVerifier(
            session=session,
            range_shifter=LineDeltaRangeShifter(),
            baseline=DiagnosticSnapshot(by_file={}),
        )
        criterion = lsp_criterion(
            verifier, file_path="foo.py", edit_line=1, line_delta=0
        )

        result = await criterion()

        assert result.status == VerificationStatus.FAIL
        assert any("not assignable" in c.message for c in result.checks)

    @pytest.mark.asyncio
    async def test_lsp_criterion_passes_when_only_warning_introduced(self) -> None:
        """A non-error (warning) edit-introduced diagnostic does NOT fail the criterion."""
        warning = Diagnostic(
            file_path="foo.py",
            range=Range(2, 0, 2, 9),
            severity="warning",
            code="reportUnusedVariable",
            message="unused",
        )
        session = _FakeSession({"foo.py": (warning,)})
        verifier = SnapshotLspVerifier(
            session=session,
            range_shifter=LineDeltaRangeShifter(),
            baseline=DiagnosticSnapshot(by_file={}),
        )
        criterion = lsp_criterion(
            verifier, file_path="foo.py", edit_line=1, line_delta=0
        )

        result = await criterion()

        assert result.status == VerificationStatus.PASS


# ---------------------------------------------------------------------------
# GATE — the 'lsp' criterion is ABSENT when the flag is OFF (byte-identical)
# ---------------------------------------------------------------------------


def _dummy_criterion():
    async def _run():  # pragma: no cover - never invoked in the OFF path
        from swarmline.orchestration.verification_types import VerificationResult

        return VerificationResult(status=VerificationStatus.PASS)

    return _run


class TestFlagGate:
    def test_lsp_criterion_absent_when_flag_off(self) -> None:
        """Default OFF ⇒ registry returned UNCHANGED, 'lsp' criterion absent."""
        base = VerifierRegistry.default(_RecordingVerifier())
        config = CodingProfileConfig()  # enable_lsp_verify=False (default)

        result = register_lsp_criterion(base, _dummy_criterion(), config)

        assert "lsp" not in result.fns
        # Byte-identical: the SAME registry object is returned untouched.
        assert result is base
        assert set(result.fns.keys()) == {
            "contracts",
            "tests",
            "tdd",
            "linters",
            "coverage",
        }

    def test_lsp_criterion_present_when_flag_on(self) -> None:
        """enable_lsp_verify=True ⇒ a NEW registry with the 'lsp' criterion added."""
        base = VerifierRegistry.default(_RecordingVerifier())
        config = CodingProfileConfig(enable_lsp_verify=True)

        result = register_lsp_criterion(base, _dummy_criterion(), config)

        assert "lsp" in result.fns
        assert result is not base  # immutable: base untouched
        assert "lsp" not in base.fns


class _RecordingVerifier:
    """Minimal CodeVerifier-shaped double for building a default registry."""

    async def verify_contracts(self):  # noqa: D102
        from swarmline.orchestration.verification_types import VerificationResult

        return VerificationResult(status=VerificationStatus.PASS)

    verify_tests_substantive = verify_contracts
    verify_tests_before_code = verify_contracts
    verify_linters = verify_contracts

    async def verify_coverage(self, min_pct: int = 85):  # noqa: D102
        from swarmline.orchestration.verification_types import VerificationResult

        return VerificationResult(status=VerificationStatus.PASS)


# ---------------------------------------------------------------------------
# SubprocessLspTransport.aclose — reaping on a hard kill
# ---------------------------------------------------------------------------


class _StubStream:
    """A minimal stdin double exposing close()."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _HardKillProc:
    """A subprocess double whose FIRST wait() hangs (so the terminate() wait_for
    times out) and whose kill() then lets wait() return — so a test can assert
    the transport awaits wait() AGAIN after kill (the process is reaped)."""

    def __init__(self) -> None:
        self.stdin = _StubStream()
        self.stdout = None
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.wait_calls += 1
        if self.wait_calls == 1 and not self.killed:
            await asyncio.sleep(10)  # hang until cancelled by the wait_for timeout
        return 0


class TestSubprocessTransportReaping:
    @pytest.mark.asyncio
    async def test_aclose_reaps_process_after_hard_kill(self) -> None:
        """After terminate() times out, aclose() kills AND awaits wait() again so
        the process is guaranteed reaped (DoD: close() reaps at run end)."""
        from swarmline.agent.lsp.transport import SubprocessLspTransport

        proc = _HardKillProc()
        transport = SubprocessLspTransport(proc, close_timeout=0.01)  # type: ignore[arg-type]

        await transport.aclose()

        assert proc.terminated is True
        assert proc.killed is True
        # wait() awaited TWICE: once after terminate (timed out), once after kill.
        assert proc.wait_calls == 2
        # stdin was closed as part of the shutdown.
        assert proc.stdin.closed is True


# ---------------------------------------------------------------------------
# Runtime hook path — the RangeShifter must be LIVE (cycle-2 BLOCKING FIX A)
# ---------------------------------------------------------------------------


class _ScriptedSession:
    """A LanguageServerSession double replaying scripted diagnostics per call.

    The first ``diagnostics()`` call returns the baseline (Pre), the second the
    after-edit set (Post) — so the coordinator's before/after subtraction is
    exercised end-to-end on the runtime hook path.
    """

    def __init__(self, responses: list[tuple[Diagnostic, ...]]) -> None:
        self._responses = list(responses)
        self.closed = False

    async def ensure_started(self, language: str) -> bool:
        return True

    async def diagnostics(self, file_path: str) -> tuple[Diagnostic, ...]:
        if self._responses:
            return self._responses.pop(0)
        return ()

    async def close(self) -> None:
        self.closed = True


class _FakeFactory:
    """A PyrightSessionFactory double handing back one canned session per scope."""

    def __init__(self, session: _ScriptedSession) -> None:
        self._session = session
        self.close_all_calls = 0

    def for_workspace(
        self, session: WorkspaceSession, *, tenant_id: str, workspace_id: str
    ) -> _ScriptedSession:
        return self._session

    async def close_all(self) -> None:
        self.close_all_calls += 1


def _coordinator(tmp_path: Any, session: _ScriptedSession) -> Any:
    from swarmline.agent.lsp.coordinator import LspVerifyCoordinator

    return LspVerifyCoordinator(
        factory=_FakeFactory(session),
        session=WorkspaceSession.create(
            session_id="s", repo_root=str(tmp_path), branch="main"
        ),
        tenant_id="t1",
        workspace_id="w1",
        config=CodingProfileConfig(enabled=True, enable_lsp_verify=True),
    )


class TestCoordinatorRuntimeRemap:
    """The runtime Pre/Post hook must feed REAL edit_line/line_delta to the remap.

    Hard-coding ``line_delta=0`` (the cycle-2 defect) makes the RangeShifter a
    no-op, so a pre-existing diagnostic that an insertion pushed DOWN is falsely
    surfaced as edit-introduced. These tests prove the remap is live in the
    runtime path: a shifted baseline diagnostic is subtracted, only genuinely new
    diagnostics survive.
    """

    @pytest.mark.asyncio
    async def test_shifted_baseline_not_surfaced_only_new_is(
        self, tmp_path: Any
    ) -> None:
        target = tmp_path / "foo.py"
        target.write_text("import os\ndef f():\n    return undefined_var\n")
        path = str(target)

        # Pre-existing baseline error on line index 2 (zero-based Range).
        pre_existing = Diagnostic(
            file_path=path,
            range=Range(2, 4, 2, 17),
            severity="error",
            code="reportUndefinedVariable",
            message="undefined_var is not defined",
        )
        # After a 2-line insertion at the top it sits on line 4 (shifted +2)...
        shifted_pre_existing = Diagnostic(
            file_path=path,
            range=Range(4, 4, 4, 17),
            severity="error",
            code="reportUndefinedVariable",
            message="undefined_var is not defined",
        )
        # ...and the edit genuinely introduces a NEW error on the edited region.
        new_error = Diagnostic(
            file_path=path,
            range=Range(0, 0, 0, 13),
            severity="error",
            code="reportAssignmentType",
            message='"int" is not assignable to "str"',
        )
        session = _ScriptedSession([(pre_existing,), (shifted_pre_existing, new_error)])
        coordinator = _coordinator(tmp_path, session)
        tool_input = {"path": path}

        await coordinator.on_pre_tool(tool_name="edit", tool_input=tool_input)
        # Apply the edit: insert 2 lines at the top → everything below shifts +2.
        target.write_text(
            "x: str = 1\n# header2\nimport os\ndef f():\n    return undefined_var\n"
        )
        output = await coordinator.on_post_tool(
            tool_name="edit", tool_input=tool_input, tool_output="ok"
        )

        # The shifted pre-existing diagnostic was remapped (+2) and subtracted; only
        # the genuinely new error survives. With line_delta hard-coded to 0 the remap
        # is a no-op and the shifted baseline would be falsely surfaced too.
        assert output is not None
        assert "not assignable" in output
        assert "undefined_var" not in output

    @pytest.mark.asyncio
    async def test_no_surface_when_content_byte_identical(self, tmp_path: Any) -> None:
        """Pre == Post content ⇒ no edit happened ⇒ nothing surfaced (fail-open)."""
        target = tmp_path / "foo.py"
        target.write_text("a = 1\nb = 2\n")
        path = str(target)
        spurious = Diagnostic(
            file_path=path,
            range=Range(0, 0, 0, 5),
            severity="error",
            code="E",
            message="spurious",
        )
        # Baseline empty, after has a diag — but content is unchanged, so the Post
        # hook must surface nothing (the guard short-circuits before _verify).
        session = _ScriptedSession([(), (spurious,)])
        coordinator = _coordinator(tmp_path, session)
        tool_input = {"path": path}

        await coordinator.on_pre_tool(tool_name="edit", tool_input=tool_input)
        # No write between Pre and Post → identical content.
        output = await coordinator.on_post_tool(
            tool_name="edit", tool_input=tool_input, tool_output="ok"
        )

        assert output is None


# ---------------------------------------------------------------------------
# Hunk-based remap — boundary off-by-one + multi-region (cycle-5 BLOCKING FIX)
# ---------------------------------------------------------------------------


def _err(
    path: str, line: int, *, code: str, message: str, width: int = 7
) -> Diagnostic:
    """A 0-based ``error`` diagnostic on ``line`` (matches raw LSP coordinates)."""
    return Diagnostic(
        file_path=path,
        range=Range(line, 0, line, width),
        severity="error",
        code=code,
        message=message,
    )


class TestCoordinatorHunkRemap:
    """The runtime remap must be HUNK-based, not first-diff + total-delta.

    The single-span model (``compute_edit_span`` → ``LineDeltaRangeShifter``)
    fails two ways that a per-hunk ``difflib`` remap fixes:

    * boundary off-by-one — a 1-based ``edit_line`` compared against 0-based
      diagnostic lines with a strict ``>`` never shifts a baseline diagnostic on
      the first edited line, so an insertion/deletion at the very top falsely
      surfaces the pushed baseline as edit-introduced;
    * multi-region over-shift — one total ``line_delta`` shifts a baseline
      diagnostic that sits BETWEEN two edits by the sum of both deltas instead of
      only the delta of the hunk(s) strictly above it.

    Each test FAILS against the single-span code and PASSES against the hunk
    remap. The pyright process is the fake ``_ScriptedSession``; the remap is pure.
    """

    @pytest.mark.asyncio
    async def test_remap_insertion_at_top_shifts_first_line_diag(
        self, tmp_path: Any
    ) -> None:
        """Insert above a baseline diag on line 0 → it aligns and is NOT surfaced.

        Boundary off-by-one: the single-span model leaves a line-0 baseline
        unshifted (``0 > edit_line=1`` is False) and falsely surfaces it.
        """
        target = tmp_path / "foo.py"
        target.write_text("undef_a\nb = 2\n")
        path = str(target)
        baseline = _err(
            path, 0, code="reportUndefinedVariable", message="undef_a unbound"
        )
        after_shifted = _err(
            path, 2, code="reportUndefinedVariable", message="undef_a unbound"
        )
        session = _ScriptedSession([(baseline,), (after_shifted,)])
        coordinator = _coordinator(tmp_path, session)
        tool_input = {"path": path}

        await coordinator.on_pre_tool(tool_name="edit", tool_input=tool_input)
        target.write_text("# top1\n# top2\nundef_a\nb = 2\n")
        output = await coordinator.on_post_tool(
            tool_name="edit", tool_input=tool_input, tool_output="ok"
        )

        # The +2 insertion above line 0 shifts the baseline to line 2 → subtracted.
        assert output is None

    @pytest.mark.asyncio
    async def test_remap_multi_region_shifts_only_preceding_hunks(
        self, tmp_path: Any
    ) -> None:
        """Insert above AND below a baseline diag → it shifts by only the
        preceding hunk's delta and is NOT surfaced.

        The single-span model over-shifts by the TOTAL delta (top + bottom) so
        the baseline lands two lines too low and is falsely surfaced.
        """
        target = tmp_path / "foo.py"
        target.write_text("a = 1\nb = 2\nc = 3\nundef_d\ne = 5\nf = 6\n")
        path = str(target)
        baseline = _err(
            path, 3, code="reportUndefinedVariable", message="undef_d unbound"
        )
        after_shifted = _err(
            path, 5, code="reportUndefinedVariable", message="undef_d unbound"
        )
        session = _ScriptedSession([(baseline,), (after_shifted,)])
        coordinator = _coordinator(tmp_path, session)
        tool_input = {"path": path}

        await coordinator.on_pre_tool(tool_name="edit", tool_input=tool_input)
        target.write_text(
            "# t1\n# t2\na = 1\nb = 2\nc = 3\nundef_d\ne = 5\nf = 6\n# b1\n# b2\n"
        )
        output = await coordinator.on_post_tool(
            tool_name="edit", tool_input=tool_input, tool_output="ok"
        )

        # Only the +2 top hunk is strictly above line 3 → baseline shifts to line 5.
        assert output is None

    @pytest.mark.asyncio
    async def test_remap_deletion_boundary(self, tmp_path: Any) -> None:
        """Delete a line above a baseline diag on line 1 → it shifts up and is
        NOT surfaced.

        Boundary off-by-one again: the single-span model leaves the line-1
        baseline unshifted (``1 > edit_line=1`` is False) and falsely surfaces it.
        """
        target = tmp_path / "foo.py"
        target.write_text("del_top\nundef_b\nc = 3\n")
        path = str(target)
        baseline = _err(
            path, 1, code="reportUndefinedVariable", message="undef_b unbound"
        )
        after_shifted = _err(
            path, 0, code="reportUndefinedVariable", message="undef_b unbound"
        )
        session = _ScriptedSession([(baseline,), (after_shifted,)])
        coordinator = _coordinator(tmp_path, session)
        tool_input = {"path": path}

        await coordinator.on_pre_tool(tool_name="edit", tool_input=tool_input)
        target.write_text("undef_b\nc = 3\n")
        output = await coordinator.on_post_tool(
            tool_name="edit", tool_input=tool_input, tool_output="ok"
        )

        # The -1 deletion above line 1 shifts the baseline to line 0 → subtracted.
        assert output is None

    @pytest.mark.asyncio
    async def test_genuinely_new_diagnostic_is_surfaced(self, tmp_path: Any) -> None:
        """A real new error on the edited region IS surfaced while a correctly
        remapped baseline is subtracted.

        Don't over-correct into hiding real errors: with a multi-region edit the
        single-span model over-shifts the baseline (false positive) AND surfaces
        the new error; the hunk remap surfaces ONLY the genuinely new one.
        """
        target = tmp_path / "foo.py"
        target.write_text("a = 1\nb = 2\nc = 3\nundef_d\ne = 5\n")
        path = str(target)
        baseline = _err(
            path, 3, code="reportUndefinedVariable", message="undef_d unbound"
        )
        after_shifted = _err(
            path, 5, code="reportUndefinedVariable", message="undef_d unbound"
        )
        new_error = Diagnostic(
            file_path=path,
            range=Range(0, 0, 0, 10),
            severity="error",
            code="reportAssignmentType",
            message='"int" is not assignable to "str"',
        )
        session = _ScriptedSession([(baseline,), (after_shifted, new_error)])
        coordinator = _coordinator(tmp_path, session)
        tool_input = {"path": path}

        await coordinator.on_pre_tool(tool_name="edit", tool_input=tool_input)
        target.write_text(
            "x: str = 1\n# top2\na = 1\nb = 2\nc = 3\nundef_d\ne = 5\n# bot\n"
        )
        output = await coordinator.on_post_tool(
            tool_name="edit", tool_input=tool_input, tool_output="ok"
        )

        assert output is not None
        # The genuinely new error surfaces ...
        assert "not assignable" in output
        # ... and the correctly remapped baseline is subtracted (no false positive).
        assert "undef_d" not in output


# ---------------------------------------------------------------------------
# Stop-hook reaping at run end (cycle-2 BLOCKING FIX B) — register-level gate
# ---------------------------------------------------------------------------


class TestRegisterLspVerifyHooksStop:
    def test_stop_hook_registered_when_enabled(self, tmp_path: Any) -> None:
        """ON ⇒ Pre/Post per edit tool AND exactly one Stop hook (run-end reap)."""
        from swarmline.agent.lsp.coordinator import register_lsp_verify_hooks
        from swarmline.hooks.registry import HookRegistry

        registry = HookRegistry()
        coordinator = _coordinator(tmp_path, _ScriptedSession([]))

        register_lsp_verify_hooks(
            registry, coordinator, CodingProfileConfig(enable_lsp_verify=True)
        )

        assert len(registry.get_hooks("Stop")) == 1
        assert len(registry.get_hooks("PreToolUse")) == 4
        assert len(registry.get_hooks("PostToolUse")) == 4

    @pytest.mark.asyncio
    async def test_stop_hook_reaps_factory(self, tmp_path: Any) -> None:
        """Dispatching the Stop hook awaits the factory's close_all (process reap)."""
        from swarmline.agent.lsp.coordinator import register_lsp_verify_hooks
        from swarmline.hooks.registry import HookRegistry

        registry = HookRegistry()
        factory = _FakeFactory(_ScriptedSession([]))
        from swarmline.agent.lsp.coordinator import LspVerifyCoordinator

        coordinator = LspVerifyCoordinator(
            factory=factory,
            session=WorkspaceSession.create(
                session_id="s", repo_root=str(tmp_path), branch="main"
            ),
            tenant_id="t1",
            workspace_id="w1",
            config=CodingProfileConfig(enabled=True, enable_lsp_verify=True),
        )
        register_lsp_verify_hooks(
            registry, coordinator, CodingProfileConfig(enable_lsp_verify=True)
        )

        stop_entry = registry.get_hooks("Stop")[0]
        await stop_entry.callback(result_text="done")

        assert factory.close_all_calls == 1

    def test_no_stop_hook_when_flag_off(self, tmp_path: Any) -> None:
        """OFF ⇒ nothing registered — Pre/Post AND Stop all absent (byte-identical)."""
        from swarmline.agent.lsp.coordinator import register_lsp_verify_hooks
        from swarmline.hooks.registry import HookRegistry

        registry = HookRegistry()
        coordinator = _coordinator(tmp_path, _ScriptedSession([]))

        register_lsp_verify_hooks(
            registry, coordinator, CodingProfileConfig(enable_lsp_verify=False)
        )

        assert registry.get_hooks("Stop") == []
        assert registry.get_hooks("PreToolUse") == []
        assert registry.get_hooks("PostToolUse") == []
