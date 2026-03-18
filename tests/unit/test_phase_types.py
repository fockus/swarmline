"""Unit-tests for PhaseState and svyazannyh tipov."""

from __future__ import annotations

from cognitia.memory.types import PhaseState, ToolEvent


class TestPhaseState:
    """Tests PhaseState."""

    def test_default_phase_is_empty(self) -> None:
        ps = PhaseState(user_id="u1")
        assert ps.phase == ""
        assert ps.notes == ""

    def test_custom_phase_and_notes(self) -> None:
        ps = PhaseState(user_id="u1", phase="cushion", notes="Формирую резерв")
        assert ps.phase == "cushion"
        assert ps.notes == "Формирую резерв"


class TestToolEvent:
    """Tests ToolEvent."""

    def test_create(self) -> None:
        event = ToolEvent(
            topic_id="t1",
            tool_name="mcp__iss__get_market_snapshot",
            latency_ms=200,
        )
        assert event.topic_id == "t1"
        assert event.tool_name == "mcp__iss__get_market_snapshot"
        assert event.input_json is None
        assert event.output_json is None
        assert event.latency_ms == 200
