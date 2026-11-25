"""Tests for EditSnapshotCoordinator (B1 fix) + hook registration.

The Pre hook must snapshot the `before` content BEFORE the edit mutates the
file (Post alone can't see `before`). Registration is one hook-entry per exact
edit/write tool name because `fnmatch` has no `|` alternation (NEW-ISSUE-1),
and is only wired when `config.enable_post_edit_verify` is True.
"""

from __future__ import annotations

import json

import pytest
from swarmline.hooks.dispatcher import DefaultHookDispatcher, HookResult
from swarmline.hooks.registry import HookRegistry
from swarmline.orchestration.lint_delta import BaselineSubtractionLinter
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.runtime.thin.edit_verify_coordinator import (
    EditSnapshotCoordinator,
    register_edit_verify_hooks,
)
from swarmline.runtime.thin.reflection import ReflectionState


class FakeSandbox:
    """In-memory SandboxProvider stub — mutable file map drives the before/after."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files: dict[str, str] = dict(files or {})

    async def read_file(self, path: str) -> str:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def write_file(self, path: str, content: str) -> None:
        self.files[path] = content

    async def execute(self, command: str):  # pragma: no cover - unused here
        raise NotImplementedError

    async def list_dir(self, path: str = "."):  # pragma: no cover - unused here
        return []

    async def glob_files(self, pattern: str):  # pragma: no cover - unused here
        return []


def _delta_linter_from(
    lint_map: dict[str, tuple[str, ...]],
) -> BaselineSubtractionLinter:
    async def lint(content: str) -> tuple[str, ...]:
        return lint_map.get(content, ())

    return BaselineSubtractionLinter(lint)


class TestPreSnapshot:
    @pytest.mark.asyncio
    async def test_pre_snapshot_before_mutation(self) -> None:
        """on_pre_tool captures `before` BEFORE the edit mutates the file."""
        sandbox = FakeSandbox({"a.py": "ORIGINAL"})
        linter = _delta_linter_from({})
        coord = EditSnapshotCoordinator(sandbox, delta_linter=linter)

        # Pre: snapshot ORIGINAL.
        pre = await coord.on_pre_tool(tool_name="edit", tool_input={"path": "a.py"})
        assert isinstance(pre, HookResult)
        assert pre.action == "allow"

        # Now the (simulated) edit mutates the file.
        sandbox.files["a.py"] = "MUTATED"

        # The snapshot retained ORIGINAL, not the post-state MUTATED.
        assert coord.snapshot_for("a.py") == "ORIGINAL"

    @pytest.mark.asyncio
    async def test_pre_snapshot_missing_file_baseline_empty(self) -> None:
        """A path that does not exist yet → empty baseline, never raises/blocks."""
        sandbox = FakeSandbox({})
        coord = EditSnapshotCoordinator(sandbox, delta_linter=_delta_linter_from({}))

        pre = await coord.on_pre_tool(
            tool_name="write", tool_input={"path": "new.py", "content": "x"}
        )

        assert pre.action == "allow"
        assert coord.snapshot_for("new.py") == ""

    @pytest.mark.asyncio
    async def test_pre_snapshot_multi_file_edit_all_paths(self) -> None:
        sandbox = FakeSandbox({"a.py": "A", "b.py": "B"})
        coord = EditSnapshotCoordinator(sandbox, delta_linter=_delta_linter_from({}))

        await coord.on_pre_tool(
            tool_name="multi_file_edit",
            tool_input={"edits": [{"path": "a.py"}, {"path": "b.py"}]},
        )

        assert coord.snapshot_for("a.py") == "A"
        assert coord.snapshot_for("b.py") == "B"

    @pytest.mark.asyncio
    async def test_pre_snapshot_never_blocks_on_read_error(self) -> None:
        """Pre is fail-open: a sandbox read explosion still yields allow."""

        class ExplodingSandbox(FakeSandbox):
            async def read_file(self, path: str) -> str:
                raise RuntimeError("boom")

        coord = EditSnapshotCoordinator(
            ExplodingSandbox({}), delta_linter=_delta_linter_from({})
        )
        pre = await coord.on_pre_tool(tool_name="edit", tool_input={"path": "a.py"})
        assert pre.action == "allow"


class TestPostDelta:
    @pytest.mark.asyncio
    async def test_post_no_snapshot_returns_none(self) -> None:
        """Post for a non-edit / unsnapshotted tool returns None (no change)."""
        coord = EditSnapshotCoordinator(
            FakeSandbox({}), delta_linter=_delta_linter_from({})
        )
        out = await coord.on_post_tool(
            tool_name="edit", tool_input={"path": "a.py"}, tool_output="ok"
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_post_invalidates_snapshot_after_render(self) -> None:
        sandbox = FakeSandbox({"a.py": "BEFORE"})
        linter = _delta_linter_from({"BEFORE": (), "AFTER": ("a.py:1: E_NEW bad",)})
        coord = EditSnapshotCoordinator(sandbox, delta_linter=linter)

        await coord.on_pre_tool(tool_name="edit", tool_input={"path": "a.py"})
        sandbox.files["a.py"] = "AFTER"

        first = await coord.on_post_tool(
            tool_name="edit", tool_input={"path": "a.py"}, tool_output="ok"
        )
        assert first is not None
        # Snapshot consumed: a second post (no fresh pre) is a no-op.
        assert coord.snapshot_for("a.py") is None
        second = await coord.on_post_tool(
            tool_name="edit", tool_input={"path": "a.py"}, tool_output="ok"
        )
        assert second is None

    @pytest.mark.asyncio
    async def test_post_clean_edit_returns_none(self) -> None:
        """An edit that introduces no new lint error leaves output unchanged."""
        sandbox = FakeSandbox({"a.py": "BEFORE"})
        coord = EditSnapshotCoordinator(sandbox, delta_linter=_delta_linter_from({}))
        await coord.on_pre_tool(tool_name="edit", tool_input={"path": "a.py"})
        sandbox.files["a.py"] = "AFTER"
        out = await coord.on_post_tool(
            tool_name="edit", tool_input={"path": "a.py"}, tool_output="ok"
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_post_failopen_on_linter_error(self) -> None:
        """A linter that raises must not break the loop (fail-open → None)."""

        class ExplodingLinter:
            async def diff(self, path: str, before: str, after: str):
                raise RuntimeError("lint boom")

        sandbox = FakeSandbox({"a.py": "BEFORE"})
        coord = EditSnapshotCoordinator(sandbox, delta_linter=ExplodingLinter())
        await coord.on_pre_tool(tool_name="edit", tool_input={"path": "a.py"})
        sandbox.files["a.py"] = "AFTER"
        out = await coord.on_post_tool(
            tool_name="edit", tool_input={"path": "a.py"}, tool_output="ok"
        )
        assert out is None


class TestRegistration:
    def test_register_per_tool_name_no_alternation(self) -> None:
        """One hook-entry per exact edit/write tool name (fnmatch has no `|`)."""
        registry = HookRegistry()
        config = CodingProfileConfig(enable_post_edit_verify=True)
        coord = EditSnapshotCoordinator(
            FakeSandbox({}), delta_linter=_delta_linter_from({})
        )

        register_edit_verify_hooks(registry, coord, config)

        pre_matchers = {e.matcher for e in registry.get_hooks("PreToolUse")}
        post_matchers = {e.matcher for e in registry.get_hooks("PostToolUse")}
        assert pre_matchers == {"edit", "write", "multi_edit", "multi_file_edit"}
        assert post_matchers == {"edit", "write", "multi_edit", "multi_file_edit"}
        # No alternation token leaked into any matcher.
        assert all("|" not in m for m in pre_matchers | post_matchers)

    def test_not_registered_when_flag_off(self) -> None:
        """Default OFF ⇒ no coordinator hooks registered."""
        registry = HookRegistry()
        config = CodingProfileConfig()  # enable_post_edit_verify=False default
        coord = EditSnapshotCoordinator(
            FakeSandbox({}), delta_linter=_delta_linter_from({})
        )

        register_edit_verify_hooks(registry, coord, config)

        assert registry.get_hooks("PreToolUse") == []
        assert registry.get_hooks("PostToolUse") == []

    @pytest.mark.asyncio
    async def test_registered_hooks_dispatch_through_dispatcher(self) -> None:
        """End-to-end via DefaultHookDispatcher: edit matches, read does not."""
        registry = HookRegistry()
        sandbox = FakeSandbox({"a.py": "BEFORE"})
        linter = _delta_linter_from({"BEFORE": (), "AFTER": ("a.py:1: E_NEW bad",)})
        coord = EditSnapshotCoordinator(sandbox, delta_linter=linter)
        register_edit_verify_hooks(
            registry, coord, CodingProfileConfig(enable_post_edit_verify=True)
        )
        dispatcher = DefaultHookDispatcher(registry)

        # A non-edit tool name must not match any coordinator hook.
        pre_read = await dispatcher.dispatch_pre_tool("read", {"path": "a.py"})
        assert pre_read.action == "allow"
        assert coord.snapshot_for("a.py") is None  # read did not snapshot

        pre_edit = await dispatcher.dispatch_pre_tool("edit", {"path": "a.py"})
        assert pre_edit.action == "allow"
        assert coord.snapshot_for("a.py") == "BEFORE"


class TestEditPreThenPostDeltaOnlyNew:
    @pytest.mark.asyncio
    async def test_edit_pre_then_post_delta_only_new(self) -> None:
        """Integration: edit introduces a NEW lint error → delta carries ONLY it,
        not the pre-existing error already present in `before`."""
        registry = HookRegistry()
        sandbox = FakeSandbox({"a.py": "BEFORE"})
        # before-content "BEFORE" already has E_OLD; after-content "AFTER" keeps
        # E_OLD and adds E_NEW. Only E_NEW must surface.
        linter = _delta_linter_from(
            {
                "BEFORE": ("a.py:1: E_OLD preexisting",),
                "AFTER": (
                    "a.py:1: E_OLD preexisting",
                    "a.py:9: E_NEW introduced",
                ),
            }
        )
        coord = EditSnapshotCoordinator(sandbox, delta_linter=linter)
        register_edit_verify_hooks(
            registry, coord, CodingProfileConfig(enable_post_edit_verify=True)
        )
        dispatcher = DefaultHookDispatcher(registry)

        await dispatcher.dispatch_pre_tool("edit", {"path": "a.py"})
        sandbox.files["a.py"] = "AFTER"  # the edit happens

        augmented = await dispatcher.dispatch_post_tool(
            "edit", {"path": "a.py"}, json.dumps({"status": "ok"})
        )

        assert augmented is not None
        assert "E_NEW introduced" in augmented
        assert "E_OLD preexisting" not in augmented


class TestPostHookComposition:
    @pytest.mark.asyncio
    async def test_edit_verify_composes_onto_user_post_modifier(self) -> None:
        """A pre-existing PostToolUse modifier + edit-verify COMPOSE, not clobber.

        The dispatcher chains post-hook output (mirrors PreToolUse), so the
        edit-verify block is appended onto the user hook's already-modified
        output instead of overwriting it (regression for last-wins clobber).
        """
        sandbox = FakeSandbox({"a.py": "BEFORE"})
        linter = _delta_linter_from(
            {"BEFORE": (), "AFTER": ("a.py:9: E_NEW introduced",)}
        )
        coord = EditSnapshotCoordinator(sandbox, delta_linter=linter)

        registry = HookRegistry()

        # User Post modifier registered FIRST → edit-verify is appended AFTER it,
        # so a last-wins dispatcher would drop this uppercasing. Chaining keeps it.
        async def _uppercase(*, tool_name: str, tool_input: dict, tool_output: str):
            return tool_output.upper()

        registry.on_post_tool_use(_uppercase, matcher="edit")
        register_edit_verify_hooks(
            registry, coord, CodingProfileConfig(enable_post_edit_verify=True)
        )
        dispatcher = DefaultHookDispatcher(registry)

        await dispatcher.dispatch_pre_tool("edit", {"path": "a.py"})
        sandbox.files["a.py"] = "AFTER"  # the edit happens

        result = await dispatcher.dispatch_post_tool(
            "edit", {"path": "a.py"}, "raw out"
        )

        assert result is not None
        assert result.startswith("RAW OUT")  # user modification preserved
        assert "E_NEW introduced" in result  # edit-verify block composed on top


class TestBoundedReflection:
    """Task 5 — ReflectionState bounds how long verify-failure feedback is fed.

    A Post-hook cannot halt the agent loop (NEW-ISSUE-2): it only rewrites
    tool_output. So the budget governs only WHETHER failure feedback keeps being
    appended. At the cap the coordinator swaps the failure block for a single
    TERMINAL note so the model finalizes instead of being goaded into more edits.
    """

    @staticmethod
    def _failing_coord(reflection: ReflectionState) -> EditSnapshotCoordinator:
        """A coordinator whose every edit introduces the same NEW lint error."""
        sandbox = FakeSandbox({"a.py": "BEFORE"})
        linter = _delta_linter_from(
            {"BEFORE": (), "AFTER": ("a.py:9: E_NEW introduced",)}
        )
        return EditSnapshotCoordinator(
            sandbox, delta_linter=linter, reflection=reflection
        )

    @staticmethod
    async def _one_failing_post(coord: EditSnapshotCoordinator) -> str | None:
        """Run one Pre→edit→Post cycle that introduces a new lint error.

        Resets the file to the clean "BEFORE" baseline first so every cycle is a
        genuine *new* introduction (before clean → after broken), not a persisting
        pre-existing error.
        """
        coord._sandbox.files["a.py"] = "BEFORE"  # clean baseline
        await coord.on_pre_tool(tool_name="edit", tool_input={"path": "a.py"})
        coord._sandbox.files["a.py"] = "AFTER"  # the edit introduces E_NEW
        return await coord.on_post_tool(
            tool_name="edit", tool_input={"path": "a.py"}, tool_output="ok"
        )

    @pytest.mark.asyncio
    async def test_reflection_bounded_stops_feedback(self) -> None:
        """After N=max_reflections failing posts, the (N+1)th swaps the failure
        block for the TERMINAL note (no more failure-feedback)."""
        reflection = ReflectionState(max_reflections=2)
        coord = self._failing_coord(reflection)

        # First N posts: failure feedback appended, counter increments.
        for _ in range(2):
            out = await self._one_failing_post(coord)
            assert out is not None
            assert "E_NEW introduced" in out  # failure feedback present
            assert "budget exhausted" not in out
        assert reflection.count == 2  # at cap now

        # (N+1)th post: terminal note, NOT another failure block.
        terminal = await self._one_failing_post(coord)
        assert terminal is not None
        assert "E_NEW introduced" not in terminal  # failure feedback gone
        assert "budget exhausted" in terminal  # terminal note present
        # Does not keep incrementing past the cap into more reflections.
        assert reflection.should_reflect() is False

    @pytest.mark.asyncio
    async def test_reflection_reset_on_success(self) -> None:
        """A clean (success) post resets the counter so a later failure reflects."""
        reflection = ReflectionState(max_reflections=1)
        sandbox = FakeSandbox({"a.py": "BEFORE"})
        # "AFTER" introduces an error; "CLEAN" introduces none.
        linter = _delta_linter_from(
            {
                "BEFORE": (),
                "AFTER": ("a.py:9: E_NEW introduced",),
                "CLEAN": (),
            }
        )
        coord = EditSnapshotCoordinator(
            sandbox, delta_linter=linter, reflection=reflection
        )

        # 1st failing post consumes the only reflection.
        first = await self._one_failing_post(coord)
        assert first is not None and "E_NEW introduced" in first
        assert reflection.count == 1
        assert reflection.should_reflect() is False

        # A clean post resets the budget.
        await coord.on_pre_tool(tool_name="edit", tool_input={"path": "a.py"})
        sandbox.files["a.py"] = "CLEAN"
        clean = await coord.on_post_tool(
            tool_name="edit", tool_input={"path": "a.py"}, tool_output="ok"
        )
        assert clean is None  # nothing to surface — byte-identical to T4
        assert reflection.count == 0  # reset_on_success fired

        # A later failure reflects again (feedback, not terminal note).
        again = await self._one_failing_post(coord)
        assert again is not None
        assert "E_NEW introduced" in again
        assert "budget exhausted" not in again

    @pytest.mark.asyncio
    async def test_no_snapshot_post_does_not_reset_budget(self) -> None:
        """A post with no fresh Pre snapshot is a no-op — it must NOT reset the
        budget, else a stale post bypasses the cap (cap-bypass regression)."""
        reflection = ReflectionState(max_reflections=1)
        coord = self._failing_coord(reflection)

        # Reach the cap with one real failing post (snapshot consumed afterwards).
        await self._one_failing_post(coord)
        assert reflection.count == 1
        assert reflection.should_reflect() is False

        # A Post WITHOUT a preceding Pre snapshot → no-op (None), count UNCHANGED.
        noop = await coord.on_post_tool(
            tool_name="edit", tool_input={"path": "a.py"}, tool_output="ok"
        )
        assert noop is None
        assert reflection.count == 1  # budget NOT reset by a no-op post
        assert reflection.should_reflect() is False

    @pytest.mark.asyncio
    async def test_coordinator_never_halts_returns_str_or_none(self) -> None:
        """The coordinator only ever returns str|None — it never raises/blocks."""
        reflection = ReflectionState(max_reflections=0)  # exhausted from the start
        coord = self._failing_coord(reflection)

        # Even at zero budget the first failing post must not raise.
        out = await self._one_failing_post(coord)
        assert out is None or isinstance(out, str)
        assert out is not None
        assert "budget exhausted" in out  # terminal immediately at cap 0

    @pytest.mark.asyncio
    async def test_reflection_failopen_on_linter_error_returns_none(self) -> None:
        """A linter explosion with reflection wired still fails open (→ None)."""

        class ExplodingLinter:
            async def diff(self, path: str, before: str, after: str):
                raise RuntimeError("lint boom")

        sandbox = FakeSandbox({"a.py": "BEFORE"})
        reflection = ReflectionState(max_reflections=3)
        coord = EditSnapshotCoordinator(
            sandbox, delta_linter=ExplodingLinter(), reflection=reflection
        )
        await coord.on_pre_tool(tool_name="edit", tool_input={"path": "a.py"})
        sandbox.files["a.py"] = "AFTER"
        out = await coord.on_post_tool(
            tool_name="edit", tool_input={"path": "a.py"}, tool_output="ok"
        )
        assert out is None
        assert reflection.count == 0  # no failure recorded on fail-open
