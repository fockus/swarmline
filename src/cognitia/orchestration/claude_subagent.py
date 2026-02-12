"""ClaudeSubagentOrchestrator — обёртка Task tool Claude SDK.

Нормализует SDK events в SubagentStatus/SubagentResult.
Структурно совместим с другими Orchestrator'ами (LSP).
"""

from __future__ import annotations

from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator


class ClaudeSubagentOrchestrator(ThinSubagentOrchestrator):
    """SubagentOrchestrator для Claude SDK runtime.

    Наследует базовую asyncio реализацию.
    SDK Task tool events маппятся на SubagentStatus через parent.
    """

