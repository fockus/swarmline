"""Pyright JSON-RPC wire helpers — severity map, diagnostic parsing, file read.

Pure functions split out of :mod:`swarmline.agent.lsp.pyright` (SRP): they turn a
raw LSP diagnostic dict into a typed :class:`Diagnostic` and read file text, with
no knowledge of the persistent-session lifecycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from swarmline.agent.lsp.session import Diagnostic, Range, Severity

# LSP DiagnosticSeverity (1=Error, 2=Warning, 3=Information, 4=Hint).
SEVERITY_MAP: dict[int, Severity] = {1: "error", 2: "warning", 3: "info", 4: "info"}


def parse_diagnostic(file_path: str, raw: Mapping[str, Any]) -> Diagnostic:
    """Build a typed :class:`Diagnostic` from a raw LSP diagnostic dict."""
    rng = raw.get("range", {})
    start = rng.get("start", {})
    end = rng.get("end", {})
    code = raw.get("code")
    return Diagnostic(
        file_path=file_path,
        range=Range(
            start_line=int(start.get("line", 0)),
            start_char=int(start.get("character", 0)),
            end_line=int(end.get("line", 0)),
            end_char=int(end.get("character", 0)),
        ),
        severity=SEVERITY_MAP.get(int(raw.get("severity", 3)), "info"),
        code=str(code) if code is not None else None,
        message=str(raw.get("message", "")),
    )


def read_text(path: str) -> str:
    """Read file text; a missing/unreadable file is an empty string (fail-open)."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""
