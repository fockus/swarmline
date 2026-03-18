"""Integration: DefaultContextBuilder + ContextBudget + Skills - assembly system_prompt. Scenario: real assembly contexta with rolyu, skillami, profilem, tselyu and summary.
Verify sloi, byudzhet, truncation.
"""

from pathlib import Path

import pytest
from cognitia.context.budget import ContextBudget
from cognitia.context.builder import BuiltContext, ContextInput, DefaultContextBuilder
from cognitia.memory.types import UserProfile
from cognitia.skills.types import LoadedSkill, McpServerSpec, SkillSpec


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """Create directory with promptami for testov."""
    # identity.md
    (tmp_path / "identity.md").write_text("Ты — Freedom, финансовый AI-помощник.", encoding="utf-8")
    # guardrails.md
    (tmp_path / "guardrails.md").write_text(
        "Никогда не давай конкретных инвестиционных рекомендаций.\n"
        "Всегда уточняй у пользователя его финансовую ситуацию.",
        encoding="utf-8",
    )
    # roles/
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "coach.md").write_text(
        "Роль: финансовый коуч. Задавай вопросы. Помогай ставить цели.",
        encoding="utf-8",
    )
    (roles_dir / "deposit_advisor.md").write_text(
        "Роль: советник по вкладам. Сравнивай ставки. Учитывай срок и сумму.",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def builder(prompts_dir: Path) -> DefaultContextBuilder:
    return DefaultContextBuilder(prompts_dir)


@pytest.fixture
def iss_skill() -> LoadedSkill:
    spec = SkillSpec(
        skill_id="iss",
        title="Московская биржа (ISS)",
        instruction_file="skills/iss/INSTRUCTION.md",
        mcp_servers=[McpServerSpec(name="iss", url="https://calculado.ru/iss/mcp")],
        tool_include=["mcp__iss__get_emitent_id", "mcp__iss__get_bonds"],
    )
    return LoadedSkill(
        spec=spec,
        instruction_md="Используй ISS API для поиска облигаций и эмитентов.",
    )


@pytest.fixture
def finuslugi_skill() -> LoadedSkill:
    spec = SkillSpec(
        skill_id="finuslugi",
        title="Финуслуги",
        instruction_file="skills/finuslugi/INSTRUCTION.md",
        mcp_servers=[McpServerSpec(name="finuslugi", url="https://calculado.ru/finuslugi/mcp")],
        tool_include=["mcp__finuslugi__search_deposits"],
    )
    return LoadedSkill(
        spec=spec,
        instruction_md="Используй Финуслуги для поиска и сравнения вкладов.",
    )


class TestBasicAssembly:
    """Basic assembly - identity + guardrails + rol."""

    @pytest.mark.asyncio
    async def test_identity_and_guardrails_always_present(
        self, builder: DefaultContextBuilder
    ) -> None:
        """Identity and guardrails vsegda in prompte."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        result = await builder.build(inp)
        assert "Freedom" in result.system_prompt
        assert "инвестиционных рекомендаций" in result.system_prompt

    @pytest.mark.asyncio
    async def test_role_included(self, builder: DefaultContextBuilder) -> None:
        """Rol vklyuchena in prompt."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        result = await builder.build(inp)
        assert "финансовый коуч" in result.system_prompt

    @pytest.mark.asyncio
    async def test_missing_role_no_error(self, builder: DefaultContextBuilder) -> None:
        """Notsushchestvuyushchaya rol - not fails, prosto without roli."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="unknown_role",
            user_text="привет",
            active_skill_ids=[],
        )
        result = await builder.build(inp)
        assert "Freedom" in result.system_prompt


class TestWithSkills:
    """Sborka with aktivnymi skillami."""

    @pytest.mark.asyncio
    async def test_skill_instructions_added(
        self, builder: DefaultContextBuilder, iss_skill: LoadedSkill
    ) -> None:
        """Instruktsii aktivnyh skillov are added."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="облигации",
            active_skill_ids=["iss"],
        )
        result = await builder.build(inp, skills=[iss_skill])
        assert "ISS API" in result.system_prompt

    @pytest.mark.asyncio
    async def test_inactive_skill_not_included(
        self, builder: DefaultContextBuilder, iss_skill: LoadedSkill
    ) -> None:
        """Notactive skill not is added."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=["finuslugi"],
        )
        result = await builder.build(inp, skills=[iss_skill])
        assert "ISS API" not in result.system_prompt

    @pytest.mark.asyncio
    async def test_multiple_skills(
        self,
        builder: DefaultContextBuilder,
        iss_skill: LoadedSkill,
        finuslugi_skill: LoadedSkill,
    ) -> None:
        """Notskolko aktivnyh skillov."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="deposit_advisor",
            user_text="вклад или облигации?",
            active_skill_ids=["iss", "finuslugi"],
        )
        result = await builder.build(inp, skills=[iss_skill, finuslugi_skill])
        assert "ISS API" in result.system_prompt
        assert "Финуслуги" in result.system_prompt


class TestWithGoalAndProfile:
    """Sborka with tselyu user and profilem."""

    @pytest.mark.asyncio
    async def test_goal_included(self, builder: DefaultContextBuilder) -> None:
        """TSel user vklyuchena in context."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="как дела",
            active_skill_ids=[],
        )
        goal_text = "\n".join(
            [
                "- Название: Накопить на автомобиль",
                "- Целевая сумма: 2,000,000",
                "- Текущий прогресс: 300,000",
                "- Фаза: savings",
            ]
        )
        result = await builder.build(inp, goal_text=goal_text)
        assert "Накопить на автомобиль" in result.system_prompt
        assert "savings" in result.system_prompt
        assert "2,000,000" in result.system_prompt

    @pytest.mark.asyncio
    async def test_profile_facts_included(self, builder: DefaultContextBuilder) -> None:
        """Fakty profilya included in context."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        profile = UserProfile(
            user_id="u1",
            facts={"возраст": "32", "доход": "150000"},
        )
        result = await builder.build(inp, user_profile=profile)
        assert "возраст" in result.system_prompt
        assert "150000" in result.system_prompt

    @pytest.mark.asyncio
    async def test_empty_profile_not_added(self, builder: DefaultContextBuilder) -> None:
        """Empty profil not dobavlyaet sektsiyu."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        profile = UserProfile(user_id="u1", facts={})
        result = await builder.build(inp, user_profile=profile)
        assert "Профиль пользователя" not in result.system_prompt


class TestSummaryAndBudget:
    """Sborka with summary and byudzhetirovanie."""

    @pytest.mark.asyncio
    async def test_summary_included(self, builder: DefaultContextBuilder) -> None:
        """Summary vklyuchen in context."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="продолжим",
            active_skill_ids=[],
        )
        result = await builder.build(inp, summary="Обсуждали вклады в Сбере.")
        assert "Обсуждали вклады" in result.system_prompt

    @pytest.mark.asyncio
    async def test_summary_truncated_on_overflow(self, builder: DefaultContextBuilder) -> None:
        """Summary obrezaetsya pri prevyshenii byudzheta."""
        tiny_budget = ContextBudget(total_tokens=500, summary_max=50)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="",
            active_skill_ids=[],
            budget=tiny_budget,
        )
        long_summary = "Обсуждение " * 500
        result = await builder.build(inp, summary=long_summary)
        assert "обрезано" in result.system_prompt or "summary" in result.truncated_packs

    @pytest.mark.asyncio
    async def test_truncated_packs_tracked(self, builder: DefaultContextBuilder) -> None:
        """Otslezhivanie obrezannyh paketov."""
        tiny_budget = ContextBudget(total_tokens=200, goal_max=10)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="",
            active_skill_ids=[],
            budget=tiny_budget,
        )
        goal_text = "- Название: " + ("Очень длинное название цели " * 50)
        result = await builder.build(inp, goal_text=goal_text)
        assert "active_goal" in result.truncated_packs

    @pytest.mark.asyncio
    async def test_notes_contain_metadata(self, builder: DefaultContextBuilder) -> None:
        """BuiltContext.notes contains metadata."""
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


class TestPhasePack:
    """Tests Phase pack in contexte."""

    @pytest.mark.asyncio
    async def test_phase_included_in_context(self, builder: DefaultContextBuilder) -> None:
        """Phase text includessya in system_prompt."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="план",
            active_skill_ids=[],
        )
        phase_text = "- Фаза: cushion\n- Заметки: Собрал 1 мес. расходов"
        result = await builder.build(inp, phase_text=phase_text)
        assert "## Текущая фаза" in result.system_prompt
        assert "cushion" in result.system_prompt

    @pytest.mark.asyncio
    async def test_phase_includes_next_phase(self, builder: DefaultContextBuilder) -> None:
        """Phase pack includes sleduyushchuyu fazu, if tekst ee contains."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="что дальше",
            active_skill_ids=[],
        )
        phase_text = "- Фаза: expenses\n- Следующая фаза: cushion"
        result = await builder.build(inp, phase_text=phase_text)
        assert "Следующая" in result.system_prompt

    @pytest.mark.asyncio
    async def test_phase_notes_in_context(self, builder: DefaultContextBuilder) -> None:
        """Zametki fazy included in context."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="прогресс",
            active_skill_ids=[],
        )
        phase_text = "- Фаза: debts\n- Заметки: Кредит погашен на 70%"
        result = await builder.build(inp, phase_text=phase_text)
        assert "Кредит погашен на 70%" in result.system_prompt

    @pytest.mark.asyncio
    async def test_no_phase_no_pack(self, builder: DefaultContextBuilder) -> None:
        """Without phase_text - nott Phase pack."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
        )
        result = await builder.build(inp, phase_text=None)
        assert "5-Phase" not in result.system_prompt


class TestBudgetEdgeCases:
    """Edge cases for byudzheta - kritichnye scenarios (§10.3)."""

    @pytest.mark.asyncio
    async def test_guardrails_always_survive_tiny_budget(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """P0 Guardrails VSEGDA ostayutsya dazhe pri minimalnom byudzhete. Eto KRITICHNYY test withoutopasnosti: identity + guardrails not should byt obrezany ni pri kakih usloviyah. """
        # Byudzhet = 50 tokenov - menshe chem guardrails, no oni vse ravno est
        tiny = ContextBudget(total_tokens=50, summary_max=10)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="",
            active_skill_ids=[],
            budget=tiny,
        )
        result = await builder.build(
            inp,
            summary="Очень длинный summary " * 100,
            goal_text="- Название: " + ("Цель " * 50),
        )
        # Identity and guardrails VSEGDA on meste
        assert "Freedom" in result.system_prompt
        assert "рекомендаций" in result.system_prompt

    @pytest.mark.asyncio
    async def test_summary_dropped_first_on_overflow(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """Summary (P5) otbrasyvaetsya pervym pri nothvatke byudzheta."""
        # Byudzhet chut bolshe guardrails, no not hvataet for summary
        budget = ContextBudget(total_tokens=200, summary_max=50)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="",
            active_skill_ids=[],
            budget=budget,
        )
        huge_summary = "Очень длинный текст " * 500
        result = await builder.build(inp, summary=huge_summary)
        assert "summary" in result.truncated_packs

    @pytest.mark.asyncio
    async def test_all_packs_exceed_budget_guardrails_remain(
        self,
        builder: DefaultContextBuilder,
        iss_skill: LoadedSkill,
    ) -> None:
        """Vse pakety prevyshayut byudzhet - guardrails ostayutsya, ostalnoe obrezano/otbrosheno."""
        budget = ContextBudget(
            total_tokens=100,
            goal_max=5,
            tools_max=5,
            profile_max=5,
            summary_max=5,
        )
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="",
            active_skill_ids=["iss"],
            budget=budget,
        )
        result = await builder.build(
            inp,
            skills=[iss_skill],
            user_profile=UserProfile(user_id="u1", facts={"key": "v" * 1000}),
            goal_text="- Название: " + ("A" * 1000),
            summary="S" * 5000,
        )
        # Guardrails on meste
        assert "Freedom" in result.system_prompt
        # CHto-to bylo obrezano
        assert len(result.truncated_packs) > 0

    @pytest.mark.asyncio
    async def test_negative_remaining_budget_still_works(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """Dazhe pri otritsatelnom remaining byudzhete - sistema not fails."""
        budget = ContextBudget(total_tokens=10)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="",
            active_skill_ids=[],
            budget=budget,
        )
        # Not should byt exception
        result = await builder.build(inp, summary="text " * 100)
        assert isinstance(result, BuiltContext)
        assert result.prompt_hash  # hash vse ravno vychislen

    @pytest.mark.asyncio
    async def test_prompt_hash_changes_with_different_content(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """Raznyy kontent -> raznyy prompt_hash."""
        inp1 = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="",
            active_skill_ids=[],
        )
        inp2 = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="deposit_advisor",
            user_text="",
            active_skill_ids=[],
        )
        h1 = (await builder.build(inp1)).prompt_hash
        h2 = (await builder.build(inp2)).prompt_hash
        assert h1 != h2, "Разные роли → разные prompt_hash"


class TestPromptHash:
    """Tests prompt_hash in BuiltContext (R-300, §12.1)."""

    @pytest.mark.asyncio
    async def test_hash_present(self, builder: DefaultContextBuilder) -> None:
        """prompt_hash prisutstvuet."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="test",
            active_skill_ids=[],
        )
        result = await builder.build(inp)
        assert result.prompt_hash
        assert len(result.prompt_hash) == 16

    @pytest.mark.asyncio
    async def test_hash_deterministic(self, builder: DefaultContextBuilder) -> None:
        """Odinakovyy prompt -> odinakovyy hash."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="test",
            active_skill_ids=[],
        )
        h1 = (await builder.build(inp)).prompt_hash
        h2 = (await builder.build(inp)).prompt_hash
        assert h1 == h2

    @pytest.mark.asyncio
    async def test_hash_in_notes(self, builder: DefaultContextBuilder) -> None:
        """prompt_hash dostupen cherez notes."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="test",
            active_skill_ids=[],
        )
        result = await builder.build(inp)
        assert result.notes["prompt_hash"] == result.prompt_hash
