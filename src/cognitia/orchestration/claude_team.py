"""ClaudeTeamOrchestrator — team mode через Claude SDK.

Делегирует в DeepAgentsTeamOrchestrator (единая базовая реализация).
LSP: взаимозаменяем.
"""

from __future__ import annotations

from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator


class ClaudeTeamOrchestrator(DeepAgentsTeamOrchestrator):
    """TeamOrchestrator для Claude SDK. Наследует базовую реализацию."""
