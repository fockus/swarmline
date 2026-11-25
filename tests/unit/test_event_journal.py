"""Contract + implementation-specific tests for the event journal.

Covers REQ-001..REQ-006:
- REQ-001/002: EventJournal.append / last_seq with monotonic sequence numbers,
  each entry carrying a parseable ISO-8601 timestamp.
- REQ-003: concurrent append keeps seq monotonic (no dup, no gap).
- REQ-004: ReplayReader.read(since, until) with inclusive bounds.
- REQ-005: replay-to-seq returns exact prefixes.
- REQ-006: read() is read-only -- callers cannot mutate journal state through
  a returned JournalEntry.

The contract set below is parametrized over both concrete implementations
(InMemoryEventJournal, JsonlEventJournal) so any correct implementation of the
EventJournal/ReplayReader protocols must satisfy it.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

import pytest

from swarmline.observability.journal import (
    EventJournal,
    InMemoryEventJournal,
    ReplayReader,
)
from swarmline.observability.jsonl_journal import JsonlEventJournal


def _make_in_memory(tmp_path: Path) -> EventJournal:
    return InMemoryEventJournal()


def _make_jsonl(tmp_path: Path) -> EventJournal:
    return JsonlEventJournal(tmp_path / "journal.jsonl")


class _JournalFactory(Protocol):
    def __call__(self, tmp_path: Path) -> EventJournal: ...


JOURNAL_FACTORIES: list[_JournalFactory] = [_make_in_memory, _make_jsonl]


@pytest.fixture(params=JOURNAL_FACTORIES, ids=["in_memory", "jsonl"])
def journal(request: pytest.FixtureRequest, tmp_path: Path) -> EventJournal:
    factory: _JournalFactory = request.param
    return factory(tmp_path)


class TestEventJournalContract:
    """Shared contract -- both implementations must satisfy every test here."""

    async def test_append_assigns_monotonic_sequential_seq(
        self, journal: EventJournal
    ) -> None:
        seq1 = await journal.append("evt", {"i": 1})
        seq2 = await journal.append("evt", {"i": 2})
        seq3 = await journal.append("evt", {"i": 3})

        assert (seq1, seq2, seq3) == (1, 2, 3)
        assert await journal.last_seq() == 3

    async def test_append_concurrent_gather_keeps_seq_monotonic_no_dup_no_gap(
        self, journal: EventJournal
    ) -> None:
        n = 25

        seqs = await asyncio.gather(
            *[journal.append("evt", {"i": i}) for i in range(n)]
        )

        assert sorted(seqs) == list(range(1, n + 1))
        assert await journal.last_seq() == n

    async def test_read_since_until_inclusive_bounds_correct_order(
        self, journal: EventJournal
    ) -> None:
        for i in range(5):
            await journal.append("evt", {"i": i})

        entries = [entry async for entry in journal.read(since=2, until=4)]

        assert [entry.seq for entry in entries] == [2, 3, 4]
        assert [entry.data["i"] for entry in entries] == [1, 2, 3]

    async def test_read_until_none_is_open_ended(self, journal: EventJournal) -> None:
        for i in range(4):
            await journal.append("evt", {"i": i})

        entries = [entry async for entry in journal.read(since=3)]

        assert [entry.seq for entry in entries] == [3, 4]

    async def test_read_empty_range_returns_empty(self, journal: EventJournal) -> None:
        for i in range(3):
            await journal.append("evt", {"i": i})

        entries = [entry async for entry in journal.read(since=10, until=20)]

        assert entries == []

    async def test_read_on_empty_journal_returns_empty(
        self, journal: EventJournal
    ) -> None:
        entries = [entry async for entry in journal.read()]

        assert entries == []

    async def test_schema_version_present_in_every_entry(
        self, journal: EventJournal
    ) -> None:
        await journal.append("evt", {"i": 1})
        await journal.append("evt", {"i": 2})

        entries = [entry async for entry in journal.read()]

        assert len(entries) == 2
        assert all(entry.schema_version == 1 for entry in entries)

    async def test_replay_entries_have_valid_iso8601_timestamp(
        self, journal: EventJournal
    ) -> None:
        """REQ-001: every replayed entry carries a non-empty, parseable ISO-8601 timestamp."""
        await journal.append("evt", {"i": 1})
        await journal.append("evt", {"i": 2})

        entries = [entry async for entry in journal.read()]

        assert len(entries) == 2
        for entry in entries:
            assert entry.timestamp
            parsed = datetime.fromisoformat(entry.timestamp)
            assert parsed is not None

    async def test_replay_up_to_seq_returns_exact_prefix(
        self, journal: EventJournal
    ) -> None:
        """REQ-005 scenario 1: read(until=k) returns exactly the first k events."""
        n = 6
        k = 4
        for i in range(n):
            await journal.append("evt", {"i": i})

        entries = [entry async for entry in journal.read(until=k)]

        assert [entry.seq for entry in entries] == list(range(1, k + 1))
        assert [entry.data["i"] for entry in entries] == list(range(k))

    async def test_replay_read_twice_yields_identical_entries(
        self, journal: EventJournal
    ) -> None:
        await journal.append("evt", {"i": 1, "nested": {"a": 1}})
        await journal.append("evt", {"i": 2, "nested": {"b": 2}})

        first = [entry async for entry in journal.read()]
        second = [entry async for entry in journal.read()]

        assert first == second

    async def test_replay_mutating_returned_entry_data_does_not_leak(
        self, journal: EventJournal
    ) -> None:
        """REQ-006: read() must not hand out a reference to internal state."""
        await journal.append("evt", {"i": 1, "nested": {"a": 1}})

        first = [entry async for entry in journal.read()][0]
        first.data["i"] = "mutated"
        first.data["nested"]["a"] = "mutated"
        first.data["new_key"] = "should not leak"

        second = [entry async for entry in journal.read()][0]

        assert second.data["i"] == 1
        assert second.data["nested"]["a"] == 1
        assert "new_key" not in second.data


class TestProtocolCompliance:
    def test_in_memory_implements_event_journal_and_replay_reader(self) -> None:
        instance = InMemoryEventJournal()

        assert isinstance(instance, EventJournal)
        assert isinstance(instance, ReplayReader)

    def test_jsonl_implements_event_journal_and_replay_reader(
        self, tmp_path: Path
    ) -> None:
        instance = JsonlEventJournal(tmp_path / "journal.jsonl")

        assert isinstance(instance, EventJournal)
        assert isinstance(instance, ReplayReader)


class TestJsonlEventJournalDurability:
    """JSONL-only: durable seq recovery across process restart (ADR)."""

    async def test_reopen_continues_seq_from_max_plus_one(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.jsonl"
        first = JsonlEventJournal(path)
        await first.append("evt", {"i": 1})
        await first.append("evt", {"i": 2})

        second = JsonlEventJournal(path)
        seq = await second.append("evt", {"i": 3})

        assert seq == 3
        assert await second.last_seq() == 3
        entries = [entry async for entry in second.read()]
        assert [entry.seq for entry in entries] == [1, 2, 3]

    async def test_reopen_with_corrupt_last_line_recovers_max_valid_seq(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "journal.jsonl"
        first = JsonlEventJournal(path)
        await first.append("evt", {"i": 1})
        await first.append("evt", {"i": 2})

        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"seq": 3, "corrupt json...\n')

        second = JsonlEventJournal(path)
        seq = await second.append("evt", {"i": "recovered"})

        assert seq == 3
        assert await second.last_seq() == 3

    async def test_reopen_truncates_unterminated_tail_and_continues_cleanly(
        self, tmp_path: Path
    ) -> None:
        """Fix 1: a partial write (no trailing newline) from a crash mid-append
        must be truncated on reopen so appends never concatenate onto a
        dangling line. Every line in the file must remain individually
        parseable JSON after recovery + a new append.
        """
        path = tmp_path / "journal.jsonl"
        first = JsonlEventJournal(path)
        await first.append("evt", {"i": 1})
        await first.append("evt", {"i": 2})

        # Simulate a crash mid-append: a partial JSON line with NO trailing
        # newline (as opposed to test_reopen_with_corrupt_last_line_recovers_
        # max_valid_seq above, which has a terminated-but-malformed line).
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                '{"seq": 3, "schema_version": 1, '
                '"timestamp": "2026-01-01T00:00:00+00:00", "event_typ'
            )

        second = JsonlEventJournal(path)
        seq = await second.append("evt", {"i": "recovered"})

        assert seq == 3
        assert await second.last_seq() == 3

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # every remaining line must be valid, parseable JSON

        entries = [entry async for entry in second.read()]
        assert [entry.seq for entry in entries] == [1, 2, 3]
        assert [entry.data.get("i") for entry in entries] == [1, 2, "recovered"]

    async def test_reopen_with_torn_utf8_tail_does_not_raise_and_recovers(
        self, tmp_path: Path
    ) -> None:
        """Byte-level fix: a crash mid-append can leave an incomplete
        multi-byte UTF-8 sequence at EOF (appends use ensure_ascii=False).
        Recovery must truncate at the BYTE level *before* any decode, so
        construction never raises UnicodeDecodeError -- text-decoding first
        would defeat the durability ADR by crashing on reopen instead of
        recovering.
        """
        path = tmp_path / "journal.jsonl"
        first = JsonlEventJournal(path)
        await first.append("evt", {"i": 1, "label": "café"})
        await first.append("evt", {"i": 2, "label": "日本"})

        # Simulate a crash mid-append: a raw partial line containing a
        # *truncated* multi-byte UTF-8 sequence (the 3-byte encoding of
        # "日" U+65E5 cut off after 2 bytes), with NO trailing newline.
        torn_fragment = (
            b'{"seq": 3, "schema_version": 1, "timestamp": '
            b'"2026-01-01T00:00:00+00:00", "event_type": "evt", '
            b'"data": {"label": "\xe6\x97'
        )
        with path.open("ab") as handle:
            handle.write(torn_fragment)

        # Sanity check: this fixture must reproduce a genuine torn UTF-8
        # tail -- decoding the raw bytes as-is has to fail.
        with pytest.raises(UnicodeDecodeError):
            path.read_bytes().decode("utf-8")

        second = JsonlEventJournal(path)  # must NOT raise UnicodeDecodeError
        seq = await second.append("evt", {"i": "recovered"})

        assert seq == 3
        assert await second.last_seq() == 3

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # every remaining line must be valid, parseable JSON

        entries = [entry async for entry in second.read()]
        assert [entry.seq for entry in entries] == [1, 2, 3]
        assert [entry.data.get("i") for entry in entries] == [1, 2, "recovered"]

    async def test_empty_or_absent_file_starts_seq_at_one(self, tmp_path: Path) -> None:
        path = tmp_path / "does_not_exist.jsonl"
        journal = JsonlEventJournal(path)

        seq = await journal.append("evt", {"i": 1})

        assert seq == 1

    async def test_append_redacts_sensitive_keys(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.jsonl"
        journal = JsonlEventJournal(path)

        await journal.append("evt", {"api_key": "sk-secret", "safe": "value"})

        entries = [entry async for entry in journal.read()]
        assert entries[0].data["api_key"] == "[REDACTED]"
        assert entries[0].data["safe"] == "value"
