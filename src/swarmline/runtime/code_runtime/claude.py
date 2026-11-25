"""ClaudeCodeRuntimeAdapter — CodeRuntimePort implementation for Claude Code.

Lazy-imports ``anthropic`` SDK. If unavailable, falls back to CLI mode
with reduced capabilities. SDK types never appear in public signatures.
"""

from __future__ import annotations

from swarmline.runtime.code_runtime.base import BaseCodeRuntimeAdapter


class ClaudeCodeRuntimeAdapter(BaseCodeRuntimeAdapter):
    """CodeRuntimePort implementation for Claude Code runtime.

    Supports two modes:
    - **sdk**: when ``anthropic`` is installed — full capabilities
    - **cli**: fallback — reduced capabilities, deterministic stub events
    """

    _sdk_module_name = "anthropic"
    _session_prefix = "claude"
    _provider_name = "claude_code"
    _sdk_caps = {
        "approvals": True,
        "subagents": True,
        "hooks": True,
        "worktrees": True,
        "session_persistence": True,
    }
