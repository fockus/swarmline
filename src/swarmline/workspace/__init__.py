"""Workspace package — safe repo/git/worktree operations.

Lazy exports via __getattr__ to keep import cost minimal.
"""

from __future__ import annotations

_TYPE_EXPORTS = {
    "MutationMode",
    "WorkspaceSessionStatus",
    "FileOperationType",
    "WorkspaceSession",
    "GitOperationResult",
    "MutationRecord",
    "MutationPolicyViolation",
    "ConflictError",
    "compute_content_hash",
}

_PROTOCOL_EXPORTS = {
    "GitOperationsPort",
    "MutationPolicyPort",
    "OwnChangesTrackerPort",
    "ConflictDetectorPort",
    "VerificationRunnerPort",
}

_MUTATION_EXPORTS = {
    "MutationPolicy",
    "OwnChangesTracker",
}

_CONFLICT_EXPORTS = {
    "ConflictDetector",
}

_GIT_EXPORTS = {
    "LocalGitOperations",
}

_VERIFICATION_EXPORTS = {
    "WorkspaceVerificationRunner",
}

_TOOLS_EXPORTS = {
    "create_workspace_tools",
}

_ALL_EXPORTS = (
    _TYPE_EXPORTS
    | _PROTOCOL_EXPORTS
    | _MUTATION_EXPORTS
    | _CONFLICT_EXPORTS
    | _GIT_EXPORTS
    | _VERIFICATION_EXPORTS
    | _TOOLS_EXPORTS
)

__all__ = list(_ALL_EXPORTS)

_MODULE_MAP: dict[str, str] = {
    **{name: "types" for name in _TYPE_EXPORTS},
    **{name: "protocols" for name in _PROTOCOL_EXPORTS},
    **{name: "mutation" for name in _MUTATION_EXPORTS},
    **{name: "conflict" for name in _CONFLICT_EXPORTS},
    **{name: "git_local" for name in _GIT_EXPORTS},
    **{name: "verification" for name in _VERIFICATION_EXPORTS},
    **{name: "tools" for name in _TOOLS_EXPORTS},
}


def __getattr__(name: str) -> object:
    module_name = _MODULE_MAP.get(name)
    if module_name is not None:
        import importlib

        mod = importlib.import_module(f"swarmline.workspace.{module_name}")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
