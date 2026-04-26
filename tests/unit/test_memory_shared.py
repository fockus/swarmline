"""Tests for shared memory normalization helpers."""

from __future__ import annotations

from types import SimpleNamespace

from swarmline.memory._shared import (
    build_goal_state,
    build_phase_state,
    build_session_state,
    json_dumps_or_none,
    json_load_or_empty_list,
    json_load_or_none,
    json_load_value,
    merge_scoped_facts,
)


class TestJsonHelpers:
    def test_json_dumps_or_none_returns_none_for_none(self) -> None:
        assert json_dumps_or_none(None) is None

    def test_json_dumps_or_none_serializes_payload(self) -> None:
        assert json_load_or_none(json_dumps_or_none({"key": "value"})) == {
            "key": "value"
        }

    def test_json_load_or_none_preserves_python_values(self) -> None:
        payload = {"items": [1, 2, 3]}
        assert json_load_or_none(payload) == payload

    def test_json_load_or_empty_list_returns_empty_for_invalid_input(self) -> None:
        assert json_load_or_empty_list("not-json") == []

    def test_json_load_value_preserves_scalars(self) -> None:
        assert json_load_value(42) == 42


class TestFactMerge:
    def test_merge_scoped_facts_prefers_topic_rows(self) -> None:
        rows = [
            SimpleNamespace(key="status", value="global", topic_id=None),
            SimpleNamespace(key="status", value="topic", topic_id="t1"),
            SimpleNamespace(key="income", value='{"amount": 120000}', topic_id=None),
        ]

        merged = merge_scoped_facts(rows)

        assert merged == {"status": "topic", "income": {"amount": 120000}}


class TestStateBuilders:
    def test_build_goal_state_normalizes_payload(self) -> None:
        state = build_goal_state(
            goal_id="goal-1",
            title="Подушка",
            target_amount="500000",
            current_amount="100000",
            phase="savings",
            plan='{"steps": ["a", "b"]}',
            is_main=1,
        )

        assert state.goal_id == "goal-1"
        assert state.target_amount == 500000
        assert state.current_amount == 100000
        assert state.plan == {"steps": ["a", "b"]}
        assert state.is_main is True

    def test_build_session_state_normalizes_payload(self) -> None:
        state = build_session_state(
            role_id="coach",
            active_skill_ids='["skill-a", "skill-b"]',
            title="Вклады",
            prompt_hash=None,
            delegated_from="orchestrator",
            delegation_turn_count="3",
            pending_delegation=None,
            delegation_summary="Подбор вклада",
        )

        assert state["role_id"] == "coach"
        assert state["active_skill_ids"] == ["skill-a", "skill-b"]
        assert state["prompt_hash"] == ""
        assert state["delegation_turn_count"] == 3

    def test_build_phase_state_normalizes_payload(self) -> None:
        phase = build_phase_state(user_id="u1", phase=None, notes=None)

        assert phase.user_id == "u1"
        assert phase.phase == ""
        assert phase.notes == ""
