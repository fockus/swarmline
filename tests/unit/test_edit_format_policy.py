"""Tests for EditFormatPolicy (REQ-SCA-010/011) + its runtime-wiring injection.

The policy maps a model id to the edit format its family handles best; the wiring
injects a one-line steering brief into the coding context ONLY when
edit_strategy="auto", and an unknown model resolves to neutral (no steering).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.runtime.thin.edit_format_policy import (
    EditFormat,
    EditFormatPolicy,
    steering_brief,
)


class TestEditFormatPolicy:
    def test_gpt_and_codex_resolve_to_patch(self) -> None:
        policy = EditFormatPolicy.default()
        assert policy.format_for("gpt-4o") == "patch"
        assert policy.format_for("openai/gpt-5.5") == "patch"
        assert policy.format_for("codex-mini-latest") == "patch"

    def test_claude_gemini_qwen_resolve_to_search_replace(self) -> None:
        policy = EditFormatPolicy.default()
        assert policy.format_for("claude-opus-4-8") == "search_replace"
        assert policy.format_for("gemini-2.0-flash") == "search_replace"
        assert policy.format_for("qwen2.5-coder") == "search_replace"

    def test_qwen_gptq_variant_is_search_replace_not_patch(self) -> None:
        # "gptq" contains the "gpt" substring — qwen must be matched first.
        assert (
            EditFormatPolicy.default().format_for("qwen2.5-coder-gptq")
            == "search_replace"
        )

    def test_unknown_or_empty_model_resolves_to_neutral(self) -> None:
        policy = EditFormatPolicy.default()
        assert policy.format_for("mistral-large") == "neutral"
        assert policy.format_for("") == "neutral"
        assert policy.format_for("llama-3.3") == "neutral"

    def test_unknown_family_gptq_suffix_is_neutral_not_patch(self) -> None:
        # "mistral-7b-gptq" contains "gpt" but is NOT an OpenAI GPT model — the
        # letter-boundary rule keeps it neutral (gpt-4o stays patch).
        policy = EditFormatPolicy.default()
        assert policy.format_for("mistral-7b-gptq") == "neutral"
        assert policy.format_for("llama-2-13b-gptq") == "neutral"
        assert policy.format_for("gpt-4o") == "patch"

    def test_case_insensitive_match(self) -> None:
        assert EditFormatPolicy.default().format_for("GPT-4O") == "patch"
        assert (
            EditFormatPolicy.default().format_for("Claude-Sonnet") == "search_replace"
        )

    def test_policy_is_overridable(self) -> None:
        table = cast(Mapping[str, EditFormat], {"myllm": "patch"})
        policy = EditFormatPolicy(family_to_format=table)
        assert policy.format_for("myllm-v1") == "patch"
        assert policy.format_for("gpt-4o") == "neutral"  # not in this table

    def test_steering_brief_content(self) -> None:
        assert "patch" in steering_brief("patch")
        assert "search_replace" in steering_brief("search_replace").lower()
        assert steering_brief("neutral") == ""


class TestEditFormatSteeringWiring:
    """edit_strategy="auto" injects a steering brief consistent with the policy;
    any other strategy leaves the coding brief untouched (byte-identical)."""

    def _filter_skill_text(self, plan: Any) -> str:
        from swarmline.context.coding_input_filter import CodingContextInputFilter

        for flt in plan.config.input_filters:
            if isinstance(flt, CodingContextInputFilter):
                return flt._skill_profile_text
        raise AssertionError("CodingContextInputFilter not wired")

    def _plan(self, tmp_path: Any, *, profile: CodingProfileConfig, model: str) -> Any:
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        agent_config = AgentConfig(
            system_prompt="coding agent",
            runtime="thin",
            cwd=str(tmp_path),
            model=model,
            coding_profile=profile,
        )
        return build_portable_runtime_plan(agent_config, "thin")

    def test_auto_injects_brief_consistent_with_policy(self, tmp_path: Any) -> None:
        plan = self._plan(
            tmp_path,
            profile=CodingProfileConfig(enabled=True, edit_strategy="auto"),
            model="gpt-4o",
        )
        resolved = plan.config.model
        expected = steering_brief(EditFormatPolicy.default().format_for(resolved))
        skill_text = self._filter_skill_text(plan)
        if expected:  # known family → its brief must be present
            assert expected in skill_text
        else:  # neutral → no steering block at all
            assert "Edit-format steering" not in skill_text

    def test_auto_unknown_family_is_neutral_no_steering(self, tmp_path: Any) -> None:
        # DeepSeek resolves fine but is NOT in the family table → neutral → no brief.
        plan = self._plan(
            tmp_path,
            profile=CodingProfileConfig(enabled=True, edit_strategy="auto"),
            model="deepseek:deepseek-chat",
        )
        assert EditFormatPolicy.default().format_for(plan.config.model) == "neutral"
        assert "Edit-format steering" not in self._filter_skill_text(plan)

    def test_non_auto_strategy_injects_no_steering(self, tmp_path: Any) -> None:
        # Literal args at each call site → ty infers the Literal subtype directly.
        for plan in (
            self._plan(
                tmp_path,
                profile=CodingProfileConfig(enabled=True, edit_strategy="legacy"),
                model="gpt-4o",
            ),
            self._plan(
                tmp_path,
                profile=CodingProfileConfig(
                    enabled=True, edit_strategy="search_replace"
                ),
                model="gpt-4o",
            ),
            self._plan(
                tmp_path,
                profile=CodingProfileConfig(enabled=True, edit_strategy="patch"),
                model="gpt-4o",
            ),
        ):
            assert "Edit-format steering" not in self._filter_skill_text(plan)
