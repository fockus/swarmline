"""Stage 2 (Sprint 1B): Unresolved-attribute batch — 4 mixed fixes.

Closes the 4 `unresolved-attribute` diagnostics ty reports against
`src/swarmline/` after Stage 1 (baseline=40). Three distinct patterns:

1. Manual marker attribute on a plain function (no decorator → no Protocol):
   `runtime/thin/executor.py:280` — ty-native ignore.
2. Duck-typed third-party SDK return (`response.text` after await):
   `runtime/thin/llm_providers.py:418` — ty-native ignore.
3. Optional union member access gated by runtime check:
   `runtime/thin/llm_providers.py:478` — ty-native ignore.
4. SQLAlchemy 2.x `Result.rowcount` — same as Sprint 1A
   `agent_registry_postgres.py` Stage 3 fix:
   `session/backends_postgres.py:61` — `cast(CursorResult, result).rowcount`.

TDD red→green: this file is added BEFORE applying fixes; the parametrized
cases all FAIL until each location has the listed structural-or-ignore fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# (relative_file_path, line_number, must_contain_token, human_label)
# Sourced directly from `ty check src/swarmline/` after Stage 1 (baseline=40).
EXPECTED_FIXES: list[tuple[str, int, str, str]] = [
    # Lines below reflect the post-`ruff format` snapshot; line drift detection
    # is the whole point of this test, so a future refactor shifting any of
    # these surfaces here immediately rather than silently regressing the fix.
    (
        "src/swarmline/runtime/thin/executor.py",
        288,
        "# ty: ignore[unresolved-attribute]",
        "marker attr on plain function",
    ),
    (
        "src/swarmline/runtime/thin/llm_providers.py",
        452,
        "# ty: ignore[unresolved-attribute]",
        "duck-typed awaited response.text",
    ),
    (
        "src/swarmline/runtime/thin/llm_providers.py",
        515,
        "# ty: ignore[unresolved-attribute, not-iterable]",
        "Gemini Content.parts gated by candidates check (Stage 5 extends with not-iterable)",
    ),
    (
        "src/swarmline/session/backends_postgres.py",
        67,
        "cast(CursorResult",
        "SQLAlchemy 2.x Result.rowcount cast (Sprint 1A pattern)",
    ),
]

assert len(EXPECTED_FIXES) == 4, (
    f"expected 4 unresolved-attribute diagnostics post-Stage 1, "
    f"got {len(EXPECTED_FIXES)}"
)


# Files where mypy-style attr/union ignores must be cleaned up.
AFFECTED_FILES = sorted({loc[0] for loc in EXPECTED_FIXES})

DEAD_MYPY_ATTR_CODES = (
    "attr-defined",
    "union-attr",
)


def _read_line(rel_path: str, line_number: int) -> str:
    """Return the 1-indexed line from a repo-relative file path."""
    full = REPO_ROOT / rel_path
    return full.read_text(encoding="utf-8").splitlines()[line_number - 1]


@pytest.mark.parametrize(
    "rel_path, line_number, must_contain, label",
    EXPECTED_FIXES,
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_each_location_has_expected_fix(
    rel_path: str, line_number: int, must_contain: str, label: str
) -> None:
    """Each unresolved-attribute location carries its prescribed fix.

    For ty-native ignores: the literal `# ty: ignore[unresolved-attribute]`
    must appear on that line. For the structural CursorResult cast: the line
    must contain `cast(CursorResult` to verify Sprint 1A's pattern was applied.
    """
    line = _read_line(rel_path, line_number)
    assert must_contain in line, (
        f"{rel_path}:{line_number} ({label}) — expected `{must_contain}`, got:\n"
        f"  {line!r}"
    )


@pytest.mark.parametrize("rel_path", AFFECTED_FILES)
def test_no_dead_mypy_attr_codes_in_affected_files(rel_path: str) -> None:
    """Affected files no longer carry mypy-only attr/union ignore codes.

    Under ADR-003 (ty strict-only), `# type: ignore[attr-defined]` and
    `# type: ignore[union-attr]` are inert. The migration replaces them
    with `# ty: ignore[unresolved-attribute]` (cases 1-3) or with a
    typed cast (case 4).

    Scoped narrowly: only checks the 3 files Stage 2 touches. A stray
    `# type: ignore[attr-defined]` elsewhere stays, to be addressed in a
    later stage if/when ty surfaces it.
    """
    full = REPO_ROOT / rel_path
    source = full.read_text(encoding="utf-8")
    for dead_code in DEAD_MYPY_ATTR_CODES:
        token = f"# type: ignore[{dead_code}"
        assert token not in source, (
            f"{rel_path} still contains dead mypy code `{token}...]`. "
            f"Replace with `# ty: ignore[unresolved-attribute]  # <reason>` "
            f"or with a typed cast."
        )


def test_backends_postgres_imports_cursor_result_and_cast() -> None:
    """Case 4 structural fix requires `cast` + `CursorResult` at module top.

    Mirrors Sprint 1A's `agent_registry_postgres.py` Stage 3 fix exactly.
    Source-level guard: a refactor that drops these imports must surface
    immediately rather than silently regressing the type-safety of `delete()`.
    """
    full = REPO_ROOT / "src/swarmline/session/backends_postgres.py"
    source = full.read_text(encoding="utf-8")
    assert "from typing import" in source and "cast" in source, (
        "backends_postgres.py must import `cast` from typing for Stage 2 fix."
    )
    assert "from sqlalchemy import" in source and "CursorResult" in source, (
        "backends_postgres.py must import `CursorResult` from sqlalchemy "
        "for Stage 2 fix (mirrors Sprint 1A agent_registry_postgres pattern)."
    )
