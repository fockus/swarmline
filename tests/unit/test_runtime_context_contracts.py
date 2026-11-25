"""Tests for swarmline runtime context contracts 1-3 — REQ-ORC-090/091/092.

TDD file: written BEFORE implementation.

Covers:
- Contract 1 (REQ-ORC-090): append-only history + stable prefix.
- Contract 2 (REQ-ORC-091): mask_tools soft-disables without removing entries
  and leaves the stable prefix (system_prompt + user_context head) unchanged.
- Contract 3 (REQ-ORC-092): ArtifactStore + to_artifact_ref replace a large
  output in context with a short, restorable reference.
"""

from __future__ import annotations

from typing import cast

from swarmline.context import (
    ArtifactStore,
    append_only,
    build_stable_prefix,
    mask_tools,
    to_artifact_ref,
)

# ---------------------------------------------------------------------------
# Contract 1 — append-only context + stable prefix (REQ-ORC-090)
# ---------------------------------------------------------------------------


class TestContract1AppendOnlyStablePrefix:
    def test_build_stable_prefix_byte_identical_across_two_turns(self) -> None:
        """Same head input across two 'turns' yields byte-identical prefix."""
        sp = "You are the orchestrator."
        uc = "Turn context: task queue has 3 items."
        turn_1 = build_stable_prefix(sp, uc)
        turn_2 = build_stable_prefix(sp, uc)
        assert turn_1 == turn_2

    def test_append_only_returns_new_tuple_with_event_appended(self) -> None:
        history: tuple[str, ...] = ("event-1", "event-2")
        result = append_only(history, "event-3")
        assert result == ("event-1", "event-2", "event-3")

    def test_append_only_supports_multiple_events_in_one_call(self) -> None:
        history: tuple[str, ...] = ("event-1",)
        result = append_only(history, "event-2", "event-3")
        assert result == ("event-1", "event-2", "event-3")

    def test_append_only_does_not_mutate_input_history(self) -> None:
        """append-only: prior entries are never mutated or reordered."""
        history: tuple[str, ...] = ("event-1", "event-2")
        original_id = id(history)
        append_only(history, "event-3")
        assert history == ("event-1", "event-2")
        assert id(history) == original_id

    def test_append_only_preserves_order_of_prior_entries(self) -> None:
        history: tuple[str, ...] = ("a", "b", "c")
        result = append_only(history, "d")
        assert result[:3] == history

    def test_stable_prefix_over_unchanged_head_identical_before_and_after_append(
        self,
    ) -> None:
        """Appending to history does not affect the stable prefix of the head."""
        sp = "System prompt for the run."
        uc = "Stable user context head."
        history: tuple[str, ...] = ("turn-1",)

        prefix_before = build_stable_prefix(sp, uc)
        history = append_only(history, "turn-2")
        prefix_after = build_stable_prefix(sp, uc)

        assert prefix_before == prefix_after
        assert history == ("turn-1", "turn-2")


# ---------------------------------------------------------------------------
# Contract 2 — mask_tools soft-disable + prefix unchanged (REQ-ORC-091)
# ---------------------------------------------------------------------------


class TestContract2MaskingPreservesPrefix:
    def test_mask_tools_soft_disables_tool_not_in_allowed_keeps_entry(self) -> None:
        ctx = {"tools": ["search", "write", "delete"]}
        original_len = len(ctx["tools"])

        result = mask_tools(cast("dict[str, object]", ctx), ["search", "write"])

        result_tools = cast("list[dict[str, object]]", result["tools"])
        assert len(result_tools) == original_len
        names = {t["name"] for t in result_tools}
        assert "delete" in names
        disabled = next(t for t in result_tools if t["name"] == "delete")
        assert disabled["enabled"] is False

    def test_mask_tools_leaves_allowed_tool_enabled_and_present(self) -> None:
        ctx = {"tools": ["search", "write"]}
        result = mask_tools(cast("dict[str, object]", ctx), ["search"])
        result_tools = cast("list[dict[str, object]]", result["tools"])
        enabled_tool = next(t for t in result_tools if t["name"] == "search")
        assert enabled_tool["enabled"] is True

    def test_masking_does_not_change_stable_prefix_of_head(self) -> None:
        """Masking touches only tools; the system_prompt+user_context prefix
        computed independently of the context dict is unaffected."""
        sp = "Orchestrator system prompt."
        uc = "Head context shared across agents."
        prefix_before = build_stable_prefix(sp, uc)

        ctx = {"tools": ["search", "write", "delete"], "system_prompt": sp}
        mask_tools(cast("dict[str, object]", ctx), ["search"])

        prefix_after = build_stable_prefix(sp, uc)
        assert prefix_before == prefix_after


# ---------------------------------------------------------------------------
# Contract 3 — artifact-ref (REQ-ORC-092)
# ---------------------------------------------------------------------------


class TestContract3ArtifactRef:
    def test_large_output_stored_and_ref_is_much_shorter_than_output(self) -> None:
        store = ArtifactStore()
        large_output = "x" * 100_000

        ref = to_artifact_ref(store, large_output)

        assert len(str(ref)) < len(large_output) / 10

    def test_restore_returns_exact_original_output(self) -> None:
        store = ArtifactStore()
        output = "This is the full tool output that must be restorable verbatim."

        ref_id = store.store(output)
        restored = store.restore(ref_id)

        assert restored == output

    def test_context_holds_ref_not_full_output(self) -> None:
        """The ref dict embedded into context must NOT contain the full output
        string — only a short opaque pointer to it."""
        store = ArtifactStore()
        output = "SENTINEL-PAYLOAD-" + ("y" * 5_000)

        ref = to_artifact_ref(store, output)

        assert output not in str(ref)
        assert output not in ref.values()

    def test_store_is_deterministic_for_identical_content(self) -> None:
        """Equal outputs dedupe to the same ref id (content-addressed store)."""
        store = ArtifactStore()
        output = "identical content"
        ref_id_1 = store.store(output)
        ref_id_2 = store.store(output)
        assert ref_id_1 == ref_id_2

    def test_restore_unknown_ref_raises_key_error(self) -> None:
        store = ArtifactStore()
        try:
            store.restore("unknown-ref-id")
        except KeyError:
            pass
        else:
            raise AssertionError("expected KeyError for unknown ref_id")

    def test_to_artifact_ref_includes_length_of_original_output(self) -> None:
        store = ArtifactStore()
        output = "a" * 42
        ref = to_artifact_ref(store, output)
        assert ref["length"] == 42
