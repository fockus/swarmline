"""`CodeAgent` -- the ergonomic public code-agent facade.

Composes the v1.7.0 thin runtime + coding profile behind one constructor;
capability blocks (governance/workspace/scratchpad/code_intel) and the
permission hook are wired in later stages::

    from swarmline import CodeAgent
    agent = CodeAgent(model="sonnet", cwd="/repo")
    async for ev in agent.run("fix the typo in README.md"):
        print(ev)

See `.memory-bank/plans/2026-06-29_feature_code-agent-facade.md` for the
staged build-out. Stage 1 pinned the public contract; Stage 2 wired
`run`/`stream`/`close` to a real thin runtime with the coding profile;
Stage 3 wired the governance/workspace/scratchpad/code_intel capability
tools + the `on_permission_request` PreToolUse hook. Later stages add
resilience knobs and session lifecycle.
"""

from __future__ import annotations

from swarmline.code_agent._facade import CodeAgent
from swarmline.code_agent.types import PermissionCallback, PermissionDecision

__all__ = ["CodeAgent", "PermissionCallback", "PermissionDecision"]
