"""CodingContextInputFilter — inject assembled coding context into system prompt.

Wires CodingContextAssembler into the real runtime input-filter pipeline so
coding-profile turns can receive task/workspace/session context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swarmline.context.budget import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    ContextBudget,
    truncate_to_budget,
)
from swarmline.context.coding_context_builder import (
    CodingContextAssembler,
    CodingSliceInput,
)
from swarmline.runtime.types import Message

#: Stage 3 (context-engineering-manus-parity): the skill LISTING (names+
#: descriptions only, never bodies) is capped to this fraction of the model's
#: context window -- the same ~1% policy Claude Code itself applies to its own
#: skill listing. Applied via the existing truncate_to_budget kernel primitive
#: (context/budget.py), never reimplemented ad hoc here.
SKILL_LISTING_BUDGET_RATIO: float = 0.01

#: Per-skill cap (characters) on the DESCRIPTION shown in the listing -- keeps
#: one skill's oversized description from crowding out every other skill's
#: entry within the overall listing budget above.
_PER_SKILL_DESCRIPTION_MAX_CHARS: int = 200


def _cap_description(text: str) -> str:
    """Truncate a single skill's description to the per-skill cap."""
    if len(text) <= _PER_SKILL_DESCRIPTION_MAX_CHARS:
        return text
    return text[: _PER_SKILL_DESCRIPTION_MAX_CHARS - 1] + "…"


class CodingContextInputFilter:
    """Build coding context slices and append them to the system prompt.

    Lazy skill loading (REQ-RCA-040): when ``lazy_skills=True`` and a
    ``skill_registry`` is provided, the ``skill_profile`` slice lists skill
    names+descriptions only — no full ``instruction_md`` bodies are embedded.
    The agent loads bodies on demand via the ``read_skill`` local tool.

    Byte-identical-when-off guarantee (REQ-RCA-070): when ``lazy_skills=False``
    (default) the filter behaves exactly as before Task 6 — the provided
    ``skill_profile_text`` is forwarded unchanged.
    """

    def __init__(
        self,
        *,
        workspace_cwd: str,
        board_text: str = "",
        search_text: str = "",
        skill_profile_text: str = "",
        task_session_store: Any | None = None,
        task_session_agent_id: str = "coding",
        task_session_task_id: str | None = None,
        budget_tokens: int = 2000,
        skill_registry: Any | None = None,
        lazy_skills: bool = False,
        context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS,
    ) -> None:
        self._workspace_cwd = workspace_cwd
        self._board_text = board_text
        self._search_text = search_text
        self._skill_profile_text = skill_profile_text
        self._task_session_store = task_session_store
        self._task_session_agent_id = task_session_agent_id
        self._task_session_task_id = task_session_task_id
        self._budget_tokens = max(int(budget_tokens), 200)
        self._assembler = CodingContextAssembler()
        self._skill_registry = skill_registry
        self._lazy_skills = lazy_skills
        # Stage 3: caller's actual model context window, used only to size the
        # skill-listing budget (SKILL_LISTING_BUDGET_RATIO) below.
        self._context_window_tokens = max(int(context_window_tokens), 1000)

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        """Inject assembled coding slices into the system prompt."""
        task_text = self._extract_last_user_text(messages)
        workspace_text = self._build_workspace_slice()
        session_text = await self._build_session_slice()

        # REQ-RCA-040 lazy path: names+descriptions only when enabled and registry set.
        # OFF path (lazy_skills=False, default): use provided text — byte-identical.
        skill_profile = (
            self._build_lazy_skill_profile()
            if self._lazy_skills and self._skill_registry is not None
            else self._skill_profile_text
        )

        result = self._assembler.assemble(
            CodingSliceInput(
                coding_mode=True,
                budget=ContextBudget(total_tokens=self._budget_tokens),
                task=task_text,
                board=self._board_text,
                workspace=workspace_text,
                search=self._search_text,
                session=session_text,
                skill_profile=skill_profile,
            )
        )
        if not result.context_text:
            return messages, system_prompt

        block = "## Coding Context\n" + result.context_text
        if result.continuity_summary:
            block += f"\n\n## Coding Context Notes\n{result.continuity_summary}"
        merged_prompt = f"{system_prompt}\n\n{block}" if system_prompt else block
        return messages, merged_prompt

    def _build_lazy_skill_profile(self) -> str:
        """Build a compact skill listing (names+descriptions only).

        Called only when lazy_skills=True and skill_registry is set.
        Full instruction_md bodies are intentionally omitted; the agent
        loads them on demand via the ``read_skill`` local tool.
        Falls back to the provided skill_profile_text when the registry
        is absent or has no skills.

        Stage 3 (context-engineering-manus-parity): each skill's description
        is capped individually (``_cap_description``), and the assembled
        listing as a whole is capped to ``SKILL_LISTING_BUDGET_RATIO`` of
        ``context_window_tokens`` via the existing ``truncate_to_budget``
        kernel primitive — both caps are no-ops for a normal-sized listing.
        """
        if self._skill_registry is None:
            return self._skill_profile_text
        skills = self._skill_registry.list_all()
        if not skills:
            return self._skill_profile_text
        lines = [
            f"- {s.spec.title} (id: {s.spec.skill_id}): "
            f"{_cap_description(s.spec.description or s.spec.title)}"
            for s in skills
        ]
        listing = (
            "Available skills (use read_skill to load full instructions):\n"
            + "\n".join(lines)
        )
        listing_budget_tokens = int(
            self._context_window_tokens * SKILL_LISTING_BUDGET_RATIO
        )
        return truncate_to_budget(listing, listing_budget_tokens)

    @staticmethod
    def _extract_last_user_text(messages: list[Message]) -> str:
        for message in reversed(messages):
            if message.role == "user" and message.content.strip():
                return message.content.strip()
        return ""

    def _build_workspace_slice(self) -> str:
        root = Path(self._workspace_cwd)
        if not root.exists():
            return f"cwd: {self._workspace_cwd} (missing)"

        entries: list[str] = []
        try:
            for entry in sorted(root.iterdir(), key=lambda p: p.name)[:12]:
                suffix = "/" if entry.is_dir() else ""
                entries.append(f"- {entry.name}{suffix}")
        except OSError:
            return f"cwd: {self._workspace_cwd} (unreadable)"

        if not entries:
            entries.append("- (empty)")
        return f"cwd: {self._workspace_cwd}\nentries:\n" + "\n".join(entries)

    async def _build_session_slice(self) -> str:
        if (
            self._task_session_store is None
            or self._task_session_task_id is None
            or not hasattr(self._task_session_store, "load")
        ):
            return ""
        try:
            payload = await self._task_session_store.load(
                self._task_session_agent_id,
                self._task_session_task_id,
            )
        except Exception:
            return ""
        if not payload:
            return ""
        if isinstance(payload, dict):
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return str(payload)
