"""DefaultContextBuilder - build system_prompt from context packets."""

from __future__ import annotations

from pathlib import Path

from swarmline.context.adaptive_layers import (
    apply_optional_cap,
    category_actuals,
    compute_present_layers,
    derive_layer_caps,
)
from swarmline.context.budget import estimate_tokens, truncate_to_budget
from swarmline.context.builder_types import (
    BuiltContext,
    ContextInput,
    compute_prompt_hash,
)
from swarmline.context.message_filters import is_error_message
from swarmline.context.saturation import SaturationCalculator
from swarmline.memory.types import (
    MemoryMessage,
    UserProfile,
)
from swarmline.skills.types import LoadedSkill

__all__ = [
    "BuiltContext",
    "ContextInput",
    "DefaultContextBuilder",
    "compute_prompt_hash",
]


class DefaultContextBuilder:
    """Build system_prompt from layered context packets.

    Layers (from base to dynamic, §10.1):
    P0: Guardrails (Identity + Guardrails) - never dropped
    P0.5: Role - never dropped, but counts toward remaining
    P1: Goal text
    P1.5: Phase text
    P2: Skill instructions (tool hints)
    P3: Memory recall (cross-topic facts)
    P4: User profile
    P4.5: Available Files (FileRegistry injection, artifacts Stage P1)
    P5: Summary (dropped first on overflow, §10.3)

    Hot-reload: prompt files are automatically re-read when changed on disk.

    Adaptive budget (opt-in, ``adaptive-budget`` spec Task 4): when
    ``inp.budget.adaptive`` is set, ``build()`` runs a two-pass feedback loop
    (REQ-007/REQ-008). ``adaptive is None`` (the default) is fully inert -
    byte-identical to the pre-Task-4 behavior.
    """

    def __init__(self, prompts_dir: str | Path) -> None:
        self._dir = Path(prompts_dir)
        self._identity: str = ""
        self._guardrails: str = ""
        self._roles: dict[str, str] = {}
        self._file_mtimes: dict[Path, float] = {}
        # ponytail: per-instance saturation state; add per-conversation keying
        # if builders get shared across concurrent turns
        self._last_saturation: dict[str, float] | None = None
        self._reload()

    # ---------- Hot-reload ----------

    def _reload(self) -> None:
        """Load or reload all prompt files from disk."""
        self._identity = self._load_file("identity.md")
        self._guardrails = self._load_file("guardrails.md")
        self._roles = {}
        self._load_roles()
        self._snapshot_mtimes()

    def _snapshot_mtimes(self) -> None:
        """Remember the mtime of all loaded prompt files."""
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
        """Check whether prompt files changed since the last load."""
        for path, old_mtime in self._file_mtimes.items():
            if not path.exists() or path.stat().st_mtime != old_mtime:
                return True
        # Check for newly added role files
        roles_dir = self._dir / "roles"
        if roles_dir.exists():
            for f in roles_dir.iterdir():
                if f.suffix == ".md" and f not in self._file_mtimes:
                    return True
        return False

    def _maybe_reload(self) -> None:
        """Reload files if they changed on disk."""
        if self._files_changed():
            self._reload()

    # ---------- Hibernate/rehydrate saturation snapshot (REQ-010) ----------

    def export_saturation(self) -> dict[str, float] | None:
        """Return a copy of the last recorded adaptive saturation state.

        ``None`` when no adaptive ``build()`` has run yet on this instance -
        never fabricated. Used by ``observability.hibernate`` to snapshot the
        builder's steering state for a later ``import_saturation()``.
        """
        if self._last_saturation is None:
            return None
        return dict(self._last_saturation)

    def import_saturation(self, data: dict[str, float] | None) -> None:
        """Seed ``_last_saturation`` from a previously exported snapshot.

        A fresh builder that imports an exported saturation steers its next
        ``allocate()`` call (via ``build()``) identically to the builder the
        snapshot was exported from (REQ-010).
        """
        self._last_saturation = dict(data) if data is not None else None

    # ---------- File loading ----------

    def _load_file(self, filename: str) -> str:
        """Load a prompt file."""
        path = self._dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _load_roles(self) -> None:
        """Load all role files from prompts/roles/."""
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
        available_files: str | None = None,
        mode: str = "default",
        step_progress: float = 0.0,
    ) -> BuiltContext:
        """Build system_prompt with budget awareness (§10.1-10.3).

        Drop order on overflow (§10.3):
        summary -> user_profile -> memory_recall -> tool_hints -> goal.
        Guardrails and Role are never dropped.

        Hot-reload: before building, we check whether files changed on disk.

        ``mode``/``step_progress`` (Task 4) only matter when
        ``inp.budget.adaptive`` is set; ignored on the static path.
        """
        self._maybe_reload()
        budget = inp.budget
        adaptive = budget.adaptive
        truncated: list[str] = []
        packs: list[str] = []
        layer_tokens: dict[str, int] = {}
        layer_caps: dict[str, int] = {}
        allocated: dict[str, int] = {}

        if adaptive is not None:
            # REQ-007/008: previous saturation steers this allocate(); None
            # on the very first compile ever -> base+temporal only.
            allocated = adaptive.allocate(mode, step_progress, self._last_saturation)
            present_layers = compute_present_layers(
                role_text=self._roles.get(inp.role_id, ""),
                memory_bank_prompt=memory_bank_prompt,
                goal_text=goal_text,
                phase_text=phase_text,
                skills=skills,
                last_messages=last_messages,
                recall_facts=recall_facts,
                user_profile_facts=user_profile.facts if user_profile else None,
                summary=summary,
                available_files=available_files,
            )
            layer_caps = derive_layer_caps(allocated, present_layers)

        # P0: Guardrails (never dropped)
        guardrails_pack = f"{self._identity}\n\n{self._guardrails}"
        guardrails_tokens = estimate_tokens(guardrails_pack)
        packs.append(guardrails_pack)
        layer_tokens["guardrails"] = guardrails_tokens
        remaining = budget.total_tokens - guardrails_tokens

        # P0.5: Role (never dropped, but counted in remaining - GAP-7)
        role_text = self._roles.get(inp.role_id, "")
        if role_text:
            role_pack = f"\n## Текущая роль: {inp.role_id}\n{role_text}"
            remaining -= estimate_tokens(role_pack)
            packs.append(role_pack)
            layer_tokens["role"] = estimate_tokens(role_pack)

        # P_MEMORY: Memory Bank prompt + auto-loaded MEMORY.md (between Role and Goal)
        if memory_bank_prompt and remaining > 0:
            mem_pack = f"\n{memory_bank_prompt}"
            if memory_bank_content:
                mem_pack += (
                    f"\n\n## Текущий банк памяти (MEMORY.md)\n{memory_bank_content}"
                )
            mem_cap = min(remaining, layer_caps.get("memory_bank", remaining))
            mem_pack, was_truncated = apply_optional_cap(mem_pack, mem_cap)
            if was_truncated:
                truncated.append("memory_bank")
            remaining -= estimate_tokens(mem_pack)
            packs.append(mem_pack)
            layer_tokens["memory_bank"] = estimate_tokens(mem_pack)
        elif memory_bank_prompt:
            truncated.append("memory_bank")

        # P1: Goal text (drop when remaining <= 0)
        if goal_text and remaining > 0:
            goal_pack = f"\n## Текущая цель\n{goal_text.strip()}"
            goal_cap = layer_caps.get("goal", budget.goal_max)
            goal_pack, was_truncated = apply_optional_cap(goal_pack, goal_cap)
            if was_truncated:
                truncated.append("active_goal")
            remaining -= estimate_tokens(goal_pack)
            packs.append(goal_pack)
            layer_tokens["goal"] = estimate_tokens(goal_pack)
        elif goal_text:
            truncated.append("active_goal")

        # P1.5: Phase text
        if phase_text and remaining > 0:
            phase_pack = f"\n## Текущая фаза\n{phase_text.strip()}"
            phase_pack, was_truncated = apply_optional_cap(
                phase_pack, layer_caps.get("phase")
            )
            if was_truncated:
                truncated.append("phase")
            remaining -= estimate_tokens(phase_pack)
            packs.append(phase_pack)
            layer_tokens["phase"] = estimate_tokens(phase_pack)
        elif phase_text:
            truncated.append("phase")

        # P2: Skill instructions (tool hints)
        if skills and remaining > 0:
            instructions = []
            for skill in skills:
                if skill.spec.skill_id in inp.active_skill_ids and skill.instruction_md:
                    instructions.append(
                        f"### Скилл: {skill.spec.title}\n{skill.instruction_md}"
                    )
            if instructions:
                tool_pack = "\n## Доступные инструменты\n" + "\n\n".join(instructions)
                tools_cap = layer_caps.get("tool_hints", budget.tools_max)
                tool_pack, was_truncated = apply_optional_cap(tool_pack, tools_cap)
                if was_truncated:
                    truncated.append("tool_hints")
                remaining -= estimate_tokens(tool_pack)
                packs.append(tool_pack)
                layer_tokens["tool_hints"] = estimate_tokens(tool_pack)
        elif skills:
            truncated.append("tool_hints")

        # P2.5: Latest conversation messages (rehydration)
        # Filter out error messages (MCP errors, empty ones) so they do not pollute context.
        if last_messages and remaining > 0:
            msg_lines = []
            for msg in last_messages:
                content = (msg.content or "").strip()
                if not content:
                    continue
                # Skip MCP error / runtime error messages
                if is_error_message(content):
                    continue
                role_label = "user" if msg.role == "user" else "assistant"
                # Truncate overly long messages (max 500 chars)
                if len(content) > 500:
                    content = content[:500] + "..."
                msg_lines.append(f"- [{role_label}]: {content}")
            messages_pack = "\n## Последние сообщения диалога\n" + "\n".join(msg_lines)
            messages_cap = layer_caps.get("last_messages", budget.messages_max)
            messages_pack, was_truncated = apply_optional_cap(
                messages_pack, messages_cap
            )
            if was_truncated:
                truncated.append("last_messages")
            remaining -= estimate_tokens(messages_pack)
            packs.append(messages_pack)
            layer_tokens["last_messages"] = estimate_tokens(messages_pack)
        elif last_messages:
            truncated.append("last_messages")

        # P3: Memory recall - cross-topic facts (GAP-1, §10.1)
        if recall_facts and remaining > 0:
            facts_lines = [f"- {k}: {v}" for k, v in recall_facts.items()]
            recall_pack = "\n## Воспоминания из прошлых диалогов\n" + "\n".join(
                facts_lines
            )
            memory_cap = layer_caps.get("memory_recall", budget.memory_max)
            recall_pack, was_truncated = apply_optional_cap(recall_pack, memory_cap)
            if was_truncated:
                truncated.append("memory_recall")
            remaining -= estimate_tokens(recall_pack)
            packs.append(recall_pack)
            layer_tokens["memory_recall"] = estimate_tokens(recall_pack)
        elif recall_facts:
            truncated.append("memory_recall")

        # P4: User profile
        if user_profile and user_profile.facts and remaining > 0:
            facts_str = "\n".join(f"- {k}: {v}" for k, v in user_profile.facts.items())
            profile_pack = f"\n## Профиль пользователя\n{facts_str}"
            profile_cap = layer_caps.get("user_profile", budget.profile_max)
            profile_pack, was_truncated = apply_optional_cap(profile_pack, profile_cap)
            if was_truncated:
                truncated.append("user_profile")
            remaining -= estimate_tokens(profile_pack)
            packs.append(profile_pack)
            layer_tokens["user_profile"] = estimate_tokens(profile_pack)
        elif user_profile and user_profile.facts:
            truncated.append("user_profile")

        # P4.5: Available Files (FileRegistry injection - artifacts Stage P1)
        if available_files and remaining > 0:
            files_pack = f"\n## Available Files\n{available_files.strip()}"
            files_cap = layer_caps.get("available_files", budget.artifacts_max)
            files_pack, was_truncated = apply_optional_cap(files_pack, files_cap)
            if was_truncated:
                truncated.append("available_files")
            remaining -= estimate_tokens(files_pack)
            packs.append(files_pack)
            layer_tokens["available_files"] = estimate_tokens(files_pack)
        elif available_files:
            truncated.append("available_files")

        # P5: Summary (dropped first on overflow, §10.3)
        if summary and remaining > 100:
            summary_pack = f"\n## Контекст диалога (summary)\n{summary}"
            summary_tokens = estimate_tokens(summary_pack)
            summary_cap = layer_caps.get("summary", budget.summary_max)
            if remaining < summary_tokens:
                summary_pack = truncate_to_budget(summary_pack, remaining)
                truncated.append("summary")
            elif summary_tokens > summary_cap:
                summary_pack = truncate_to_budget(summary_pack, summary_cap)
                truncated.append("summary")
            remaining -= estimate_tokens(summary_pack)
            packs.append(summary_pack)
            layer_tokens["summary"] = estimate_tokens(summary_pack)
        elif summary:
            truncated.append("summary")

        if adaptive is not None:
            # REQ-007: saturation of this compile feeds the NEXT allocate().
            actual_by_category = category_actuals(layer_tokens)
            self._last_saturation = SaturationCalculator.calculate(
                actual_by_category, allocated
            )

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
