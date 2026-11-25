"""skill_tool — on-demand skill body loader tool (REQ-RCA-040).

create_skill_read_tool() returns a (ToolSpec, executor) pair that the LLM
can invoke to load the full instruction_md of a skill when lazy loading is
enabled via CodingProfileConfig.enable_lazy_skills.

Byte-identical-when-off guarantee: this module is only wired into the tool
surface when enable_lazy_skills=True.  When the flag is False (default) this
factory is never called and nothing here affects any other execution path.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from swarmline.runtime.types import ToolSpec

_READ_SKILL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "skill_id": {
            "type": "string",
            "description": (
                "ID of the skill whose full instruction body should be loaded. "
                "Use the skill_id shown in the available-skills list."
            ),
        },
    },
    "required": ["skill_id"],
}

_READ_SKILL_DESCRIPTION = (
    "Load the full instruction body for a skill on demand.  "
    "Call this tool with a skill_id to retrieve the complete instruction_md "
    "that was omitted from the system prompt for token efficiency."
)


def create_skill_read_tool(
    registry: Any,
) -> tuple[ToolSpec, Callable[[dict[str, Any]], str]]:
    """Return (ToolSpec, executor) for the read_skill tool.

    Args:
        registry: SkillRegistry instance.  Typed as ``Any`` to avoid a
                  circular import; the contract is that ``registry.get(skill_id)``
                  returns a ``LoadedSkill | None``.

    Returns:
        Tuple of (ToolSpec, sync executor).
        executor({"skill_id": "<id>"}) → JSON string:
            success: {"skill_id": ..., "title": ..., "instruction_md": ...}
            error:   {"error": "<message>"}
    """
    spec = ToolSpec(
        name="read_skill",
        description=_READ_SKILL_DESCRIPTION,
        parameters=_READ_SKILL_SCHEMA,
        is_local=True,
    )

    def executor(args: dict[str, Any]) -> str:
        skill_id: str = args.get("skill_id", "")
        if not skill_id or not skill_id.strip():
            return json.dumps({"error": "skill_id is required"})
        loaded = registry.get(skill_id.strip())
        if loaded is None:
            return json.dumps({"error": f"Skill '{skill_id}' not found in registry"})
        return json.dumps(
            {
                "skill_id": loaded.spec.skill_id,
                "title": loaded.spec.title,
                "instruction_md": loaded.instruction_md,
            },
            ensure_ascii=False,
        )

    return spec, executor
