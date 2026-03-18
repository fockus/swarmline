"""Tests for DefaultContextBuilder and ContextBudget."""

from pathlib import Path

import pytest
from cognitia.context import (
    ContextBudget,
    ContextInput,
    DefaultContextBuilder,
    estimate_tokens,
    truncate_to_budget,
)
from cognitia.memory.types import UserProfile
from cognitia.skills.types import LoadedSkill, SkillSpec


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """Create vremennuyu directory with promptami."""
    (tmp_path / "identity.md").write_text("Ты — Freedom AI, финансовый ментор.")
    (tmp_path / "guardrails.md").write_text("Не давай инвестрекомендаций.")

    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "coach.md").write_text("Ты в роли коуча. Мотивируй.")
    (roles_dir / "diagnostician.md").write_text("Проведи диагностику.")

    return tmp_path


@pytest.fixture
def builder(prompts_dir: Path) -> DefaultContextBuilder:
    return DefaultContextBuilder(prompts_dir)


class TestEstimateTokens:
    """Tests otsenki tokenov."""

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 1  # minimum 1

    def test_short_string(self) -> None:
        # "hello" = 5 chars -> ~1-2 tokens
        result = estimate_tokens("hello")
        assert result >= 1

    def test_longer_string(self) -> None:
        text = "a" * 400  # 400 chars -> ~100 tokens
        result = estimate_tokens(text)
        assert result == 101  # 400 // 4 + 1


class TestTruncateToBudget:
    """Tests obrezki teksta by byudzhetu."""

    def test_short_text_not_truncated(self) -> None:
        text = "short"
        result = truncate_to_budget(text, 100)
        assert result == text

    def test_long_text_truncated(self) -> None:
        text = "a" * 1000
        result = truncate_to_budget(text, 10)  # 10 * 4 = 40 chars
        assert len(result) < 1000
        assert "[обрезано]" in result


class TestDefaultContextBuilder:
    """Tests sborki contexta."""

    @pytest.mark.asyncio
    async def test_basic_prompt(self, builder: DefaultContextBuilder) -> None:
        """Basic prompt contains identity and guardrails."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="unknown_role",
            user_text="привет",
            active_skill_ids=[],
        )
        result = await builder.build(inp)
        assert "Freedom AI" in result.system_prompt
        assert "инвестрекомендаций" in result.system_prompt

    @pytest.mark.asyncio
    async def test_role_included(self, builder: DefaultContextBuilder) -> None:
        """Prompt contains tekst roli."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        result = await builder.build(inp)
        assert "коуча" in result.system_prompt

    @pytest.mark.asyncio
    async def test_goal_included(self, builder: DefaultContextBuilder) -> None:
        """Prompt contains aktivnuyu tsel."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        goal_text = "\n".join(
            [
                "- Название: Накопить 300к",
                "- Целевая сумма: 300,000",
                "- Текущий прогресс: 50,000",
                "- Фаза: savings",
            ]
        )
        result = await builder.build(inp, goal_text=goal_text)
        assert "Накопить 300к" in result.system_prompt
        assert "300,000" in result.system_prompt

    @pytest.mark.asyncio
    async def test_user_profile_included(self, builder: DefaultContextBuilder) -> None:
        """Prompt contains fakty o polzovatele."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        profile = UserProfile(user_id="u1", facts={"income": 100000, "risk": "medium"})
        result = await builder.build(inp, user_profile=profile)
        assert "income" in result.system_prompt

    @pytest.mark.asyncio
    async def test_skill_instruction_included(self, builder: DefaultContextBuilder) -> None:
        """Prompt contains instruktsiyu aktivnogo skilla."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=["iss"],
        )
        skill = LoadedSkill(
            spec=SkillSpec(
                skill_id="iss",
                title="MOEX ISS",
                instruction_file="skills/iss/INSTRUCTION.md",
            ),
            instruction_md="Используй для поиска ценных бумаг на MOEX.",
        )
        result = await builder.build(inp, skills=[skill])
        assert "MOEX ISS" in result.system_prompt

    @pytest.mark.asyncio
    async def test_truncated_packs_reported(self, builder: DefaultContextBuilder) -> None:
        """Pri prevyshenii byudzheta pakety are truncated."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
            budget=ContextBudget(total_tokens=50),  # Ochen malenkiy byudzhet
        )
        result = await builder.build(inp, summary="x" * 10000)
        assert "summary" in result.truncated_packs

    @pytest.mark.asyncio
    async def test_notes_contain_metadata(self, builder: DefaultContextBuilder) -> None:
        """Notes soderzhat metadata."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=["iss"],
        )
        result = await builder.build(inp)
        assert result.notes["role_id"] == "coach"
        assert "iss" in result.notes["active_skills"]

    @pytest.mark.asyncio
    async def test_memory_recall_included(self, builder: DefaultContextBuilder) -> None:
        """P3: Memory recall - kross-topic fakty vklyuchayutsya in prompt (GAP-1, §10.1)."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        recall = {"income": "150000", "main_goal": "квартира"}
        result = await builder.build(inp, recall_facts=recall)
        assert "Воспоминания из прошлых диалогов" in result.system_prompt
        assert "income" in result.system_prompt
        assert "квартира" in result.system_prompt

    @pytest.mark.asyncio
    async def test_memory_recall_truncated(self, builder: DefaultContextBuilder) -> None:
        """P3: Memory recall obrezaetsya pri prevyshenii memory_max."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
            budget=ContextBudget(memory_max=10),  # Ochen malenkiy limit
        )
        recall = {f"fact_{i}": "x" * 100 for i in range(20)}
        result = await builder.build(inp, recall_facts=recall)
        assert "memory_recall" in result.truncated_packs

    @pytest.mark.asyncio
    async def test_role_deducts_remaining(self, builder: DefaultContextBuilder) -> None:
        """Rol considerssya in remaining budget (GAP-7)."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
            budget=ContextBudget(total_tokens=100),  # Malenkiy byudzhet
        )
        # S rolyu tool_budget should byt menshe chem without
        result_with_role = await builder.build(inp)
        inp_no_role = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="nonexistent",
            user_text="привет",
            active_skill_ids=[],
            budget=ContextBudget(total_tokens=100),
        )
        result_no_role = await builder.build(inp_no_role)
        assert result_with_role.tool_budget <= result_no_role.tool_budget

    @pytest.mark.asyncio
    async def test_budget_overflow_drops_low_priority(self, builder: DefaultContextBuilder) -> None:
        """Pri budget overflow nizkoprioritetnye pakety dropayutsya (GAP-5, §10.3)."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
            # Malenkiy byudzhet - hvatit tolko on guardrails + role
            budget=ContextBudget(total_tokens=50),
        )
        goal_text = "\n".join(
            [
                "- Название: Test",
                "- Целевая сумма: 100,000",
                "- Фаза: expenses",
            ]
        )
        phase_text = "- Фаза: expenses"
        profile = UserProfile(user_id="u1", facts={"income": "100k"})
        recall = {"key": "val"}

        result = await builder.build(
            inp,
            goal_text=goal_text,
            phase_text=phase_text,
            user_profile=profile,
            recall_facts=recall,
            summary="long " * 1000,
        )

        # Guardrails and rol vsegda est
        assert "Freedom AI" in result.system_prompt
        # Nizkoprioritetnye should byt dropnuty
        dropped = result.truncated_packs
        # Hotya by summary should byt dropnut
        assert "summary" in dropped


# ---------------------------------------------------------------------------
# P2.5: Poslednie messages dialoga (last_messages)
# ---------------------------------------------------------------------------
from cognitia.memory.types import MemoryMessage  # noqa: E402


class TestContextBuilderLastMessages:
    """Tests for pack P2.5 - poslednie messages dialoga."""

    @staticmethod
    def _make_inp(role_id: str = "coach", budget: ContextBudget | None = None) -> ContextInput:
        return ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id=role_id,
            user_text="тест",
            active_skill_ids=[],
            budget=budget or ContextBudget(),
        )

    @pytest.mark.asyncio
    async def test_last_messages_included_in_prompt(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """If last_messages peredany, oni poyavlyayutsya in system_prompt."""
        messages = [
            MemoryMessage(role="user", content="Мой доход 120 000 рублей"),
            MemoryMessage(role="assistant", content="Отлично! Давайте разберём бюджет."),
        ]
        result = await builder.build(self._make_inp(), last_messages=messages)
        assert "Последние сообщения" in result.system_prompt
        assert "120 000" in result.system_prompt
        assert "разберём бюджет" in result.system_prompt

    @pytest.mark.asyncio
    async def test_last_messages_empty_list_no_pack(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """Empty list last_messages - pack not is added."""
        result = await builder.build(self._make_inp(), last_messages=[])
        assert "Последние сообщения" not in result.system_prompt

    @pytest.mark.asyncio
    async def test_last_messages_none_no_pack(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """last_messages=None - pack not is added."""
        result = await builder.build(self._make_inp(), last_messages=None)
        assert "Последние сообщения" not in result.system_prompt

    @pytest.mark.asyncio
    async def test_last_messages_truncated_by_budget(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """Dlinnye messages are truncated by budget.messages_max."""
        inp = self._make_inp(budget=ContextBudget(messages_max=100))
        messages = [
            MemoryMessage(role="user", content="A" * 2000),
        ]
        result = await builder.build(inp, last_messages=messages)
        assert "Последние сообщения" in result.system_prompt
        assert "last_messages" in result.truncated_packs

    @pytest.mark.asyncio
    async def test_messages_max_in_context_budget(self) -> None:
        """ContextBudget imeet pole messages_max."""
        budget = ContextBudget(messages_max=1500)
        assert budget.messages_max == 1500

    @pytest.mark.asyncio
    async def test_default_messages_max(self) -> None:
        """Po umolchaniyu messages_max = 2000."""
        budget = ContextBudget()
        assert budget.messages_max == 2000


class TestContextBuilderHotReload:
    """Tests hot-reload promptov - files perechityvayutsya pri izmenotnii on diske."""

    @pytest.mark.asyncio
    async def test_role_file_change_picked_up(self, prompts_dir: Path) -> None:
        """Izmenennyy file roli podhvatyvaetsya without perezapuska."""
        builder = DefaultContextBuilder(prompts_dir)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        result1 = await builder.build(inp)
        assert "коуча" in result1.system_prompt

        # Menyaem file roli on diske
        role_file = prompts_dir / "roles" / "coach.md"
        role_file.write_text("Ты новый суперкоуч!")
        # Garantiruem otlichie mtime (notkotorye FS imeyut sekundnuyu tochnost)
        import os
        import time

        os.utime(role_file, (time.time() + 1, time.time() + 1))

        result2 = await builder.build(inp)
        assert "суперкоуч" in result2.system_prompt
        assert "коуча" not in result2.system_prompt

    @pytest.mark.asyncio
    async def test_identity_file_change_picked_up(self, prompts_dir: Path) -> None:
        """Izmenennyy identity.md podhvatyvaetsya without perezapuska."""
        builder = DefaultContextBuilder(prompts_dir)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        result1 = await builder.build(inp)
        assert "Freedom AI" in result1.system_prompt

        # Menyaem identity
        identity_file = prompts_dir / "identity.md"
        identity_file.write_text("Ты — Мегабот, финансовый гуру.")
        import os
        import time

        os.utime(identity_file, (time.time() + 1, time.time() + 1))

        result2 = await builder.build(inp)
        assert "Мегабот" in result2.system_prompt
        assert "Freedom AI" not in result2.system_prompt

    @pytest.mark.asyncio
    async def test_new_role_file_picked_up(self, prompts_dir: Path) -> None:
        """New file roli podhvatyvaetsya without perezapuska."""
        builder = DefaultContextBuilder(prompts_dir)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="wizard",
            user_text="привет",
            active_skill_ids=[],
        )
        result1 = await builder.build(inp)
        assert "волшебник" not in result1.system_prompt

        # Add novuyu rol
        (prompts_dir / "roles" / "wizard.md").write_text("Ты финансовый волшебник!")

        result2 = await builder.build(inp)
        assert "волшебник" in result2.system_prompt

    @pytest.mark.asyncio
    async def test_no_reload_when_files_unchanged(self, prompts_dir: Path) -> None:
        """If files not menyalis - povtornaya loading not proishodit."""
        builder = DefaultContextBuilder(prompts_dir)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        result1 = await builder.build(inp)
        result2 = await builder.build(inp)
        # Kontent odinakovyy - prompt_hash sovfails
        assert result1.prompt_hash == result2.prompt_hash
