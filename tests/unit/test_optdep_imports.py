"""Stage 1 (Sprint 1B): OptDep batch — 22 unresolved-import → 0.

Establishes source-level invariants for every optional-dependency import line
flagged by `ty check src/swarmline/`. The TDD red→green pivot point: this
file is added BEFORE applying ignore comments to the 13 source files; the
parametrized cases all FAIL until each line carries `# ty: ignore[unresolved-import]`
plus an "optional dep" reason comment.

Why ty-native `# ty: ignore` rather than classic `# type: ignore`:
    `pyproject.toml [tool.ty.analysis] respect-type-ignore-comments = false`
    makes mypy-style `# type: ignore` comments INERT under strict mode. Verified:
    `# ty: ignore[unresolved-import]` suppresses the diagnostic; the `# type: ...`
    variant does not.

Why "optional dep" in the comment:
    Project policy on `# type: ignore` requires a reason comment explaining the
    suppression. We mirror that for `# ty: ignore`. Surfacing intent makes future
    Sprint 1B+ stages easier to triage when re-categorising.

Invariants tested:
    1. Each (file, line) location actually contains the expected import statement
       for the listed optional module — guards against off-by-one drift if upstream
       refactors shift line numbers.
    2. Each such line carries `# ty: ignore[unresolved-import]`.
    3. Each such line carries the literal substring `optional dep`.
    4. The 13 affected files contain NO `# type: ignore[import-untyped]` or
       `# type: ignore[import-not-found]` (mypy-only codes, dead under ty strict).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# (relative_file_path, line_number, top-level module name)
# Sourced directly from `ty check src/swarmline/` 2026-04-25 baseline=62.
# Update this list ONLY in lock-step with deliberate ty-baseline movement.
OPT_IMPORT_LOCATIONS: list[tuple[str, int, str]] = [
    ("src/swarmline/runtime/agent_sdk_adapter.py", 49, "claude_code_sdk"),
    ("src/swarmline/runtime/agent_sdk_adapter.py", 89, "claude_code_sdk"),
    ("src/swarmline/runtime/openai_agents/runtime.py", 70, "agents"),
    ("src/swarmline/runtime/openai_agents/runtime.py", 224, "agents.mcp"),
    ("src/swarmline/runtime/openai_agents/tool_bridge.py", 34, "agents"),
    ("src/swarmline/multi_agent/graph_communication_nats.py", 48, "nats"),
    ("src/swarmline/multi_agent/graph_communication_redis.py", 48, "redis.asyncio"),
    ("src/swarmline/observability/event_bus_nats.py", 53, "nats"),
    ("src/swarmline/observability/event_bus_redis.py", 54, "redis.asyncio"),
    ("src/swarmline/observability/otel_exporter.py", 44, "opentelemetry"),
    ("src/swarmline/observability/otel_exporter.py", 45, "opentelemetry.trace"),
    ("src/swarmline/mcp/_server.py", 85, "fastmcp"),
    ("src/swarmline/tools/extractors.py", 26, "pymupdf4llm"),
    ("src/swarmline/tools/extractors.py", 35, "fitz"),
    ("src/swarmline/tools/extractors.py", 68, "nbformat"),
    ("src/swarmline/tools/sandbox_docker.py", 99, "docker"),
    ("src/swarmline/tools/sandbox_e2b.py", 56, "e2b_code_interpreter"),
    ("src/swarmline/tools/sandbox_openshell.py", 80, "openshell"),
    ("src/swarmline/tools/web_httpx.py", 26, "trafilatura"),
    ("src/swarmline/tools/web_providers/crawl4ai.py", 20, "crawl4ai"),
    (
        "src/swarmline/tools/web_providers/crawl4ai.py",
        21,
        "crawl4ai.markdown_generation_strategy",
    ),
    ("src/swarmline/tools/web_providers/tavily.py", 16, "tavily"),
]

assert len(OPT_IMPORT_LOCATIONS) == 22, (
    f"expected 22 unresolved-import diagnostics from baseline=62, "
    f"got {len(OPT_IMPORT_LOCATIONS)}"
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DEAD_MYPY_CODES = ("import-untyped", "import-not-found")


def _read_line(rel_path: str, line_number: int) -> str:
    """Return the 1-indexed line from a repo-relative file path."""
    full = REPO_ROOT / rel_path
    return full.read_text(encoding="utf-8").splitlines()[line_number - 1]


@pytest.mark.parametrize(
    "rel_path, line_number, module",
    OPT_IMPORT_LOCATIONS,
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_line_contains_expected_optional_module_import(
    rel_path: str, line_number: int, module: str
) -> None:
    """The flagged line actually imports the named module.

    Guards against silent line-number drift: if a refactor renumbers, the
    OPT_IMPORT_LOCATIONS table must be updated in the same commit, otherwise
    this test surfaces the discrepancy immediately.
    """
    line = _read_line(rel_path, line_number)
    # Accept either `from <module> import …` or `import <module>` (with submodule paths).
    pattern = re.compile(
        rf"\b(from\s+{re.escape(module)}\b|import\s+{re.escape(module)}\b)"
    )
    assert pattern.search(line), (
        f"{rel_path}:{line_number} — expected import of '{module}', got:\n  {line!r}"
    )


@pytest.mark.parametrize(
    "rel_path, line_number, module",
    OPT_IMPORT_LOCATIONS,
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_optional_import_line_has_ty_ignore_comment(
    rel_path: str, line_number: int, module: str
) -> None:
    """Every optional-dependency import line carries `# ty: ignore[unresolved-import]`.

    `respect-type-ignore-comments = false` in pyproject.toml makes classic
    `# type: ignore[...]` inert. Only `# ty: ignore[<rule>]` (ty-native) actually
    suppresses the diagnostic.
    """
    line = _read_line(rel_path, line_number)
    assert "# ty: ignore[unresolved-import]" in line, (
        f"{rel_path}:{line_number} — missing `# ty: ignore[unresolved-import]` "
        f"on optional `{module}` import:\n  {line!r}"
    )


@pytest.mark.parametrize(
    "rel_path, line_number, module",
    OPT_IMPORT_LOCATIONS,
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_optional_import_line_has_reason_comment(
    rel_path: str, line_number: int, module: str
) -> None:
    """Every `# ty: ignore` carries the project-mandated reason `optional dep`."""
    line = _read_line(rel_path, line_number)
    assert "optional dep" in line, (
        f"{rel_path}:{line_number} — missing 'optional dep' reason comment "
        f"on optional `{module}` import:\n  {line!r}"
    )


@pytest.mark.parametrize("rel_path", sorted({loc[0] for loc in OPT_IMPORT_LOCATIONS}))
def test_no_dead_mypy_import_codes_in_affected_files(rel_path: str) -> None:
    """Affected files no longer carry mypy-only `import-untyped` / `import-not-found`.

    Cleanup invariant: under ADR-003 (ty strict-only, no mypy), these codes
    have no effect — keeping them is dead clutter. The migration replaces them
    with `# ty: ignore[unresolved-import]`.
    """
    full = REPO_ROOT / rel_path
    source = full.read_text(encoding="utf-8")
    for dead_code in DEAD_MYPY_CODES:
        token = f"# type: ignore[{dead_code}"
        assert token not in source, (
            f"{rel_path} still contains dead mypy code `{token}...]`. "
            f"Replace with `# ty: ignore[unresolved-import]  # optional dep`."
        )
