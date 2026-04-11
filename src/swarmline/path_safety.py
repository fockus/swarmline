"""Helpers for safe namespace/path segment handling."""

from __future__ import annotations

from pathlib import Path

_SAFE_SEGMENT_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)


def validate_namespace_segment(name: str, label: str) -> str:
    """Validate a namespace/path segment and return it unchanged."""
    if not name or ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Invalid {label}: {name!r}")
    if not all(ch in _SAFE_SEGMENT_CHARS for ch in name):
        raise ValueError(f"Invalid characters in {label}: {name!r}")
    return name


def build_isolated_path(root: str | Path, *segments: str) -> Path:
    """Build a path under root and reject traversal through raw segments."""
    resolved_root = Path(root).resolve()
    candidate = resolved_root
    for segment in segments:
        candidate = candidate / segment
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_root):
        raise ValueError(f"Path traversal detected: {resolved_candidate}")
    return resolved_candidate
