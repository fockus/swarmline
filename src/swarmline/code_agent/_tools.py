"""Capability tool assembly (code-agent-facade plan, Stage 3).

`assemble_capability_tools` wires the v1.7.0 capability tool factories --
governance, workspace, scratchpad, code_intel -- into one merged
`(specs, executors)` pair that `CodeAgent._augment_plan` merges into the
portable runtime plan. Every collaborator constructed here is an EXISTING
port implementation (see the plan's "What v1.7.0 already provides" reuse
table); this module adds no new Protocol and no new tool executor of its
own, with one narrow exception: `_ShellCommandRunner`, a thin adapter over
the EXISTING `orchestration.code_verifier.CommandRunner` Protocol (mirrors
how `LocalGitOperations` adapts `GitOperationsPort`) -- `WorkspaceVerificationRunner`
needs a `CommandRunner` and no production implementation ships one yet.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmline.orchestration.code_verifier import CommandResult
    from swarmline.runtime.types import ToolSpec

#: Wall-clock budget for a single `run_verification`/`run_lint` invocation.
#: ponytail: the thin runtime's local-tool executor (`runtime/thin/
#: executor.py`, class `ToolExecutor`) wraps EVERY local tool call in its
#: own 30s timeout, unconditionally (constructed with the class default;
#: not configurable via the facade today) -- the coding toolpack's own
#: `bash` tool has the exact same 30s ceiling via
#: `SandboxConfig.timeout_seconds`. This stays comfortably under that so
#: OUR clean, structured timeout result fires first instead of the generic
#: "Таймаут выполнения ..." the executor produces. A real full test/lint
#: suite still exceeds both ceilings -- that is a pre-existing platform
#: constraint, not something this module can fix; raise/make-configurable
#: the executor's timeout when long-running verification becomes a
#: priority.
_VERIFY_COMMAND_TIMEOUT_SECONDS = 25.0


async def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Best-effort SIGKILL to the WHOLE process group `proc` leads.

    `proc` is started with `start_new_session=True` (its own session/process
    group), so killing just `proc.pid` (the shell) would leave anything IT
    spawned -- e.g. the actual test/lint command a `cd ... && <command>`
    shell line runs -- alive, reparented and orphaned. `os.killpg` reaches
    the whole group in one shot. Swallows `ProcessLookupError`/
    `PermissionError` (already exited / exotic sandbox) -- this is cleanup,
    not a correctness-critical path.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError, TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=5.0)


class _ShellCommandRunner:
    """`CommandRunner` (orchestration.code_verifier) backed by a real shell.

    `WorkspaceVerificationRunner` builds commands of the shape
    ``cd <cwd> && <command>`` -- a combinator only a real shell understands
    (unlike e.g. `LocalGitOperations`, which never needs shell semantics and
    always uses `create_subprocess_exec`). This is safe here because
    `WorkspaceVerificationRunner` validates the agent-supplied ``command``
    against a shell-metacharacter blocklist BEFORE building the
    ``cd ... &&`` wrapper -- the only shell operator that ever reaches the
    shell is the one `WorkspaceVerificationRunner` adds itself.
    """

    async def run(self, command: str) -> CommandResult:
        from swarmline.orchestration.code_verifier import CommandResult

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_VERIFY_COMMAND_TIMEOUT_SECONDS
            )
        except TimeoutError:
            # OUR OWN budget elapsed -- no outer cancellation involved.
            # Report a clean, structured timeout result instead of raising.
            await _kill_process_group(proc)
            return CommandResult(
                exit_code=124,
                stdout="",
                stderr=(
                    "verification command timed out after "
                    f"{_VERIFY_COMMAND_TIMEOUT_SECONDS:.0f}s"
                ),
            )
        except asyncio.CancelledError:
            # An OUTER cancellation (e.g. ToolExecutor's own per-call
            # timeout) reached us mid-command. Kill the whole process group
            # so the shell's child never survives as an orphan, then
            # propagate the cancellation -- swallowing `CancelledError` here
            # would violate asyncio's cancellation contract.
            await _kill_process_group(proc)
            raise
        return CommandResult(
            exit_code=proc.returncode if proc.returncode is not None else 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )


def _assemble_governance_tools() -> tuple[
    dict[str, ToolSpec], dict[str, Callable[..., Any]]
]:
    """Build the 4 governance tools with default (in-memory) port impls."""
    from swarmline.governance.approval_gates import ApprovalGateManager
    from swarmline.governance.audit_trail import InMemoryAuditTrail
    from swarmline.governance.governance_tools import create_governance_tools
    from swarmline.governance.permission_manager import PermissionManager
    from swarmline.governance.secret_boundary import SecretBoundaryManager

    return create_governance_tools(
        permission_manager=PermissionManager(),
        approval_gate=ApprovalGateManager(),
        audit_trail=InMemoryAuditTrail(),
        secret_boundary=SecretBoundaryManager(),
    )


def _assemble_code_intel_tools() -> tuple[
    dict[str, ToolSpec], dict[str, Callable[..., Any]]
]:
    """Build the 5 code-intel tools with default (Python+TS) analyzers."""
    from swarmline.code_intel.coverage_checker import ImportBasedCoverageAnalyzer
    from swarmline.code_intel.impact_analyzer import GraphImpactAnalyzer
    from swarmline.code_intel.language_parsers import (
        CompositeLanguageParser,
        PythonSeamParser,
        TypeScriptSeamParser,
    )
    from swarmline.code_intel.repo_mapper import ASTRepoMapper
    from swarmline.code_intel.tools import create_code_intel_tools

    language_parser = CompositeLanguageParser()
    language_parser.register_parser(PythonSeamParser())
    language_parser.register_parser(TypeScriptSeamParser())

    return create_code_intel_tools(
        repo_mapper=ASTRepoMapper(),
        impact_analyzer=GraphImpactAnalyzer(),
        language_parser=language_parser,
        coverage_analyzer=ImportBasedCoverageAnalyzer(),
    )


def _assemble_scratchpad_tools() -> tuple[
    dict[str, ToolSpec], dict[str, Callable[..., Any]]
]:
    """Build the 4 scratchpad tools over a fresh in-memory provider."""
    from swarmline.scratchpad.inmemory_provider import InMemoryScratchpadProvider
    from swarmline.scratchpad.tools import create_scratchpad_tools

    return create_scratchpad_tools(InMemoryScratchpadProvider())


def _assemble_workspace_tools(
    cwd: str,
) -> tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]]:
    """Build the 6 workspace tools bound to a `WorkspaceSession` rooted at `cwd`."""
    from swarmline.workspace.conflict import ConflictDetector
    from swarmline.workspace.git_local import LocalGitOperations
    from swarmline.workspace.mutation import MutationPolicy, OwnChangesTracker
    from swarmline.workspace.tools import create_workspace_tools
    from swarmline.workspace.types import MutationMode, WorkspaceSession
    from swarmline.workspace.verification import WorkspaceVerificationRunner

    session = WorkspaceSession.create(
        session_id=str(uuid.uuid4()),
        repo_root=cwd,
        # Informational metadata only -- no workspace tool reads `.branch`
        # (git operations use `session.repo_root`/`.worktree_path`, both
        # `cwd` here, so this never affects which repo the tools touch).
        branch="unknown",
        # AUTO_APPLY: the coding toolpack already lets the agent write/edit
        # files directly -- that IS the facade's purpose. Scoping
        # `git_commit`/`git_revert` to READ_ONLY here would just add a
        # second, redundant write gate on top of the coding-profile tool
        # policy + the optional `on_permission_request` hook.
        mutation_mode=MutationMode.AUTO_APPLY,
    )
    return create_workspace_tools(
        LocalGitOperations(),
        MutationPolicy(),
        OwnChangesTracker(),
        ConflictDetector(),
        WorkspaceVerificationRunner(_ShellCommandRunner()),
        session,
    )


def _apply_verify_command_override(
    executors: dict[str, Callable[..., Any]], verify_command: str | None
) -> None:
    """Wrap the `run_verification` executor so a missing `command` argument
    for `check_type == "tests"` defaults to `verify_command` instead of
    `WorkspaceVerificationRunner`'s hardcoded `"pytest"` (code-agent-facade
    plan, Stage 4).

    An explicit `command` from the caller (the LLM) always wins -- this only
    supplies a smarter DEFAULT, never overrides an explicit request; `lint`
    checks are untouched (the override is scoped to the TEST command only,
    per the plan). No-op when `verify_command` is `None` -- byte-identical
    to the pre-Stage-4 wiring (Strangler Fig: new knob is purely additive).
    """
    if verify_command is None:
        return
    original = executors["run_verification"]

    async def _run_verification_with_override(args: dict[str, Any]) -> str:
        effective_args = dict(args)
        if effective_args.get("check_type") == "tests" and not effective_args.get(
            "command"
        ):
            effective_args["command"] = verify_command
        return await original(effective_args)

    executors["run_verification"] = _run_verification_with_override


def assemble_capability_tools(
    cwd: str,
    *,
    verify_command: str | None = None,
) -> tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]]:
    """Merge the governance/workspace/scratchpad/code_intel capability tools.

    Returns the `(specs, executors)` pair `CodeAgent._augment_plan` merges
    into the portable runtime plan. The 4 capability blocks use disjoint
    tool-name namespaces (each factory's own tool list is fixed and
    non-overlapping), so merging them here is a plain `dict.update` with no
    internal collisions; only the merge against the CODING toolpack (done by
    the caller, `_facade._augment_plan`) needs a precedence rule, since only
    that pack can register a colliding name (e.g. `repo_map` when
    `enable_repo_map_ranking` is set on the coding profile).

    `verify_command` (Stage 4) overrides the DEFAULT test command
    `run_verification` forwards to `WorkspaceVerificationRunner` -- see
    `_apply_verify_command_override`.
    """
    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable[..., Any]] = {}

    for block_specs, block_executors in (
        _assemble_governance_tools(),
        _assemble_workspace_tools(cwd),
        _assemble_scratchpad_tools(),
        _assemble_code_intel_tools(),
    ):
        specs.update(block_specs)
        executors.update(block_executors)

    _apply_verify_command_override(executors, verify_command)

    return specs, executors
