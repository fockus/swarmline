"""Stage 4 (Sprint 1B): Argument-type batch — 22 mixed fixes.

Closes the 22 argument-type diagnostics ty reports against `src/swarmline/`
after Stage 3 (baseline=27):
- 17× `invalid-argument-type` — SDK type-stub strictness vs runtime dict
- 3× `unknown-argument` — REAL BUG in pi_sdk/event_mapper.py (TurnMetrics field names)
- 2× `no-matching-overload` — OpenAI ChatCompletion overload strictness

Stage 4 split:
- 18 line-anchored ty-native ignores (`# ty: ignore[<rule>]` + reason)
- 1 STRUCTURAL fix in `pi_sdk/event_mapper.py` covering 4 errors at lines 83-87
  (rename `input_tokens`→`tokens_in`, `output_tokens`→`tokens_out`,
   drop `total_tokens=` (field doesn't exist), guard `model` with `or ""`).

The structural fix is mandatory because it's a real latent bug — `TurnMetrics(...)`
with `input_tokens=...` would raise `TypeError("got unexpected keyword argument")`
at runtime. ty caught it; we close it properly, not via suppression.

For the 18 SDK-strictness cases, ty-native ignore is correct: Anthropic, OpenAI,
Google, langgraph, structlog stubs are stricter than runtime acceptance. Building
TypedDict converters per adapter is out-of-scope refactor.

TDD red→green: this file is added BEFORE applying fixes; cases all FAIL until
the listed fix lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# (relative_file_path, line_number, must_contain_token, reason_substring, human_label)
# Sourced from `ty check src/swarmline/` after Stage 3 (baseline=27).
EXPECTED_FIXES: list[tuple[str, int, str, str, str]] = [
    (
        "src/swarmline/mcp/_tools_plans.py",
        106,
        "# ty: ignore[invalid-argument-type]",
        "Literal",
        "Plan.approve(by) Literal narrow not propagated by ty",
    ),
    (
        "src/swarmline/observability/logger.py",
        39,
        "# ty: ignore[invalid-argument-type]",
        "structlog",
        "structlog Processor union strict; concrete renderer accepted at runtime",
    ),
    (
        "src/swarmline/observability/logger.py",
        41,
        "# ty: ignore[invalid-argument-type]",
        "structlog",
        "structlog Processor union strict; concrete renderer accepted at runtime",
    ),
    (
        "src/swarmline/orchestration/workflow_langgraph.py",
        27,
        "# ty: ignore[invalid-argument-type]",
        "langgraph",
        "langgraph TypedDictLikeV1 constraint; dict accepted at runtime",
    ),
    (
        "src/swarmline/orchestration/workflow_langgraph.py",
        39,
        "# ty: ignore[invalid-argument-type]",
        "langgraph",
        "langgraph _Node union strict; callable accepted at runtime",
    ),
    (
        "src/swarmline/runtime/codex_adapter.py",
        103,
        "# ty: ignore[invalid-argument-type]",
        "OpenAI",
        "OpenAI ChatCompletionMessageParam strict; runtime dict matches",
    ),
    (
        "src/swarmline/runtime/factory.py",
        144,
        "# ty: ignore[invalid-argument-type]",
        "hasattr",
        "model narrowed by hasattr check above; ty doesn't propagate",
    ),
    (
        "src/swarmline/runtime/options_builder.py",
        139,
        "# ty: ignore[invalid-argument-type]",
        "Literal",
        "claude_code_sdk hooks Literal keys vs str dict; runtime-equivalent",
    ),
    (
        "src/swarmline/runtime/pi_sdk/runtime.py",
        253,
        "# ty: ignore[invalid-argument-type]",
        "isinstance",
        "args narrowed by isinstance dict check above",
    ),
    (
        "src/swarmline/runtime/thin/llm_providers.py",
        216,
        "# ty: ignore[invalid-argument-type]",
        "Anthropic",
        "Anthropic MessageParam strict; runtime dict matches (stream)",
    ),
    (
        "src/swarmline/runtime/thin/llm_providers.py",
        243,
        "# ty: ignore[invalid-argument-type]",
        "Anthropic",
        "Anthropic MessageParam strict; runtime dict matches (create)",
    ),
    (
        "src/swarmline/runtime/thin/llm_providers.py",
        244,
        "# ty: ignore[invalid-argument-type]",
        "Anthropic",
        "Anthropic ToolParam strict; runtime dict matches (create tools)",
    ),
    (
        "src/swarmline/runtime/thin/llm_providers.py",
        312,
        "# ty: ignore[no-matching-overload]",
        "OpenAI",
        "OpenAI ChatCompletion overload — runtime dict structure matches (call)",
    ),
    (
        "src/swarmline/runtime/thin/llm_providers.py",
        333,
        "# ty: ignore[no-matching-overload]",
        "OpenAI",
        "OpenAI ChatCompletion overload — runtime dict structure matches (stream)",
    ),
    (
        "src/swarmline/runtime/thin/llm_providers.py",
        369,
        "# ty: ignore[invalid-argument-type]",
        "OpenAI",
        "OpenAI MessageParam strict; runtime dict matches (call_with_tools)",
    ),
    (
        "src/swarmline/runtime/thin/llm_providers.py",
        371,
        "# ty: ignore[invalid-argument-type]",
        "OpenAI",
        "OpenAI ChatCompletionToolParam strict; runtime dict matches",
    ),
    (
        "src/swarmline/runtime/thin/llm_providers.py",
        508,
        "# ty: ignore[invalid-argument-type]",
        "Google",
        "Google Tool union strict; runtime list matches",
    ),
    (
        "src/swarmline/runtime/thin/react_strategy.py",
        338,
        "# ty: ignore[invalid-argument-type]",
        "hasattr",
        "tc.assistant_message hasattr-narrow not propagated by ty",
    ),
]

assert len(EXPECTED_FIXES) == 18, (
    f"expected 18 line-anchored fixes (22 errors − 4 covered by event_mapper "
    f"structural fix), got {len(EXPECTED_FIXES)}"
)

# Files where Stage 4 fixes land (used by cleanup invariants).
AFFECTED_FILES_LINE_FIX = sorted({loc[0] for loc in EXPECTED_FIXES})


def _read_line(rel_path: str, line_number: int) -> str:
    """Return the 1-indexed line from a repo-relative file path."""
    full = REPO_ROOT / rel_path
    return full.read_text(encoding="utf-8").splitlines()[line_number - 1]


@pytest.mark.parametrize(
    "rel_path, line_number, must_contain, reason_substr, label",
    EXPECTED_FIXES,
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_each_location_has_argument_type_ignore(
    rel_path: str,
    line_number: int,
    must_contain: str,
    reason_substr: str,
    label: str,
) -> None:
    """Each argument-type location carries ty-native ignore + reason.

    The literal `# ty: ignore[<rule>]` must appear, and a reason-substring
    (per location) must follow on the same line. The reason documents WHY
    the SDK type-stub is stricter than runtime acceptance.
    """
    line = _read_line(rel_path, line_number)
    assert must_contain in line, (
        f"{rel_path}:{line_number} ({label}) — expected `{must_contain}`, got:\n"
        f"  {line!r}"
    )
    assert reason_substr.lower() in line.lower(), (
        f"{rel_path}:{line_number} ({label}) — expected reason "
        f"substring `{reason_substr}` on the same line, got:\n"
        f"  {line!r}"
    )


def test_event_mapper_uses_canonical_turn_metrics_field_names() -> None:
    """Stage 4 STRUCTURAL fix: event_mapper.py uses canonical TurnMetrics fields.

    Real bug closure: `TurnMetrics(input_tokens=...)` would raise
    `TypeError("got unexpected keyword argument")` at runtime. The fix renames
    to `tokens_in`/`tokens_out` (canonical field names from `domain_types.py:205`)
    and drops `total_tokens=` (field doesn't exist on TurnMetrics).

    This regression-guards against future cargo-cult re-additions.
    """
    full = REPO_ROOT / "src/swarmline/runtime/pi_sdk/event_mapper.py"
    source = full.read_text(encoding="utf-8")

    # Negative invariants — bug names must not return.
    for forbidden in ("input_tokens=", "output_tokens=", "total_tokens="):
        assert forbidden not in source, (
            f"event_mapper.py still uses non-existent TurnMetrics kwarg "
            f"`{forbidden}` — TurnMetrics has fields `tokens_in`, `tokens_out`, "
            f"no `total_tokens`. See domain_types.py:205."
        )

    # Positive invariants — canonical names must be present.
    for required in ("tokens_in=", "tokens_out="):
        assert required in source, (
            f"event_mapper.py missing canonical TurnMetrics kwarg `{required}` — "
            f"the structural fix must use the real dataclass fields."
        )


def test_event_mapper_guards_model_against_none() -> None:
    """Stage 4 STRUCTURAL fix: model kwarg must guard against None.

    `_optional_str` returns `str | None`, but TurnMetrics.model is `str = ""`.
    Fix: `model=_optional_str(...) or ""` to coerce None → empty string.
    """
    full = REPO_ROOT / "src/swarmline/runtime/pi_sdk/event_mapper.py"
    source = full.read_text(encoding="utf-8")
    assert 'model=_optional_str(metrics.get("model")) or ""' in source, (
        'event_mapper.py must guard `model=` against None via `or ""` — '
        'TurnMetrics.model is `str = ""`, not `str | None`.'
    )


@pytest.mark.parametrize("rel_path", AFFECTED_FILES_LINE_FIX)
def test_no_naked_argument_type_ignores(rel_path: str) -> None:
    """Every `# ty: ignore[invalid-argument-type|no-matching-overload]` carries reason.

    Project policy: ty-native ignores require a trailing reason (≥10 chars)
    explaining WHY suppression is justified. Empty ignores are dead code.
    """
    full = REPO_ROOT / rel_path
    source = full.read_text(encoding="utf-8")
    for token in (
        "# ty: ignore[invalid-argument-type]",
        "# ty: ignore[no-matching-overload]",
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
