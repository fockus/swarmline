"""CodingContextInputFilter — inject assembled coding context into system prompt.

Wires CodingContextAssembler into the real runtime input-filter pipeline so
coding-profile turns can receive task/workspace/session context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swarmline.context.budget import ContextBudget
from swarmline.context.coding_context_builder import CodingContextAssembler, CodingSliceInput
from swarmline.runtime.types import Message


class CodingContextInputFilter:
    """Build coding context slices and append them to the system prompt."""

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

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        """Inject assembled coding slices into the system prompt."""
        task_text = self._extract_last_user_text(messages)
        workspace_text = self._build_workspace_slice()
        session_text = await self._build_session_slice()

        result = self._assembler.assemble(
            CodingSliceInput(
                coding_mode=True,
                budget=ContextBudget(total_tokens=self._budget_tokens),
                task=task_text,
                board=self._board_text,
                workspace=workspace_text,
                search=self._search_text,
                session=session_text,
                skill_profile=self._skill_profile_text,
            )
        )
        if not result.context_text:
            return messages, system_prompt

        block = "## Coding Context\n" + result.context_text
        if result.continuity_summary:
            block += f"\n\n## Coding Context Notes\n{result.continuity_summary}"
        merged_prompt = f"{system_prompt}\n\n{block}" if system_prompt else block
        return messages, merged_prompt

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

