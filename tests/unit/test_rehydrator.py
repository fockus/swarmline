"""Tests for SessionRehydrator (sektsiya 8.4 arhitektury). Contract: build_rehydration_payload(ctx) -> Mapping with klyuchami: role_id, active_skill_ids, summary, last_messages, goal, phase_state ISP: konstruktor prinimaet 5 melkih protocolov, a not monolitnyy MemoryProvider.
"""

from unittest.mock import AsyncMock

import pytest
from swarmline.memory.types import GoalState, MemoryMessage, PhaseState
from swarmline.session.rehydrator import DefaultSessionRehydrator
from swarmline.types import TurnContext


def _make_ctx(**kwargs) -> TurnContext:
    defaults = {
        "user_id": "u1",
        "topic_id": "t1",
        "role_id": "coach",
        "model": "sonnet",
        "active_skill_ids": (),
    }
    defaults.update(kwargs)
    return TurnContext(**defaults)


def _make_stores() -> dict:
    """Create set mock-hranilishch for rehydrator."""
    messages = AsyncMock()
    messages.get_messages.return_value = [
        MemoryMessage(role="user", content="какой вклад лучше?"),
        MemoryMessage(role="assistant", content="Зависит от суммы и срока."),
    ]

    summaries = AsyncMock()
    summaries.get_summary.return_value = "Пользователь интересуется вкладами."

    goals = AsyncMock()
    goals.get_active_goal.return_value = GoalState(
        goal_id="g1",
        title="Накопить 500к",
        target_amount=500000,
        current_amount=100000,
        phase="savings",
    )

    sessions = AsyncMock()
    sessions.get_session_state.return_value = {
        "role_id": "deposit_advisor",
        "active_skill_ids": ["finuslugi", "iss-price"],
        "title": "Вклады",
        "prompt_hash": "abc123def456",
    }

    phases = AsyncMock()
    phases.get_phase_state.return_value = PhaseState(
        user_id="u1", phase="savings", notes="50% от цели"
    )

    return {
        "messages": messages,
        "summaries": summaries,
        "goals": goals,
        "sessions": sessions,
        "phases": phases,
    }


@pytest.fixture
def stores() -> dict:
    return _make_stores()


@pytest.fixture
def rehydrator(stores: dict) -> DefaultSessionRehydrator:
    return DefaultSessionRehydrator(**stores)


class TestBuildPayload:
    """build_rehydration_payload() returns full payload."""

    @pytest.mark.asyncio
    async def test_returns_role_id(self, rehydrator: DefaultSessionRehydrator) -> None:
        """Payload contains role_id from BD."""
        payload = await rehydrator.build_rehydration_payload(_make_ctx())
        assert payload["role_id"] == "deposit_advisor"

    @pytest.mark.asyncio
    async def test_returns_active_skills(self, rehydrator: DefaultSessionRehydrator) -> None:
        """Payload contains active_skill_ids."""
        payload = await rehydrator.build_rehydration_payload(_make_ctx())
        assert payload["active_skill_ids"] == ["finuslugi", "iss-price"]

    @pytest.mark.asyncio
    async def test_returns_summary(self, rehydrator: DefaultSessionRehydrator) -> None:
        """Payload contains rolling summary."""
        payload = await rehydrator.build_rehydration_payload(_make_ctx())
        assert "вкладами" in payload["summary"]

    @pytest.mark.asyncio
    async def test_returns_last_messages(self, rehydrator: DefaultSessionRehydrator) -> None:
        """Payload contains last N messages."""
        payload = await rehydrator.build_rehydration_payload(_make_ctx())
        assert len(payload["last_messages"]) == 2
        assert payload["last_messages"][0].role == "user"

    @pytest.mark.asyncio
    async def test_returns_active_goal(self, rehydrator: DefaultSessionRehydrator) -> None:
        """Payload contains aktivnuyu tsel."""
        payload = await rehydrator.build_rehydration_payload(_make_ctx())
        assert payload["goal"].title == "Накопить 500к"
        assert payload["goal"].phase == "savings"

    @pytest.mark.asyncio
    async def test_returns_phase_state(self, rehydrator: DefaultSessionRehydrator) -> None:
        """Payload contains phase_state (R-703)."""
        payload = await rehydrator.build_rehydration_payload(_make_ctx())
        assert payload["phase_state"] is not None
        assert payload["phase_state"].phase == "savings"
        assert payload["phase_state"].notes == "50% от цели"

    @pytest.mark.asyncio
    async def test_returns_prompt_hash(self, rehydrator: DefaultSessionRehydrator) -> None:
        """Payload contains prompt_hash for diagnostics (GAP-2, §8.4)."""
        payload = await rehydrator.build_rehydration_payload(_make_ctx())
        assert payload["prompt_hash"] == "abc123def456"


class TestMissingData:
    """Payload pri otsutstvii dannyh in BD."""

    @pytest.mark.asyncio
    async def test_no_session_state(self) -> None:
        """If nott session_state - ispolzuem dannye from ctx."""
        stores = _make_stores()
        stores["sessions"].get_session_state.return_value = None
        rh = DefaultSessionRehydrator(**stores)
        payload = await rh.build_rehydration_payload(_make_ctx(role_id="coach"))
        assert payload["role_id"] == "coach"
        assert payload["active_skill_ids"] == []
        assert payload["prompt_hash"] == ""

    @pytest.mark.asyncio
    async def test_no_summary(self) -> None:
        """If nott summary - None."""
        stores = _make_stores()
        stores["summaries"].get_summary.return_value = None
        rh = DefaultSessionRehydrator(**stores)
        payload = await rh.build_rehydration_payload(_make_ctx())
        assert payload["summary"] is None

    @pytest.mark.asyncio
    async def test_no_goal(self) -> None:
        """If nott tseli - None."""
        stores = _make_stores()
        stores["goals"].get_active_goal.return_value = None
        rh = DefaultSessionRehydrator(**stores)
        payload = await rh.build_rehydration_payload(_make_ctx())
        assert payload["goal"] is None

    @pytest.mark.asyncio
    async def test_no_messages(self) -> None:
        """If nott soobshcheniy - empty list."""
        stores = _make_stores()
        stores["messages"].get_messages.return_value = []
        rh = DefaultSessionRehydrator(**stores)
        payload = await rh.build_rehydration_payload(_make_ctx())
        assert payload["last_messages"] == []

    @pytest.mark.asyncio
    async def test_no_phase_state(self) -> None:
        """If nott phase_state - None."""
        stores = _make_stores()
        stores["phases"].get_phase_state.return_value = None
        rh = DefaultSessionRehydrator(**stores)
        payload = await rh.build_rehydration_payload(_make_ctx())
        assert payload["phase_state"] is None


class TestPartialData:
    """Edge cases: chastichnye dannye pri rehydration."""

    @pytest.mark.asyncio
    async def test_session_state_without_skills_key(self) -> None:
        """Session state without active_skill_ids -> empty list."""
        stores = _make_stores()
        stores["sessions"].get_session_state.return_value = {
            "role_id": "coach",
            # nott active_skill_ids
        }
        rh = DefaultSessionRehydrator(**stores)
        payload = await rh.build_rehydration_payload(_make_ctx())
        assert payload["role_id"] == "coach"
        assert payload["active_skill_ids"] == []

    @pytest.mark.asyncio
    async def test_all_empty_returns_ctx_defaults(self) -> None:
        """Vse hranilishcha empty -> ispolzuem dannye from ctx."""
        stores = _make_stores()
        stores["sessions"].get_session_state.return_value = None
        stores["summaries"].get_summary.return_value = None
        stores["messages"].get_messages.return_value = []
        stores["goals"].get_active_goal.return_value = None
        stores["phases"].get_phase_state.return_value = None

        rh = DefaultSessionRehydrator(**stores)
        ctx = _make_ctx(role_id="diagnostician", active_skill_ids=("iss",))
        payload = await rh.build_rehydration_payload(ctx)

        assert payload["role_id"] == "diagnostician"
        assert payload["active_skill_ids"] == ["iss"]
        assert payload["summary"] is None
        assert payload["last_messages"] == []
        assert payload["goal"] is None
        assert payload["phase_state"] is None

    @pytest.mark.asyncio
    async def test_last_n_messages_limit(self) -> None:
        """Rehydrator zaprashivaet rovno last_n messages."""
        stores = _make_stores()
        rh = DefaultSessionRehydrator(**stores, last_n_messages=3)
        await rh.build_rehydration_payload(_make_ctx())
        stores["messages"].get_messages.assert_called_once_with("u1", "t1", limit=3)

    @pytest.mark.asyncio
    async def test_phase_state_full_payload(self) -> None:
        """Phase state with polnymi dannymi includessya in payload."""
        stores = _make_stores()
        rh = DefaultSessionRehydrator(**stores)
        payload = await rh.build_rehydration_payload(_make_ctx())
        phase = payload["phase_state"]
        assert phase.user_id == "u1"
        assert phase.phase == "savings"
        assert phase.notes == "50% от цели"
