"""Deterministic summary appendices (ref: Hermes/OpenClaw digests 2026-09-27).

Exact identifiers are extracted by regex, never trusted to the LLM; every human
turn of the compacted region survives verbatim (budgeted); a context-recovery
hint is rendered only when the host configures one.
"""

from __future__ import annotations

import pytest
from _compaction_fakes import (
    long_history,
    scripted_summarizer,
    structured_summary,
    summary_messages,
)

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan
from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
from swarmline.compaction_anchors import (
    ANCHOR_BUDGET_CHARS,
    USER_MESSAGES_BUDGET_CHARS,
    render_anchor_index,
    render_recovery_section,
    render_user_messages_section,
)
from swarmline.domain_types import Message

_SHA_SHORT = "746631b"
_SHA_FULL = "42d45d6a1b2c3d4e5f60718293a4b5c6d7e8f901"
_UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


def _filter(llm_call, **config: object) -> ConversationCompactionFilter:
    defaults: dict[str, object] = {
        "threshold_tokens": 1_000,
        "preserve_recent_pairs": 1,
        "tier_3_enabled": False,
    }
    defaults.update(config)
    return ConversationCompactionFilter(
        config=CompactionConfig(**defaults), llm_call=llm_call
    )  # type: ignore[arg-type]


def test_anchor_index_extracts_urls_paths_shas_errors_exactly() -> None:
    texts = [
        f"see https://example.com/docs/page?id=7&x=y and commit {_SHA_SHORT} then {_SHA_FULL}",
        f"edited src/taskloom/app.py and /etc/hosts and ./scripts/run.sh for run_7f3a9c21 id {_UUID}",
        "Traceback (most recent call last):\nValueError: Error: boom at line 3\nprocess exited with exit code 2",
        f"again https://example.com/docs/page?id=7&x=y and {_SHA_SHORT}; and/or 1/2 are not paths; 1234567 is a number",
    ]

    section = render_anchor_index(texts)

    assert section.startswith("## Anchor Index (mechanically extracted, exact)")
    for anchor in (
        "https://example.com/docs/page?id=7&x=y",
        _SHA_SHORT,
        _SHA_FULL,
        "src/taskloom/app.py",
        "/etc/hosts",
        "./scripts/run.sh",
        "run_7f3a9c21",
        _UUID,
        "Traceback (most recent call last):",
        "ValueError: Error: boom at line 3",
        "process exited with exit code 2",
    ):
        assert anchor in section, anchor
    assert "- https://example.com/docs/page?id=7&x=y (x2)" in section
    assert "and/or" not in section
    assert "1234567" not in section
    assert "5717" not in section.replace(
        _UUID, ""
    )  # UUID parts are not re-extracted as SHAs


def test_anchor_index_deterministic_and_within_budget() -> None:
    texts = [f"https://example.com/item/{i:04d} src/file{i}.py" for i in range(600)] + [
        "https://example.com/item/0007"
    ] * 3

    first = render_anchor_index(texts)
    second = render_anchor_index(list(texts))

    assert first == second
    assert len(first) <= ANCHOR_BUDGET_CHARS
    lines = first.splitlines()[1:]
    assert lines[0] == "- https://example.com/item/0007 (x4)"  # frequency first
    assert lines[1:3] == [
        "- https://example.com/item/0000 (x1)",
        "- https://example.com/item/0001 (x1)",
    ]  # then lexicographic


def test_anchor_index_empty_when_nothing_found() -> None:
    assert render_anchor_index(["plain words only"]) == ""


def test_user_messages_section_newest_first_budgeted_with_marker() -> None:
    messages = [
        f"msg{i} " + str(i) * 2_995 for i in range(6)
    ]  # 3000 chars each, newest first

    section = render_user_messages_section(messages)

    assert section.startswith("## User Messages (verbatim, newest first)")
    assert (
        section.index("msg0 ")
        < section.index("msg1 ")
        < section.index("msg2 ")
        < section.index("msg3 ")
    )
    assert "msg4 " not in section and "msg5 " not in section
    assert section.count("[truncated 1000 chars]") == 4
    assert "[truncated 6000 chars]" in section  # the two omitted messages
    body = section.replace("[truncated 1000 chars]", "").replace(
        "[truncated 6000 chars]", ""
    )
    assert sum(len(m[:2_000]) for m in messages[:4]) == USER_MESSAGES_BUDGET_CHARS
    assert len(body) < USER_MESSAGES_BUDGET_CHARS + 200


def test_user_messages_section_empty_when_no_messages() -> None:
    assert render_user_messages_section([]) == ""


async def test_user_messages_section_skips_recitation_and_reminders() -> None:
    messages = long_history("THE FIRST ASK")
    messages[2:2] = [
        Message(
            role="user",
            content="<plan-recitation>\nPLAN TEXT\n</plan-recitation>",
            metadata={"recitation": True},
        ),
        Message(
            role="user", content="<system-reminder>REMINDER TEXT</system-reminder>"
        ),
    ]

    result, _ = await _filter(scripted_summarizer(structured_summary())).filter(
        messages, "sys"
    )

    [summary] = summary_messages(result)
    section = summary.content.split("## User Messages (verbatim, newest first)")[1]
    assert "THE FIRST ASK" in section
    assert "continue 0:" in section
    assert "PLAN TEXT" not in summary.content
    assert "REMINDER TEXT" not in summary.content
    # The newest human turn sits in the verbatim section and is not repeated here.
    assert "continue 5:" not in section


async def test_summary_preserves_anchors_llm_forgot() -> None:
    messages = long_history(
        f"deploy {_SHA_SHORT} from https://git.example.com/repo.git"
    )

    result, _ = await _filter(scripted_summarizer(structured_summary())).filter(
        messages, "sys"
    )

    [summary] = summary_messages(result)
    anchors = summary.content.split("## Anchor Index (mechanically extracted, exact)")[
        1
    ]
    assert f"- {_SHA_SHORT} (x" in anchors
    assert "- https://git.example.com/repo.git (x" in anchors


@pytest.mark.parametrize(
    "hint",
    [
        None,
        "Older turns are searchable: call history_search(query) to recover exact wording.",
    ],
)
async def test_recovery_section_only_when_hint_configured(hint: str | None) -> None:
    result, _ = await _filter(
        scripted_summarizer(structured_summary()), recovery_hint=hint
    ).filter(long_history(), "sys")

    [summary] = summary_messages(result)
    if hint is None:
        assert "## Context Recovery" not in summary.content
        assert render_recovery_section(None) == ""
    else:
        assert f"## Context Recovery\n{hint}" in summary.content


async def test_llm_summary_over_16k_chars_rejected_and_fallback_used() -> None:
    oversized = structured_summary("OVERSIZED").replace(
        "Progress: ", "Progress: " + "p" * 16_001
    )
    messages = long_history(rounds=40)

    result, _ = await _filter(
        scripted_summarizer(oversized), threshold_tokens=5_000
    ).filter(messages, "sys")

    [summary] = summary_messages(result)
    assert "OVERSIZED" not in summary.content
    assert "local fallback" in summary.content


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Use history_search.", "Use history_search."), (42, None), (None, None)],
)
def test_runtime_wiring_threads_recovery_hint(
    raw: object, expected: str | None
) -> None:
    native: dict[str, object] = {"compaction_enabled": True}
    if raw is not None:
        native["compaction_recovery_hint"] = raw
    config = AgentConfig(system_prompt="sys", runtime="thin", native_config=native)

    plan = build_portable_runtime_plan(config, "thin")

    assert plan.config.compaction is not None
    assert plan.config.compaction.recovery_hint == expected
