"""ProjectInstructionFilter — auto-discovers and injects project instruction
files into the system prompt before each LLM call.

Scans for instruction files (AGENTS.md, RULES.md, CLAUDE.md, GEMINI.md)
from the current working directory up through parent dirs and the home
directory. Merges discovered content with home (lowest priority) first
and project root (highest priority) last, prepending to the system prompt.

Implements InputFilter protocol — plugs into ThinRuntime via
RuntimeConfig.input_filters without modifying ThinRuntime.run().
"""

from __future__ import annotations

import os
from pathlib import Path

from swarmline.runtime.types import Message

# Repo-local precedence order at each directory level
INSTRUCTION_FILES: list[str] = ["AGENTS.md", "RULES.md", "CLAUDE.md", "GEMINI.md"]


class ProjectInstructionFilter:
    """Discovers and injects project instruction files into the system prompt.

    Walk-up algorithm:
    1. Start at cwd, walk up to filesystem root
    2. At each level: merge all present files in INSTRUCTION_FILES order
    3. Also check home directory (separate from walk-up chain)
    4. Merge: home content first (lowest priority), then parents → cwd last (highest)
    5. Prepend merged content to system_prompt

    Caching: file content is cached by (path, mtime). Re-reads on mtime change.
    """

    def __init__(
        self,
        cwd: str | Path | None = None,
        home: str | Path | None = None,
    ) -> None:
        self._cwd = Path(cwd).resolve() if cwd else Path.cwd()
        self._home = Path(home).resolve() if home else Path.home()
        self._cache: dict[Path, tuple[float, str]] = {}

    def _read_cached(self, path: Path) -> str | None:
        """Read file content with mtime-based caching. Returns None for missing/empty."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None

        cached = self._cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1] or None

        try:
            content = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None

        self._cache[path] = (mtime, content)
        return content or None

    def _find_at_level(self, directory: Path) -> list[str]:
        """Find all instruction file contents at a directory level."""
        contents: list[str] = []
        for filename in INSTRUCTION_FILES:
            candidate = directory / filename
            if candidate.is_symlink():
                continue
            if candidate.is_file():
                content = self._read_cached(candidate)
                if content:
                    contents.append(content)
        return contents

    def _collect_walk_up(self) -> list[str]:
        """Walk from cwd up to root, collecting instruction content per level.

        Returns contents ordered from outermost parent to cwd (ready for merge).
        """
        segments: list[tuple[int, list[str]]] = []
        current = self._cwd
        depth = 0

        while True:
            contents = self._find_at_level(current)
            if contents:
                segments.append((depth, contents))
            parent = current.parent
            if parent == current:
                break
            current = parent
            depth += 1

        # Reverse: outermost parent first, cwd last
        segments.sort(key=lambda x: x[0], reverse=True)
        merged: list[str] = []
        for _, level_contents in segments:
            merged.extend(level_contents)
        return merged

    def _collect_home(self) -> list[str]:
        """Collect instruction content from home directory (if not in walk-up path)."""
        # Skip if home is an ancestor of cwd (already covered by walk-up)
        try:
            self._cwd.relative_to(self._home)
            return []
        except ValueError:
            pass

        return self._find_at_level(self._home)

    def _discover(self) -> str:
        """Discover and merge all instruction content.

        Merge order: home (lowest) → outermost parent → ... → cwd (highest).
        """
        parts: list[str] = []

        home_contents = self._collect_home()
        parts.extend(home_contents)

        walk_up = self._collect_walk_up()
        parts.extend(walk_up)

        return "\n\n".join(parts)

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        """Prepend discovered instruction content to system_prompt."""
        instructions = self._discover()
        if not instructions:
            return messages, system_prompt

        merged = f"{instructions}\n\n{system_prompt}" if system_prompt else instructions
        return messages, merged
