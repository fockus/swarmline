"""LspVerifyCoordinator — in-turn type-aware verify hook (Task 8 wiring).

Mirrors :class:`~swarmline.runtime.thin.edit_verify_coordinator.EditSnapshotCoordinator`
(the T4 lint-delta loop) but type-aware: a ``PreToolUse`` hook snapshots the
baseline pyright diagnostics for the file an edit will touch; a ``PostToolUse``
hook re-reads diagnostics on the SAME persistent session, computes the
edit-introduced set via :class:`SnapshotLspVerifier`, runs it through the gated
``lsp`` criterion (:func:`register_lsp_criterion` → :func:`lsp_criterion`), and
appends any edit-introduced type error to ``tool_output``.

Fail-open throughout: pyright missing / not started, or any error, leaves the
agent loop untouched (mirrors the dispatcher's fail-open contract). The hook is
only registered when ``enable_lsp_verify`` is set AND a code-workspace
``WorkspaceSession`` seam is present — flag off ⇒ byte-identical default path.
"""

from __future__ import annotations

import asyncio
import logging
from types import MappingProxyType
from typing import TYPE_CHECKING

from swarmline.agent.lsp.edit_span import PendingEdit, read_lines
from swarmline.agent.lsp.range_shift import LineDeltaRangeShifter, remap_by_opcodes
from swarmline.agent.lsp.session import DiagnosticSnapshot
from swarmline.agent.lsp.verifier import (
    SnapshotLspVerifier,
    lsp_criterion,
    register_lsp_criterion,
)
from swarmline.hooks.dispatcher import HookResult
from swarmline.orchestration.verification_types import (
    VerificationResult,
    VerificationStatus,
)
from swarmline.orchestration.verifier_registry import VerifierRegistry

if TYPE_CHECKING:
    from swarmline.agent.lsp.pyright import PyrightSessionFactory
    from swarmline.agent.lsp.session import LanguageServerSession
    from swarmline.hooks.registry import HookRegistry
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig
    from swarmline.workspace.types import WorkspaceSession

logger = logging.getLogger(__name__)

# Exact edit/write tool names this coordinator snapshots — registered one-per-name
# because the dispatcher's fnmatch matchers have no `|` alternation (NEW-ISSUE-1),
# matching EditSnapshotCoordinator's EDIT_TOOL_NAMES.
EDIT_TOOL_NAMES: tuple[str, ...] = ("edit", "write", "multi_edit", "multi_file_edit")

# An immutable empty base registry: register_lsp_criterion gates the `lsp` entry
# onto it, so the in-turn check honours the SAME flag as the DoD registry path.
_EMPTY_REGISTRY: VerifierRegistry = VerifierRegistry(fns=MappingProxyType({}))


class LspVerifyCoordinator:
    """Snapshots baseline diagnostics on Pre, surfaces edit-introduced errors on Post.

    Holds a per-run ``{path: baseline_snapshot}`` map. A baseline is invalidated
    (popped) after its delta is rendered, so a stale Post without a fresh Pre is a
    no-op.
    """

    def __init__(
        self,
        *,
        factory: PyrightSessionFactory,
        session: WorkspaceSession,
        tenant_id: str,
        workspace_id: str,
        config: CodingProfileConfig,
    ) -> None:
        self._factory = factory
        self._session = session
        self._tenant_id = tenant_id
        self._workspace_id = workspace_id
        self._config = config
        self._range_shifter = LineDeltaRangeShifter()
        self._baselines: dict[str, PendingEdit] = {}

    def _server(self) -> LanguageServerSession:
        """Resolve the pyright session for this coordinator's scope (one per scope)."""
        return self._factory.for_workspace(
            self._session,
            tenant_id=self._tenant_id,
            workspace_id=self._workspace_id,
        )

    def _root(self) -> str:
        """Workspace root used to resolve relative edit paths to file content."""
        return self._session.worktree_path or self._session.repo_root

    async def on_pre_tool(self, *, tool_name: str, tool_input: dict) -> HookResult:
        """Snapshot the baseline pyright diagnostics for the path(s) to be edited.

        Best-effort: server unavailable (fail-open ``ensure_started`` → False) → no
        baseline captured → the Post hook is a no-op. ALWAYS allow — blocking is
        Task 6's concern, never this coordinator's.
        """
        try:
            server = self._server()
            if not await server.ensure_started("python"):
                return HookResult.allow()
            root = self._root()
            for path in _paths_for(tool_name, tool_input):
                diags = await server.diagnostics(path)
                pre_lines = await asyncio.to_thread(read_lines, root, path)
                self._baselines[path] = PendingEdit(
                    baseline=DiagnosticSnapshot(by_file={path: diags}),
                    pre_lines=pre_lines,
                )
        except Exception:
            logger.warning(
                "LspVerifyCoordinator.on_pre_tool failed for %r (fail-open)",
                tool_name,
                exc_info=True,
            )
        return HookResult.allow()

    async def on_post_tool(
        self, *, tool_name: str, tool_input: dict, tool_output: str
    ) -> str | None:
        """Append edit-introduced type errors (if any) to ``tool_output``.

        Returns the augmented output when an edit-introduced error exists, else
        None (no change). The baseline for each path is invalidated afterwards.
        Fail-open → None.
        """
        try:
            server = self._server()
            root = self._root()
            blocks: list[str] = []
            for path in _paths_for(tool_name, tool_input):
                pending = self._baselines.pop(path, None)
                if pending is None:
                    continue  # no fresh Pre snapshot → nothing to compare
                post_lines = await asyncio.to_thread(read_lines, root, path)
                if pending.pre_lines == post_lines:
                    continue  # byte-identical content → no edit was applied
                result = await self._verify(server, path, pending, post_lines)
                if result is not None and result.status == VerificationStatus.FAIL:
                    blocks.append(_render_result(result))
            if not blocks:
                return None
            return tool_output + "\n\n" + "\n".join(blocks)
        except Exception:
            logger.warning(
                "LspVerifyCoordinator.on_post_tool failed for %r (fail-open)",
                tool_name,
                exc_info=True,
            )
            return None

    async def on_stop(self, *, result_text: str) -> None:
        """Reap every pyright process started during the run (run-end cleanup).

        Registered as a ``Stop`` hook so the per-``(tenant, workspace)`` pyright
        sessions the factory spun up are closed when the run ends (DoD: process
        reaped at run end). Without it the subprocesses leak past the run.
        Fail-open: a cleanup error never propagates into the agent loop.
        """
        try:
            await self._factory.close_all()
        except Exception:
            logger.warning(
                "LspVerifyCoordinator.on_stop close_all failed (fail-open)",
                exc_info=True,
            )

    async def _verify(
        self,
        server: LanguageServerSession,
        path: str,
        pending: PendingEdit,
        post_lines: tuple[str, ...],
    ) -> VerificationResult | None:
        """Run the gated ``lsp`` criterion for a single edited file.

        The baseline is remapped through the edit with the hunk-based
        :func:`remap_by_opcodes` (pre vs post lines), which shifts each baseline
        diagnostic by the cumulative delta of the hunks strictly above it —
        correct at the insertion/deletion boundary and across multi-region edits.
        The remapped baseline is then fed to :class:`SnapshotLspVerifier` with the
        identity shift (``line_delta=0`` makes its ``LineDeltaRangeShifter`` a
        no-op, so the hunk remap is not applied twice); only genuinely
        edit-introduced diagnostics survive the subtraction. The criterion is
        installed via :func:`register_lsp_criterion`, so the in-turn check is
        reachable only when ``enable_lsp_verify`` is set — the same gate the DoD
        registry uses.
        """
        remapped = remap_by_opcodes(
            pending.baseline, path, pending.pre_lines, post_lines
        )
        verifier = SnapshotLspVerifier(
            session=server,
            range_shifter=self._range_shifter,
            baseline=remapped,
        )
        criterion = lsp_criterion(
            verifier,
            file_path=path,
            edit_line=0,
            line_delta=0,
        )
        registry = register_lsp_criterion(_EMPTY_REGISTRY, criterion, self._config)
        fn = registry.fns.get("lsp")
        if fn is None:
            return None
        return await fn()


def register_lsp_verify_hooks(
    registry: HookRegistry,
    coordinator: LspVerifyCoordinator,
    config: CodingProfileConfig,
) -> None:
    """Register the coordinator's Pre/Post/Stop hooks — gated on the flag.

    Gated on ``config.enable_lsp_verify``: when False, nothing is registered (the
    default path stays byte-identical — no Pre, no Post, and no Stop hook). One
    ``PreToolUse`` and one ``PostToolUse`` entry per name in
    :data:`EDIT_TOOL_NAMES`, each with ``matcher`` set to the exact name — never
    an alternation (fnmatch has no ``|`` support). A single ``Stop`` hook reaps
    the per-``(tenant, workspace)`` pyright processes the factory spun up, so they
    never leak past the run (DoD: process reaped at run end).
    """
    if not config.enable_lsp_verify:
        return
    for name in EDIT_TOOL_NAMES:
        registry.on_pre_tool_use(coordinator.on_pre_tool, matcher=name)
        registry.on_post_tool_use(coordinator.on_post_tool, matcher=name)
    registry.on_stop(coordinator.on_stop)


def _paths_for(tool_name: str, tool_input: dict) -> list[str]:
    """Extract mutated path(s) from a tool's input.

    edit/write/multi_edit use a single ``path`` key; multi_file_edit carries
    ``edits: [{path, ...}]`` across files. Mirrors EditSnapshotCoordinator._paths_for
    (duplicated rather than imported to keep the application layer off infrastructure).
    """
    if tool_name == "multi_file_edit":
        edits = tool_input.get("edits") or []
        seen: list[str] = []
        for edit in edits:
            path = edit.get("path") if isinstance(edit, dict) else None
            if isinstance(path, str) and path and path not in seen:
                seen.append(path)
        return seen
    path = tool_input.get("path")
    return [path] if isinstance(path, str) and path else []


def _render_result(result: VerificationResult) -> str:
    """Render a verify-feedback block from a FAIL VerificationResult."""
    lines = ["[lsp] " + result.summary]
    for check in result.checks:
        lines.append(f"  - {check.message}")
    return "\n".join(lines)
