"""Tests for PostgresMemoryProvider - cherez mock SQLAlchemy session. Verify, chto metody vyzyvayut pravilnye SQL-queries with pravilnymi parameterami.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from swarmline.memory.postgres import _USER_ID_SUB, PostgresMemoryProvider, _json_or_none
from swarmline.memory.types import GoalState


def _mock_session_factory():
    """Create mock async_sessionmaker."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = session
    return factory, session


class TestJsonOrNone:
    """_json_or_none - utilita serializatsii."""

    def test_none_returns_none(self) -> None:
        assert _json_or_none(None) is None

    def test_dict_returns_json(self) -> None:
        result = _json_or_none({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_list_returns_json(self) -> None:
        result = _json_or_none([1, 2, 3])
        assert json.loads(result) == [1, 2, 3]

    def test_string_returns_json(self) -> None:
        result = _json_or_none("hello")
        assert json.loads(result) == "hello"


class TestUserIdSubquery:
    """_USER_ID_SUB - edinaya konstanta for podquery."""

    def test_contains_select(self) -> None:
        assert "SELECT id FROM users" in _USER_ID_SUB
        assert "external_id" in _USER_ID_SUB


class TestSaveMessage:
    """save_message - INSERT in messages."""

    @pytest.mark.asyncio
    async def test_calls_execute(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        await provider.save_message("u1", "t1", "user", "Привет!")

        session.execute.assert_awaited_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_tool_calls(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        tools = [{"name": "iss", "input": {}}]
        await provider.save_message("u1", "t1", "assistant", "Ответ", tool_calls=tools)

        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["role"] == "assistant"
        assert params["tool_calls"] is not None


class TestGetMessages:
    """get_messages - SELECT from messages."""

    @pytest.mark.asyncio
    async def test_returns_messages(self) -> None:
        factory, session = _mock_session_factory()

        # Mockiruem result query
        row1 = MagicMock()
        row1.role = "user"
        row1.content = "Вопрос?"
        row1.tool_calls = None

        row2 = MagicMock()
        row2.role = "assistant"
        row2.content = "Ответ!"
        row2.tool_calls = None

        result_mock = MagicMock()
        result_mock.fetchall.return_value = [row2, row1]  # DESC
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        messages = await provider.get_messages("u1", "t1", limit=10)

        assert len(messages) == 2
        # Should byt in ASC poryadke (reversed)
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"


class TestCountMessages:
    """count_messages — SELECT COUNT(*)."""

    @pytest.mark.asyncio
    async def test_returns_count(self) -> None:
        factory, session = _mock_session_factory()
        row = MagicMock()
        row.cnt = 42
        result_mock = MagicMock()
        result_mock.fetchone.return_value = row
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        count = await provider.count_messages("u1", "t1")
        assert count == 42

    @pytest.mark.asyncio
    async def test_returns_zero_on_no_row(self) -> None:
        factory, session = _mock_session_factory()
        result_mock = MagicMock()
        result_mock.fetchone.return_value = None
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        count = await provider.count_messages("u1", "t1")
        assert count == 0


class TestDeleteMessagesBefore:
    """delete_messages_before - DELETE with keep_last."""

    @pytest.mark.asyncio
    async def test_returns_rowcount(self) -> None:
        factory, session = _mock_session_factory()
        result_mock = MagicMock()
        result_mock.rowcount = 5
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        deleted = await provider.delete_messages_before("u1", "t1", keep_last=10)
        assert deleted == 5
        session.commit.assert_awaited_once()


class TestUpsertFact:
    """upsert_fact — INSERT ... ON CONFLICT DO UPDATE."""

    @pytest.mark.asyncio
    async def test_serializes_value(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        await provider.upsert_fact("u1", "возраст", 32, source="user")

        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["key"] == "возраст"
        assert json.loads(params["value"]) == 32
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_source_priority_clause_for_ai_inferred_over_mcp(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        await provider.upsert_fact(
            "u1",
            "recommendation",
            "ai",
            topic_id="t1",
            source="ai_inferred",
        )

        query = str(session.execute.call_args[0][0])
        assert "facts.source" in query
        assert "EXCLUDED.source" in query
        assert "ai_inferred" in query
        assert "mcp" in query

    @pytest.mark.asyncio
    async def test_query_enforces_documented_source_precedence(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        await provider.upsert_fact("u1", "status", "value", source="mcp")

        statement = str(session.execute.call_args.args[0])
        assert "ai_inferred" in statement
        assert "mcp" in statement
        assert "facts.source" in statement
        assert "EXCLUDED.source" in statement


class TestGetFacts:
    """get_facts — SELECT key, value."""

    @pytest.mark.asyncio
    async def test_with_topic(self) -> None:
        factory, session = _mock_session_factory()
        row = MagicMock()
        row.key = "возраст"
        row.value = 32
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [row]
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        facts = await provider.get_facts("u1", topic_id="t1")
        assert facts == {"возраст": 32}

    @pytest.mark.asyncio
    async def test_without_topic(self) -> None:
        factory, session = _mock_session_factory()
        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        facts = await provider.get_facts("u1", topic_id=None)
        assert facts == {}

    @pytest.mark.asyncio
    async def test_with_topic_same_key_prefers_topic_value(self) -> None:
        factory, session = _mock_session_factory()
        global_row = MagicMock()
        global_row.key = "status"
        global_row.value = "global"
        global_row.topic_id = None
        topic_row = MagicMock()
        topic_row.key = "status"
        topic_row.value = "topic"
        topic_row.topic_id = "t1"
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [global_row, topic_row]
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        facts = await provider.get_facts("u1", topic_id="t1")
        assert facts == {"status": "topic"}


class TestSaveGoalUpsert:
    """save_goal should upsert'it sushchestvuyushchuyu tsel."""

    @pytest.mark.asyncio
    async def test_uses_upsert_query(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        goal = GoalState(goal_id="t1", title="Подушка", current_amount=100000)
        await provider.save_goal("u1", goal)

        statement = str(session.execute.call_args.args[0])
        assert "ON CONFLICT (user_id, topic_id)" in statement
        assert "DO UPDATE SET" in statement


class TestSaveSummary:
    """save_summary - INSERT ... ON CONFLICT DO UPDATE with versiey."""

    @pytest.mark.asyncio
    async def test_calls_execute(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        await provider.save_summary("u1", "t1", "Summary text", 15)

        session.execute.assert_awaited_once()
        params = session.execute.call_args[0][1]
        assert params["summary"] == "Summary text"
        assert params["messages_covered"] == 15


class TestGetSummary:
    """get_summary — SELECT summary."""

    @pytest.mark.asyncio
    async def test_returns_summary(self) -> None:
        factory, session = _mock_session_factory()
        row = MagicMock()
        row.summary = "Обсуждали вклады"
        result_mock = MagicMock()
        result_mock.fetchone.return_value = row
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        summary = await provider.get_summary("u1", "t1")
        assert summary == "Обсуждали вклады"

    @pytest.mark.asyncio
    async def test_returns_none_when_absent(self) -> None:
        factory, session = _mock_session_factory()
        result_mock = MagicMock()
        result_mock.fetchone.return_value = None
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        summary = await provider.get_summary("u1", "t1")
        assert summary is None


class TestEnsureUser:
    """ensure_user — INSERT ... ON CONFLICT DO NOTHING."""

    @pytest.mark.asyncio
    async def test_returns_external_id(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        result = await provider.ensure_user("telegram_123")
        assert result == "telegram_123"
        session.commit.assert_awaited_once()


class TestSaveGoal:
    """save_goal - INSERT in goals."""

    @pytest.mark.asyncio
    async def test_saves_goal(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        goal = GoalState(
            goal_id="g1",
            title="Накопить",
            target_amount=500_000,
            current_amount=100_000,
            phase="savings",
            plan=["Шаг 1", "Шаг 2"],
        )
        await provider.save_goal("u1", goal)

        session.execute.assert_awaited_once()
        params = session.execute.call_args[0][1]
        assert params["title"] == "Накопить"
        assert json.loads(params["plan"]) == ["Шаг 1", "Шаг 2"]

    @pytest.mark.asyncio
    async def test_saves_goal_without_plan(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        goal = GoalState(goal_id="g1", title="Цель", phase="assessment")
        await provider.save_goal("u1", goal)

        params = session.execute.call_args[0][1]
        assert params["plan"] is None


class TestGetActiveGoal:
    """get_active_goal - SELECT from goals."""

    @pytest.mark.asyncio
    async def test_returns_goal(self) -> None:
        factory, session = _mock_session_factory()
        row = MagicMock()
        row.topic_id = "g1"
        row.title = "Накопить"
        row.target_amount = 500000
        row.current_amount = 100000
        row.phase = "savings"
        row.plan = ["step1"]
        row.is_main = True
        result_mock = MagicMock()
        result_mock.fetchone.return_value = row
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        goal = await provider.get_active_goal("u1", "g1")

        assert goal is not None
        assert goal.title == "Накопить"
        assert goal.is_main is True

    @pytest.mark.asyncio
    async def test_returns_none_when_no_goal(self) -> None:
        factory, session = _mock_session_factory()
        result_mock = MagicMock()
        result_mock.fetchone.return_value = None
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        goal = await provider.get_active_goal("u1", "t1")
        assert goal is None


class TestSessionState:
    """save/get_session_state - table topics."""

    @pytest.mark.asyncio
    async def test_save_session_state(self) -> None:
        factory, session = _mock_session_factory()
        provider = PostgresMemoryProvider(factory)

        await provider.save_session_state("u1", "t1", "coach", ["iss"])
        session.execute.assert_awaited_once()
        params = session.execute.call_args[0][1]
        assert params["role_id"] == "coach"
        assert json.loads(params["skill_ids"]) == ["iss"]

    @pytest.mark.asyncio
    async def test_get_session_state(self) -> None:
        factory, session = _mock_session_factory()
        row = MagicMock()
        row.role_id = "deposit_advisor"
        row.active_skill_ids = ["finuslugi"]
        row.title = "Вклады"
        row.prompt_hash = "abc"
        row.delegated_from = "orchestrator"
        row.delegation_turn_count = 3
        row.pending_delegation = None
        row.delegation_summary = "Подбор вклада"
        result_mock = MagicMock()
        result_mock.fetchone.return_value = row
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        state = await provider.get_session_state("u1", "t1")

        assert state["role_id"] == "deposit_advisor"
        assert state["active_skill_ids"] == ["finuslugi"]
        assert state["title"] == "Вклады"
        assert state["delegated_from"] == "orchestrator"
        assert state["delegation_turn_count"] == 3
        assert state["pending_delegation"] is None
        assert state["delegation_summary"] == "Подбор вклада"

    @pytest.mark.asyncio
    async def test_get_session_state_not_found(self) -> None:
        factory, session = _mock_session_factory()
        result_mock = MagicMock()
        result_mock.fetchone.return_value = None
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        state = await provider.get_session_state("u1", "t_missing")
        assert state is None


class TestGetUserProfile:
    """get_user_profile - agregatsiya faktov."""

    @pytest.mark.asyncio
    async def test_returns_profile_with_facts(self) -> None:
        factory, session = _mock_session_factory()
        row = MagicMock()
        row.key = "возраст"
        row.value = 32
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [row]
        session.execute.return_value = result_mock

        provider = PostgresMemoryProvider(factory)
        profile = await provider.get_user_profile("u1")

        assert profile.user_id == "u1"
        assert profile.facts == {"возраст": 32}
