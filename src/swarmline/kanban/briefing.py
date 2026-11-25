"""Deterministic worker briefing renderer (opt-in kanban module, pure function).

Long-task-kanban-continuation increment (Sprint 1a, Stage 4, AGR-012/AGR-017,
REQ-LTK-016..019): a worker picking up a card — a kanban dispatcher run, a
spawn child, or an in-run subagent — needs one rendered document with
everything it needs, instead of re-reading a transcript to get oriented.

`render_worker_context` renders sections in this canonical order (mirrors
Hermes' `build_worker_context()`):

    1. title + id (header, always present)
    2. body (card description)
    3. parent goal
    4. prior attempts (most recent shown in full, older collapsed to one line)
    5. results of done child cards
    6. progress notes
    7. artifact/file references
    8. completion instruction (always present)

Every section but the header and the completion instruction is OMITTED
(never rendered as an empty heading) when it has no content (REQ-LTK-019).
Every size-bounded field is truncated at a UTF-8 character boundary — never
splitting a multi-byte character — with a `…[truncated N chars]` marker
where N is the number of characters (not bytes) dropped (REQ-LTK-017).

GUARANTEED, under one precondition: the header (title+id) and the
completion instruction survive even on a pathological card (huge
body/title, many notes/attempts/parents/children/artifacts) — reserved
first. Only `card.title` is ever truncated (hard, to "" if needed);
`card.id` survives whenever `total_bytes` holds `# {id}` + separator +
completion (~215 B for a short id) — smaller is a degenerate zone, not
specially guarded beyond not crashing. Middle sections (body, parent goal,
prior attempts, done children, progress notes, artifacts) fill whatever
budget remains in canonical order: the first that no longer fits in full
is truncated (dropped if not even the marker fits its share), every
section after it is dropped. Capped at `caps.total_bytes` — one linear
pass, no whole-document shrink loop.

The function is pure (no I/O, no wall clock) and deterministic: the same
input always renders the same output. Notes are grouped by `kind` and
ordered by their own `at` timestamp — never by call/insertion order or by
iterating an unordered collection (REQ-LTK-018).

Zero external dependencies — stdlib only. Part of the opt-in
`swarmline.kanban` package: the swarmline core never imports it
(REQ-ORC-014).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swarmline.kanban.types import KanbanNote, KanbanTask

_TRUNCATION_PREFIX = "…[truncated "
_TRUNCATION_SUFFIX = " chars]"

_COMPLETION_INSTRUCTION = (
    "## Next Steps\n\n"
    "When this card is fully done, call `kanban_complete`. To record "
    "progress without finishing — so a future attempt (yours or another "
    "worker's) sees what you tried — call `kanban_note`."
)


@dataclass(frozen=True)
class BriefingCaps:
    """Size caps for `render_worker_context`'s rendered sections, in UTF-8 bytes.

    One dataclass holds every cap (DRY) so a caller can tune the whole
    briefing's footprint in one place.

    Attributes:
        body_bytes: Max size of the rendered card body/description.
        field_bytes: Max size of any other single rendered field (a parent's
            goal snippet, one attempt's text, one done-child's result, one
            progress note, one artifact ref).
        max_notes: Max number of progress notes rendered (newest kept).
        max_full_attempts: Max number of the most recent attempts rendered
            in full; older attempts are collapsed to one line each.
        total_bytes: Cap on the whole document. `card.id` + completion
            survive whenever this holds both (module docstring, "GUARANTEED").
    """

    body_bytes: int = 8192
    field_bytes: int = 2048
    max_notes: int = 10
    max_full_attempts: int = 3
    total_bytes: int = 16384


def render_worker_context(
    card: KanbanTask,
    *,
    parents: list[KanbanTask],
    done_children_results: list[tuple[KanbanTask, str]],
    notes: list[KanbanNote],
    artifact_refs: list[str],
    caps: BriefingCaps = BriefingCaps(),  # noqa: B008 -- frozen dataclass, safe default
) -> str:
    """Render one deterministic markdown briefing document for a worker.

    See the module docstring for the canonical section order, the
    truncation/omission rules (REQ-LTK-016..019), and which two sections
    are GUARANTEED to survive a pathological card.
    """
    header = _render_header(card, caps)

    attempts = sorted((n for n in notes if n.kind == "attempt"), key=lambda n: n.at)
    progress = sorted((n for n in notes if n.kind == "progress"), key=lambda n: n.at)

    optional_sections = [
        _render_body(card, caps),
        _render_parent_goal(parents, caps),
        _render_prior_attempts(attempts, caps),
        _render_done_children(done_children_results, caps),
        _render_progress_notes(progress, caps),
        _render_artifact_refs(artifact_refs, caps),
    ]

    return _assemble_within_budget(
        header, optional_sections, _COMPLETION_INSTRUCTION, caps.total_bytes
    )


# ---------------------------------------------------------------------------
# Section renderers — each returns "" when it has nothing to show.
# ---------------------------------------------------------------------------


def _render_header(card: KanbanTask, caps: BriefingCaps) -> str:
    id_part = f" ({card.id})"
    fixed = len(f"# {id_part}{_SEPARATOR}{_COMPLETION_INSTRUCTION}".encode())
    budget = max(0, min(caps.field_bytes, caps.total_bytes - fixed))
    title = _truncate_utf8(card.title, budget)
    if len(title.encode("utf-8")) > budget:
        title = ""
    return f"# {title}{id_part}"


def _render_body(card: KanbanTask, caps: BriefingCaps) -> str:
    body = card.metadata.get("body")
    if not body:
        return ""
    return "## Description\n\n" + _truncate_utf8(str(body), caps.body_bytes)


def _render_parent_goal(parents: list[KanbanTask], caps: BriefingCaps) -> str:
    if not parents:
        return ""
    lines = ["## Parent Goal", ""]
    for parent in parents:
        title = _truncate_utf8(parent.title, caps.field_bytes)
        goal_body = parent.metadata.get("body")
        if goal_body:
            snippet = _truncate_utf8(str(goal_body), caps.field_bytes)
            lines.append(f"- {title} ({parent.id}): {snippet}")
        else:
            lines.append(f"- {title} ({parent.id})")
    return "\n".join(lines)


def _render_prior_attempts(attempts: list[KanbanNote], caps: BriefingCaps) -> str:
    if not attempts:
        return ""
    split_at = max(0, len(attempts) - caps.max_full_attempts)
    older, recent = attempts[:split_at], attempts[split_at:]

    lines = ["## Prior Attempts"]
    if older:
        lines.append("")
        for note in older:
            outcome = note.outcome or "unknown"
            summary = _truncate_utf8(_collapse_whitespace(note.text), caps.field_bytes)
            lines.append(f"- {note.at} ({outcome}): {summary}")
    for note in recent:
        outcome = note.outcome or "unknown"
        text = _truncate_utf8(note.text, caps.field_bytes)
        lines.append(f"\n### Attempt at {note.at} ({outcome})\n\n{text}")
    return "\n".join(lines)


def _render_done_children(
    done_children_results: list[tuple[KanbanTask, str]], caps: BriefingCaps
) -> str:
    if not done_children_results:
        return ""
    parts = ["## Completed Subtasks"]
    for child, result in done_children_results:
        title = _truncate_utf8(child.title, caps.field_bytes)
        text = _truncate_utf8(str(result), caps.field_bytes)
        parts.append(f"\n### {title} ({child.id})\n\n{text}")
    return "\n".join(parts)


def _render_progress_notes(progress: list[KanbanNote], caps: BriefingCaps) -> str:
    if not progress:
        return ""
    capped = progress[-caps.max_notes :] if caps.max_notes > 0 else []
    if not capped:
        return ""
    lines = ["## Progress Notes", ""]
    for note in capped:
        summary = _truncate_utf8(_collapse_whitespace(note.text), caps.field_bytes)
        lines.append(f"- {note.at}: {summary}")
    return "\n".join(lines)


def _render_artifact_refs(artifact_refs: list[str], caps: BriefingCaps) -> str:
    if not artifact_refs:
        return ""
    lines = ["## Artifacts", ""]
    for ref in artifact_refs:
        lines.append(f"- {_truncate_utf8(str(ref), caps.field_bytes)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SEPARATOR = "\n\n"
_SEPARATOR_BYTES = len(_SEPARATOR.encode("utf-8"))


def _assemble_within_budget(
    header: str, optional_sections: list[str], completion: str, total_bytes: int
) -> str:
    """Join `header` + as many `optional_sections` as fit + `completion`.

    `header`/`completion` are GUARANTEED: their byte cost (+ separators) is
    reserved first; if that alone exceeds `total_bytes`, `header` is shrunk
    further — `completion` is never touched. `optional_sections` are then
    appended in canonical order until the budget runs out: the first one
    that doesn't fit in full is truncated to fill what's left (dropped, not
    appended oversized, if even the marker wouldn't fit `available`), every
    section after it is dropped — one linear pass, no whole-document shrink.
    """
    completion_bytes = len(completion.encode("utf-8"))
    reserved = len(header.encode("utf-8")) + _SEPARATOR_BYTES + completion_bytes
    if reserved > total_bytes:
        header_budget = max(0, total_bytes - completion_bytes - _SEPARATOR_BYTES)
        header = _truncate_utf8(header, header_budget)
        reserved = len(header.encode("utf-8")) + _SEPARATOR_BYTES + completion_bytes

    parts = [header]
    remaining = total_bytes - reserved
    for section in optional_sections:
        if not section:
            continue
        cost = len(section.encode("utf-8")) + _SEPARATOR_BYTES
        if cost <= remaining:
            parts.append(section)
            remaining -= cost
            continue
        available = remaining - _SEPARATOR_BYTES
        if available > 0:
            truncated = _truncate_utf8(section, available)
            if len(truncated.encode("utf-8")) <= available:
                parts.append(truncated)
        break

    parts.append(completion)
    return _SEPARATOR.join(parts)


def _collapse_whitespace(text: str) -> str:
    """Flatten `text` onto one line — collapses newlines/runs of whitespace."""
    return " ".join(text.split())


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """Truncate `text` to at most `max_bytes` UTF-8 bytes, marker included.

    Never splits a multi-byte UTF-8 character: the kept prefix is decoded
    from a byte slice with `errors="ignore"`, which drops an incomplete
    trailing multi-byte sequence wholesale rather than emitting a partial
    character. The `…[truncated N chars]` marker reports N as the number of
    *characters* (not bytes) dropped from the original text, and the
    returned string (kept prefix + marker) itself fits within `max_bytes`
    whenever `max_bytes` is large enough to hold the marker at all.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    budget = max_bytes
    while budget > 0:
        candidate = encoded[:budget].decode("utf-8", errors="ignore")
        dropped = len(text) - len(candidate)
        result = f"{candidate}{_TRUNCATION_PREFIX}{dropped}{_TRUNCATION_SUFFIX}"
        if len(result.encode("utf-8")) <= max_bytes:
            return result
        budget -= 1

    # max_bytes is smaller than the marker itself — best effort, no content kept.
    return f"{_TRUNCATION_PREFIX}{len(text)}{_TRUNCATION_SUFFIX}"
