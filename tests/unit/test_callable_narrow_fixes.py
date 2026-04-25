"""Stage 3 (Sprint 1B): Callable-narrow batch — 9 mixed fixes.

Closes the 9 `call-non-callable` diagnostics ty reports against
`src/swarmline/` after Stage 2 (baseline=36). Three distinct narrowing
failures, but uniform fix: ty-native `# ty: ignore[call-non-callable]`
+ reason-comment.

Why uniform ty-native ignore (option 1) over structural narrow (option 2):
- All 9 are runtime-correct duck-typed call sites. Suppression is the
  minimum-viable diff; behavioral parity is preserved.
- Adding `assert ... is not None` would change semantics under -O /
  PYTHONOPTIMIZE and add noise to call graphs.
- Protocol redesign with optional methods is out-of-scope for Sprint 1B.

TDD red→green: this file is added BEFORE applying fixes; the parametrized
cases all FAIL until each location has the listed structural-or-ignore fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# (relative_file_path, line_number, must_contain_token, reason_substring, human_label)
# Sourced directly from `ty check src/swarmline/` after Stage 2 (baseline=36).
EXPECTED_FIXES: list[tuple[str, int, str, str, str]] = [
    (
        "src/swarmline/compaction.py",
        167,
        "# ty: ignore[call-non-callable]",
        "Optional Callable",
        "Optional Callable hook (replaces dead # type: ignore[misc])",
    ),
    (
        "src/swarmline/multi_agent/graph_orchestrator.py",
        363,
        "# ty: ignore[call-non-callable]",
        "hasattr",
        "hasattr-narrow on object-typed _task_board.cancel_task (failure path)",
    ),
    (
        "src/swarmline/multi_agent/graph_orchestrator.py",
        393,
        "# ty: ignore[call-non-callable]",
        "hasattr",
        "hasattr-narrow on object-typed _task_board.cancel_task (cancel path)",
    ),
    (
        "src/swarmline/orchestration/generic_workflow_engine.py",
        53,
        "# ty: ignore[call-non-callable]",
        "hasattr",
        "hasattr-narrow on Protocol-or-Callable executor",
    ),
    (
        "src/swarmline/orchestration/generic_workflow_engine.py",
        61,
        "# ty: ignore[call-non-callable]",
        "hasattr",
        "hasattr-narrow on Protocol-or-Callable verifier",
    ),
    (
        "src/swarmline/orchestration/manager.py",
        39,
        "# ty: ignore[call-non-callable]",
        "hasattr",
        "hasattr-narrow on optional Protocol method set_namespace",
    ),
    (
        "src/swarmline/tools/web_providers/crawl4ai.py",
        52,
        "# ty: ignore[call-non-callable]",
        "AsyncWebCrawler",
        "Optional class CrawlerRunConfig — gated by AsyncWebCrawler None check above",
    ),
    (
        "src/swarmline/tools/web_providers/crawl4ai.py",
        53,
        "# ty: ignore[call-non-callable]",
        "AsyncWebCrawler",
        "Optional class DefaultMarkdownGenerator — gated by AsyncWebCrawler None check above",
    ),
    (
        "src/swarmline/tools/web_providers/tavily.py",
        51,
        "# ty: ignore[call-non-callable]",
        "nested",
        "Optional class TavilyClient inside nested _sync_search — outer narrow lost",
    ),
]

assert len(EXPECTED_FIXES) == 9, (
    f"expected 9 call-non-callable diagnostics post-Stage 2, got {len(EXPECTED_FIXES)}"
)


# Files where Stage 3 fixes land. Used by cleanup invariants.
AFFECTED_FILES = sorted({loc[0] for loc in EXPECTED_FIXES})


def _read_line(rel_path: str, line_number: int) -> str:
    """Return the 1-indexed line from a repo-relative file path."""
    full = REPO_ROOT / rel_path
    return full.read_text(encoding="utf-8").splitlines()[line_number - 1]


@pytest.mark.parametrize(
    "rel_path, line_number, must_contain, reason_substr, label",
    EXPECTED_FIXES,
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_each_location_has_call_non_callable_ignore(
    rel_path: str,
    line_number: int,
    must_contain: str,
    reason_substr: str,
    label: str,
) -> None:
    """Each call-non-callable location carries ty-native ignore + reason.

    The literal `# ty: ignore[call-non-callable]` must appear, and a
    reason-substring (per location) must follow somewhere on the same line.
    The reason is the documentation of WHY structural narrowing failed
    (`hasattr` not propagated, nested-fn scope, Optional-class share).
    """
    line = _read_line(rel_path, line_number)
    assert must_contain in line, (
        f"{rel_path}:{line_number} ({label}) — expected `{must_contain}`, got:\n"
        f"  {line!r}"
    )
    assert reason_substr.lower() in line.lower(), (
        f"{rel_path}:{line_number} ({label}) — expected reason "
        f"substring `{reason_substr}` after the ignore, got:\n"
        f"  {line!r}"
    )


def test_compaction_no_dead_mypy_misc_near_llm_call() -> None:
    """Stage 3 cleanup invariant: compaction.py drops `# type: ignore[misc]`.

    The dead `# type: ignore[misc]` at the `_llm_call` invocation is replaced
    by the ty-native `# ty: ignore[call-non-callable]`. Under ADR-003 (strict
    ty, `respect-type-ignore-comments = false`) the mypy comment was inert
    anyway — keeping it is dead code.
    """
    full = REPO_ROOT / "src/swarmline/compaction.py"
    source = full.read_text(encoding="utf-8")
    assert "# type: ignore[misc]" not in source, (
        "compaction.py still contains dead `# type: ignore[misc]` — replace "
        "with `# ty: ignore[call-non-callable]` + reason."
    )


@pytest.mark.parametrize("rel_path", AFFECTED_FILES)
def test_no_naked_call_non_callable_ignores(rel_path: str) -> None:
    """Every `# ty: ignore[call-non-callable]` carries a reason comment.

    Project policy: ty-native ignores require a trailing reason explaining
    WHY suppression is justified. Empty `# ty: ignore[call-non-callable]`
    without rationale is treated as dead code.
    """
    full = REPO_ROOT / rel_path
    source = full.read_text(encoding="utf-8")
    token = "# ty: ignore[call-non-callable]"
    for lineno, line in enumerate(source.splitlines(), start=1):
        if token not in line:
            continue
        # Trailing reason: anything after the ignore that contains text after `#`
        after = line.split(token, 1)[1].strip()
        # Either the ignore is followed by `  # <reason>` (canonical) or by
        # extra inline text containing `#` later. Accept any non-empty
        # comment ≥ 10 characters after the token.
        assert after.startswith("#") and len(after.lstrip("# ").strip()) >= 10, (
            f"{rel_path}:{lineno} — naked `{token}` without reason, got:\n"
            f"  {line!r}\n"
            f"Append `  # <why-narrowing-failed>` (≥10 chars)."
        )
