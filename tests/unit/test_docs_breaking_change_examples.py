"""Stage 3 of plans/2026-04-27_fix_post-review-polish.md (review C4).

Closes review finding C4 (HIGH UX): published docs must reflect the v1.5.0
breaking change in ``serve.create_app`` — when ``allow_unauthenticated_query=
True``, an explicit ``host=`` argument is now mandatory. Any code example
showing ``allow_unauthenticated_query=True`` without ``host=`` will fail at
factory time when the user copy-pastes it.

This invariant guards 4 user-facing docs files. Future regressions (someone
re-introduces a stale snippet) flip these tests immediately.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

DOCS_TO_AUDIT = (
    "docs/migration-guide.md",
    "docs/migration/v1.4-to-v1.5.md",
    "docs/getting-started.md",
    "docs/configuration.md",
)


# Markers in the preceding 5 lines that flag a snippet as a deliberate
# "before / deprecated" example — these snippets are intentionally broken
# (they document the v1.4.x form that v1.5.0 rejects) and should be skipped.
_DEPRECATED_CONTEXT_MARKERS = (
    "**Before",
    "Before (v1.4",
    "DEPRECATED",
    "deprecated",
    "Legacy",
    "legacy",
    "v1.4.x",
)


def _snippet_is_in_deprecated_context(content: str, span_start: int) -> bool:
    """Return True if the matched create_app(...) snippet lies under a
    deliberate "Before / Deprecated / v1.4.x" markdown header / paragraph.

    Looks at the 12 lines preceding ``span_start`` (covers a typical fenced
    code block + opening header). Catches both inline markers like
    ``**Before (v1.4.x):**`` and prose like "still works in 1.5.0".
    """
    preceding = content[:span_start].splitlines()[-12:]
    block = "\n".join(preceding)
    return any(marker in block for marker in _DEPRECATED_CONTEXT_MARKERS)


_FENCED_PYTHON_BLOCK_RE = re.compile(
    r"```(?:python|py)\s*\n(.*?)\n```",
    flags=re.DOTALL,
)


@pytest.mark.parametrize("doc_path", DOCS_TO_AUDIT)
def test_doc_does_not_show_unauthenticated_query_without_host(doc_path: str) -> None:
    """Every CURRENT-usage ``create_app(..., allow_unauthenticated_query=True,
    ...)`` snippet inside a fenced ``python`` code block must include
    ``host=`` to remain runnable on v1.5.0+.

    Two scoping rules keep this test focused on copy-pasteable code:

    1. Only fenced ```python``` blocks are scanned. Inline-backtick references
       in prose (TL;DR / bullet lists / heading text) are documentation, not
       runnable code, and are intentionally allowed to mention the v1.4.x form.
    2. Snippets under "Before / Deprecated / Legacy / v1.4.x" headers are
       deliberately broken examples (migration guides need them) and are
       skipped via 12-line preceding-context scan.

    Catches the C4 regression scenario: a CURRENT-usage docs example surviving
    past the breaking-change consolidation without a ``host=`` argument.
    """
    full_path = REPO_ROOT / doc_path
    assert full_path.exists(), f"audit target missing: {doc_path}"
    content = full_path.read_text(encoding="utf-8")

    # Catch every create_app(...) snippet mentioning allow_unauthenticated_query=True.
    snippet_re = re.compile(
        r"create_app\([^)]*allow_unauthenticated_query\s*=\s*True[^)]*\)",
        flags=re.DOTALL,
    )

    for block_match in _FENCED_PYTHON_BLOCK_RE.finditer(content):
        block_body = block_match.group(1)
        block_offset = block_match.start(1)
        for snippet_match in snippet_re.finditer(block_body):
            snippet = snippet_match.group(0)
            absolute_start = block_offset + snippet_match.start()
            if _snippet_is_in_deprecated_context(content, absolute_start):
                continue
            assert "host=" in snippet, (
                f"{doc_path}: CURRENT-usage example with allow_unauthenticated_query=True "
                f"must include host= (breaking change since v1.5.0). "
                f"Offending snippet:\n{snippet!r}"
            )


def test_v14_to_v15_migration_guide_documents_breaking_change() -> None:
    """``docs/migration/v1.4-to-v1.5.md`` must explicitly cover the
    ``serve.create_app`` breaking change introduced by the v1.5.0 audit
    closure (P2 #5). Without it, upgrading users hit a runtime ValueError
    with no migration trail."""
    path = REPO_ROOT / "docs/migration/v1.4-to-v1.5.md"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "host=" in content, (
        "docs/migration/v1.4-to-v1.5.md must include a host= migration snippet "
        "for the v1.5.0 serve.create_app breaking change (audit P2 #5)."
    )
    assert "allow_unauthenticated_query" in content, (
        "docs/migration/v1.4-to-v1.5.md must mention allow_unauthenticated_query "
        "in the breaking-change context."
    )
