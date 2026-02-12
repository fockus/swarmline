"""Unit-тесты для InMemoryMemoryProvider (R-521)."""

from __future__ import annotations

import pytest

from cognitia.memory.inmemory import InMemoryMemoryProvider
from cognitia.memory.types import GoalState, ToolEvent


@pytest.fixture
def provider() -> InMemoryMemoryProvider:
    return InMemoryMemoryProvider()


class TestMessages:
    """Тесты операций с сообщениями."""

    @pytest.mark.asyncio
    async def test_save_and_get_messages(self, provider: InMemoryMemoryProvider) -> None:
        await provider.save_message("u1", "t1", "user", "Привет")
        await provider.save_message("u1", "t1", "assistant", "Здравствуйте!")
        msgs = await provider.get_messages("u1", "t1")
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_get_messages_limit(self, provider: InMemoryMemoryProvider) -> None:
        for i in range(20):
            await provider.save_message("u1", "t1", "user", f"msg-{i}")
        msgs = await provider.get_messages("u1", "t1", limit=5)
        assert len(msgs) == 5
        assert msgs[-1].content == "msg-19"

    @pytest.mark.asyncio
    async def test_count_messages(self, provider: InMemoryMemoryProvider) -> None:
        await provider.save_message("u1", "t1", "user", "one")
        await provider.save_message("u1", "t1", "assistant", "two")
        assert await provider.count_messages("u1", "t1") == 2
        assert await provider.count_messages("u1", "t2") == 0

    @pytest.mark.asyncio
    async def test_delete_messages_before(self, provider: InMemoryMemoryProvider) -> None:
        for i in range(10):
            await provider.save_message("u1", "t1", "user", f"msg-{i}")
        deleted = await provider.delete_messages_before("u1", "t1", keep_last=3)
        assert deleted == 7
        msgs = await provider.get_messages("u1", "t1")
        assert len(msgs) == 3
        assert msgs[0].content == "msg-7"

    @pytest.mark.asyncio
    async def test_messages_isolated_by_topic(self, provider: InMemoryMemoryProvider) -> None:
        await provider.save_message("u1", "t1", "user", "topic1")
        await provider.save_message("u1", "t2", "user", "topic2")
        msgs1 = await provider.get_messages("u1", "t1")
        msgs2 = await provider.get_messages("u1", "t2")
        assert len(msgs1) == 1
        assert len(msgs2) == 1
        assert msgs1[0].content == "topic1"
        assert msgs2[0].content == "topic2"


class TestFacts:
    """Тесты операций с фактами."""

    @pytest.mark.asyncio
    async def test_upsert_and_get_facts(self, provider: InMemoryMemoryProvider) -> None:
        await provider.upsert_fact("u1", "income", 100000)
        facts = await provider.get_facts("u1")
        assert facts["income"] == 100000

    @pytest.mark.asyncio
    async def test_facts_global_and_topic(self, provider: InMemoryMemoryProvider) -> None:
        await provider.upsert_fact("u1", "name", "Иван")  # глобальный
        await provider.upsert_fact("u1", "goal", "вклад", topic_id="t1")
        # С topic_id — видим оба
        facts = await provider.get_facts("u1", topic_id="t1")
        assert "name" in facts
        assert "goal" in facts
        # Без topic_id — только глобальные
        facts_global = await provider.get_facts("u1")
        assert "name" in facts_global
        assert "goal" not in facts_global

    @pytest.mark.asyncio
    async def test_upsert_overwrites(self, provider: InMemoryMemoryProvider) -> None:
        await provider.upsert_fact("u1", "income", 50000)
        await provider.upsert_fact("u1", "income", 100000)
        facts = await provider.get_facts("u1")
        assert facts["income"] == 100000


class TestSummaries:

    @pytest.mark.asyncio
    async def test_save_and_get_summary(self, provider: InMemoryMemoryProvider) -> None:
        await provider.save_summary("u1", "t1", "Пользователь хочет вклад", 5)
        result = await provider.get_summary("u1", "t1")
        assert result == "Пользователь хочет вклад"

    @pytest.mark.asyncio
    async def test_get_summary_none(self, provider: InMemoryMemoryProvider) -> None:
        assert await provider.get_summary("u1", "t_absent") is None


class TestUsers:

    @pytest.mark.asyncio
    async def test_ensure_user(self, provider: InMemoryMemoryProvider) -> None:
        uid = await provider.ensure_user("tg_12345")
        assert uid == "tg_12345"


class TestGoals:

    @pytest.mark.asyncio
    async def test_save_and_get_goal(self, provider: InMemoryMemoryProvider) -> None:
        goal = GoalState(goal_id="t1", title="Накопить 1М", target_amount=1000000)
        await provider.save_goal("u1", goal)
        result = await provider.get_active_goal("u1", "t1")
        assert result is not None
        assert result.title == "Накопить 1М"

    @pytest.mark.asyncio
    async def test_get_goal_none(self, provider: InMemoryMemoryProvider) -> None:
        assert await provider.get_active_goal("u1", "absent") is None


class TestSessionState:

    @pytest.mark.asyncio
    async def test_save_and_get_session_state(self, provider: InMemoryMemoryProvider) -> None:
        await provider.save_session_state("u1", "t1", "coach", ["finuslugi"])
        state = await provider.get_session_state("u1", "t1")
        assert state is not None
        assert state["role_id"] == "coach"
        assert state["active_skill_ids"] == ["finuslugi"]
        # Delegation defaults
        assert state["delegated_from"] is None
        assert state["delegation_turn_count"] == 0
        assert state["pending_delegation"] is None
        assert state["delegation_summary"] is None

    @pytest.mark.asyncio
    async def test_get_session_state_none(self, provider: InMemoryMemoryProvider) -> None:
        assert await provider.get_session_state("u1", "absent") is None

    @pytest.mark.asyncio
    async def test_session_state_delegation_persist(self, provider: InMemoryMemoryProvider) -> None:
        """Delegation fields сохраняются и восстанавливаются."""
        await provider.save_session_state(
            "u1", "t1", "deposit_advisor", ["finuslugi"],
            delegated_from="orchestrator",
            delegation_turn_count=5,
            pending_delegation=None,
            delegation_summary="Подбор вклада",
        )
        state = await provider.get_session_state("u1", "t1")
        assert state is not None
        assert state["delegated_from"] == "orchestrator"
        assert state["delegation_turn_count"] == 5
        assert state["delegation_summary"] == "Подбор вклада"


class TestProfile:

    @pytest.mark.asyncio
    async def test_get_user_profile(self, provider: InMemoryMemoryProvider) -> None:
        await provider.upsert_fact("u1", "age", 30)
        profile = await provider.get_user_profile("u1")
        assert profile.user_id == "u1"
        assert profile.facts["age"] == 30


class TestPhaseState:
    """Тесты фазы 5-Phase (R-703)."""

    @pytest.mark.asyncio
    async def test_save_and_get_phase(self, provider: InMemoryMemoryProvider) -> None:
        await provider.save_phase_state("u1", "cushion", "3 мес. резерв")
        phase = await provider.get_phase_state("u1")
        assert phase is not None
        assert phase.phase == "cushion"
        assert phase.notes == "3 мес. резерв"

    @pytest.mark.asyncio
    async def test_get_phase_none(self, provider: InMemoryMemoryProvider) -> None:
        assert await provider.get_phase_state("absent") is None

    @pytest.mark.asyncio
    async def test_phase_update(self, provider: InMemoryMemoryProvider) -> None:
        await provider.save_phase_state("u1", "expenses")
        await provider.save_phase_state("u1", "debts", "Кредит погашен на 50%")
        phase = await provider.get_phase_state("u1")
        assert phase.phase == "debts"
        assert phase.notes == "Кредит погашен на 50%"


class TestToolEvents:
    """Тесты событий инструментов (§9.1)."""

    @pytest.mark.asyncio
    async def test_save_tool_event(self, provider: InMemoryMemoryProvider) -> None:
        event = ToolEvent(
            topic_id="t1",
            tool_name="mcp__finuslugi__get_bank_deposits",
            input_json={"limit": 5},
            output_json={"deposits": []},
            latency_ms=150,
        )
        await provider.save_tool_event("u1", event)
        assert len(provider._tool_events) == 1
        assert provider._tool_events[0]["tool_name"] == "mcp__finuslugi__get_bank_deposits"
        assert provider._tool_events[0]["latency_ms"] == 150
