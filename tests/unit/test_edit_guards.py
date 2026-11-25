"""Tests for anti-flailing edit guards + provenance (Task 6, REQ-SCA-050/051/052).

Covers:
- PostEditGuardHook escalates a hint after N consecutive same-path failures.
- PreEditGuardHook refuses (HookResult.block) once the hard-cap is reached —
  BEFORE the mutation runs (M3: a refusal cannot live in PostToolUse).
- A successful edit resets the consecutive-failure counter for that path.
- Reading a file written by THIS agent gets a [provenance] trust-label.
- Excessive summary/doc writes raise a churn_flag hint.
- Fail-open: unparseable tool_output / missing tracker never raise, never annotate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from swarmline.hooks.dispatcher import HookResult
from swarmline.runtime.thin.edit_guards import (
    EditGuardState,
    PostEditGuardHook,
    PreEditGuardHook,
    ProvenancePostHook,
)
from swarmline.workspace.types import FileOperationType, MutationRecord


def _failure_output(path: str) -> str:
    """Serialize a failed EditOutcome JSON exactly as the edit executors do."""
    return json.dumps(
        {
            "status": "error",
            "applied": False,
            "mode": "single_file",
            "message": "no hunks applied",
            "path": path,
            "results": [
                {
                    "path": path,
                    "status": "failed",
                    "failure": "not_found",
                    "detail": "old_string not found",
                    "match_strategy": None,
                }
            ],
            "failure": "not_found",
            "detail": "old_string not found",
        }
    )


def _success_output(path: str) -> str:
    """Serialize an applied EditOutcome JSON exactly as the edit executors do."""
    return json.dumps(
        {
            "status": "ok",
            "applied": True,
            "mode": "single_file",
            "message": "1 applied",
            "path": path,
            "results": [
                {
                    "path": path,
                    "status": "persisted",
                    "failure": None,
                    "detail": "applied",
                    "match_strategy": "exact",
                }
            ],
        }
    )


class _StubTracker:
    """Minimal OwnChangesTrackerPort stub holding pre-seeded mutations."""

    def __init__(self, mutations: dict[str, list[MutationRecord]]) -> None:
        self._mutations = mutations

    def record_mutation(self, session_id: str, record: MutationRecord) -> None:
        self._mutations.setdefault(session_id, []).append(record)

    def get_mutations(self, session_id: str) -> list[MutationRecord]:
        return list(self._mutations.get(session_id, []))

    def is_own_commit(self, session_id: str, commit_hash: str) -> bool:
        return False

    def record_commit(self, session_id: str, commit_hash: str) -> None:
        return None


def _mutation(path: str) -> MutationRecord:
    return MutationRecord(
        file_path=path,
        operation=FileOperationType.MODIFY,
        before_hash=None,
        after_hash=None,
        timestamp=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# PostEditGuardHook — escalation on consecutive failures
# ---------------------------------------------------------------------------


class TestPostEditGuardEscalation:
    async def test_nth_consecutive_failure_appends_escalation_hint(self) -> None:
        """At escalate_threshold consecutive failures the post hook appends a hint."""
        state = EditGuardState.with_defaults()
        post = PostEditGuardHook(state)
        path = "src/foo.py"

        out_1 = await post(
            tool_name="edit",
            tool_input={"path": path},
            tool_output=_failure_output(path),
        )
        out_2 = await post(
            tool_name="edit",
            tool_input={"path": path},
            tool_output=_failure_output(path),
        )
        # Below threshold (escalate_threshold default 3): no hint yet.
        assert out_1 is None
        assert out_2 is None

        out_3 = await post(
            tool_name="edit",
            tool_input={"path": path},
            tool_output=_failure_output(path),
        )
        assert out_3 is not None
        assert path in out_3
        assert "3 times" in out_3
        assert state.consecutive_failures[path] == 3

    async def test_failures_on_different_paths_do_not_aggregate(self) -> None:
        """Consecutive-failure counters are per-path, not global."""
        state = EditGuardState.with_defaults()
        post = PostEditGuardHook(state)

        for _ in range(2):
            await post(
                tool_name="edit",
                tool_input={"path": "a.py"},
                tool_output=_failure_output("a.py"),
            )
        out = await post(
            tool_name="edit",
            tool_input={"path": "b.py"},
            tool_output=_failure_output("b.py"),
        )
        assert out is None
        assert state.consecutive_failures["a.py"] == 2
        assert state.consecutive_failures["b.py"] == 1


class TestPostEditGuardSuccessResets:
    async def test_success_resets_consecutive_failures_for_path(self) -> None:
        """A successful edit zeroes the consecutive-failure counter for that path."""
        state = EditGuardState.with_defaults()
        post = PostEditGuardHook(state)
        path = "src/bar.py"

        await post(
            tool_name="edit",
            tool_input={"path": path},
            tool_output=_failure_output(path),
        )
        await post(
            tool_name="edit",
            tool_input={"path": path},
            tool_output=_failure_output(path),
        )
        assert state.consecutive_failures[path] == 2

        await post(
            tool_name="edit",
            tool_input={"path": path},
            tool_output=_success_output(path),
        )
        assert state.consecutive_failures[path] == 0
        # edits_per_path keeps counting every applied/attempted edit.
        assert state.edits_per_path[path] == 3


# ---------------------------------------------------------------------------
# PreEditGuardHook — hard-cap refusal BEFORE mutation
# ---------------------------------------------------------------------------


class TestPreEditGuardHardCap:
    async def test_blocks_when_hard_cap_reached(self) -> None:
        """At hard_cap consecutive failures, Pre hook blocks BEFORE the mutation."""
        state = EditGuardState.with_defaults()
        path = "src/loop.py"
        state.consecutive_failures[path] = state.hard_cap

        pre = PreEditGuardHook(state)
        result = await pre(tool_name="edit", tool_input={"path": path})

        assert isinstance(result, HookResult)
        assert result.action == "block"
        assert result.message is not None
        assert path in result.message

    async def test_allows_below_hard_cap(self) -> None:
        """Below the hard-cap, the Pre hook allows the edit."""
        state = EditGuardState.with_defaults()
        path = "src/ok.py"
        state.consecutive_failures[path] = state.hard_cap - 1

        pre = PreEditGuardHook(state)
        result = await pre(tool_name="edit", tool_input={"path": path})

        assert result.action == "allow"

    async def test_multi_file_edit_blocks_when_any_path_capped(self) -> None:
        """A multi_file_edit is blocked if ANY of its target paths is capped."""
        state = EditGuardState.with_defaults()
        state.consecutive_failures["b.py"] = state.hard_cap

        pre = PreEditGuardHook(state)
        result = await pre(
            tool_name="multi_file_edit",
            tool_input={"edits": [{"path": "a.py"}, {"path": "b.py"}]},
        )
        assert result.action == "block"
        assert "b.py" in (result.message or "")

    async def test_non_edit_tool_always_allowed(self) -> None:
        """A non-edit tool name is never blocked by the Pre guard."""
        state = EditGuardState.with_defaults()
        state.consecutive_failures["x.py"] = state.hard_cap

        pre = PreEditGuardHook(state)
        result = await pre(tool_name="read", tool_input={"path": "x.py"})
        assert result.action == "allow"


class TestPreThenPostHardCapFlow:
    async def test_post_drives_failures_then_pre_refuses(self) -> None:
        """End-to-end: Post accumulates failures, Pre refuses once hard_cap hit."""
        state = EditGuardState.with_defaults()
        post = PostEditGuardHook(state)
        pre = PreEditGuardHook(state)
        path = "src/stubborn.py"

        for _ in range(state.hard_cap):
            allow = await pre(tool_name="edit", tool_input={"path": path})
            assert allow.action == "allow"
            await post(
                tool_name="edit",
                tool_input={"path": path},
                tool_output=_failure_output(path),
            )

        # The (hard_cap + 1)-th attempt is refused BEFORE mutating anything.
        blocked = await pre(tool_name="edit", tool_input={"path": path})
        assert blocked.action == "block"


# ---------------------------------------------------------------------------
# Churn flag — summary/doc write spam
# ---------------------------------------------------------------------------


class TestChurnFlag:
    async def test_excess_summary_writes_appends_churn_hint(self) -> None:
        """Past churn_threshold doc/summary writes, a churn_flag hint is appended."""
        state = EditGuardState.with_defaults()
        post = PostEditGuardHook(state)

        last_out: str | None = None
        for i in range(state.churn_threshold):
            path = f"notes/summary_{i}.md"
            last_out = await post(
                tool_name="write",
                tool_input={"path": path},
                tool_output=_success_output(path),
            )

        assert state.summary_doc_writes == state.churn_threshold
        assert last_out is not None
        assert "summary/doc" in last_out

    async def test_code_writes_do_not_count_as_doc_churn(self) -> None:
        """Writing .py source files never increments summary_doc_writes."""
        state = EditGuardState.with_defaults()
        post = PostEditGuardHook(state)

        for i in range(state.churn_threshold + 2):
            path = f"src/module_{i}.py"
            await post(
                tool_name="write",
                tool_input={"path": path},
                tool_output=_success_output(path),
            )
        assert state.summary_doc_writes == 0


# ---------------------------------------------------------------------------
# Provenance trust-label (REQ-SCA-051)
# ---------------------------------------------------------------------------


class TestProvenancePostHook:
    async def test_reading_own_written_file_gets_provenance_label(self) -> None:
        """Reading a file in get_mutations gets a [provenance] trust-label."""
        path = "src/generated.py"
        tracker = _StubTracker({"sess-1": [_mutation(path)]})
        hook = ProvenancePostHook(tracker=tracker, session_id="sess-1")

        out = await hook(
            tool_name="read", tool_input={"path": path}, tool_output="file contents"
        )
        assert out is not None
        assert "[provenance]" in out
        assert path in out
        assert "file contents" in out

    async def test_reading_unwritten_file_gets_no_label(self) -> None:
        """A file NOT in get_mutations is read without any provenance annotation."""
        tracker = _StubTracker({"sess-1": [_mutation("src/written.py")]})
        hook = ProvenancePostHook(tracker=tracker, session_id="sess-1")

        out = await hook(
            tool_name="read",
            tool_input={"path": "src/other.py"},
            tool_output="contents",
        )
        assert out is None

    async def test_bash_command_referencing_own_file_gets_label(self) -> None:
        """A bash command that names an own-written path is annotated."""
        path = "src/built.py"
        tracker = _StubTracker({"sess-1": [_mutation(path)]})
        hook = ProvenancePostHook(tracker=tracker, session_id="sess-1")

        out = await hook(
            tool_name="bash",
            tool_input={"command": f"cat {path}"},
            tool_output="line1\nline2",
        )
        assert out is not None
        assert "[provenance]" in out
        assert path in out

    async def test_bash_basename_substring_does_not_false_positive(self) -> None:
        """Own 'a.py' must NOT label a command that only touches 'data.py'."""
        tracker = _StubTracker({"sess-1": [_mutation("a.py")]})
        hook = ProvenancePostHook(tracker=tracker, session_id="sess-1")

        out = await hook(
            tool_name="bash",
            tool_input={"command": "cat data.py"},
            tool_output="x",
        )
        assert out is None

    async def test_bash_path_prefixed_token_still_matches(self) -> None:
        """A command naming './a.py' still labels own 'a.py' (path-suffix token)."""
        tracker = _StubTracker({"sess-1": [_mutation("a.py")]})
        hook = ProvenancePostHook(tracker=tracker, session_id="sess-1")

        out = await hook(
            tool_name="bash",
            tool_input={"command": "python ./a.py"},
            tool_output="x",
        )
        assert out is not None
        assert "[provenance]" in out

    async def test_missing_session_yields_no_label(self) -> None:
        """No session id → fail-open, no annotation."""
        tracker = _StubTracker({"sess-1": [_mutation("src/x.py")]})
        hook = ProvenancePostHook(tracker=tracker, session_id=None)

        out = await hook(
            tool_name="read", tool_input={"path": "src/x.py"}, tool_output="c"
        )
        assert out is None

    async def test_missing_tracker_yields_no_label(self) -> None:
        """No tracker → fail-open, no annotation."""
        hook = ProvenancePostHook(tracker=None, session_id="sess-1")
        out = await hook(
            tool_name="read", tool_input={"path": "src/x.py"}, tool_output="c"
        )
        assert out is None


# ---------------------------------------------------------------------------
# Fail-open robustness
# ---------------------------------------------------------------------------


class TestFailOpen:
    @pytest.mark.parametrize(
        "bad_output",
        ["not json at all", "", "12345", json.dumps([1, 2, 3])],
    )
    async def test_unparseable_output_records_nothing(self, bad_output: str) -> None:
        """Non-EditOutcome tool_output is treated as 'no outcome' — never raises."""
        state = EditGuardState.with_defaults()
        post = PostEditGuardHook(state)
        path = "src/foo.py"

        out = await post(
            tool_name="edit", tool_input={"path": path}, tool_output=bad_output
        )
        assert out is None
        # No failure recorded: unparseable output carries no outcome info.
        assert state.consecutive_failures.get(path, 0) == 0

    async def test_post_hook_missing_path_is_noop(self) -> None:
        """An edit tool_input without a usable path is a silent no-op."""
        state = EditGuardState.with_defaults()
        post = PostEditGuardHook(state)
        out = await post(
            tool_name="edit", tool_input={}, tool_output=_failure_output("x.py")
        )
        assert out is None


# ---------------------------------------------------------------------------
# EditGuardState defaults / overridability
# ---------------------------------------------------------------------------


class TestEditGuardStateDefaults:
    def test_with_defaults_uses_documented_thresholds(self) -> None:
        state = EditGuardState.with_defaults()
        assert state.escalate_threshold == 3
        assert state.hard_cap == 5
        assert state.churn_threshold == 5
        assert state.consecutive_failures == {}
        assert state.edits_per_path == {}
        assert state.summary_doc_writes == 0

    def test_thresholds_are_overridable(self) -> None:
        state = EditGuardState.with_defaults(
            escalate_threshold=2, hard_cap=4, churn_threshold=7
        )
        assert state.escalate_threshold == 2
        assert state.hard_cap == 4
        assert state.churn_threshold == 7


# ---------------------------------------------------------------------------
# Guard-before-verify Post ordering (REQ-SCA-050)
# ---------------------------------------------------------------------------


class TestGuardVerifyPostOrdering:
    """The guard Post hook MUST run before the verify Post hook.

    The dispatcher chains PostToolUse output: verify appends a ``[verify]`` block
    to ``tool_output``, and the guard parses ``tool_output`` as JSON. A guard that
    ran AFTER verify would see non-JSON and record no outcome — so a successful
    edit would fail to reset the consecutive-failure streak (REQ-SCA-050).
    """

    @staticmethod
    async def _fake_verify(
        *, tool_name: str, tool_input: dict, tool_output: str
    ) -> str:
        """Mimic EditSnapshotCoordinator annotating an edit's output."""
        return tool_output + "\n\n[verify] lint delta for this edit"

    async def test_guard_before_verify_records_outcome_and_keeps_feedback(
        self,
    ) -> None:
        from swarmline.hooks.dispatcher import DefaultHookDispatcher
        from swarmline.hooks.registry import HookRegistry

        state = EditGuardState.with_defaults()
        path = "src/foo.py"
        state.consecutive_failures[path] = 2  # near the streak

        registry = HookRegistry()
        registry.on_post_tool_use(PostEditGuardHook(state), matcher="edit")  # guard 1st
        registry.on_post_tool_use(self._fake_verify, matcher="edit")  # verify 2nd
        dispatcher = DefaultHookDispatcher(registry)

        out = await dispatcher.dispatch_post_tool(
            "edit", {"path": path}, _success_output(path)
        )
        # Guard saw the RAW JSON → reset the streak; verify's feedback still present.
        assert state.consecutive_failures[path] == 0
        assert out is not None
        assert "[verify]" in out

    async def test_guard_after_verify_misses_outcome(self) -> None:
        """Negative control locking in the fix: verify-first → guard can't parse →
        a successful edit does NOT reset the streak."""
        from swarmline.hooks.dispatcher import DefaultHookDispatcher
        from swarmline.hooks.registry import HookRegistry

        state = EditGuardState.with_defaults()
        path = "src/foo.py"
        state.consecutive_failures[path] = 2

        registry = HookRegistry()
        registry.on_post_tool_use(self._fake_verify, matcher="edit")  # verify 1st
        registry.on_post_tool_use(PostEditGuardHook(state), matcher="edit")  # guard 2nd
        dispatcher = DefaultHookDispatcher(registry)

        await dispatcher.dispatch_post_tool(
            "edit", {"path": path}, _success_output(path)
        )
        # Guard received "JSON\n\n[verify]..." → json.loads fails → outcome unrecorded.
        assert state.consecutive_failures[path] == 2
