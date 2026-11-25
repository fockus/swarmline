"""Tests for Stage 5 recitation wiring in agent/runtime_wiring.py
(context-engineering-manus-parity) -- RuntimeConfig.input_filters threading
via AgentConfig.native_config, generic (not gated on coding_profile)."""

from __future__ import annotations

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan
from swarmline.context.recitation_input_filter import RecitationInputFilter


def _recitation_filters(plan) -> list[RecitationInputFilter]:
    return [
        f for f in plan.config.input_filters if isinstance(f, RecitationInputFilter)
    ]


class TestRecitationWiring_Absent:
    def test_no_recitation_plan_text_is_a_hard_no_op(self) -> None:
        """Absent native_config key -> RecitationInputFilter never constructed,
        byte-identical to pre-Stage-5 behaviour."""
        cfg = AgentConfig(system_prompt="test", runtime="thin", cwd="/tmp/test-coding")
        plan = build_portable_runtime_plan(cfg, "thin")
        assert _recitation_filters(plan) == []

    def test_blank_recitation_plan_text_is_a_hard_no_op(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={"recitation_plan_text": "   "},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert _recitation_filters(plan) == []

    def test_not_gated_on_coding_profile(self) -> None:
        """Unlike CodingContextInputFilter, recitation must wire in even when
        coding_profile is entirely absent (None)."""
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={"recitation_plan_text": "PLAN_TEXT_MARKER"},
        )
        assert cfg.coding_profile is None
        plan = build_portable_runtime_plan(cfg, "thin")
        assert len(_recitation_filters(plan)) == 1


class TestRecitationWiring_Present:
    def test_plan_text_threaded_into_filter(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={"recitation_plan_text": "PLAN_TEXT_MARKER"},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        filters = _recitation_filters(plan)
        assert len(filters) == 1
        assert filters[0]._plan_text == "PLAN_TEXT_MARKER"

    def test_summary_text_threaded_when_present(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={
                "recitation_plan_text": "FULL_MARKER",
                "recitation_plan_summary_text": "SPARSE_MARKER",
            },
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        filters = _recitation_filters(plan)
        assert filters[0]._plan_summary_text == "SPARSE_MARKER"

    def test_default_summary_falls_back_to_full_text(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={"recitation_plan_text": "FULL_MARKER"},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        filters = _recitation_filters(plan)
        assert filters[0]._plan_summary_text == "FULL_MARKER"

    def test_cadence_threaded_when_present(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={
                "recitation_plan_text": "FULL_MARKER",
                "recitation_cadence": 3,
            },
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        filters = _recitation_filters(plan)
        assert filters[0]._cadence == 3

    def test_default_cadence_is_module_constant(self) -> None:
        from swarmline.context.recitation_input_filter import RECITATION_CADENCE

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            native_config={"recitation_plan_text": "FULL_MARKER"},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        filters = _recitation_filters(plan)
        assert filters[0]._cadence == RECITATION_CADENCE
