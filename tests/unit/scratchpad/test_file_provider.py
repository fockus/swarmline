"""Contract + persistence tests for FileScratchpadProvider.

`TestScratchpadContract` runs the SAME assertions as
`test_inmemory_provider.py` against BOTH providers — the file-backed
implementation must be behaviourally indistinguishable from the reference
in-memory one for every non-durability aspect.

`TestFileDurability` covers what the in-memory provider cannot satisfy: a new
provider instance over the same ``base_dir`` sees earlier writes (process
restart), which is the whole reason this class exists.
"""

from __future__ import annotations

import json

import logging

from collections.abc import Callable
from pathlib import Path

import pytest

from swarmline.scratchpad.file_provider import FileScratchpadProvider
from swarmline.scratchpad.inmemory_provider import InMemoryScratchpadProvider
from swarmline.scratchpad.protocols import ScratchpadProvider

ProviderFactory = Callable[[], ScratchpadProvider]


@pytest.fixture(params=["inmemory", "file"])
def provider(request: pytest.FixtureRequest, tmp_path: Path) -> ScratchpadProvider:
    """The reference provider and the file-backed one, under identical assertions."""
    if request.param == "inmemory":
        return InMemoryScratchpadProvider()
    return FileScratchpadProvider(base_dir=tmp_path / "scratchpad")


@pytest.fixture
def reopen(tmp_path: Path) -> ProviderFactory:
    """Build a fresh FileScratchpadProvider over one shared base_dir (restart simulation)."""
    base_dir = tmp_path / "durable"

    def _factory() -> ScratchpadProvider:
        return FileScratchpadProvider(base_dir=base_dir)

    return _factory


class TestScratchpadContract:
    """Mirrors test_inmemory_provider.py — must hold for ANY ScratchpadProvider."""

    def test_implements_scratchpad_provider_protocol(
        self, provider: ScratchpadProvider
    ) -> None:
        assert isinstance(provider, ScratchpadProvider)

    async def test_write_new_key_returns_entry_with_matching_fields(
        self, provider: ScratchpadProvider
    ) -> None:
        entry = await provider.write("notes", "hello world")
        assert entry.key == "notes"
        assert entry.content == "hello world"

    async def test_write_with_tags_preserves_tags(
        self, provider: ScratchpadProvider
    ) -> None:
        entry = await provider.write("notes", "content", tags=("draft", "review"))
        assert entry.tags == ("draft", "review")

    async def test_write_existing_key_upserts_content(
        self, provider: ScratchpadProvider
    ) -> None:
        await provider.write("notes", "v1")
        await provider.write("notes", "v2")
        entries = await provider.read(None)
        assert isinstance(entries, list) and len(entries) == 1
        assert entries[0].content == "v2"

    async def test_write_existing_key_keeps_created_at_and_advances_updated_at(
        self, provider: ScratchpadProvider
    ) -> None:
        first = await provider.write("notes", "v1")
        second = await provider.write("notes", "v2")
        assert second.created_at == first.created_at
        assert second.updated_at >= first.updated_at

    async def test_read_none_returns_empty_list_when_empty(
        self, provider: ScratchpadProvider
    ) -> None:
        assert await provider.read(None) == []

    async def test_read_none_returns_all_entries(
        self, provider: ScratchpadProvider
    ) -> None:
        await provider.write("a", "1")
        await provider.write("b", "2")
        entries = await provider.read(None)
        assert isinstance(entries, list)
        assert {e.key for e in entries} == {"a", "b"}

    async def test_read_existing_key_returns_entry(
        self, provider: ScratchpadProvider
    ) -> None:
        await provider.write("research", "findings")
        entry = await provider.read("research")
        assert entry is not None and not isinstance(entry, list)
        assert entry.key == "research"
        assert entry.content == "findings"

    async def test_read_missing_key_returns_none(
        self, provider: ScratchpadProvider
    ) -> None:
        assert await provider.read("missing") is None

    async def test_search_matches_content_case_insensitive(
        self, provider: ScratchpadProvider
    ) -> None:
        await provider.write("a", "API design patterns")
        await provider.write("b", "other note")
        results = await provider.search("api")
        assert [e.key for e in results] == ["a"]

    async def test_search_matches_key(self, provider: ScratchpadProvider) -> None:
        await provider.write("research_notes", "x")
        await provider.write("draft", "x")
        results = await provider.search("research")
        assert [e.key for e in results] == ["research_notes"]

    async def test_search_matches_tags(self, provider: ScratchpadProvider) -> None:
        await provider.write("a", "content", tags=("review",))
        await provider.write("b", "content")
        results = await provider.search("review")
        assert [e.key for e in results] == ["a"]

    async def test_search_empty_query_returns_empty(
        self, provider: ScratchpadProvider
    ) -> None:
        await provider.write("a", "x")
        assert await provider.search("") == []

    async def test_delete_existing_key_returns_true(
        self, provider: ScratchpadProvider
    ) -> None:
        await provider.write("a", "x")
        assert await provider.delete("a") is True
        assert await provider.read("a") is None

    async def test_delete_missing_key_returns_false(
        self, provider: ScratchpadProvider
    ) -> None:
        assert await provider.delete("missing") is False


class TestFileDurability:
    """The reason FileScratchpadProvider exists — survives process restart."""

    async def test_new_instance_over_same_base_dir_sees_earlier_writes(
        self, reopen: ProviderFactory
    ) -> None:
        await reopen().write("plan", "step 1 done", tags=("wip",))

        restarted = await reopen().read("plan")

        assert restarted is not None and not isinstance(restarted, list)
        assert restarted.content == "step 1 done"
        assert restarted.tags == ("wip",)

    async def test_new_instance_preserves_timestamps(
        self, reopen: ProviderFactory
    ) -> None:
        written = await reopen().write("plan", "content")

        restarted = await reopen().read("plan")

        assert restarted is not None and not isinstance(restarted, list)
        assert restarted.created_at == written.created_at
        assert restarted.updated_at == written.updated_at

    async def test_new_instance_sees_upsert_not_duplicate(
        self, reopen: ProviderFactory
    ) -> None:
        await reopen().write("plan", "v1")
        await reopen().write("plan", "v2")

        entries = await reopen().read(None)

        assert isinstance(entries, list) and len(entries) == 1
        assert entries[0].content == "v2"

    async def test_new_instance_does_not_resurrect_deleted_entry(
        self, reopen: ProviderFactory
    ) -> None:
        await reopen().write("plan", "content")
        assert await reopen().delete("plan") is True

        assert await reopen().read("plan") is None

    async def test_new_instance_preserves_write_order(
        self, reopen: ProviderFactory
    ) -> None:
        await reopen().write("a", "1")
        await reopen().write("b", "2")
        await reopen().write("c", "3")

        entries = await reopen().read(None)

        assert isinstance(entries, list)
        assert [e.key for e in entries] == ["a", "b", "c"]


class TestFileIsolation:
    async def test_distinct_base_dirs_do_not_share_entries(
        self, tmp_path: Path
    ) -> None:
        alpha = FileScratchpadProvider(base_dir=tmp_path / "alpha")
        beta = FileScratchpadProvider(base_dir=tmp_path / "beta")

        await alpha.write("secret", "alpha only")

        assert await beta.read("secret") is None
        assert await beta.read(None) == []

    async def test_keys_with_path_separators_stay_inside_base_dir(
        self, tmp_path: Path
    ) -> None:
        """A traversal key must land in the JSON payload, never on the filesystem.

        `base_dir / "../../escape"` resolves to `tmp_path.parent / "escape"` — that
        exact path is asserted absent, so a file-per-entry implementation fails here.
        """
        base_dir = tmp_path / "guarded"
        provider = FileScratchpadProvider(base_dir=base_dir)

        await provider.write("../../escape", "payload")

        # base_dir holds the store and nothing else — no traversal artefacts.
        assert [p.name for p in base_dir.iterdir()] == ["scratchpad.json"]
        # The key is data inside the JSON object, not a path component.
        payload = json.loads((base_dir / "scratchpad.json").read_text(encoding="utf-8"))
        assert "../../escape" in payload
        assert not (tmp_path.parent / "escape").exists()

        entry = await FileScratchpadProvider(base_dir=base_dir).read("../../escape")
        assert entry is not None and not isinstance(entry, list)
        assert entry.content == "payload"


class TestFileStorageBehaviour:
    async def test_write_creates_base_dir_when_missing(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "nested" / "scratchpad"
        provider = FileScratchpadProvider(base_dir=base_dir)

        await provider.write("a", "x")

        assert base_dir.is_dir()

    async def test_write_leaves_no_temp_file_behind(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "scratchpad"
        provider = FileScratchpadProvider(base_dir=base_dir)

        await provider.write("a", "x")

        assert [p.name for p in base_dir.iterdir()] == ["scratchpad.json"]

    async def test_store_is_valid_json_with_entry_payload(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "scratchpad"
        provider = FileScratchpadProvider(base_dir=base_dir)

        await provider.write("a", "content", tags=("t1",))

        payload = json.loads((base_dir / "scratchpad.json").read_text(encoding="utf-8"))
        assert payload["a"]["content"] == "content"
        assert payload["a"]["tags"] == ["t1"]

    async def test_corrupt_store_degrades_to_empty_and_is_quarantined(
        self, tmp_path: Path
    ) -> None:
        base_dir = tmp_path / "scratchpad"
        base_dir.mkdir(parents=True)
        (base_dir / "scratchpad.json").write_text("{not json", encoding="utf-8")

        provider = FileScratchpadProvider(base_dir=base_dir)

        assert await provider.read(None) == []
        assert any(
            p.name.startswith("scratchpad.json.corrupt-") for p in base_dir.iterdir()
        )

    async def test_absent_store_starts_empty_without_creating_files(
        self, tmp_path: Path
    ) -> None:
        base_dir = tmp_path / "scratchpad"

        provider = FileScratchpadProvider(base_dir=base_dir)

        assert await provider.read(None) == []
        assert not base_dir.exists()


class TestPersistFailureLeavesNoPhantomState:
    """In-memory state must not diverge from the file when `_persist` fails.

    `write`/`delete` mutated `self._entries` BEFORE persisting, so an OSError
    (disk full, read-only mount, permissions) left the entry present in memory
    and absent on disk: `read` confidently returned a note that would vanish on
    restart, and `delete` reported success for a note still on disk. Same class
    as the space-files finding in Sprint A — the store is the source of truth,
    so memory must roll back to match it.
    """

    @staticmethod
    def _fail_persist(provider: FileScratchpadProvider) -> None:
        def _boom() -> None:
            raise OSError("disk full")

        provider._persist = _boom  # type: ignore[method-assign]

    async def test_failed_write_does_not_appear_in_reads(self, tmp_path: Path) -> None:
        provider = FileScratchpadProvider(base_dir=tmp_path / "sp")
        self._fail_persist(provider)

        with pytest.raises(OSError):
            await provider.write("plan", "never persisted")

        assert await provider.read("plan") is None, (
            "phantom write — read returned an entry that is not on disk"
        )
        assert await provider.read(None) == []

    async def test_failed_write_does_not_clobber_the_previous_version(
        self, tmp_path: Path
    ) -> None:
        provider = FileScratchpadProvider(base_dir=tmp_path / "sp")
        await provider.write("plan", "original content")
        self._fail_persist(provider)

        with pytest.raises(OSError):
            await provider.write("plan", "update that failed to persist")

        surviving = await provider.read("plan")
        assert surviving is not None and not isinstance(surviving, list)
        assert surviving.content == "original content"

    async def test_failed_delete_keeps_the_entry_readable(self, tmp_path: Path) -> None:
        provider = FileScratchpadProvider(base_dir=tmp_path / "sp")
        await provider.write("plan", "still here")
        self._fail_persist(provider)

        with pytest.raises(OSError):
            await provider.delete("plan")

        surviving = await provider.read("plan")
        assert surviving is not None and not isinstance(surviving, list)
        assert surviving.content == "still here", (
            "phantom delete — entry vanished from memory but remains on disk"
        )

    async def test_failed_write_state_matches_a_restart(self, tmp_path: Path) -> None:
        """The strongest form: in-memory state equals what a fresh process sees."""
        base = tmp_path / "sp"
        provider = FileScratchpadProvider(base_dir=base)
        await provider.write("kept", "durable")
        self._fail_persist(provider)

        with pytest.raises(OSError):
            await provider.write("lost", "not durable")

        restarted = FileScratchpadProvider(base_dir=base)
        assert {e.key for e in await provider.read(None)} == {
            e.key for e in await restarted.read(None)
        }


class TestDamagedEntriesAreQuarantinedNotDropped:
    """A single malformed entry must not silently destroy a note.

    Bad entries were skipped with a bare `continue`, so the next write rewrote
    the store without them — permanent, unlogged data loss. Same class as the
    whole-store corruption path, which already quarantines.
    """

    @staticmethod
    def _store_with_one_bad_entry(tmp_path: Path) -> Path:
        base = tmp_path / "sp"
        base.mkdir(parents=True, exist_ok=True)
        store = base / "scratchpad.json"
        store.write_text(
            json.dumps(
                {
                    "good": {
                        "content": "readable note",
                        "tags": [],
                        "created_at": "2026-07-19T10:00:00+00:00",
                        "updated_at": "2026-07-19T10:00:00+00:00",
                    },
                    "broken": {
                        "content": "note with a bad timestamp",
                        "tags": [],
                        "created_at": "not-a-date",
                    },
                }
            ),
            encoding="utf-8",
        )
        return base

    async def test_good_entries_still_load(self, tmp_path: Path) -> None:
        provider = FileScratchpadProvider(
            base_dir=self._store_with_one_bad_entry(tmp_path)
        )

        entry = await provider.read("good")

        assert entry is not None and not isinstance(entry, list)
        assert entry.content == "readable note"

    def test_damaged_entry_is_written_aside(self, tmp_path: Path) -> None:
        base = self._store_with_one_bad_entry(tmp_path)

        FileScratchpadProvider(base_dir=base)

        quarantined = list(base.glob("scratchpad.json.damaged-*"))
        assert quarantined, "unreadable entry was dropped with no copy kept"
        assert "broken" in json.loads(quarantined[0].read_text(encoding="utf-8"))

    def test_damage_is_logged_at_error_level(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        base = self._store_with_one_bad_entry(tmp_path)

        with caplog.at_level(
            logging.ERROR, logger="swarmline.scratchpad.file_provider"
        ):
            FileScratchpadProvider(base_dir=base)

        assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
            "silent data loss — nothing logged"
        )

    async def test_next_write_does_not_resurrect_the_damaged_entry(
        self, tmp_path: Path
    ) -> None:
        base = self._store_with_one_bad_entry(tmp_path)
        provider = FileScratchpadProvider(base_dir=base)

        await provider.write("fresh", "new note")

        persisted = json.loads((base / "scratchpad.json").read_text(encoding="utf-8"))
        assert set(persisted) == {"good", "fresh"}
