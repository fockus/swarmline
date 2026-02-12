"""DeepAgentsSubagentOrchestrator — subagent'ы через asyncio (LangGraph-ready).

Структурно совместим с ThinSubagentOrchestrator (LSP).
При наличии langchain можно расширить через LangGraph Send().
"""

from __future__ import annotations

from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator


class DeepAgentsSubagentOrchestrator(ThinSubagentOrchestrator):
    """SubagentOrchestrator для DeepAgents runtime.

    Наследует базовую asyncio реализацию из ThinSubagentOrchestrator.
    При наличии langchain может быть расширен через LangGraph nodes.
    """

