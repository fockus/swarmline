"""Canonical timestamp helpers shared by the kanban adapters.

`KanbanDispatch` decides lease staleness by comparing `stale_before` against a
card's `last_heartbeat_at` — and on every adapter that comparison is a plain
string comparison (in SQLite it happens inside the `UPDATE ... WHERE` itself).
A lexicographic comparison agrees with a chronological one ONLY while both
sides are written in one canonical form, so:

* `now_iso` is the single writer of that form — canonical UTC, offset `+00:00`;
* `canonical_iso` normalizes a caller-supplied instant into it, so an equally
  valid ISO-8601 spelling (a `Z` suffix, or a non-UTC offset) cannot silently
  mean a different instant than the string order implies.

Without the normalization an hour-old cutoff spelled `...T05:00:00+03:00` sorts
ABOVE the canonical `...T03:00:00+00:00` heartbeat it is an hour behind, so a
live lease reads as stale and its card gets executed twice (LTK-BL-11).
"""

from __future__ import annotations

from datetime import UTC, datetime


def now_iso() -> str:
    """Return the current instant in the canonical form the adapters store."""
    return datetime.now(UTC).isoformat()


def canonical_iso(value: str) -> str:
    """Normalize an ISO-8601 instant into the canonical UTC form.

    Accepts the `Z` suffix and any UTC offset. A naive timestamp is read as
    UTC, which is what every in-tree writer produces. Raises `ValueError` (the
    error `datetime.fromisoformat` already raises) when `value` is not an
    instant at all — comparing arbitrary text byte by byte would silently
    decide lease liveness from a caller's typo.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()
