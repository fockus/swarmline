"""Тесты для DefaultContextBuilder и ContextBudget."""

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
    """Создать временную директорию с промптами."""
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
    """Тесты оценки токенов."""

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 1  # минимум 1

    def test_short_string(self) -> None:
        # "hello" = 5 chars -> ~1-2 tokens
        result = estimate_tokens("hello")
        assert result >= 1

    def test_longer_string(self) -> None:
        text = "a" * 400  # 400 chars -> ~100 tokens
        result = estimate_tokens(text)
        assert result == 101  # 400 // 4 + 1


class TestTruncateToBudget:
    """Тесты обрезки текста по бюджету."""

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
    """Тесты сборки контекста."""

    @pytest.mark.asyncio
    async def test_basic_prompt(self, builder: DefaultContextBuilder) -> None:
        """Базовый промпт содержит identity и guardrails."""
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
        """Промпт содержит текст роли."""
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
        """Промпт содержит активную цель."""
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
        """Промпт содержит факты о пользователе."""
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
        """Промпт содержит инструкцию активного скилла."""
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
        """При превышении бюджета пакеты обрезаются."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
            budget=ContextBudget(total_tokens=50),  # Очень маленький бюджет
        )
        result = await builder.build(inp, summary="x" * 10000)
        assert "summary" in result.truncated_packs

    @pytest.mark.asyncio
    async def test_notes_contain_metadata(self, builder: DefaultContextBuilder) -> None:
        """Notes содержат метаданные."""
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
        """P3: Memory recall — кросс-topic факты включаются в prompt (GAP-1, §10.1)."""
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
        """P3: Memory recall обрезается при превышении memory_max."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
            budget=ContextBudget(memory_max=10),  # Очень маленький лимит
        )
        recall = {f"fact_{i}": "x" * 100 for i in range(20)}
        result = await builder.build(inp, recall_facts=recall)
        assert "memory_recall" in result.truncated_packs

    @pytest.mark.asyncio
    async def test_role_deducts_remaining(self, builder: DefaultContextBuilder) -> None:
        """Роль учитывается в remaining budget (GAP-7)."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
            budget=ContextBudget(total_tokens=100),  # Маленький бюджет
        )
        # С ролью tool_budget должен быть меньше чем без
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
        """При budget overflow низкоприоритетные пакеты дропаются (GAP-5, §10.3)."""
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            user_text="привет",
            active_skill_ids=[],
            # Маленький бюджет — хватит только на guardrails + role
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
            user_profile=profile, recall_facts=recall, summary="long " * 1000,
        )

        # Guardrails и роль всегда есть
        assert "Freedom AI" in result.system_prompt
        # Низкоприоритетные должны быть дропнуты
        dropped = result.truncated_packs
        # Хотя бы summary должен быть дропнут
        assert "summary" in dropped


# ---------------------------------------------------------------------------
# P2.5: Последние сообщения диалога (last_messages)
# ---------------------------------------------------------------------------
from cognitia.memory.types import MemoryMessage


class TestContextBuilderLastMessages:
    """Тесты для pack P2.5 — последние сообщения диалога."""

    @staticmethod
    def _make_inp(role_id: str = "coach", budget: ContextBudget | None = None) -> ContextInput:
        return ContextInput(
            user_id="u1", topic_id="t1", role_id=role_id,
            user_text="тест", active_skill_ids=[],
            budget=budget or ContextBudget(),
        )

    @pytest.mark.asyncio
    async def test_last_messages_included_in_prompt(
        self, builder: DefaultContextBuilder,
    ) -> None:
        """Если last_messages переданы, они появляются в system_prompt."""
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
        self, builder: DefaultContextBuilder,
    ) -> None:
        """Пустой список last_messages — pack не добавляется."""
        result = await builder.build(self._make_inp(), last_messages=[])
        assert "Последние сообщения" not in result.system_prompt

    @pytest.mark.asyncio
    async def test_last_messages_none_no_pack(
        self, builder: DefaultContextBuilder,
    ) -> None:
        """last_messages=None — pack не добавляется."""
        result = await builder.build(self._make_inp(), last_messages=None)
        assert "Последние сообщения" not in result.system_prompt

    @pytest.mark.asyncio
    async def test_last_messages_truncated_by_budget(
        self, builder: DefaultContextBuilder,
    ) -> None:
        """Длинные сообщения обрезаются по budget.messages_max."""
        inp = self._make_inp(budget=ContextBudget(messages_max=100))
        messages = [
            MemoryMessage(role="user", content="A" * 2000),
        ]
        result = await builder.build(inp, last_messages=messages)
        assert "Последние сообщения" in result.system_prompt
        assert "last_messages" in result.truncated_packs

    @pytest.mark.asyncio
    async def test_messages_max_in_context_budget(self) -> None:
        """ContextBudget имеет поле messages_max."""
        budget = ContextBudget(messages_max=1500)
        assert budget.messages_max == 1500

    @pytest.mark.asyncio
    async def test_default_messages_max(self) -> None:
        """По умолчанию messages_max = 2000."""
        budget = ContextBudget()
        assert budget.messages_max == 2000


class TestContextBuilderHotReload:
    """Тесты hot-reload промптов — файлы перечитываются при изменении на диске."""

    @pytest.mark.asyncio
    async def test_role_file_change_picked_up(self, prompts_dir: Path) -> None:
        """Изменённый файл роли подхватывается без перезапуска."""
        builder = DefaultContextBuilder(prompts_dir)
        inp = ContextInput(
            user_id="u1", topic_id="t1", role_id="coach",
            user_text="привет", active_skill_ids=[],
        )
        result1 = await builder.build(inp)
        assert "коуча" in result1.system_prompt

        # Меняем файл роли на диске
        role_file = prompts_dir / "roles" / "coach.md"
        role_file.write_text("Ты новый суперкоуч!")
        # Гарантируем отличие mtime (некоторые FS имеют секундную точность)
        import os
        import time
        os.utime(role_file, (time.time() + 1, time.time() + 1))

        result2 = await builder.build(inp)
        assert "суперкоуч" in result2.system_prompt
        assert "коуча" not in result2.system_prompt

    @pytest.mark.asyncio
    async def test_identity_file_change_picked_up(self, prompts_dir: Path) -> None:
        """Изменённый identity.md подхватывается без перезапуска."""
        builder = DefaultContextBuilder(prompts_dir)
        inp = ContextInput(
            user_id="u1", topic_id="t1", role_id="coach",
            user_text="привет", active_skill_ids=[],
        )
        result1 = await builder.build(inp)
        assert "Freedom AI" in result1.system_prompt

        # Меняем identity
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
        """Новый файл роли подхватывается без перезапуска."""
        builder = DefaultContextBuilder(prompts_dir)
        inp = ContextInput(
            user_id="u1", topic_id="t1", role_id="wizard",
            user_text="привет", active_skill_ids=[],
        )
        result1 = await builder.build(inp)
        assert "волшебник" not in result1.system_prompt

        # Добавляем новую роль
        (prompts_dir / "roles" / "wizard.md").write_text("Ты финансовый волшебник!")

        result2 = await builder.build(inp)
        assert "волшебник" in result2.system_prompt

    @pytest.mark.asyncio
    async def test_no_reload_when_files_unchanged(self, prompts_dir: Path) -> None:
        """Если файлы не менялись — повторная загрузка не происходит."""
        builder = DefaultContextBuilder(prompts_dir)
        inp = ContextInput(
            user_id="u1", topic_id="t1", role_id="coach",
            user_text="привет", active_skill_ids=[],
        )
        result1 = await builder.build(inp)
        result2 = await builder.build(inp)
        # Контент одинаковый — prompt_hash совпадает
        assert result1.prompt_hash == result2.prompt_hash
