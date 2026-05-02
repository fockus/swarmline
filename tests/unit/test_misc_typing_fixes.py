"""Stage 5 (Sprint 1B): Misc typing remainders — 5 → 0.

Closes the final 5 ty diagnostics against `src/swarmline/` after Stage 4
(baseline=5) to drive the project to baseline=0:

- 2× `invalid-return-type` — overload/SDK return-type strictness
  - `multi_agent/workspace.py:124` — tempfile.mkdtemp overload returns
    `str | bytes`, but with `prefix=str` the runtime always returns `str`.
  - `runtime/adapter.py:212` — claude_agent_sdk returns `McpStatusResponse`
    (dict-compatible TypedDict), annotation expects `dict[str, Any]`.
- 2× `invalid-assignment` — narrowing/optional-stub strictness
  - `orchestration/thin_subagent.py:153` — `runtime._cwd = ...` after
    `hasattr(runtime, "_cwd")` narrow that ty doesn't propagate.
  - `tools/web_providers/duckduckgo.py:19` — Optional Dependency Stub
    pattern: `DDGS = None` after `ImportError` declares-then-rebinds.
- 1× `not-iterable` — Gemini Content.parts (Unknown | list[Part] | None)
  - `runtime/thin/llm_providers.py:515` — already carries
    `# ty: ignore[unresolved-attribute]` from Stage 2; we extend the same
    ignore to also cover `not-iterable` (multi-rule on the same line).

All 5 are SDK / framework type-stub strictness vs runtime acceptance —
no real bugs (Stage 4 closed the only latent bug in event_mapper.py).
Canonical Sprint 1B pattern: ty-native ignore + reason-comment ≥10 chars.

TDD red→green: this file is added BEFORE applying fixes; cases all FAIL
until the listed fix lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# (relative_file_path, line_number, must_contain_token, reason_substring, human_label)
EXPECTED_FIXES: list[tuple[str, int, str, str, str]] = [
    (
        "src/swarmline/multi_agent/workspace.py",
        124,
        "# ty: ignore[invalid-return-type]",
        "tempfile.mkdtemp",
        "tempfile.mkdtemp overload returns str|bytes; str when prefix is str",
    ),
    (
        "src/swarmline/orchestration/thin_subagent.py",
        149,
        "# ty: ignore[invalid-assignment]",
        "hasattr",
        "_cwd narrowed via hasattr check above; ty doesn't propagate",
    ),
    (
        "src/swarmline/runtime/adapter.py",
        217,
        "# ty: ignore[invalid-return-type]",
        "McpStatusResponse",
        "claude_agent_sdk McpStatusResponse is dict-compatible at runtime",
    ),
    (
        "src/swarmline/tools/web_providers/duckduckgo.py",
        19,
        "# ty: ignore[invalid-assignment]",
        "optional dependency",
        "Optional Dependency Stub: DDGS=None when ddgs not installed",
    ),
]

# `not-iterable` is added to the existing multi-rule ignore on line 515
# (already carries `unresolved-attribute` from Stage 2). We assert both
# rules appear via a separate test below so the line-anchored test stays
# single-rule.

assert len(EXPECTED_FIXES) == 4, (
    f"expected 4 single-rule line-anchored fixes (5th is multi-rule extension), "
    f"got {len(EXPECTED_FIXES)}"
)

AFFECTED_FILES_LINE_FIX = sorted({loc[0] for loc in EXPECTED_FIXES})
GEMINI_PARTS_FILE = "src/swarmline/runtime/thin/llm_providers.py"
GEMINI_PARTS_LINE = 521


def _read_line(rel_path: str, line_number: int) -> str:
    """Return the 1-indexed line from a repo-relative file path."""
    full = REPO_ROOT / rel_path
    return full.read_text(encoding="utf-8").splitlines()[line_number - 1]


@pytest.mark.parametrize(
    "rel_path, line_number, must_contain, reason_substr, label",
    EXPECTED_FIXES,
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_each_misc_location_has_ty_native_ignore(
    rel_path: str,
    line_number: int,
    must_contain: str,
    reason_substr: str,
    label: str,
) -> None:
    """Each misc location carries ty-native ignore + reason on the same line."""
    line = _read_line(rel_path, line_number)
    assert must_contain in line, (
        f"{rel_path}:{line_number} ({label}) — expected `{must_contain}`, got:\n"
        f"  {line!r}"
    )
    assert reason_substr.lower() in line.lower(), (
        f"{rel_path}:{line_number} ({label}) — expected reason substring "
        f"`{reason_substr}` on the same line, got:\n"
        f"  {line!r}"
    )


def test_gemini_parts_loop_carries_both_unresolved_attribute_and_not_iterable() -> None:
    """Stage 5 multi-rule extension: `for part in response.candidates[0].content.parts`.

    The Gemini Content.parts access already triggers `unresolved-attribute`
    (covered in Stage 2). With `respect-type-ignore-comments = false`,
    iterating the (Unknown | list[Part] | None) union also triggers
    `not-iterable`. Both rules must appear on the same line — either via
    a single `# ty: ignore[unresolved-attribute, not-iterable]` block or
    via two adjacent `# ty: ignore[<rule>]` comments. We accept either form.
    """
    line = _read_line(GEMINI_PARTS_FILE, GEMINI_PARTS_LINE)

    # Both rules must appear (in any of the supported syntactic forms).
    assert "unresolved-attribute" in line, (
        f"{GEMINI_PARTS_FILE}:{GEMINI_PARTS_LINE} — missing "
        f"`unresolved-attribute` ignore on Gemini Content.parts loop:\n"
        f"  {line!r}"
    )
    assert "not-iterable" in line, (
        f"{GEMINI_PARTS_FILE}:{GEMINI_PARTS_LINE} — missing `not-iterable` "
        f"ignore on Gemini Content.parts loop (Stage 5 extension):\n"
        f"  {line!r}"
    )
    # Reason must remain present (Stage 2 reason intact).
    assert "candidates" in line.lower() or "gemini" in line.lower(), (
        f"{GEMINI_PARTS_FILE}:{GEMINI_PARTS_LINE} — expected reason mentioning "
        f"`candidates` truthy check or `Gemini` on the same line, got:\n"
        f"  {line!r}"
    )


@pytest.mark.parametrize("rel_path", AFFECTED_FILES_LINE_FIX)
def test_no_naked_misc_ignores(rel_path: str) -> None:
    """Every Stage 5 ty-native ignore in touched files carries reason ≥10 chars.

    Project policy: ty-native ignores require a trailing reason explaining
    WHY suppression is justified. Empty ignores are dead code.
    """
    full = REPO_ROOT / rel_path
    source = full.read_text(encoding="utf-8")
    for token in (
        "# ty: ignore[invalid-return-type]",
        "# ty: ignore[invalid-assignment]",
        "# ty: ignore[not-iterable]",
    ):
        for lineno, line in enumerate(source.splitlines(), start=1):
            if token not in line:
                continue
            after = line.split(token, 1)[1].strip()
            assert after.startswith("#") and len(after.lstrip("# ").strip()) >= 10, (
                f"{rel_path}:{lineno} — naked `{token}` without reason, got:\n"
                f"  {line!r}\n"
                f"Append `  # <why-stub-stricter-than-runtime>` (≥10 chars)."
            )


def test_no_inert_mypy_style_ignores_remain_at_stage5_locations() -> None:
    """Stage 5 must replace ALL inert `# type: ignore[...]` at the 4 fix locations.

    Under ty strict mode (`respect-type-ignore-comments = false`), the
    legacy mypy syntax `# type: ignore[...]` is INERT — diagnostics still
    fire. Stage 5 ensures none of the 4 fix locations carry the legacy
    syntax that previously hid the errors before Sprint 1B.
    """
    inert_token = "# type: ignore["
    for rel_path, line_number, _, _, label in EXPECTED_FIXES:
        line = _read_line(rel_path, line_number)
        assert inert_token not in line, (
            f"{rel_path}:{line_number} ({label}) — line still carries inert "
            f"`{inert_token}...]` (mypy-style). Stage 5 replaces these with "
            f"ty-native `# ty: ignore[...]`. Got:\n  {line!r}"
        )
