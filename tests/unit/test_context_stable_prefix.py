"""Tests for swarmline.context.stable_prefix — REQ-OSS-060.

TDD file: written BEFORE implementation.
Covers build_stable_prefix and mask_tools as standalone module-level functions.
"""

from __future__ import annotations

import pytest

# --- import guard (will fail until implementation exists) ---
from swarmline.context.stable_prefix import build_stable_prefix, mask_tools


# ---------------------------------------------------------------------------
# build_stable_prefix
# ---------------------------------------------------------------------------


class TestBuildStablePrefix:
    def test_deterministic_same_inputs_produce_identical_output(self) -> None:
        """Same system_prompt + user_context always returns the same string."""
        sp = "You are an assistant."
        uc = "User likes concise answers."
        result_a = build_stable_prefix(sp, uc)
        result_b = build_stable_prefix(sp, uc)
        assert result_a == result_b

    def test_deterministic_multiple_calls_are_stable(self) -> None:
        """Three independent calls with identical args yield identical output."""
        results = {build_stable_prefix("sys", "ctx") for _ in range(3)}
        assert len(results) == 1

    def test_different_inputs_produce_different_prefix_segment(self) -> None:
        """Distinct inputs produce distinct output strings."""
        r1 = build_stable_prefix("sys A", "ctx A")
        r2 = build_stable_prefix("sys B", "ctx B")
        assert r1 != r2

    def test_different_system_prompt_changes_output(self) -> None:
        r1 = build_stable_prefix("prompt X", "ctx")
        r2 = build_stable_prefix("prompt Y", "ctx")
        assert r1 != r2

    def test_different_user_context_changes_output(self) -> None:
        r1 = build_stable_prefix("sys", "ctx X")
        r2 = build_stable_prefix("sys", "ctx Y")
        assert r1 != r2

    def test_prefix_tag_starts_with_expected_format(self) -> None:
        """Return value must start with [PREFIX: and contain 16 hex chars."""
        result = build_stable_prefix("sys", "ctx")
        assert result.startswith("[PREFIX:")
        # Extract the tag — between [ and ]
        tag_end = result.index("]")
        tag_body = result[len("[PREFIX:") : tag_end]
        assert len(tag_body) == 16, (
            f"expected 16 hex chars, got {len(tag_body)}: {tag_body!r}"
        )
        assert all(c in "0123456789abcdef" for c in tag_body), f"not hex: {tag_body!r}"

    def test_output_contains_system_prompt_verbatim(self) -> None:
        sp = "You are a careful agent."
        result = build_stable_prefix(sp, "ctx")
        assert sp in result

    def test_output_contains_user_context_verbatim(self) -> None:
        uc = "User prefers bullet points."
        result = build_stable_prefix("sys", uc)
        assert uc in result

    def test_separator_between_system_prompt_and_user_context(self) -> None:
        """system_prompt and user_context are separated by \\n---\\n."""
        sp = "System part."
        uc = "User part."
        result = build_stable_prefix(sp, uc)
        assert "\n---\n" in result
        # The separator must appear between the two parts
        sep_idx = result.index("\n---\n")
        sp_idx = result.index(sp)
        uc_idx = result.index(uc)
        assert sp_idx < sep_idx < uc_idx

    def test_empty_strings_are_valid_inputs(self) -> None:
        """Empty strings do not raise; output still has prefix tag."""
        result = build_stable_prefix("", "")
        assert result.startswith("[PREFIX:")

    def test_exact_structure_matches_spec(self) -> None:
        """Full structural check: [PREFIX:<hash>]<system_prompt>\\n---\\n<user_context>."""
        import hashlib
        import json

        sp = "Hello system"
        uc = "Hello user"
        raw = json.dumps(
            {"system_prompt": sp, "user_context": uc}, sort_keys=True, ensure_ascii=True
        )
        expected_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        expected = f"[PREFIX:{expected_hash}]{sp}\n---\n{uc}"
        assert build_stable_prefix(sp, uc) == expected


# ---------------------------------------------------------------------------
# mask_tools
# ---------------------------------------------------------------------------


class TestMaskTools:
    def test_str_tools_enabled_for_allowed(self) -> None:
        ctx = {"tools": ["search", "calc", "write"]}
        result = mask_tools(ctx, ["search", "write"])
        assert result["tools"] == [
            {"name": "search", "enabled": True},
            {"name": "calc", "enabled": False},
            {"name": "write", "enabled": True},
        ]

    def test_str_tools_all_disabled_when_empty_allowed(self) -> None:
        ctx = {"tools": ["a", "b"]}
        result = mask_tools(ctx, [])
        assert result["tools"] == [
            {"name": "a", "enabled": False},
            {"name": "b", "enabled": False},
        ]

    def test_dict_tools_name_extracted(self) -> None:
        ctx = {
            "tools": [{"name": "search", "params": {}}, {"name": "write", "params": {}}]
        }
        result = mask_tools(ctx, ["search"])
        assert result["tools"] == [
            {"name": "search", "enabled": True},
            {"name": "write", "enabled": False},
        ]

    def test_mixed_str_and_dict_tools(self) -> None:
        ctx = {"tools": ["str_tool", {"name": "dict_tool"}]}
        result = mask_tools(ctx, ["dict_tool"])
        assert result["tools"] == [
            {"name": "str_tool", "enabled": False},
            {"name": "dict_tool", "enabled": True},
        ]

    def test_no_tools_key_returns_copy_equal_to_input(self) -> None:
        ctx = {"model": "claude", "temperature": 0.7}
        result = mask_tools(ctx, ["any"])
        assert result == ctx

    def test_no_tools_key_returns_different_object_mutation_isolation(self) -> None:
        """Returned dict must be a NEW object even when tools key is absent."""
        ctx = {"model": "claude"}
        result = mask_tools(ctx, [])
        assert result is not ctx

    def test_non_list_tools_value_returns_copy_unchanged(self) -> None:
        ctx = {"tools": "not-a-list"}
        result = mask_tools(ctx, ["tool"])
        assert result["tools"] == "not-a-list"
        assert result is not ctx

    def test_original_context_not_mutated_with_str_tools(self) -> None:
        original_tools = ["a", "b", "c"]
        ctx: dict[str, object] = {"tools": original_tools}
        mask_tools(ctx, ["a"])
        # Original list must not be replaced
        assert ctx["tools"] is original_tools
        assert ctx["tools"] == ["a", "b", "c"]

    def test_original_context_not_mutated_with_dict_tools(self) -> None:
        tool_dict = {"name": "t1"}
        ctx: dict[str, object] = {"tools": [tool_dict]}
        mask_tools(ctx, [])
        # tool_dict must not have gained an "enabled" key
        assert "enabled" not in tool_dict

    def test_returns_new_dict_object(self) -> None:
        ctx = {"tools": ["x"]}
        result = mask_tools(ctx, ["x"])
        assert result is not ctx

    def test_other_context_keys_preserved(self) -> None:
        ctx = {"tools": ["t"], "model": "gpt-4", "temperature": 0.5}
        result = mask_tools(ctx, ["t"])
        assert result["model"] == "gpt-4"
        assert result["temperature"] == 0.5

    def test_dict_tool_missing_name_key_falls_back_to_str(self) -> None:
        """Dict tool with no 'name' key → str(tool) used as name."""
        tool: dict[str, object] = {"action": "run"}
        ctx: dict[str, object] = {"tools": [tool]}
        result = mask_tools(ctx, [])
        # name should be str(tool.get("name", tool)) = str(tool) since "name" missing
        assert result["tools"][0]["name"] == str(tool)

    def test_empty_tools_list_returns_empty_masked_list(self) -> None:
        ctx = {"tools": []}
        result = mask_tools(ctx, ["any"])
        assert result["tools"] == []

    @pytest.mark.parametrize(
        "allowed,tool_name,expected_enabled",
        [
            (["alpha"], "alpha", True),
            (["alpha"], "beta", False),
            ([], "alpha", False),
            (["alpha", "beta"], "beta", True),
        ],
    )
    def test_enabled_flag_correctness_parametrized(
        self,
        allowed: list[str],
        tool_name: str,
        expected_enabled: bool,
    ) -> None:
        ctx = {"tools": [tool_name]}
        result = mask_tools(ctx, allowed)
        assert result["tools"][0]["enabled"] is expected_enabled
