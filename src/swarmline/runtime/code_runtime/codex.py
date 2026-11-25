"""CodexCodeRuntimeAdapter — CodeRuntimePort implementation for Codex/OpenAI.

Lazy-imports ``openai`` SDK. If unavailable, falls back to CLI mode
with reduced capabilities. SDK types never appear in public signatures.
"""

from __future__ import annotations

from swarmline.runtime.code_runtime.base import BaseCodeRuntimeAdapter


class CodexCodeRuntimeAdapter(BaseCodeRuntimeAdapter):
    """CodeRuntimePort implementation for Codex/OpenAI runtime.

    Supports two modes:
    - **sdk**: when ``openai`` is installed — full capabilities
    - **cli**: fallback — reduced capabilities, deterministic stub events
    """

    _sdk_module_name = "openai"
    _session_prefix = "codex"
    _provider_name = "codex"
    _sdk_caps = {
        "approvals": True,
        "subagents": False,
        "hooks": False,
        "worktrees": True,
        "session_persistence": True,
    }
