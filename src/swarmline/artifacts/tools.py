"""Agent-facing tools: artifact.create/load + workspace.read/write/....

Thin re-export shim: the actual factories live in ``tools_artifact.py``
(``create_artifact_tools``) and ``tools_workspace.py`` (``create_workspace_tools``),
split out to respect the file-size ceiling. Import from here for convenience:
``from swarmline.artifacts.tools import create_artifact_tools, create_workspace_tools``.
"""

from __future__ import annotations

from swarmline.artifacts.tools_artifact import create_artifact_tools
from swarmline.artifacts.tools_workspace import create_workspace_tools

#: Reminder block for the agent system prompt -- without this + the tools
#: above, the File Registry is invisible to the model (Manus "recitation").
WORKSPACE_MEMORY_PROMPT = """## WORKSPACE MEMORY (Extended Memory Pattern)
You have a workspace with files that persist across steps:
- `todo.md` -- current task list and focus
- `plan.md` -- the current top-level plan
- `status.md` -- current state

### Workspace Tools (USE THEM!)
- `workspace.read` / `workspace.write` / `workspace.update_todo` / \
`workspace.update_plan` / `workspace.search` / `workspace.list_files`

### Artifact Creation
- `artifact.create` -- create files (reports, data files, multi-file folders)
- `artifact.load` -- load a previously created artifact
"""

__all__ = ["WORKSPACE_MEMORY_PROMPT", "create_artifact_tools", "create_workspace_tools"]
