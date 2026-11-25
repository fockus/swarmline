"""Artifacts capability -- typed file/artifact system for agent working memory.

Ported from Aura's ``RunWorkspace`` artifact subsystem ("File System = Context",
Manus-style): typed directory routing (:class:`ArtifactType`), a human/LLM-
readable File Registry (``.registry.md``, injected into context by
``context/builder.py``'s ``available_files`` param), versioned live files, an
append-only step journal, and sub-agent inheritance via
``ArtifactRoot.create_child()`` / ``read_parent_file()``.

Lazy exports via ``__getattr__`` to keep import cost minimal (mirrors
``swarmline.workspace``/``swarmline.todo``).
"""

from __future__ import annotations

_TYPE_EXPORTS = {"Artifact", "ArtifactType", "FileEntry", "StepJournalEntry"}
_PROTOCOL_EXPORTS = {"ArtifactStorePort"}
_RUN_ROOT_EXPORTS = {"ArtifactRoot"}
_REGISTRY_EXPORTS = {"ArtifactRegistry"}
_FILE_REGISTRY_EXPORTS = {"FileRegistry"}
_LIVE_FILES_EXPORTS = {"LiveFilesManager"}
_STEP_JOURNAL_EXPORTS = {"StepJournal"}
_HOOKS_EXPORTS = {"PostStepHookRunner"}
_FS_STORE_EXPORTS = {"FSArtifactStore"}
_TOOLS_EXPORTS = {
    "WORKSPACE_MEMORY_PROMPT",
    "create_artifact_tools",
    "create_workspace_tools",
}

_ALL_EXPORTS = (
    _TYPE_EXPORTS
    | _PROTOCOL_EXPORTS
    | _RUN_ROOT_EXPORTS
    | _REGISTRY_EXPORTS
    | _FILE_REGISTRY_EXPORTS
    | _LIVE_FILES_EXPORTS
    | _STEP_JOURNAL_EXPORTS
    | _HOOKS_EXPORTS
    | _FS_STORE_EXPORTS
    | _TOOLS_EXPORTS
)

__all__ = list(_ALL_EXPORTS)

_MODULE_MAP: dict[str, str] = {
    **{name: "types" for name in _TYPE_EXPORTS},
    **{name: "protocols" for name in _PROTOCOL_EXPORTS},
    **{name: "run_root" for name in _RUN_ROOT_EXPORTS},
    **{name: "registry" for name in _REGISTRY_EXPORTS},
    **{name: "file_registry" for name in _FILE_REGISTRY_EXPORTS},
    **{name: "live_files" for name in _LIVE_FILES_EXPORTS},
    **{name: "step_journal" for name in _STEP_JOURNAL_EXPORTS},
    **{name: "hooks" for name in _HOOKS_EXPORTS},
    **{name: "fs_store" for name in _FS_STORE_EXPORTS},
    **{name: "tools" for name in _TOOLS_EXPORTS},
}


def __getattr__(name: str) -> object:
    module_name = _MODULE_MAP.get(name)
    if module_name is not None:
        import importlib

        mod = importlib.import_module(f"swarmline.artifacts.{module_name}")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
