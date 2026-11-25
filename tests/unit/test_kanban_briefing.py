"""Tests for `swarmline.kanban.briefing` and the `kanban_note` tool
(open-beta-hermes-saas Sprint 1a Stage 4, REQ-LTK-016..021).

TDD: written before `swarmline.kanban.briefing` exists — the first run of
this file is expected to fail on import (`ModuleNotFoundError`), which is
the RED evidence required by mb-engineering-core Iron Law §2/§7.
"""

from __future__ import annotations

import json
import re

import pytest

from swarmline.kanban.briefing import BriefingCaps, render_worker_context
from swarmline.kanban.tools import create_kanban_note_tools
from swarmline.kanban.types import KanbanNote, KanbanStatus, KanbanTask

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _card(**overrides: object) -> KanbanTask:
    defaults: dict[str, object] = {
        "id": "card-1",
        "title": "Ship the widget",
        "status": KanbanStatus.RUNNING,
        "metadata": {},
    }
    defaults.update(overrides)
    return KanbanTask(**defaults)  # type: ignore[arg-type]


def _note(
    kind: str,
    text: str,
    at: str,
    *,
    run_id: str | None = None,
    outcome: str | None = None,
) -> KanbanNote:
    return KanbanNote(kind=kind, text=text, at=at, run_id=run_id, outcome=outcome)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# render_worker_context
# ---------------------------------------------------------------------------


def test_briefing_sections_in_canonical_order() -> None:
    card = _card(metadata={"body": "Full task description."})
    parent = _card(id="parent-1", title="Parent goal card")
    child = _card(id="child-1", title="Child card")
    notes = [
        _note(
            "attempt",
            "Tried X, failed on Y.",
            "2026-01-01T00:00:00+00:00",
            run_id="run-1",
            outcome="failed",
        ),
        _note("progress", "Halfway through step 2.", "2026-01-02T00:00:00+00:00"),
    ]

    doc = render_worker_context(
        card,
        parents=[parent],
        done_children_results=[(child, "Child finished successfully.")],
        notes=notes,
        artifact_refs=["s3://bucket/report.txt"],
    )

    positions = [
        doc.index(card.title),
        doc.index("Full task description."),
        doc.index(parent.title),
        doc.index("Tried X, failed on Y."),
        doc.index("Child finished successfully."),
        doc.index("Halfway through step 2."),
        doc.index("s3://bucket/report.txt"),
        doc.index("kanban_complete"),
    ]
    assert positions == sorted(positions)
    assert "kanban_note" in doc


def test_briefing_omits_empty_sections() -> None:
    card = _card(metadata={})

    doc = render_worker_context(
        card,
        parents=[],
        done_children_results=[],
        notes=[],
        artifact_refs=[],
    )

    for heading in (
        "Description",
        "Parent Goal",
        "Prior Attempts",
        "Completed Subtasks",
        "Progress Notes",
        "Artifacts",
    ):
        assert heading not in doc
    assert card.title in doc
    assert "kanban_complete" in doc


def test_briefing_collapses_older_attempts_to_one_line() -> None:
    card = _card(metadata={"body": "desc"})
    attempts = [
        _note(
            "attempt",
            f"Full detail of attempt {i}\nwith a second line.",
            f"2026-01-0{i}T00:00:00+00:00",
            outcome="failed",
        )
        for i in range(1, 6)
    ]
    caps = BriefingCaps(max_full_attempts=2)

    doc = render_worker_context(
        card,
        parents=[],
        done_children_results=[],
        notes=attempts,
        artifact_refs=[],
        caps=caps,
    )

    for i in (1, 2, 3):
        assert f"Full detail of attempt {i}\nwith a second line." not in doc
        assert f"Full detail of attempt {i} with a second line." in doc
    for i in (4, 5):
        assert f"Full detail of attempt {i}\nwith a second line." in doc


def test_briefing_truncates_body_on_char_boundary_with_marker() -> None:
    # Every character is 2 bytes in UTF-8 (Cyrillic "д"). An ODD cap makes a
    # naive single byte-slice land mid-character, so an implementation that
    # emits U+FFFD (or splits the char) fails here; 100 would let such an
    # implementation pass.
    body = "привет" * 50  # 300 chars, 600 bytes
    card = _card(metadata={"body": body})
    caps = BriefingCaps(body_bytes=101)

    doc = render_worker_context(
        card,
        parents=[],
        done_children_results=[],
        notes=[],
        artifact_refs=[],
        caps=caps,
    )

    assert "�" not in doc  # no broken/replacement characters
    assert body not in doc  # truncation actually happened

    match = re.search(r"…\[truncated (\d+) chars\]", doc)
    assert match is not None
    dropped = int(match.group(1))
    assert 0 < dropped < len(body)

    kept = body[: len(body) - dropped]
    marker = f"…[truncated {dropped} chars]"
    assert kept + marker in doc
    # the truncated body fragment itself respects the field/body cap
    assert len((kept + marker).encode("utf-8")) <= caps.body_bytes


def test_briefing_total_cap_enforced_on_pathological_card() -> None:
    huge_title = "Y" * 50_000
    huge_body = "x" * 50_000
    card = _card(title=huge_title, metadata={"body": huge_body})
    many_parents = [
        _card(id=f"parent-{i}", title=f"Parent {i}" * 20) for i in range(50)
    ]
    many_children = [
        (_card(id=f"child-{i}", title=f"Child {i}"), "result " * 500) for i in range(50)
    ]
    many_notes = [
        _note(
            "attempt" if i % 2 == 0 else "progress",
            "note text " * 200,
            f"2026-01-01T00:{i:02d}:00+00:00",
            outcome="failed",
        )
        for i in range(50)
    ]
    many_artifacts = [f"s3://bucket/artifact-{i}.txt" * 5 for i in range(50)]
    caps = BriefingCaps()

    doc = render_worker_context(
        card,
        parents=many_parents,
        done_children_results=many_children,
        notes=many_notes,
        artifact_refs=many_artifacts,
        caps=caps,
    )

    # Total-cap invariant.
    assert len(doc.encode("utf-8")) <= caps.total_bytes

    # The two GUARANTEED sections must survive a pathological card, not just
    # the byte-length cap (REQ-LTK-016): the header (with the card id) and
    # the completion instruction, which is where the `kanban_complete`/
    # `kanban_note` tool-call guidance lives.
    assert f"({card.id})" in doc
    assert "kanban_complete" in doc
    assert "kanban_note" in doc

    # The (unbounded) title is truncated to the field cap, on a character
    # boundary, with the marker — same rule as every other field — and the
    # header is the very first thing in the document.
    match = re.search(r"…\[truncated (\d+) chars\]", doc)
    assert match is not None
    dropped = int(match.group(1))
    assert 0 < dropped < len(huge_title)
    kept_title = huge_title[: len(huge_title) - dropped]
    header_fragment = f"# {kept_title}…[truncated {dropped} chars]"
    assert doc.startswith(header_fragment)
    assert len(header_fragment.encode("utf-8")) - 2 <= caps.field_bytes  # minus "# "


def test_briefing_total_cap_holds_when_remaining_budget_is_smaller_than_marker() -> (
    None
):
    """A section that overflows the tail budget by LESS than the truncation
    marker's own size must be dropped entirely, not appended oversized.

    `_truncate_utf8`'s degenerate fallback (`max_bytes` too small even for
    the bare marker) does not itself re-check the byte budget, so the caller
    (`_assemble_within_budget`) must verify the truncated result actually
    fits before appending it — otherwise the document can end up 1..N bytes
    over `caps.total_bytes` (N up to the marker's own byte length).
    """
    card = _card(metadata={"body": "x" * 9000})
    caps = BriefingCaps()

    for n in range(1700, 1900):
        children = [
            (_card(id=f"child-{i}", title=f"Child {i}"), "r" * 1500) for i in range(4)
        ]
        children.append((_card(id="child-4", title="Child 4"), "r" * n))

        doc = render_worker_context(
            card,
            parents=[],
            done_children_results=children,
            notes=[],
            artifact_refs=["s3://bucket/report.txt"],
            caps=caps,
        )

        assert len(doc.encode("utf-8")) <= caps.total_bytes, n
        assert "kanban_complete" in doc, n


def test_briefing_total_cap_truncates_first_overflowing_section_and_omits_later_ones() -> (
    None
):
    """Canonical-order tail behavior under a tight `total_bytes`: sections up to
    and including the first one that overflows survive (the overflowing one
    truncated with the marker); every section after it is omitted outright,
    and the completion instruction still lands last."""
    card = _card(metadata={"body": "Short description that fits easily."})
    parent = _card(id="parent-1", title="Parent", metadata={"body": "g" * 2000})
    notes = [_note("progress", "Halfway done.", "2026-01-01T00:00:00+00:00")]
    caps = BriefingCaps(total_bytes=600)

    doc = render_worker_context(
        card,
        parents=[parent],
        done_children_results=[],
        notes=notes,
        artifact_refs=["s3://bucket/report.txt"],
        caps=caps,
    )

    assert len(doc.encode("utf-8")) <= caps.total_bytes

    # Description (fits) and Parent Goal (overflows, truncated) survive.
    assert "## Description" in doc
    assert "Short description that fits easily." in doc
    assert "## Parent Goal" in doc
    assert "…[truncated" in doc

    # Everything canonically AFTER the first overflowing section is dropped.
    assert "## Progress Notes" not in doc
    assert "## Artifacts" not in doc

    # The completion instruction is still the very last section.
    assert doc.endswith("call `kanban_note`.")


@pytest.mark.parametrize(
    "title_len,total_bytes",
    [(3000, 220), (100, 300), (3000, 600), (3000, 1024), (3000, 2048)],
)
def test_briefing_header_keeps_card_id_when_total_cap_is_below_header_cost(
    title_len: int, total_bytes: int
) -> None:
    """`card.id` is load-bearing (`kanban_complete(task_id)` needs it) and is
    never itself truncated — only `card.title` is. A caller-tunable
    `total_bytes` below the default `field_bytes` must still keep the id in
    the header, even though the title may be truncated hard or dropped."""
    card = _card(title="T" * title_len)
    caps = BriefingCaps(total_bytes=total_bytes)

    doc = render_worker_context(
        card,
        parents=[],
        done_children_results=[],
        notes=[],
        artifact_refs=[],
        caps=caps,
    )

    header = doc.split("\n\n")[0]
    assert header.startswith("# ")
    assert header.endswith(" (card-1)")
    assert len(doc.encode("utf-8")) <= total_bytes
    assert "kanban_complete" in doc


def test_briefing_output_deterministic_for_same_input() -> None:
    card = _card(metadata={"body": "desc"})
    parent = _card(id="parent-1", title="Parent")
    child = _card(id="child-1", title="Child")
    notes = [
        _note("attempt", "attempt text", "2026-01-01T00:00:00+00:00", outcome="failed"),
        _note("progress", "progress text", "2026-01-02T00:00:00+00:00"),
    ]
    kwargs: dict[str, object] = {
        "parents": [parent],
        "done_children_results": [(child, "done result")],
        "notes": notes,
        "artifact_refs": ["ref-1"],
    }

    doc1 = render_worker_context(card, **kwargs)  # type: ignore[arg-type]
    doc2 = render_worker_context(card, **kwargs)  # type: ignore[arg-type]

    assert doc1 == doc2


# ---------------------------------------------------------------------------
# kanban_note tool
# ---------------------------------------------------------------------------


class _NotesStore:
    """Minimal real stub implementing `KanbanNotes` (has `append_note`)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, KanbanNote, int]] = []

    async def append_note(
        self, task_id: str, note: KanbanNote, *, max_notes: int
    ) -> KanbanTask:
        self.calls.append((task_id, note, max_notes))
        return _card(id=task_id, metadata={"notes": [note.text]})


class _NoNotesStore:
    """Minimal real stub that does NOT implement `KanbanNotes` (no `append_note`)."""

    async def create_task(self, task: KanbanTask) -> None:  # pragma: no cover - unused
        raise NotImplementedError


async def test_kanban_note_tool_appends_progress_note() -> None:
    store = _NotesStore()
    specs, executors = create_kanban_note_tools(store)

    assert "kanban_note" in specs
    assert "kanban_note" in executors

    raw = await executors["kanban_note"]({"task_id": "card-1", "text": "halfway there"})
    result = json.loads(raw)

    assert result["status"] == "ok"
    assert len(store.calls) == 1
    task_id, note, max_notes = store.calls[0]
    assert task_id == "card-1"
    assert note.kind == "progress"
    assert note.text == "halfway there"
    assert max_notes == BriefingCaps().max_notes


def test_kanban_note_tool_absent_when_store_lacks_notes_protocol() -> None:
    store = _NoNotesStore()

    specs, executors = create_kanban_note_tools(store)

    assert specs == {}
    assert executors == {}
