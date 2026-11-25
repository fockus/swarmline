"""Storage protocols for the kanban module (opt-in, hermes-semantics minimum).

`KanbanStore` is the storage-agnostic persistence contract for kanban
tasks: create, link (multi-parent + cycle-guard), status transitions
(including the typed block/escalation transition, REQ-ORC-015), listing,
and recursive subtree retrieval. `KanbanReadiness` is a narrow, single-
method contract for parent-gated promotion (REQ-ORC-013): recomputing
whether a parent's children are all done and, if so, promoting it to
`ready`.

`KanbanDispatch` and `KanbanNotes` (long-task-kanban-continuation increment,
Sprint 1a, AGR-012/AGR-017, REQ-LTK-009..015) are additive: CAS-safe card
capture with lease liveness, and a FIFO-capped progress journal.

Both InMemory (`inmemory.py`) and SQLite (`sqlite.py`) adapters implement
every protocol in this module and satisfy the same shared contract tests
(`tests/unit/test_kanban_store.py`, `test_kanban_dispatch_contract.py`) —
contract-first, per swarmline convention: Protocol -> contract tests ->
implementation.

Design note (ISP <=5): `complete_task` is deliberately NOT part of the
`KanbanStore` protocol. It is sugar for `set_status(task_id,
KanbanStatus.DONE)`, implemented as a concrete convenience method on each
adapter so callers get an ergonomic name (and the parent-gated-promotion
call site reads naturally) without inflating the storage contract past
five methods.

Zero external dependencies — stdlib typing only. This module is part of
the opt-in `swarmline.kanban` package: the swarmline core never imports
it (REQ-ORC-014).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from swarmline.kanban.types import BlockKind, KanbanNote, KanbanStatus, KanbanTask

# Number of times a card may re-enter `blocked` before the store escalates
# it to `triage` instead of blocking it again (REQ-ORC-015). Shared by
# every KanbanStore adapter so the escalation policy stays in one place.
_BLOCK_ESCALATION_THRESHOLD = 3


@runtime_checkable
class KanbanStore(Protocol):
    """Storage-agnostic persistence for the recursive kanban board. ISP: 5 methods."""

    async def create_task(self, task: KanbanTask) -> None: ...

    async def link_tasks(self, parent_id: str, child_id: str) -> None: ...

    async def set_status(
        self,
        task_id: str,
        status: KanbanStatus,
        *,
        block_kind: BlockKind | None = None,
    ) -> KanbanTask: ...

    async def list_tasks(self, **filters: Any) -> list[KanbanTask]: ...

    async def get_subtree(self, task_id: str) -> list[KanbanTask]: ...


@runtime_checkable
class KanbanReadiness(Protocol):
    """Parent-gated promotion for one task. ISP: 1 method."""

    async def recompute_ready(self, task_id: str) -> list[str]: ...


@runtime_checkable
class KanbanAssignment(Protocol):
    """Who is working a card, and whether they are still alive. ISP: 2 methods.

    Kanban-unification increment (Sprint J, AGR-007) — mirrors hermes'
    `kanban_claim`/`kanban_heartbeat` tool semantics (see
    `hermes-agent/tools/kanban_tools.py`): claiming and heartbeating are
    deliberately orthogonal to `KanbanStore.set_status` — neither method
    moves a card's lifecycle `status` on its own, they only stamp who/when.
    """

    async def claim_task(self, task_id: str, assignee: str) -> KanbanTask:
        """Record `assignee` as the current claimant; stamps `claimed_at`
        and `last_heartbeat_at` to now. Idempotent — reclaiming (by the same
        or a different assignee) simply overwrites the prior claim. Raises
        `ValueError` if `task_id` is unknown."""
        ...

    async def heartbeat(self, task_id: str) -> KanbanTask:
        """Bump `last_heartbeat_at` to now for an already-claimed task.
        Raises `ValueError` if `task_id` is unknown or has never been
        claimed (`claim_task` first)."""
        ...


@runtime_checkable
class KanbanRetitle(Protocol):
    """Update a card's title. ISP: 1 method.

    Kanban-unification fix-cycle 1 (Sprint J, codex round 1, M-3): the
    application-layer todo->kanban sync needs to propagate a changed todo
    `content` onto its mirrored card without touching `status` — this is
    the missing primitive `KanbanStore.set_status` doesn't cover.
    """

    async def update_title(self, task_id: str, title: str) -> KanbanTask:
        """Replace `title`; leaves every other field untouched. Raises
        `ValueError` if `task_id` is unknown."""
        ...


@runtime_checkable
class KanbanDispatch(Protocol):
    """CAS-based card capture with lease liveness. ISP: 3 methods.

    Long-task-kanban-continuation increment (Sprint 1a, AGR-012/AGR-017,
    REQ-LTK-009..013): closes the deferral left by `KanbanAssignment.claim_task`,
    which unconditionally overwrites a claim. `try_claim`/`release_claim` are the
    CAS-safe capture/release pair; `list_claimable` is the "what's free to pick
    up" query the dispatcher polls. `stale_before` is a timestamp fallback only —
    per design D-LTK-5, the primary liveness signal (whether the lease-holding
    run is terminal) is checked by the caller, which calls `release_claim`
    proactively when it observes a terminal run.

    Timestamp format (LTK-BL-11): `stale_before` may be ANY ISO-8601 instant —
    a `Z` suffix, a non-UTC offset, or a naive value (read as UTC) are all
    accepted and normalized to canonical UTC before any comparison, and a value
    that is not an instant raises `ValueError` instead of being compared as raw
    text. Adapters themselves stamp `claimed_at`/`last_heartbeat_at` in that
    canonical form (`kanban._time.now_iso`), which is what makes the underlying
    lexicographic comparison equivalent to a chronological one.
    """

    async def try_claim(
        self,
        task_id: str,
        assignee: str,
        *,
        lease_id: str,
        stale_before: str,
    ) -> KanbanTask | None:
        """Claim `task_id` for `assignee` under `lease_id` ONLY IF it
        currently has no lease, or its `last_heartbeat_at` is older than
        `stale_before`. On success, stamps `assignee`, `claimed_at`,
        `last_heartbeat_at` to now, `metadata['lease_id']=lease_id`, and
        `metadata['dispatched']=True`. Returns None (no-op) when the card
        is held by a live lease. Raises `ValueError` if `task_id` is
        unknown."""
        ...

    async def release_claim(self, task_id: str, *, lease_id: str) -> KanbanTask:
        """Clear `metadata['lease_id']` ONLY IF it currently equals
        `lease_id`; a foreign or absent lease is a no-op that returns the
        task unchanged. `assignee`/`claimed_at`/`last_heartbeat_at` and
        `metadata['dispatched']` are left untouched — they are historical
        (who last worked it, whether it was ever dispatched), independent
        of whether a lease is currently held. Raises `ValueError` if
        `task_id` is unknown."""
        ...

    async def list_claimable(
        self,
        *,
        statuses: Sequence[KanbanStatus],
        stale_before: str,
        limit: int,
        include_fresh_claims: bool = False,
    ) -> list[KanbanTask]:
        """Return up to `limit` leaf cards (no child links) whose `status`
        is in `statuses` and that are free (no lease) or stale
        (`last_heartbeat_at < stale_before`), ordered by creation time. By
        default excludes cards held under a live (non-stale) lease. When
        `include_fresh_claims` is True, ALSO returns those live-held leaf
        cards — for application-side liveness/reconciliation reads (e.g.
        checking whether a lease-holder's run is still alive) — but this
        listing itself grants no ownership and mutates nothing."""
        ...


@runtime_checkable
class KanbanNotes(Protocol):
    """Progress journal on a card. ISP: 1 method.

    Long-task-kanban-continuation increment (Sprint 1a, AGR-012, REQ-LTK-014):
    lets a worker resuming a previously-attempted card see what earlier
    attempts already tried. Per design D-LTK-6, the journal lives in
    `metadata['notes']` (a JSON-plain `list[dict]`) — no schema migration,
    since the `metadata` column already exists on every adapter.
    """

    async def append_note(
        self,
        task_id: str,
        note: KanbanNote,
        *,
        max_notes: int,
    ) -> KanbanTask:
        """Append `note` to `metadata['notes']`, keeping only the newest
        `max_notes` entries (oldest dropped first). Raises `ValueError` if
        `task_id` is unknown."""
        ...
