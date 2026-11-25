"""Code Runtime adapters — CodeRuntimePort implementations.

Lazy exports: adapters are only imported when accessed,
so optional SDK dependencies (anthropic, openai) don't cause
ImportError at import time.
"""

from __future__ import annotations

from typing import Any

_OPTIONAL_EXPORTS: dict[str, tuple[str, str]] = {
    "ClaudeCodeRuntimeAdapter": (
        "swarmline.runtime.code_runtime.claude",
        "ClaudeCodeRuntimeAdapter",
    ),
    "CodexCodeRuntimeAdapter": (
        "swarmline.runtime.code_runtime.codex",
        "CodexCodeRuntimeAdapter",
    ),
}


def __getattr__(name: str) -> Any:
    if name in _OPTIONAL_EXPORTS:
        module_path, attr = _OPTIONAL_EXPORTS[name]
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_OPTIONAL_EXPORTS)
