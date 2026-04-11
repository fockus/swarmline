"""Integration: SessionManager + Rehydrator + RoleRouter + ModelPolicy - zhiznotnnyy tsikl sessions. Scenario: createdie sessions -> opredelenie roli -> selection models -> rehydration.
"""

import warnings
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from swarmline.memory.types import GoalState, MemoryMessage
from swarmline.routing.role_router import KeywordRoleRouter
from swarmline.runtime.model_policy import ModelPolicy
from swarmline.session.manager import InMemorySessionManager
from swarmline.session.rehydrator import DefaultSessionRehydrator
from swarmline.session.types import SessionKey, SessionState
from swarmline.types import TurnContext


def _mock_adapter(connected: bool = True) -> MagicMock:
    adapter = MagicMock()
    type(adapter).is_connected = PropertyMock(return_value=connected)
    adapter.connect = AsyncMock()
    adapter.disconnect = AsyncMock()
    return adapter


@pytest.fixture
def router() -> KeywordRoleRouter:
    return KeywordRoleRouter(
        default_role="coach",
        keyword_map={
            "deposit_advisor": ["вклад", "депозит"],
            "portfolio_builder": ["облигаци", "акции", "портфель"],
            "diagnostician": ["диагностик", "расход"],
            "strategy_planner": ["стратеги", "план на год"],
        },
    )


@pytest.fixture
def model_policy() -> ModelPolicy:
    return ModelPolicy(
        default_model="sonnet",
        escalation_model="opus",
        escalate_roles={"strategy_planner"},
        min_skills_for_escalation=2,
    )


@pytest.fixture
def memory() -> AsyncMock:
    m = AsyncMock()
    m.get_session_state.return_value = {
        "role_id": "deposit_advisor",
        "active_skill_ids": ["finuslugi"],
        "title": "Вклады",
    }
    m.get_summary.return_value = "Обсуждали вклады."
    m.get_messages.return_value = [
        MemoryMessage(role="user", content="какой вклад лучше?"),
    ]
    m.get_active_goal.return_value = GoalState(
        goal_id="g1",
        title="Накопить 500к",
        target_amount=500_000,
        current_amount=100_000,
        phase="savings",
    )
    return m


class TestRoleRoutingToModelSelection:
    """TSepochka: tekst user -> rol -> model."""

    def test_deposit_question_sonnet(
        self, router: KeywordRoleRouter, model_policy: ModelPolicy
    ) -> None:
        """Vopros pro vklady -> deposit_advisor -> sonnet."""
        role = router.resolve("какой вклад выгоднее?")
        assert role == "deposit_advisor"
        model = model_policy.select(role)
        assert model == "sonnet"

    def test_strategy_question_opus(
        self, router: KeywordRoleRouter, model_policy: ModelPolicy
    ) -> None:
        """Vopros pro strategiyu -> strategy_planner -> opus."""
        role = router.resolve("составь стратегию на год")
        assert role == "strategy_planner"
        model = model_policy.select(role)
        assert model == "opus"

    def test_keyword_escalation_to_opus(
        self, router: KeywordRoleRouter, model_policy: ModelPolicy
    ) -> None:
        """Keyword 'plan' in tekste -> opus dazhe for coach."""
        role = router.resolve("привет")
        assert role == "coach"
        model = model_policy.select_for_turn(
            role_id=role,
            user_text="составь план",
        )
        assert model == "opus"

    def test_multi_skill_escalation(
        self, router: KeywordRoleRouter, model_policy: ModelPolicy
    ) -> None:
        """2+ skilla -> opus."""
        role = router.resolve("сравни вклады и облигации")
        model = model_policy.select_for_turn(
            role_id=role,
            user_text="сравни вклады и облигации",
            active_skill_count=2,
        )
        assert model == "opus"


class TestSessionLifecycle:
    """Full zhiznotnnyy tsikl sessions with menotdzherom."""

    @pytest.mark.asyncio
    async def test_create_session_manage_close(self) -> None:
        """Create -> use -> zakryt sessiyu."""
        mgr = InMemorySessionManager()
        key = SessionKey("u1", "t1")
        adapter = _mock_adapter()
        # Suppress DeprecationWarning — intentional legacy-path testing
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            state = SessionState(key=key, adapter=adapter, role_id="coach")

        # Create
        mgr.register(state)
        assert mgr.get(key) is state
        assert len(mgr.list_sessions()) == 1

        # Update rol
        mgr.update_role(key, "deposit_advisor", ["finuslugi"])
        assert mgr.get(key).role_id == "deposit_advisor"
        assert mgr.get(key).active_skill_ids == ["finuslugi"]

        # Zakryt
        await mgr.close(key)
        assert mgr.get(key) is None
        adapter.disconnect.assert_awaited_once()


class TestRehydrationFlow:
    """Rehydration: rehydration sostoyaniya sessions from pamyati."""

    @pytest.mark.asyncio
    async def test_full_rehydration(self, memory: AsyncMock) -> None:
        """Full payload pri nalichii vseh dannyh."""
        # ISP: peredaem 5 melkih store vmesto odnogo monolitnogo MemoryProvider
        memory.get_phase_state.return_value = None
        rehydrator = DefaultSessionRehydrator(
            messages=memory,
            summaries=memory,
            goals=memory,
            sessions=memory,
            phases=memory,
            last_n_messages=5,
        )
        ctx = TurnContext(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            model="sonnet",
            active_skill_ids=(),
        )
        payload = await rehydrator.build_rehydration_payload(ctx)

        assert payload["role_id"] == "deposit_advisor"  # Iz BD, not from ctx
        assert payload["active_skill_ids"] == ["finuslugi"]
        assert "вклады" in payload["summary"].lower()
        assert len(payload["last_messages"]) == 1
        assert payload["goal"].title == "Накопить 500к"

    @pytest.mark.asyncio
    async def test_rehydration_fallback_to_ctx(self, memory: AsyncMock) -> None:
        """Without dannyh in BD - fallback on ctx."""
        memory.get_session_state.return_value = None
        memory.get_phase_state.return_value = None
        rehydrator = DefaultSessionRehydrator(
            messages=memory,
            summaries=memory,
            goals=memory,
            sessions=memory,
            phases=memory,
        )
        ctx = TurnContext(
            user_id="u1",
            topic_id="t1",
            role_id="diagnostician",
            model="sonnet",
            active_skill_ids=("iss",),
        )
        payload = await rehydrator.build_rehydration_payload(ctx)
        assert payload["role_id"] == "diagnostician"
        assert payload["active_skill_ids"] == ["iss"]
