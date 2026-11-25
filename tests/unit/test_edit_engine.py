"""Tests for Task 1 — tolerant edit-format engine.

REQ-SCA-001, REQ-SCA-002, REQ-SCA-003, REQ-SCA-004.
TDD phase: tests written first, implementation follows.

Naming convention: test_<what>_<condition>_<result>.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest

from swarmline.tools.sandbox_local import LocalSandboxProvider
from swarmline.tools.types import SandboxConfig


@pytest.fixture()
def big_sandbox(tmp_path: Any) -> LocalSandboxProvider:
    """LocalSandboxProvider with a generous file-size limit for edit tests."""
    config = SandboxConfig(
        root_path=str(tmp_path),
        user_id="test",
        topic_id="edit",
        max_file_size_bytes=1024 * 1024,
        timeout_seconds=5,
        allow_host_execution=True,
    )
    return LocalSandboxProvider(config)


# ---------------------------------------------------------------------------
# REQ-SCA-001 — tolerant fuzzy cascade
# ---------------------------------------------------------------------------


class TestTolerantFuzzyCascade:
    async def test_edit_tolerant_matches_whitespace_drift(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """An old_string differing only in whitespace/indentation still matches.

        File content is indented with 4 spaces; the model sends old_string with
        2-space indentation. The whitespace/indent-flexible cascade must match.
        """
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        original = "def f():\n    x = 1\n    return x\n"
        await big_sandbox.write_file("m.py", original)

        _, executors = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )

        # old_string uses 2-space indent — drifted from the on-disk 4-space.
        result = await executors["edit"](
            {
                "path": "m.py",
                "old_string": "  x = 1\n  return x",
                "new_string": "    x = 2\n    return x",
            }
        )
        data = json.loads(result)
        assert data["status"] == "ok"
        content = await big_sandbox.read_file("m.py")
        assert "x = 2" in content
        assert "x = 1" not in content

    async def test_edit_tolerant_exact_match_records_strategy(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """An exact match still works and reports match_strategy == 'exact'."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        await big_sandbox.write_file("a.py", "alpha = 1\nbeta = 2\n")
        _, executors = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )

        result = await executors["edit"](
            {"path": "a.py", "old_string": "alpha = 1", "new_string": "alpha = 9"}
        )
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "exact" in json.dumps(data)


# ---------------------------------------------------------------------------
# REQ-SCA-002 — structured failure
# ---------------------------------------------------------------------------


class TestStructuredFailure:
    async def test_edit_tolerant_not_found_detail(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """A genuine miss yields a structured not_found failure with detail text."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        await big_sandbox.write_file("b.txt", "hello world\n")
        _, executors = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )

        result = await executors["edit"](
            {"path": "b.txt", "old_string": "nonexistent anchor", "new_string": "x"}
        )
        data = json.loads(result)
        assert data["status"] == "error"
        # Machine-actionable structured failure, not a bare bool.
        assert data["failure"] == "not_found"
        assert isinstance(data["detail"], str)
        assert data["detail"]  # non-empty actionable hint
        # File unchanged.
        assert await big_sandbox.read_file("b.txt") == "hello world\n"

    async def test_edit_tolerant_matched_n_times(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """An ambiguous old_string matching multiple times fails with matched_n_times."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        await big_sandbox.write_file("c.txt", "dup\ndup\ndup\n")
        _, executors = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )

        result = await executors["edit"](
            {"path": "c.txt", "old_string": "dup", "new_string": "x"}
        )
        data = json.loads(result)
        assert data["status"] == "error"
        assert data["failure"] == "matched_n_times"
        # Detail must be machine-actionable and mention the count + remedy.
        assert "3" in data["detail"]
        assert "anchor" in data["detail"].lower()
        # Nothing persisted on an ambiguous match.
        assert await big_sandbox.read_file("c.txt") == "dup\ndup\ndup\n"


# ---------------------------------------------------------------------------
# REQ-SCA-003 — transactional multi_file_edit
# ---------------------------------------------------------------------------


class TestMultiFileEditTransactional:
    async def test_multi_file_edit_all_or_nothing(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """3 files, 1 failing hunk ⇒ ALL files unchanged on disk (transactional)."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        await big_sandbox.write_file("f1.txt", "one\n")
        await big_sandbox.write_file("f2.txt", "two\n")
        await big_sandbox.write_file("f3.txt", "three\n")

        _, executors = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )

        result = await executors["multi_file_edit"](
            {
                "edits": [
                    {"path": "f1.txt", "old_string": "one", "new_string": "ONE"},
                    {"path": "f2.txt", "old_string": "two", "new_string": "TWO"},
                    # This hunk cannot match → whole transaction must roll back.
                    {
                        "path": "f3.txt",
                        "old_string": "MISSING",
                        "new_string": "X",
                    },
                ]
            }
        )
        data = json.loads(result)
        assert data["status"] == "error"
        assert data["applied"] is False
        # NOTHING persisted.
        assert await big_sandbox.read_file("f1.txt") == "one\n"
        assert await big_sandbox.read_file("f2.txt") == "two\n"
        assert await big_sandbox.read_file("f3.txt") == "three\n"

    async def test_multi_file_edit_full_success_writes_all(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """When every hunk validates, all files are written."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        await big_sandbox.write_file("g1.txt", "one\n")
        await big_sandbox.write_file("g2.txt", "two\n")

        _, executors = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="patch")
        )

        result = await executors["multi_file_edit"](
            {
                "edits": [
                    {"path": "g1.txt", "old_string": "one", "new_string": "ONE"},
                    {"path": "g2.txt", "old_string": "two", "new_string": "TWO"},
                ]
            }
        )
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["applied"] is True
        assert await big_sandbox.read_file("g1.txt") == "ONE\n"
        assert await big_sandbox.read_file("g2.txt") == "TWO\n"


# ---------------------------------------------------------------------------
# REQ-SCA-004 — path normalization before lock
# ---------------------------------------------------------------------------


class TestPathLock:
    async def test_path_normalize_before_lock(self) -> None:
        """`a/../b` and `b` resolve to the same lock key — same underlying lock object."""
        from swarmline.tools.edit.strategy import AsyncPathLock

        lock = AsyncPathLock()
        key_a = os.path.realpath("a/../b")
        key_b = os.path.realpath("b")
        assert key_a == key_b

        # Acquiring the same realpath twice (sequentially) must use one lock.
        async with lock.acquire_all((key_a,)):
            pass
        async with lock.acquire_all((key_b,)):
            pass
        # Internal registry deduplicates by realpath key.
        assert lock.lock_count == 1

    async def test_path_lock_serializes_overlapping_acquire(self) -> None:
        """Two coroutines acquiring the same path do not interleave their bodies."""
        from swarmline.tools.edit.strategy import AsyncPathLock

        lock = AsyncPathLock()
        key = os.path.realpath("shared")
        order: list[str] = []

        async def worker(tag: str) -> None:
            async with lock.acquire_all((key,)):
                order.append(f"{tag}-enter")
                await asyncio.sleep(0.01)
                order.append(f"{tag}-exit")

        await asyncio.gather(worker("a"), worker("b"))
        # Each enter must be immediately followed by its own exit (no interleave).
        assert order[0].endswith("-enter")
        assert order[1].endswith("-exit")
        assert order[0][0] == order[1][0]
        assert order[2][0] == order[3][0]

    async def test_path_lock_sorted_order_no_deadlock(self) -> None:
        """Overlapping multi-path acquisitions in sorted order do not deadlock."""
        from swarmline.tools.edit.strategy import AsyncPathLock

        lock = AsyncPathLock()
        p1 = os.path.realpath("p1")
        p2 = os.path.realpath("p2")

        async def edit_both() -> None:
            async with lock.acquire_all(tuple(sorted((p1, p2)))):
                await asyncio.sleep(0.005)

        # If locks weren't sorted, opposite acquisition orders could deadlock.
        await asyncio.wait_for(asyncio.gather(edit_both(), edit_both()), timeout=2.0)


# ---------------------------------------------------------------------------
# REQ-SCA-001/003 — legacy path byte-identical + opt-in wiring
# ---------------------------------------------------------------------------


class TestLegacyUnchanged:
    async def test_legacy_edit_unchanged(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """With edit_strategy='legacy'/config=None, edit is first-occurrence exact."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        for cfg in (None, CodingProfileConfig()):  # None and legacy default
            await big_sandbox.write_file("d.py", "x = 1\nx = 1\n")
            _, executors = create_sandbox_tools(big_sandbox, config=cfg)

            # First-occurrence-only exact replace.
            result = await executors["edit"](
                {"path": "d.py", "old_string": "x = 1", "new_string": "y = 2"}
            )
            data = json.loads(result)
            assert data["status"] == "ok"
            assert set(data.keys()) == {"status", "path"}  # legacy shape
            content = await big_sandbox.read_file("d.py")
            assert content == "y = 2\nx = 1\n"  # only first occurrence changed

    async def test_legacy_edit_not_found_errors(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """Legacy edit errors (no fuzzy) when old_string is absent."""
        from swarmline.tools.builtin import create_sandbox_tools

        await big_sandbox.write_file("e.txt", "hello")
        _, executors = create_sandbox_tools(big_sandbox, config=None)
        result = await executors["edit"](
            {"path": "e.txt", "old_string": "missing", "new_string": "x"}
        )
        data = json.loads(result)
        assert data["status"] == "error"
        # Legacy message shape, no structured failure field.
        assert "failure" not in data

    async def test_multi_edit_schema_unchanged(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """multi_edit spec and behaviour identical across legacy / non-legacy config."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        specs_legacy, exec_legacy = create_sandbox_tools(big_sandbox, config=None)
        specs_sr, exec_sr = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )

        # Spec must be byte-identical across modes.
        ml = specs_legacy["multi_edit"]
        ms = specs_sr["multi_edit"]
        assert ml.name == ms.name
        assert ml.description == ms.description
        assert ml.parameters == ms.parameters

        # Behaviour: first-occurrence single-file array, unchanged in both modes.
        await big_sandbox.write_file("m.py", "a = 1\nb = 2\nc = 3\n")
        result = await exec_sr["multi_edit"](
            {
                "path": "m.py",
                "edits": [
                    {"old_string": "a = 1", "new_string": "a = 10"},
                    {"old_string": "c = 3", "new_string": "c = 30"},
                ],
            }
        )
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["edits_applied"] == 2
        content = await big_sandbox.read_file("m.py")
        assert content == "a = 10\nb = 2\nc = 30\n"

    def test_multi_file_edit_in_pack_only_when_enabled(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """multi_file_edit present in toolpack iff edit_strategy != 'legacy'."""
        from swarmline.runtime.thin.coding_toolpack import build_coding_toolpack
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        # Legacy / None — absent.
        assert (
            "multi_file_edit"
            not in build_coding_toolpack(big_sandbox, config=None).tool_names
        )
        assert (
            "multi_file_edit"
            not in build_coding_toolpack(
                big_sandbox, config=CodingProfileConfig()
            ).tool_names
        )
        assert (
            "multi_file_edit"
            not in build_coding_toolpack(
                big_sandbox, config=CodingProfileConfig(edit_strategy="legacy")
            ).tool_names
        )

        # Non-legacy — present.
        for strategy in ("search_replace", "patch", "auto"):
            pack = build_coding_toolpack(
                big_sandbox,
                config=CodingProfileConfig(edit_strategy=strategy),  # type: ignore[arg-type]
            )
            assert "multi_file_edit" in pack.tool_names
            assert "multi_file_edit" in pack.executors

    def test_multi_file_edit_executor_present_in_sandbox_tools_when_enabled(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """create_sandbox_tools exposes multi_file_edit only for non-legacy strategies."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        specs_legacy, exec_legacy = create_sandbox_tools(big_sandbox, config=None)
        assert "multi_file_edit" not in specs_legacy
        assert "multi_file_edit" not in exec_legacy

        specs_sr, exec_sr = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )
        assert "multi_file_edit" in specs_sr
        assert "multi_file_edit" in exec_sr


# ---------------------------------------------------------------------------
# Domain VO + outcome invariants
# ---------------------------------------------------------------------------


class TestEditOutcomeInvariants:
    async def test_search_replace_single_file_partial_applied(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """SearchReplaceStrategy.apply (non-transactional) persists matching hunks.

        single_file invariant: applied ⟺ any persisted.
        """
        from swarmline.tools.edit.strategy import Hunk, SearchReplaceStrategy

        await big_sandbox.write_file("s.txt", "keep alpha here\n")
        strat = SearchReplaceStrategy()
        outcome = await strat.apply(
            (
                Hunk(path="s.txt", old="alpha", new="ALPHA"),
                Hunk(path="s.txt", old="ZZZ-missing", new="X"),
            ),
            big_sandbox,
            transactional=False,
        )
        assert outcome.mode == "single_file"
        assert outcome.applied is True  # at least one persisted
        statuses = {r.status for r in outcome.results}
        assert "persisted" in statuses
        assert "failed" in statuses
        assert "ALPHA" in await big_sandbox.read_file("s.txt")

    async def test_v4a_transactional_nothing_persisted_on_failure(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """V4APatchStrategy: on any failure, no hunk is persisted (validated→failed)."""
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy

        await big_sandbox.write_file("t1.txt", "one\n")
        await big_sandbox.write_file("t2.txt", "two\n")
        strat = V4APatchStrategy()
        outcome = await strat.apply(
            (
                Hunk(path="t1.txt", old="one", new="ONE"),
                Hunk(path="t2.txt", old="MISSING", new="X"),
            ),
            big_sandbox,
            transactional=True,
        )
        assert outcome.mode == "transactional_multi_file"
        assert outcome.applied is False
        # No file mutated.
        assert await big_sandbox.read_file("t1.txt") == "one\n"
        assert await big_sandbox.read_file("t2.txt") == "two\n"
        # No result reports 'persisted'.
        assert all(r.status != "persisted" for r in outcome.results)


# ---------------------------------------------------------------------------
# F4 — path aliasing within a transaction shares one snapshot
# ---------------------------------------------------------------------------


class TestPathAliasing:
    async def test_multi_file_edit_path_aliases_share_one_snapshot(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """Two hunks on `b.txt` and `./b.txt` address the same file and must
        compose sequentially against ONE evolving snapshot — not two independent
        ones that clobber each other (F4 fix: canonical transaction key).

        Expected: on-disk file contains BOTH edits (second sees first's change),
        no lost update.
        """
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy

        await big_sandbox.write_file("b.txt", "alpha beta gamma\n")
        strat = V4APatchStrategy()

        # Hunk 1 targets "b.txt" (bare path).
        # Hunk 2 targets "./b.txt" (dot-prefixed — same realpath).
        outcome = await strat.apply(
            (
                Hunk(path="b.txt", old="alpha", new="ALPHA"),
                Hunk(path="./b.txt", old="beta", new="BETA"),
            ),
            big_sandbox,
            transactional=True,
        )

        assert outcome.applied is True, f"Expected success, got: {outcome.message}"
        content = await big_sandbox.read_file("b.txt")
        assert "ALPHA" in content
        assert "BETA" in content
        # Original tokens replaced.
        assert "alpha" not in content
        assert "beta" not in content

    async def test_multi_file_edit_aliases_count_as_one_file(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """Aliased paths all get their originals stored under the same canonical key,
        so rollback restores the single file if a subsequent hunk fails.
        """
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy

        await big_sandbox.write_file("x.txt", "one two three\n")
        strat = V4APatchStrategy()

        # First two hunks on aliased paths succeed; third fails → rollback.
        outcome = await strat.apply(
            (
                Hunk(path="x.txt", old="one", new="ONE"),
                Hunk(path="./x.txt", old="two", new="TWO"),
                Hunk(path="x.txt", old="MISSING", new="X"),
            ),
            big_sandbox,
            transactional=True,
        )

        assert outcome.applied is False
        # File must be unchanged (rolled back to original).
        assert await big_sandbox.read_file("x.txt") == "one two three\n"


# ---------------------------------------------------------------------------
# F1 — write-phase rollback on IO failure (BLOCKER)
# ---------------------------------------------------------------------------


class TestTransactionalWriteRollback:
    async def test_multi_file_edit_rolls_back_on_write_failure(
        self, tmp_path: Any
    ) -> None:
        """V4APatchStrategy restores the first file when the second write raises.

        Scenario: sandbox whose write_file raises on the SECOND application call
        but allows restoration writes (to simulate a per-file permission error,
        not a full disk failure).
        Expected: first file restored to its original content; applied is False.
        """
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy
        from swarmline.tools.types import SandboxConfig
        from swarmline.tools.sandbox_local import LocalSandboxProvider

        # Real sandbox for reads and restore writes.
        cfg = SandboxConfig(
            root_path=str(tmp_path),
            user_id="test",
            topic_id="edit_rb",
            max_file_size_bytes=1024 * 1024,
            timeout_seconds=5,
            allow_host_execution=False,
        )
        real = LocalSandboxProvider(cfg)
        await real.write_file("r1.txt", "original_one\n")
        await real.write_file("r2.txt", "original_two\n")

        # Track write calls: first application write goes through; second application
        # write (different content) fails; restore writes (same-as-original) go through.
        application_write_count = 0

        class FailSecondApplicationWrite:
            """Raises on the 2nd application write; allows restore writes."""

            async def read_file(self, path: str) -> str:
                return await real.read_file(path)

            async def write_file(self, path: str, content: str) -> None:
                nonlocal application_write_count
                # Restore writes carry the original content — allow them.
                is_restore = content in ("original_one\n", "original_two\n")
                if not is_restore:
                    application_write_count += 1
                    if application_write_count >= 2:
                        raise OSError(f"simulated write failure for {path!r}")
                await real.write_file(path, content)

            async def execute(self, command: str):  # type: ignore[return]
                raise NotImplementedError

            async def list_dir(self, path: str = ".") -> list[str]:  # type: ignore[return]
                raise NotImplementedError

            async def glob_files(self, pattern: str) -> list[str]:  # type: ignore[return]
                raise NotImplementedError

        sandbox = FailSecondApplicationWrite()
        strat = V4APatchStrategy()
        outcome = await strat.apply(
            (
                Hunk(path="r1.txt", old="original_one", new="REPLACED_ONE"),
                Hunk(path="r2.txt", old="original_two", new="REPLACED_TWO"),
            ),
            sandbox,  # type: ignore[arg-type]
            transactional=True,
        )

        assert outcome.applied is False
        # First file must be restored (rollback via best-effort restore).
        assert await real.read_file("r1.txt") == "original_one\n"
        # Second file was never written (write raised before any content was set).
        assert await real.read_file("r2.txt") == "original_two\n"

    async def test_multi_file_edit_rollback_failure_surfaces_unrestored_path(
        self, tmp_path: Any
    ) -> None:
        """When both the application write AND the restore write fail, the outcome
        must surface a `rollback_failed` result naming the still-modified path —
        not claim "nothing written" (F1-residual fix).
        """
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy
        from swarmline.tools.types import SandboxConfig
        from swarmline.tools.sandbox_local import LocalSandboxProvider

        cfg = SandboxConfig(
            root_path=str(tmp_path),
            user_id="test",
            topic_id="edit_rf",
            max_file_size_bytes=1024 * 1024,
            timeout_seconds=5,
            allow_host_execution=False,
        )
        real = LocalSandboxProvider(cfg)
        await real.write_file("p1.txt", "original_p1\n")
        await real.write_file("p2.txt", "original_p2\n")

        # First application write (p1.txt) succeeds; second (p2.txt) raises;
        # restore of p1.txt also raises → p1.txt stays MODIFIED on disk.
        write_ops: list[str] = []

        class FailAllAfterFirst:
            """Passes only the very first write; all subsequent writes raise."""

            async def read_file(self, path: str) -> str:
                return await real.read_file(path)

            async def write_file(self, path: str, content: str) -> None:
                write_ops.append(path)
                if len(write_ops) == 1:
                    await real.write_file(path, content)
                else:
                    raise OSError(f"disk full on call {len(write_ops)} for {path}")

            async def execute(self, command: str):  # type: ignore[return]
                raise NotImplementedError

            async def list_dir(self, path: str = ".") -> list[str]:  # type: ignore[return]
                raise NotImplementedError

            async def glob_files(self, pattern: str) -> list[str]:  # type: ignore[return]
                raise NotImplementedError

        sandbox = FailAllAfterFirst()
        strat = V4APatchStrategy()
        outcome = await strat.apply(
            (
                Hunk(path="p1.txt", old="original_p1", new="CHANGED_P1"),
                Hunk(path="p2.txt", old="original_p2", new="CHANGED_P2"),
            ),
            sandbox,  # type: ignore[arg-type]
            transactional=True,
        )

        assert outcome.applied is False
        # At least one result must be `rollback_failed` naming p1.txt.
        rf_results = [r for r in outcome.results if r.failure == "rollback_failed"]
        assert rf_results, (
            f"Expected rollback_failed result; got: {[r.failure for r in outcome.results]}"
        )
        assert any("p1.txt" in r.detail for r in rf_results)
        assert any("manual recovery" in r.detail.lower() for r in rf_results)
        # The outcome message must not claim "nothing written".
        assert (
            "nothing written" not in outcome.message.lower()
            or "p1.txt" in outcome.message
        )

    async def test_write_error_rollback_round_trip_verifies_restore(self) -> None:
        """The write-error rollback path must ROUND-TRIP-VERIFY each restore.

        A silently-corrupting provider — one whose restore write raises NO exception
        but persists wrong bytes — must NOT be reported as a clean rollback. The
        write-error path routes through ``_rollback_writes`` (REQ-SCA-061), so the
        corrupted restore of w1 is read back, found mismatched, and surfaced as a
        LOUD ``rollback_failed`` (regression for the cycle-4 data_integrity finding:
        the path previously used a raw ``write_file`` with no read-back).
        """
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy

        storage: dict[str, str] = {"w1.txt": "orig_one\n", "w2.txt": "orig_two\n"}
        originals = {"orig_one\n", "orig_two\n"}

        class CorruptRestoreSandbox:
            """1st application write persists; 2nd raises (→ write_error rollback);
            restore writes SUCCEED but silently corrupt (no raise, wrong bytes)."""

            def __init__(self) -> None:
                self._app_writes = 0

            async def read_file(self, path: str) -> str:
                return storage[path]

            async def write_file(self, path: str, content: str) -> None:
                if content in originals:  # restore write → corrupt silently
                    storage[path] = content + "CORRUPTED_RESTORE\n"
                    return
                self._app_writes += 1
                if self._app_writes >= 2:
                    raise OSError(f"simulated write failure for {path!r}")
                storage[path] = content

            async def execute(self, command: str):  # type: ignore[return]
                raise NotImplementedError

            async def list_dir(self, path: str = ".") -> list[str]:  # type: ignore[return]
                raise NotImplementedError

            async def glob_files(self, pattern: str) -> list[str]:  # type: ignore[return]
                raise NotImplementedError

        outcome = await V4APatchStrategy().apply(
            (
                Hunk(path="w1.txt", old="orig_one", new="NEW_ONE"),
                Hunk(path="w2.txt", old="orig_two", new="NEW_TWO"),
            ),
            CorruptRestoreSandbox(),  # type: ignore[arg-type]
            transactional=True,
        )

        assert outcome.applied is False
        rf = [r for r in outcome.results if r.failure == "rollback_failed"]
        assert rf, (
            "corrupted restore on the write-error path must surface rollback_failed, "
            f"got: {[r.failure for r in outcome.results]}"
        )
        assert any("w1.txt" in r.detail for r in rf)
        assert any("manual recovery" in r.detail.lower() for r in rf)


# ---------------------------------------------------------------------------
# F2 — block_anchor interior-line tightening
# ---------------------------------------------------------------------------


class TestBlockAnchorInterior:
    async def test_block_anchor_rejects_mismatched_interior(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """block_anchor must NOT match when interior lines differ.

        Same first and last line, but the middle line is different.
        The cascade must NOT silently replace the wrong block.
        """
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        file_content = "START\nactual_middle_line\nEND\n"
        await big_sandbox.write_file("ba.py", file_content)

        _, executors = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )

        # old_string has same first/last line but a DIFFERENT middle.
        result = await executors["edit"](
            {
                "path": "ba.py",
                "old_string": "START\nSTALE_middle_line\nEND",
                "new_string": "START\nnew_line\nEND",
            }
        )
        data = json.loads(result)
        # Must fail — not a silent wrong replacement.
        assert data["status"] == "error"
        assert data["failure"] in ("not_found", "ambiguous")
        # File unchanged.
        assert await big_sandbox.read_file("ba.py") == file_content

    async def test_block_anchor_matches_when_interior_equivalent(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """block_anchor still matches when interior is whitespace-equivalent."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        # 4-space-indented block.
        file_content = "    START\n    middle = 1\n    END\n"
        await big_sandbox.write_file("ba2.py", file_content)

        _, executors = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )

        # old_string uses 2-space indent — whitespace drift, but same content.
        result = await executors["edit"](
            {
                "path": "ba2.py",
                "old_string": "  START\n  middle = 1\n  END",
                "new_string": "    START\n    middle = 2\n    END",
            }
        )
        data = json.loads(result)
        assert data["status"] == "ok"
        content = await big_sandbox.read_file("ba2.py")
        assert "middle = 2" in content


# ---------------------------------------------------------------------------
# F3 — shared strategy/lock across concurrent executor calls
# ---------------------------------------------------------------------------


class TestConcurrentMultiFileEditSerializes:
    def test_multi_file_edit_executor_shares_single_strategy_instance(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """The multi_file_edit executor captures one shared V4APatchStrategy (with
        its AsyncPathLock) constructed once in the factory closure — not a fresh
        one per invocation (F3 fix).

        Verified by inspecting the executor's closure for the strategy instance and
        confirming the same object is reused across two calls (same id).
        """
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig
        from swarmline.tools.edit.strategy import V4APatchStrategy

        _, executors = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )
        executor = executors["multi_file_edit"]

        # The executor is a closure; its free variables include _strategy.
        cell_contents = [
            c.cell_contents
            for c in executor.__closure__  # type: ignore[union-attr]
            if isinstance(c.cell_contents, V4APatchStrategy)
        ]
        assert len(cell_contents) == 1, (
            "Expected exactly one V4APatchStrategy in the executor closure"
        )
        strategy_instance = cell_contents[0]

        # Calling the factory again produces a DIFFERENT strategy (sanity check
        # that we are not comparing two separate factories' strategies).
        _, executors2 = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )
        executor2 = executors2["multi_file_edit"]
        cell_contents2 = [
            c.cell_contents
            for c in executor2.__closure__  # type: ignore[union-attr]
            if isinstance(c.cell_contents, V4APatchStrategy)
        ]
        assert len(cell_contents2) == 1
        other_strategy = cell_contents2[0]
        # Different factory call → different instance.
        assert strategy_instance is not other_strategy

        # But within a single factory call, the strategy in the closure
        # is the ONE shared instance — same object identity.
        assert id(strategy_instance) == id(cell_contents[0])

    async def test_multi_file_edit_concurrent_calls_serialize_via_lock(
        self, big_sandbox: LocalSandboxProvider
    ) -> None:
        """Two concurrent multi_file_edit calls on the same path serialize:
        the second call queues up and sees the first call's final state.

        No barriers needed — we launch both and then observe that the final
        on-disk content is one of the two expected values (not a corrupt mix),
        and exactly one call succeeds while the other either succeeds or sees
        a not_found failure on stale content.
        """
        import json
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        await big_sandbox.write_file("serial.txt", "start\n")

        _, executors = create_sandbox_tools(
            big_sandbox, config=CodingProfileConfig(edit_strategy="search_replace")
        )

        # Both calls target the same path with the same old_string but different
        # new_string values. The lock ensures they run sequentially: the first to
        # acquire replaces "start" → "middle"; the second either replaces "middle"
        # → "end" (if it uses the updated content) or fails (if it reads "start"
        # but "start" is already gone). Either outcome proves no interleave.
        async def writer_a() -> str:
            return await executors["multi_file_edit"](
                {
                    "edits": [
                        {
                            "path": "serial.txt",
                            "old_string": "start",
                            "new_string": "middle",
                        }
                    ]
                }
            )

        async def writer_b() -> str:
            return await executors["multi_file_edit"](
                {
                    "edits": [
                        {
                            "path": "serial.txt",
                            "old_string": "start",
                            "new_string": "also_middle",
                        }
                    ]
                }
            )

        results = await asyncio.gather(writer_a(), writer_b(), return_exceptions=True)
        datas = [json.loads(r) for r in results if isinstance(r, str)]

        # Exactly ONE must succeed (the one that acquired the lock first and found
        # "start"). The other will fail with not_found because "start" was already
        # replaced by the first writer.
        successes = [d for d in datas if d.get("status") == "ok"]
        failures = [d for d in datas if d.get("status") == "error"]
        assert len(successes) == 1, f"Expected exactly 1 success, got: {datas}"
        assert len(failures) == 1
        assert failures[0]["failure"] == "not_found"

        # Final content is consistent — one writer won.
        final = await big_sandbox.read_file("serial.txt")
        assert final in ("middle\n", "also_middle\n")


# ---------------------------------------------------------------------------
# F4-deep — sandbox-alias conflict detected loudly (not silent lost update)
# ---------------------------------------------------------------------------


class TestSandboxAliasConflict:
    async def test_multi_file_edit_sandbox_alias_conflict_fails_loudly(
        self, tmp_path: Any
    ) -> None:
        """Two hunks on names that resolve to different realpath keys but map to the
        SAME backing buffer (sandbox-internal alias, e.g. workspace symlink) must NOT
        silently produce a lost-update.  The write-phase stale guard must detect the
        alias mid-transaction, roll back, and return applied=False with an
        alias_conflict failure kind.

        The backing file's final content must equal the original (clean rollback), NOT
        a corrupt mix where one hunk's replacement clobbered the other's.
        """
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy

        # In-memory aliasing sandbox: 'target.txt' and 'link.txt' share one buffer.
        # os.path.realpath treats them as DIFFERENT keys (different strings, no host
        # symlink registered) — which is exactly the case F4-deep addresses.
        storage: dict[str, str] = {"target.txt": "alpha beta gamma\n"}
        # 'link.txt' is an alias — reads/writes go to the same storage slot.
        ALIAS = "link.txt"
        PRIMARY = "target.txt"

        class AliasSandbox:
            async def read_file(self, path: str) -> str:
                # Both names read from the shared buffer.
                return storage[PRIMARY]

            async def write_file(self, path: str, content: str) -> None:
                storage[PRIMARY] = content

            async def execute(self, command: str):  # type: ignore[return]
                raise NotImplementedError

            async def list_dir(self, path: str = ".") -> list[str]:  # type: ignore[return]
                raise NotImplementedError

            async def glob_files(self, pattern: str) -> list[str]:  # type: ignore[return]
                raise NotImplementedError

        sandbox = AliasSandbox()
        strat = V4APatchStrategy()

        outcome = await strat.apply(
            (
                Hunk(path=PRIMARY, old="alpha", new="ALPHA"),
                Hunk(path=ALIAS, old="beta", new="BETA"),
            ),
            sandbox,  # type: ignore[arg-type]
            transactional=True,
        )

        # Must NOT silently produce "alpha BETA" (lost-update).
        assert outcome.applied is False, (
            f"Expected applied=False; backing content: {storage[PRIMARY]!r}"
        )
        # At least one result must carry the alias_conflict failure kind.
        conflict_results = [r for r in outcome.results if r.failure == "alias_conflict"]
        assert conflict_results, (
            f"Expected alias_conflict result; got failures: "
            f"{[r.failure for r in outcome.results]}"
        )
        # The detail must name the conflict path and suggest the remedy.
        conflict_detail = conflict_results[0].detail
        assert (
            "alias" in conflict_detail.lower() or "conflict" in conflict_detail.lower()
        )
        assert (
            "retry" in conflict_detail.lower() or "separate" in conflict_detail.lower()
        )
        # Backing file must be rolled back to original.
        assert storage[PRIMARY] == "alpha beta gamma\n", (
            f"Backing file not rolled back; content: {storage[PRIMARY]!r}"
        )

    async def test_alias_conflict_rollback_round_trip_verifies_restore(self) -> None:
        """The alias-conflict rollback path must ROUND-TRIP-VERIFY each restore.

        Same corruption scenario as the write-error case, but reached through the
        alias-conflict branch: a provider whose restore write silently corrupts must
        be flagged ``rollback_failed``, not trusted as a clean rollback. The path now
        routes through ``_rollback_writes`` (REQ-SCA-061) — regression for the
        cycle-4 data_integrity finding (it previously used a raw ``write_file``).
        """
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy

        orig = "alpha beta gamma\n"

        class CorruptRestoreAliasSandbox:
            """target.txt/link.txt share one buffer (alias). The rollback restore
            write SUCCEEDS but silently corrupts — no exception, wrong bytes."""

            def __init__(self) -> None:
                self.buf = orig

            async def read_file(self, path: str) -> str:
                return self.buf

            async def write_file(self, path: str, content: str) -> None:
                if content == orig:  # restore write → corrupt silently
                    self.buf = content + "CORRUPTED\n"
                else:
                    self.buf = content

            async def execute(self, command: str):  # type: ignore[return]
                raise NotImplementedError

            async def list_dir(self, path: str = ".") -> list[str]:  # type: ignore[return]
                raise NotImplementedError

            async def glob_files(self, pattern: str) -> list[str]:  # type: ignore[return]
                raise NotImplementedError

        outcome = await V4APatchStrategy().apply(
            (
                Hunk(path="target.txt", old="alpha", new="ALPHA"),
                Hunk(path="link.txt", old="beta", new="BETA"),
            ),
            CorruptRestoreAliasSandbox(),  # type: ignore[arg-type]
            transactional=True,
        )

        assert outcome.applied is False
        rf = [r for r in outcome.results if r.failure == "rollback_failed"]
        assert rf, (
            "corrupted restore on the alias-conflict path must surface "
            f"rollback_failed, got: {[r.failure for r in outcome.results]}"
        )
        assert any("manual recovery" in r.detail.lower() for r in rf)

    async def test_multi_file_edit_guard_reread_failure_aborts_loudly(
        self, tmp_path: Any
    ) -> None:
        """When the guard re-read raises during Pass 2, the transaction must ABORT
        (not proceed with the write), existing writes must be rolled back, and
        applied must be False — not the silent `alpha BETA` lost-update.

        Scenario: Pass-1 reads succeed; first alias write succeeds; guard re-read
        of the SECOND path raises. The guard must treat the exception as "cannot
        verify — abort" and route into the alias-conflict rollback path.
        """
        from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy

        storage: dict[str, str] = {"target.txt": "alpha beta gamma\n"}
        PRIMARY = "target.txt"
        ALIAS = "link.txt"

        reads: list[str] = []
        writes: list[str] = []

        class GuardRereadFailsSandbox:
            """Pass-1 reads succeed; guard re-reads (second read of ALIAS) raise."""

            async def read_file(self, path: str) -> str:
                reads.append(path)
                # Pass-1 reads: both paths needed.  Guard re-reads happen in Pass 2
                # AFTER the first write (target.txt).  The guard re-reads ALIAS
                # before attempting to write it — that is the call we want to fail.
                # Allow the first two reads (Pass-1 dry-run), fail the third+.
                if len(reads) <= 2:
                    return storage[PRIMARY]
                raise OSError(f"simulated guard re-read failure for {path!r}")

            async def write_file(self, path: str, content: str) -> None:
                writes.append(path)
                storage[PRIMARY] = content

            async def execute(self, command: str):  # type: ignore[return]
                raise NotImplementedError

            async def list_dir(self, path: str = ".") -> list[str]:  # type: ignore[return]
                raise NotImplementedError

            async def glob_files(self, pattern: str) -> list[str]:  # type: ignore[return]
                raise NotImplementedError

        sandbox = GuardRereadFailsSandbox()
        strat = V4APatchStrategy()

        outcome = await strat.apply(
            (
                Hunk(path=PRIMARY, old="alpha", new="ALPHA"),
                Hunk(path=ALIAS, old="beta", new="BETA"),
            ),
            sandbox,  # type: ignore[arg-type]
            transactional=True,
        )

        # Must abort: applied=False, NOT "alpha BETA".
        assert outcome.applied is False, (
            f"Expected applied=False; backing content: {storage[PRIMARY]!r}"
        )
        # The outcome must surface the abort — alias_conflict or a clear abort reason.
        abort_results = [
            r
            for r in outcome.results
            if r.failure in ("alias_conflict", "not_found", "rollback_failed")
            and r.failure is not None
            and (
                "alias" in (r.detail or "").lower()
                or "conflict" in (r.detail or "").lower()
                or "verify" in (r.detail or "").lower()
                or "abort" in (r.detail or "").lower()
                or "read failed" in (r.detail or "").lower()
            )
        ]
        assert abort_results, (
            f"Expected an abort/alias/conflict result; failures: "
            f"{[(r.failure, r.detail) for r in outcome.results]}"
        )
        # Backing file must not contain the BETA replacement (no silent write).
        assert "BETA" not in storage[PRIMARY], (
            f"BETA was written despite guard re-read failure; content: {storage[PRIMARY]!r}"
        )
        # Rollback: if target.txt was written (ALPHA), it must be restored to original.
        assert storage[PRIMARY] == "alpha beta gamma\n", (
            f"Backing file not rolled back; content: {storage[PRIMARY]!r}"
        )
