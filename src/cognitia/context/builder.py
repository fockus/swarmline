"""DefaultContextBuilder — сборка system_prompt из контекстных пакетов."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from cognitia.context.budget import ContextBudget, estimate_tokens, truncate_to_budget
from cognitia.memory.types import (
    MemoryMessage,
    UserProfile,
)
from cognitia.skills.types import LoadedSkill


def compute_prompt_hash(prompt: str) -> str:
    """Вычислить SHA256-хеш system_prompt (R-300, §12.1)."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ContextInput:
    """Входные данные для сборки контекста."""

    user_id: str
    topic_id: str
    role_id: str
    user_text: str
    active_skill_ids: list[str]
    budget: ContextBudget = field(default_factory=ContextBudget)


@dataclass(frozen=True)
class BuiltContext:
    """Результат сборки контекста."""

    system_prompt: str
    prompt_hash: str  # SHA256-хеш system_prompt (§12.1)
    tool_budget: int  # сколько tools можно дать в контекст
    truncated_packs: list[str]  # какие пакеты были обрезаны
    notes: dict[str, str] = field(default_factory=dict)


class DefaultContextBuilder:
    """Сборщик system_prompt из многослойных контекстных пакетов.

    Слои (от base к dynamic, §10.1):
    P0: Guardrails (Identity + Guardrails) — никогда не отбрасываются
    P0.5: Role — никогда не отбрасывается, но учитывает remaining
    P1: Goal text
    P1.5: Phase text
    P2: Skill instructions (tool hints)
    P3: Memory recall (кросс-topic факты)
    P4: User profile
    P5: Summary (отбрасывается первым при переполнении, §10.3)

    Hot-reload: файлы промптов перечитываются автоматически при изменении на диске.
    """

    def __init__(self, prompts_dir: str | Path) -> None:
        self._dir = Path(prompts_dir)
        self._identity: str = ""
        self._guardrails: str = ""
        self._roles: dict[str, str] = {}
        self._file_mtimes: dict[Path, float] = {}
        self._reload()

    # ---------- Hot-reload ----------

    def _reload(self) -> None:
        """Загрузить или перезагрузить все промпт-файлы с диска."""
        self._identity = self._load_file("identity.md")
        self._guardrails = self._load_file("guardrails.md")
        self._roles = {}
        self._load_roles()
        self._snapshot_mtimes()

    def _snapshot_mtimes(self) -> None:
        """Запомнить mtime всех загруженных промпт-файлов."""
        self._file_mtimes = {}
        for name in ("identity.md", "guardrails.md"):
            path = self._dir / name
            if path.exists():
                self._file_mtimes[path] = path.stat().st_mtime
        roles_dir = self._dir / "roles"
        if roles_dir.exists():
            for f in roles_dir.iterdir():
                if f.suffix == ".md":
                    self._file_mtimes[f] = f.stat().st_mtime

    def _files_changed(self) -> bool:
        """Проверить, изменились ли файлы промптов с момента последней загрузки."""
        for path, old_mtime in self._file_mtimes.items():
            if not path.exists() or path.stat().st_mtime != old_mtime:
                return True
        # Проверяем появление новых файлов ролей
        roles_dir = self._dir / "roles"
        if roles_dir.exists():
            for f in roles_dir.iterdir():
                if f.suffix == ".md" and f not in self._file_mtimes:
                    return True
        return False

    def _maybe_reload(self) -> None:
        """Перезагрузить файлы, если они изменились на диске."""
        if self._files_changed():
            self._reload()

    # ---------- Загрузка файлов ----------

    def _load_file(self, filename: str) -> str:
        """Загрузить промпт-файл."""
        path = self._dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _load_roles(self) -> None:
        """Загрузить все файлы ролей из prompts/roles/."""
        roles_dir = self._dir / "roles"
        if not roles_dir.exists():
            return
        for f in roles_dir.iterdir():
            if f.suffix == ".md":
                self._roles[f.stem] = f.read_text(encoding="utf-8")

    async def build(
        self,
        inp: ContextInput,
        *,
        skills: list[LoadedSkill] | None = None,
        user_profile: UserProfile | None = None,
        goal_text: str | None = None,
        phase_text: str | None = None,
        recall_facts: dict[str, str] | None = None,
        summary: str | None = None,
        last_messages: list[MemoryMessage] | None = None,
        memory_bank_content: str | None = None,
        memory_bank_prompt: str | None = None,
    ) -> BuiltContext:
        """Собрать system_prompt с учётом бюджета (§10.1-10.3).

        Порядок drop при overflow (§10.3):
        summary → user_profile → memory_recall → tool_hints → goal.
        Guardrails и Role — никогда не отбрасываются.

        Hot-reload: перед сборкой проверяем, не изменились ли файлы на диске.
        """
        self._maybe_reload()
        budget = inp.budget
        truncated: list[str] = []
        packs: list[str] = []

        # P0: Guardrails (никогда не отбрасываются)
        guardrails_pack = f"{self._identity}\n\n{self._guardrails}"
        guardrails_tokens = estimate_tokens(guardrails_pack)
        packs.append(guardrails_pack)
        remaining = budget.total_tokens - guardrails_tokens

        # P0.5: Role (никогда не отбрасывается, но учитываем в remaining — GAP-7)
        role_text = self._roles.get(inp.role_id, "")
        if role_text:
            role_pack = f"\n## Текущая роль: {inp.role_id}\n{role_text}"
            remaining -= estimate_tokens(role_pack)
            packs.append(role_pack)

        # P_MEMORY: Memory Bank prompt + auto-loaded MEMORY.md (между Role и Goal)
        if memory_bank_prompt and remaining > 0:
            mem_pack = f"\n{memory_bank_prompt}"
            if memory_bank_content:
                mem_pack += f"\n\n## Текущий банк памяти (MEMORY.md)\n{memory_bank_content}"
            mem_tokens = estimate_tokens(mem_pack)
            if mem_tokens > remaining:
                mem_pack = truncate_to_budget(mem_pack, remaining)
                truncated.append("memory_bank")
            remaining -= estimate_tokens(mem_pack)
            packs.append(mem_pack)
        elif memory_bank_prompt:
            truncated.append("memory_bank")

        # P1: Goal text (drop при remaining <= 0)
        if goal_text and remaining > 0:
            goal_pack = f"\n## Текущая цель\n{goal_text.strip()}"
            goal_tokens = estimate_tokens(goal_pack)
            if goal_tokens > budget.goal_max:
                goal_pack = truncate_to_budget(goal_pack, budget.goal_max)
                truncated.append("active_goal")
            remaining -= estimate_tokens(goal_pack)
            packs.append(goal_pack)
        elif goal_text:
            truncated.append("active_goal")

        # P1.5: Phase text
        if phase_text and remaining > 0:
            phase_pack = f"\n## Текущая фаза\n{phase_text.strip()}"
            remaining -= estimate_tokens(phase_pack)
            packs.append(phase_pack)
        elif phase_text:
            truncated.append("phase")

        # P2: Skill instructions (tool hints)
        if skills and remaining > 0:
            instructions = []
            for skill in skills:
                if skill.spec.skill_id in inp.active_skill_ids and skill.instruction_md:
                    instructions.append(f"### Скилл: {skill.spec.title}\n{skill.instruction_md}")
            if instructions:
                tool_pack = "\n## Доступные инструменты\n" + "\n\n".join(instructions)
                tool_tokens = estimate_tokens(tool_pack)
                if tool_tokens > budget.tools_max:
                    tool_pack = truncate_to_budget(tool_pack, budget.tools_max)
                    truncated.append("tool_hints")
                remaining -= estimate_tokens(tool_pack)
                packs.append(tool_pack)
        elif skills:
            truncated.append("tool_hints")

        # P2.5: Последние сообщения диалога (rehydration)
        # Фильтруем ошибочные сообщения (MCP errors, пустые) чтобы не загрязнять контекст.
        if last_messages and remaining > 0:
            msg_lines = []
            for msg in last_messages:
                content = (msg.content or "").strip()
                if not content:
                    continue
                # Пропускаем MCP error / runtime error сообщения
                if _is_error_message(content):
                    continue
                role_label = "user" if msg.role == "user" else "assistant"
                # Обрезаем слишком длинные сообщения (макс 500 символов)
                if len(content) > 500:
                    content = content[:500] + "..."
                msg_lines.append(f"- [{role_label}]: {content}")
            messages_pack = "\n## Последние сообщения диалога\n" + "\n".join(msg_lines)
            msg_tokens = estimate_tokens(messages_pack)
            if msg_tokens > budget.messages_max:
                messages_pack = truncate_to_budget(messages_pack, budget.messages_max)
                truncated.append("last_messages")
            remaining -= estimate_tokens(messages_pack)
            packs.append(messages_pack)
        elif last_messages:
            truncated.append("last_messages")

        # P3: Memory recall — кросс-topic факты (GAP-1, §10.1)
        if recall_facts and remaining > 0:
            facts_lines = [f"- {k}: {v}" for k, v in recall_facts.items()]
            recall_pack = "\n## Воспоминания из прошлых диалогов\n" + "\n".join(facts_lines)
            recall_tokens = estimate_tokens(recall_pack)
            if recall_tokens > budget.memory_max:
                recall_pack = truncate_to_budget(recall_pack, budget.memory_max)
                truncated.append("memory_recall")
            remaining -= estimate_tokens(recall_pack)
            packs.append(recall_pack)
        elif recall_facts:
            truncated.append("memory_recall")

        # P4: User profile
        if user_profile and user_profile.facts and remaining > 0:
            facts_str = "\n".join(f"- {k}: {v}" for k, v in user_profile.facts.items())
            profile_pack = f"\n## Профиль пользователя\n{facts_str}"
            profile_tokens = estimate_tokens(profile_pack)
            if profile_tokens > budget.profile_max:
                profile_pack = truncate_to_budget(profile_pack, budget.profile_max)
                truncated.append("user_profile")
            remaining -= estimate_tokens(profile_pack)
            packs.append(profile_pack)
        elif user_profile and user_profile.facts:
            truncated.append("user_profile")

        # P5: Summary (отбрасывается первым при переполнении, §10.3)
        if summary and remaining > 100:
            summary_pack = f"\n## Контекст диалога (summary)\n{summary}"
            summary_tokens = estimate_tokens(summary_pack)
            if remaining < summary_tokens:
                summary_pack = truncate_to_budget(summary_pack, remaining)
                truncated.append("summary")
            elif summary_tokens > budget.summary_max:
                summary_pack = truncate_to_budget(summary_pack, budget.summary_max)
                truncated.append("summary")
            remaining -= estimate_tokens(summary_pack)
            packs.append(summary_pack)
        elif summary:
            truncated.append("summary")

        system_prompt = "\n".join(packs)
        p_hash = compute_prompt_hash(system_prompt)

        return BuiltContext(
            system_prompt=system_prompt,
            prompt_hash=p_hash,
            tool_budget=max(remaining, 0),
            truncated_packs=truncated,
            notes={
                "role_id": inp.role_id,
                "active_skills": ",".join(inp.active_skill_ids),
                "total_tokens_approx": str(estimate_tokens(system_prompt)),
                "prompt_hash": p_hash,
            },
        )


# ---------- Утилиты для фильтрации сообщений ----------

# Маркеры ошибочных сообщений, которые не несут полезного контекста для модели.
_ERROR_MARKERS = (
    '{"error"',
    "MCP error",
    "Таймаут при вызове",
    "HTTP ошибка MCP",
    "Runtime не ответил вовремя",
    "Не удалось получить ответ",
    "SDK subprocess упал",
    "Ошибка SDK",
    "Client error",
)


def _is_error_message(content: str) -> bool:
    """Проверить, является ли сообщение ошибкой / шумом, который не стоит класть в контекст."""
    if not content:
        return True
    # Быстрая проверка по первым символам
    if content.startswith('{"error"') or content.startswith("⚠️"):
        return True
    # Проверка по маркерам (в первых 200 символах для скорости)
    prefix = content[:200]
    return any(marker in prefix for marker in _ERROR_MARKERS)
