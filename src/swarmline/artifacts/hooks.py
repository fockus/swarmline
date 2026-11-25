"""PostStepHookRunner -- mandatory post-step bookkeeping.

Ported from Aura's ``application/components/workspace/hooks.py``. After every
step: (1) save the raw tool output, (2) write a step note, (3) update
``todo.md`` (recitation), (4) update ``status.md``, (5) append a
:class:`~swarmline.artifacts.types.StepJournalEntry`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.artifacts.step_journal import StepJournal
from swarmline.artifacts.types import StepJournalEntry


def _read_or_default(path: Path, default: str) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else default


class PostStepHookRunner:
    """Runs the mandatory post-step hooks for one :class:`ArtifactRoot`."""

    def __init__(self, root: ArtifactRoot) -> None:
        self.root = root
        self.journal = StepJournal(root=root)

    async def run(
        self,
        *,
        step_id: int,
        task: str,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_output: Any,
        status: str,
        summary: str | None = None,
        artifacts_created: list[str] | None = None,
    ) -> StepJournalEntry:
        """Run all post-step hooks and append the resulting journal entry."""
        raw_output_path = self._save_tool_output(
            step_id, tool_name, tool_args, tool_output
        )
        notes_path = self._create_step_note(step_id, task, tool_name, status, summary)
        self._update_todo(step_id, task, status)
        self._update_status(step_id, tool_name, status, summary)

        entry = StepJournalEntry(
            step_id=step_id,
            task=task,
            tool_name=tool_name,
            tool_args=tool_args,
            status=status,
            summary=summary,
            raw_output_path=raw_output_path,
            artifacts_created=tuple(artifacts_created or ()),
            mutations=("todo.md", "status.md"),
            notes_path=notes_path,
        )
        self.journal.append(entry)
        return entry

    def _save_tool_output(
        self, step_id: int, tool_name: str, tool_args: dict[str, Any], tool_output: Any
    ) -> str:
        safe_tool_name = tool_name.replace(".", "_")
        filename = f"step_{step_id:03d}_{safe_tool_name}.json"
        file_path = self.root.path / "tool_outputs" / filename
        content = {
            "step_id": step_id,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "timestamp": datetime.now(UTC).isoformat(),
            "results": tool_output,
        }
        file_path.write_text(
            json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return f"tool_outputs/{filename}"

    def _create_step_note(
        self, step_id: int, task: str, tool_name: str, status: str, summary: str | None
    ) -> str:
        filename = f"step_{step_id:03d}.md"
        file_path = self.root.path / "notes" / filename
        lines = [
            f"# Step {step_id}",
            "",
            f"**Task:** {task}",
            f"**Tool:** {tool_name}",
            f"**Status:** {status}",
            "",
        ]
        if summary:
            lines.extend(["## Summary", "", summary, ""])
        lines.extend(["---", f"*Generated at {datetime.now(UTC).isoformat()}*"])
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return f"notes/{filename}"

    def _update_todo(self, step_id: int, task: str, status: str) -> None:
        current = _read_or_default(self.root.path / "todo.md", "# TODO\n")
        marker = (
            f"- [x] Step {step_id}: {task}"
            if status == "ok"
            else f"- [ ] Step {step_id}: {task} (FAILED)"
        )
        if "## Completed" in current:
            head, tail = current.split("## Completed", 1)
            new_todo = f"{head}## Completed\n\n{marker}\n{tail.lstrip(chr(10))}"
        else:
            new_todo = current.rstrip() + f"\n\n## Completed\n\n{marker}\n"
        (self.root.path / "todo.md").write_text(new_todo, encoding="utf-8")

    def _update_status(
        self, step_id: int, tool_name: str, status: str, summary: str | None
    ) -> None:
        current = _read_or_default(self.root.path / "status.md", "# Status\n")
        line = f"Step {step_id}: {tool_name} ({status})"
        if summary:
            line += f" — {summary}"
        if "## Last Action" in current:
            lines = current.split("\n")
            for i, entry in enumerate(lines):
                if "## Last Action" in entry:
                    for j in range(i + 1, len(lines)):
                        if lines[j].strip() and not lines[j].startswith("#"):
                            lines[j] = line
                            break
                    else:
                        lines.insert(i + 1, line)
                    break
            new_status = "\n".join(lines)
        else:
            new_status = current.rstrip() + f"\n\n## Last Action\n\n{line}\n"
        (self.root.path / "status.md").write_text(new_status, encoding="utf-8")
