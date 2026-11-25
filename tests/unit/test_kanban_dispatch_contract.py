"""Contract tests for `KanbanDispatch` + `KanbanNotes` (open-beta-hermes-saas Sprint 1a
Stage 3, REQ-LTK-009..015).

TDD: written before `swarmline.kanban.store.KanbanDispatch`/`KanbanNotes` exist (must
fail on import first). ONE shared contract suite parametrized over BOTH adapters
(InMemory + SQLite), same convention as `test_kanban_assignment.py`/
`test_kanban_retitle.py`.

Closes the claim/lease deferral left open by `KanbanAssignment.claim_task` (which
unconditionally overwrites a claim): `KanbanDispatch` adds CAS-based capture
(`try_claim`/`release_claim`) plus "what's free to pick up" selection
(`list_claimable`), and `KanbanNotes` adds a FIFO-capped progress journal
(`append_note`) — see design.md D-LTK-5 (lease liveness) / D-LTK-6 (note journal).
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from swarmline.kanban.store import KanbanDispatch, KanbanNotes
from swarmline.kanban.types import KanbanNote, KanbanStatus, KanbanTask

# ---------------------------------------------------------------------------
# Fixtures — same contract test runs against every adapter
# ---------------------------------------------------------------------------


@pytest.fixture(params=["inmemory", "sqlite"])
def store(request: pytest.FixtureRequest):
    if request.param == "inmemory":
        from swarmline.kanban.inmemory import InMemoryKanbanStore

        return InMemoryKanbanStore()

    from swarmline.kanban.sqlite import SqliteKanbanStore

    return SqliteKanbanStore()


def _task(task_id: str, title: str = "Task", **kwargs: object) -> KanbanTask:
    return KanbanTask(id=task_id, title=title, **kwargs)  # type: ignore[arg-type]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Protocol shape (ISP)
# ---------------------------------------------------------------------------


class TestProtocolShape:
    def test_adapter_satisfies_kanban_dispatch_protocol(self, store) -> None:
        assert isinstance(store, KanbanDispatch)

    def test_adapter_satisfies_kanban_notes_protocol(self, store) -> None:
        assert isinstance(store, KanbanNotes)

    def test_kanban_dispatch_protocol_has_at_most_five_methods(self) -> None:
        methods = [
            name
            for name in vars(KanbanDispatch)
            if not name.startswith("_") and callable(getattr(KanbanDispatch, name))
        ]
        assert len(methods) <= 5

    def test_kanban_notes_protocol_has_at_most_five_methods(self) -> None:
        methods = [
            name
            for name in vars(KanbanNotes)
            if not name.startswith("_") and callable(getattr(KanbanNotes, name))
        ]
        assert len(methods) <= 5

    def test_kanban_dispatch_signatures_are_token_only(self) -> None:
        """SPC-03: the CAS surface takes only opaque tokens (task_id/assignee/
        lease_id/stale_before/limit/statuses/include_fresh_claims) — never a
        run id or any other taskloom-side identifier. Pins the exact parameter
        list so a future edit cannot smuggle a run dependency into swarmline.
        """
        try_claim_params = list(inspect.signature(KanbanDispatch.try_claim).parameters)
        assert try_claim_params == [
            "self",
            "task_id",
            "assignee",
            "lease_id",
            "stale_before",
        ]

        release_claim_params = list(
            inspect.signature(KanbanDispatch.release_claim).parameters
        )
        assert release_claim_params == ["self", "task_id", "lease_id"]

        list_claimable_params = list(
            inspect.signature(KanbanDispatch.list_claimable).parameters
        )
        assert list_claimable_params == [
            "self",
            "statuses",
            "stale_before",
            "limit",
            "include_fresh_claims",
        ]


# ---------------------------------------------------------------------------
# try_claim
# ---------------------------------------------------------------------------


class TestTryClaim:
    async def test_try_claim_free_card_succeeds(self, store) -> None:
        await store.create_task(_task("t1"))

        claimed = await store.try_claim(
            "t1", "agent-a", lease_id="lease-1", stale_before=_iso(datetime.now(UTC))
        )

        assert claimed is not None
        assert claimed.assignee == "agent-a"
        assert claimed.metadata["lease_id"] == "lease-1"
        assert claimed.metadata["dispatched"] is True
        assert claimed.claimed_at is not None
        assert claimed.last_heartbeat_at is not None

    async def test_try_claim_held_fresh_card_returns_none(self, store) -> None:
        now = datetime.now(UTC)
        await store.create_task(
            _task(
                "t1",
                metadata={"lease_id": "lease-1"},
                last_heartbeat_at=_iso(now),
            )
        )
        stale_before = _iso(now - timedelta(hours=4))

        result = await store.try_claim(
            "t1", "agent-b", lease_id="lease-2", stale_before=stale_before
        )

        assert result is None
        refetched = (await store.list_tasks())[0]
        assert refetched.assignee is None

    async def test_try_claim_stale_card_reclaims(self, store) -> None:
        now = datetime.now(UTC)
        old_heartbeat = now - timedelta(hours=5)
        stale_before = now - timedelta(hours=4)
        assert (
            old_heartbeat.isoformat() < stale_before.isoformat()
        )  # real, ordered timestamps
        await store.create_task(
            _task(
                "t1",
                metadata={"lease_id": "lease-1"},
                last_heartbeat_at=_iso(old_heartbeat),
            )
        )

        reclaimed = await store.try_claim(
            "t1", "agent-b", lease_id="lease-2", stale_before=_iso(stale_before)
        )

        assert reclaimed is not None
        assert reclaimed.assignee == "agent-b"
        assert reclaimed.metadata["lease_id"] == "lease-2"

    async def test_try_claim_concurrent_claimers_exactly_one_wins(self, store) -> None:
        """Scenario 2 (spec, gates REQ-LTK-009..012): the CAS-safe property
        advertised in the CHANGELOG — N concurrent try_claim calls under
        DIFFERENT lease_ids must produce exactly one winner, and a loser's
        lease_id can never subsequently be used to release the winner's lease.
        """
        await store.create_task(_task("t1"))
        stale_before = _iso(datetime.now(UTC))  # captured BEFORE the race

        results = await asyncio.gather(
            *[
                store.try_claim(
                    "t1", f"agent-{i}", lease_id=f"lease-{i}", stale_before=stale_before
                )
                for i in range(8)
            ]
        )

        winners = [r for r in results if r is not None]
        assert len(winners) == 1
        winner = winners[0]

        refetched = (await store.list_tasks())[0]
        assert refetched.metadata["lease_id"] == winner.metadata["lease_id"]
        assert refetched.assignee == winner.assignee

        unchanged = await store.release_claim("t1", lease_id="lease-never-granted")
        assert unchanged.metadata["lease_id"] == winner.metadata["lease_id"]
        assert unchanged.assignee == winner.assignee


# ---------------------------------------------------------------------------
# release_claim
# ---------------------------------------------------------------------------


class TestReleaseClaim:
    async def test_release_with_foreign_lease_is_noop(self, store) -> None:
        await store.create_task(_task("t1"))
        claimed = await store.try_claim(
            "t1", "agent-a", lease_id="lease-1", stale_before=_iso(datetime.now(UTC))
        )
        assert claimed is not None

        unchanged = await store.release_claim("t1", lease_id="not-my-lease")

        assert unchanged.assignee == "agent-a"
        assert unchanged.metadata["lease_id"] == "lease-1"

    async def test_release_with_matching_lease_clears_it(self, store) -> None:
        await store.create_task(_task("t1"))
        claimed = await store.try_claim(
            "t1", "agent-a", lease_id="lease-1", stale_before=_iso(datetime.now(UTC))
        )
        assert claimed is not None

        released = await store.release_claim("t1", lease_id="lease-1")

        assert "lease_id" not in released.metadata
        assert released.metadata["dispatched"] is True

        reclaimed = await store.try_claim(
            "t1", "agent-b", lease_id="lease-2", stale_before=_iso(datetime.now(UTC))
        )

        assert reclaimed is not None
        assert reclaimed.assignee == "agent-b"
        assert reclaimed.metadata["lease_id"] == "lease-2"

    async def test_release_observed_terminal_lease_cannot_clear_replaced_token(
        self, store
    ) -> None:
        """A caller that observed lease-1's run go terminal, but raced a stale
        reclaim under lease-2, must not be able to clear the NEW token: its
        `release_claim(lease_id="lease-1")` is a stale-token no-op, and
        lease-2 (plus its assignee) must remain exactly as the reclaim left
        them.
        """
        now = datetime.now(UTC)
        await store.create_task(
            _task(
                "t1",
                metadata={"lease_id": "lease-1"},
                assignee="agent-a",
                last_heartbeat_at=_iso(now - timedelta(hours=5)),
            )
        )
        stale_before = _iso(now - timedelta(hours=4))
        reclaimed = await store.try_claim(
            "t1", "agent-b", lease_id="lease-2", stale_before=stale_before
        )
        assert reclaimed is not None
        assert reclaimed.metadata["lease_id"] == "lease-2"

        unchanged = await store.release_claim("t1", lease_id="lease-1")

        assert unchanged.metadata["lease_id"] == "lease-2"
        assert unchanged.assignee == "agent-b"


# ---------------------------------------------------------------------------
# list_claimable
# ---------------------------------------------------------------------------


class TestListClaimable:
    async def test_list_claimable_returns_only_childless_cards_in_requested_statuses(
        self, store
    ) -> None:
        await store.create_task(_task("parent", status=KanbanStatus.TODO))
        await store.create_task(_task("child", status=KanbanStatus.TODO))
        await store.link_tasks("parent", "child")
        await store.create_task(_task("leaf-wrong-status", status=KanbanStatus.DONE))

        result = await store.list_claimable(
            statuses=[KanbanStatus.TODO],
            stale_before=_iso(datetime.now(UTC)),
            limit=10,
        )

        assert {t.id for t in result} == {"child"}

    async def test_list_claimable_skips_fresh_claims_and_respects_limit(
        self, store
    ) -> None:
        now = datetime.now(UTC)
        await store.create_task(
            _task(
                "held",
                status=KanbanStatus.TODO,
                metadata={"lease_id": "lease-1"},
                last_heartbeat_at=_iso(now),
            )
        )
        await store.create_task(_task("free-1", status=KanbanStatus.TODO))
        await store.create_task(_task("free-2", status=KanbanStatus.TODO))

        result = await store.list_claimable(
            statuses=[KanbanStatus.TODO],
            stale_before=_iso(now - timedelta(hours=4)),
            limit=1,
        )

        assert [t.id for t in result] == ["free-1"]

    async def test_list_claimable_includes_stale_claims(self, store) -> None:
        """REQ-LTK-013's disjunction is "free OR stale" — pins the stale half,
        which on the SQLite adapter is a SEPARATE Python predicate
        (`list_claimable_sync`) from the SQL `WHERE` clause `try_claim_sync`
        uses, so it can silently drift out of sync with it.
        """
        now = datetime.now(UTC)
        stale_before = _iso(now - timedelta(hours=4))
        await store.create_task(
            _task(
                "stale-held",
                status=KanbanStatus.TODO,
                metadata={"lease_id": "lease-1"},
                last_heartbeat_at=_iso(now - timedelta(hours=5)),
            )
        )
        await store.create_task(
            _task(
                "fresh-held",
                status=KanbanStatus.TODO,
                metadata={"lease_id": "lease-2"},
                last_heartbeat_at=_iso(now),
            )
        )
        await store.create_task(_task("free", status=KanbanStatus.TODO))

        result = await store.list_claimable(
            statuses=[KanbanStatus.TODO],
            stale_before=stale_before,
            limit=10,
        )

        ids = {t.id for t in result}
        assert "stale-held" in ids
        assert "fresh-held" not in ids
        assert "free" in ids

    async def test_list_claimable_include_fresh_exposes_held_running_candidate(
        self, store
    ) -> None:
        """`include_fresh_claims=True` additionally surfaces held-but-live
        cards for application-side reconciliation, WITHOUT granting ownership
        or mutating anything — the default call must still exclude them.
        """
        now = datetime.now(UTC)
        await store.create_task(
            _task(
                "running-fresh",
                status=KanbanStatus.RUNNING,
                metadata={"lease_id": "lease-1"},
                assignee="agent-a",
                last_heartbeat_at=_iso(now),
            )
        )

        default_result = await store.list_claimable(
            statuses=[KanbanStatus.RUNNING],
            stale_before=_iso(now - timedelta(hours=4)),
            limit=10,
        )
        assert default_result == []

        included = await store.list_claimable(
            statuses=[KanbanStatus.RUNNING],
            stale_before=_iso(now - timedelta(hours=4)),
            limit=10,
            include_fresh_claims=True,
        )
        assert [t.id for t in included] == ["running-fresh"]

        refetched = (await store.list_tasks())[0]
        assert refetched.metadata["lease_id"] == "lease-1"
        assert refetched.assignee == "agent-a"
        assert refetched.last_heartbeat_at == _iso(now)


# ---------------------------------------------------------------------------
# append_note
# ---------------------------------------------------------------------------


class TestAppendNote:
    async def test_append_note_fifo_cap_keeps_newest(self, store) -> None:
        await store.create_task(_task("t1"))

        for i in range(4):
            await store.append_note(
                "t1",
                KanbanNote(
                    kind="progress", text=f"note-{i}", at=_iso(datetime.now(UTC))
                ),
                max_notes=3,
            )
        refetched = (await store.list_tasks())[0]

        texts = [note["text"] for note in refetched.metadata["notes"]]
        assert texts == ["note-1", "note-2", "note-3"]

    async def test_append_note_cap_leaves_body_untouched(self, store) -> None:
        body = "A long task description that must survive note-cap eviction untouched."
        await store.create_task(_task("t1", metadata={"body": body}))

        for i in range(4):
            await store.append_note(
                "t1",
                KanbanNote(
                    kind="progress", text=f"note-{i}", at=_iso(datetime.now(UTC))
                ),
                max_notes=3,
            )
        refetched = (await store.list_tasks())[0]

        assert refetched.metadata["body"] == body
        assert len(refetched.metadata["notes"]) == 3


# ---------------------------------------------------------------------------
# `stale_before` format contract (LTK-BL-11)
# ---------------------------------------------------------------------------


class TestStaleBeforeFormatContract:
    """`stale_before` is compared against `last_heartbeat_at` lexicographically,
    which is only equivalent to a chronological comparison while BOTH sides are
    canonical UTC (`datetime.now(UTC).isoformat()`, offset `+00:00`).

    A caller that passes an equally valid ISO-8601 instant in another form — a
    non-UTC offset, or the `Z` suffix — silently means a DIFFERENT instant than
    the string order implies. The consequence is not a cosmetic one: a live
    lease gets reclaimed and its card is executed twice.
    """

    async def test_cutoff_in_a_non_utc_offset_does_not_reclaim_a_live_lease(
        self, store
    ) -> None:
        """An hour-old cutoff written as `+03:00` must not make a fresh lease stale.

        Lexicographically `...T05:00:00+03:00` sorts ABOVE the canonical
        `...T03:00:00+00:00` heartbeat it is an hour BEHIND, so a raw string
        comparison declares the live lease stale and hands the card away.
        """
        from datetime import timezone

        now = datetime.now(UTC)
        await store.create_task(
            _task("t1", metadata={"lease_id": "lease-1"}, last_heartbeat_at=_iso(now))
        )
        cutoff = (now - timedelta(hours=1)).astimezone(timezone(timedelta(hours=3)))

        result = await store.try_claim(
            "t1", "agent-b", lease_id="lease-2", stale_before=cutoff.isoformat()
        )

        assert result is None, (
            "a live lease was reclaimed because the cutoff used a +03:00 offset"
        )
        refetched = (await store.list_tasks())[0]
        assert refetched.metadata["lease_id"] == "lease-1"

    async def test_cutoff_at_the_same_instant_with_z_suffix_is_not_stale(
        self, store
    ) -> None:
        """`Z` and `+00:00` are the same instant; `Z` must not sort as later.

        `"+"` (0x2B) sorts before `"Z"` (0x5A), so a canonical heartbeat compares
        as strictly less than the very same instant spelled with `Z` — turning an
        equal timestamp into a stale one at the boundary.
        """
        now = datetime.now(UTC)
        await store.create_task(
            _task("t1", metadata={"lease_id": "lease-1"}, last_heartbeat_at=_iso(now))
        )
        cutoff_z = now.isoformat().replace("+00:00", "Z")

        result = await store.try_claim(
            "t1", "agent-b", lease_id="lease-2", stale_before=cutoff_z
        )

        assert result is None, "an equal instant spelled with Z was treated as stale"

    async def test_list_claimable_ignores_a_live_lease_under_a_non_utc_cutoff(
        self, store
    ) -> None:
        """The same normalization must hold on the listing path, not only on claim."""
        from datetime import timezone

        now = datetime.now(UTC)
        await store.create_task(
            _task(
                "t1",
                status=KanbanStatus.READY,
                metadata={"lease_id": "lease-1"},
                last_heartbeat_at=_iso(now),
            )
        )
        cutoff = (now - timedelta(hours=1)).astimezone(timezone(timedelta(hours=3)))

        claimable = await store.list_claimable(
            statuses=[KanbanStatus.READY], stale_before=cutoff.isoformat(), limit=10
        )

        assert claimable == [], (
            "a live lease was offered as claimable under a +03:00 cutoff"
        )

    async def test_an_unparseable_cutoff_is_rejected(self, store) -> None:
        """A cutoff that is not an ISO-8601 instant is a caller bug, not a
        comparison to silently carry out against arbitrary text."""
        await store.create_task(_task("t1"))

        with pytest.raises(ValueError):
            await store.try_claim(
                "t1", "agent-b", lease_id="lease-2", stale_before="not-a-timestamp"
            )

    def test_canonical_form_orders_lexicographically_as_it_orders_in_time(self) -> None:
        """The property every comparison above leans on, asserted directly."""
        from swarmline.kanban._time import now_iso

        stamps = [now_iso() for _ in range(5)]

        assert stamps == sorted(stamps)
        assert all(s.endswith("+00:00") for s in stamps)

    def test_equivalent_spellings_normalize_to_one_string(self) -> None:
        """`Z`, a +03:00 offset and a naive value naming ONE instant must not
        produce three different cutoffs."""
        from swarmline.kanban._time import canonical_iso

        as_z = canonical_iso("2026-09-21T03:00:00Z")
        as_offset = canonical_iso("2026-09-21T06:00:00+03:00")
        as_naive = canonical_iso("2026-09-21T03:00:00")

        assert as_z == as_offset == as_naive
