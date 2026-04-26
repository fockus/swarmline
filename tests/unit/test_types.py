"""Tests for bazovyh tipov: TurnContext, ContextPack, SkillSet."""

import pytest
from swarmline.types import ContextPack, SkillSet, TurnContext


class TestTurnContext:
    """TurnContext - edinyy context turn'a (sektsiya 17 arhitektury)."""

    def test_create(self) -> None:
        """Createdie with obyazatelnymi polyami."""
        ctx = TurnContext(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            model="sonnet",
            active_skill_ids=("iss", "funds"),
        )
        assert ctx.user_id == "u1"
        assert ctx.topic_id == "t1"
        assert ctx.role_id == "coach"
        assert ctx.model == "sonnet"
        assert ctx.active_skill_ids == ("iss", "funds")

    def test_frozen(self) -> None:
        """TurnContext notizmenyaem (frozen dataclass)."""
        ctx = TurnContext(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            model="sonnet",
            active_skill_ids=(),
        )
        with pytest.raises(AttributeError):
            ctx.user_id = "u2"  # type: ignore[misc]

    def test_hashable(self) -> None:
        """TurnContext mozhno use kak klyuch dict."""
        ctx1 = TurnContext(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            model="sonnet",
            active_skill_ids=("iss",),
        )
        ctx2 = TurnContext(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            model="sonnet",
            active_skill_ids=("iss",),
        )
        assert hash(ctx1) == hash(ctx2)
        assert ctx1 == ctx2
        assert {ctx1: 1}[ctx2] == 1

    def test_different_skills_not_equal(self) -> None:
        """TurnContext with raznymi skills - raznye obekty."""
        ctx1 = TurnContext(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            model="sonnet",
            active_skill_ids=("iss",),
        )
        ctx2 = TurnContext(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            model="sonnet",
            active_skill_ids=("funds",),
        )
        assert ctx1 != ctx2


class TestContextPack:
    """ContextPack - edinitsa contexta with prioritetom (sektsiya 17 arhitektury)."""

    def test_create(self) -> None:
        """Createdie with obyazatelnymi polyami."""
        pack = ContextPack(
            pack_id="guardrails",
            priority=0,
            content="Не давай инвестрекомендаций.",
            tokens_estimate=10,
        )
        assert pack.pack_id == "guardrails"
        assert pack.priority == 0
        assert pack.content == "Не давай инвестрекомендаций."
        assert pack.tokens_estimate == 10

    def test_frozen(self) -> None:
        """ContextPack notizmenyaem."""
        pack = ContextPack(
            pack_id="role",
            priority=1,
            content="text",
            tokens_estimate=5,
        )
        with pytest.raises(AttributeError):
            pack.content = "new"  # type: ignore[misc]

    def test_sort_by_priority(self) -> None:
        """ContextPack mozhno sortirovat by prioritetu."""
        packs = [
            ContextPack(pack_id="summary", priority=6, content="s", tokens_estimate=1),
            ContextPack(
                pack_id="guardrails", priority=0, content="g", tokens_estimate=1
            ),
            ContextPack(pack_id="role", priority=1, content="r", tokens_estimate=1),
        ]
        sorted_packs = sorted(packs, key=lambda p: p.priority)
        assert [p.pack_id for p in sorted_packs] == ["guardrails", "role", "summary"]


class TestSkillSet:
    """SkillSet - imenovannyy set skilov (sektsiya 5.1 arhitektury)."""

    def test_create(self) -> None:
        """Createdie with id, skilami and local tools."""
        ss = SkillSet(
            set_id="deposits_basic",
            skill_ids=("finuslugi", "funds", "iss-price"),
            local_tool_ids=("calculate_goal_plan",),
        )
        assert ss.set_id == "deposits_basic"
        assert "finuslugi" in ss.skill_ids
        assert "calculate_goal_plan" in ss.local_tool_ids

    def test_frozen(self) -> None:
        """SkillSet notizmenyaem."""
        ss = SkillSet(set_id="x", skill_ids=(), local_tool_ids=())
        with pytest.raises(AttributeError):
            ss.set_id = "y"  # type: ignore[misc]

    def test_empty_defaults(self) -> None:
        """Empty set without tools."""
        ss = SkillSet(set_id="coach_set")
        assert ss.skill_ids == ()
        assert ss.local_tool_ids == ()
