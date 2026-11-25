"""LocalFsProjectRulesLoader — filesystem loader for project instruction files.

REQ-OSS-060: swarmline-native, zero product coupling.

Discovers and reads agent instruction files (CLAUDE.md, AGENTS.md,
.github/AGENTS.md) from a given project root directory with security
hardening:

- Precedence: CLAUDE.md > AGENTS.md > .github/AGENTS.md (D-03 semantics)
- Path-traversal guard: resolved path must be inside resolved project_root
- Size cap: 1MB hard limit
- Not-found detection

All error conditions raise ``ValueError`` — no product-level exception types
are imported. Callers that require a domain-specific error type should catch
``ValueError`` and re-raise.

Note: pathlib operations are CPU-bound (no blocking I/O for resolve/stat/exists).
ASYNC240 noqa applied — this codebase uses asyncio (not trio/anyio), and
filesystem stat/exists are fast syscalls acceptable in an async context for
local paths.
"""

from __future__ import annotations

from pathlib import Path  # noqa: ASYNC240

_SIZE_CAP_BYTES = 1_048_576  # 1 MB hard limit

_CANDIDATE_NAMES = [
    "CLAUDE.md",  # highest precedence (D-03)
    "AGENTS.md",  # second
    ".github/AGENTS.md",  # fallback
]


class LocalFsProjectRulesLoader:
    """Path-based loader for AGENTS.md/CLAUDE.md — security-hardened, product-free.

    Generic swarmline primitive (REQ-OSS-060). Raises ``ValueError`` on all
    guard violations so product layers can re-raise their own error types.
    """

    async def discover_paths(self, project_root: str) -> list[str]:
        """Return first matching candidate path under project_root, in precedence order.

        Returns list with 0 or 1 element (resolved absolute path string).
        Caller picks the first element.
        """
        root = Path(project_root).resolve()  # noqa: ASYNC240
        for candidate in _CANDIDATE_NAMES:
            candidate_path = root / candidate
            if candidate_path.exists() and candidate_path.is_file():  # noqa: ASYNC240
                return [str(candidate_path)]
        return []

    async def read(self, path: str, *, project_root: str) -> str:
        """Read file content with path-traversal and size-cap guards.

        Args:
            path: Absolute or relative path to the file to read.
            project_root: Trusted root directory; ``path`` must resolve inside it.

        Returns:
            UTF-8 decoded file content.

        Raises:
            ValueError: Path resolves outside project_root (traversal / symlink escape).
            ValueError: File size exceeds 1MB cap.
            ValueError: File does not exist at the resolved path.
        """
        resolved_path = Path(path).resolve()  # noqa: ASYNC240
        resolved_root = Path(project_root).resolve()  # noqa: ASYNC240

        # Reject paths that escape project root (traversal / symlink escape)
        try:
            resolved_path.relative_to(resolved_root)
        except ValueError as err:
            raise ValueError(
                f"Path traversal rejected: '{path}' resolves outside project root '{project_root}'"
            ) from err

        # Not-found check before stat (avoids confusing FileNotFoundError from stat)
        if not resolved_path.exists():  # noqa: ASYNC240
            raise ValueError(f"Rules file not found: '{path}'")

        # Size cap
        file_size = resolved_path.stat().st_size  # noqa: ASYNC240
        if file_size > _SIZE_CAP_BYTES:
            raise ValueError(
                f"Rules file too large: {file_size} bytes exceeds 1MB cap "
                f"({_SIZE_CAP_BYTES} bytes). File: '{path}'"
            )

        return resolved_path.read_text(encoding="utf-8")  # noqa: ASYNC240
