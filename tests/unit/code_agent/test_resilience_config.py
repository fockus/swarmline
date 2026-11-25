"""Unit tests -- resilience config knobs (code-agent-facade plan, Stage 4).

Turning on the runtime resilience features the v1.7.0 blocks already
support is "mostly setting `RuntimeConfig` fields" -- these tests assert the
facade actually sets them on the built plan, both ways (enabled/disabled).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swarmline.code_agent import CodeAgent
from swarmline.compaction import CompactionConfig
from swarmline.evolution.recovery import RecoveryCascade
from swarmline.evolution.stuck_detector import StuckDetector

pytestmark = pytest.mark.asyncio


def _build_plan(agent: CodeAgent):
    from swarmline.agent.runtime_wiring import build_portable_runtime_plan

    plan = build_portable_runtime_plan(
        agent._config, "thin", runtime_factory=agent._factory
    )
    return agent._augment_plan(plan)


class TestCompactionKnob:
    async def test_facade_sets_compaction_on_runtime_config_when_enabled(
        self, tmp_path: Path
    ) -> None:
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))  # compaction=True default

        plan = _build_plan(agent)

        assert isinstance(plan.config.compaction, CompactionConfig)

    async def test_facade_disables_compaction_when_flag_false(
        self, tmp_path: Path
    ) -> None:
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), compaction=False)

        plan = _build_plan(agent)

        assert plan.config.compaction is None


class TestEvolutionKnob:
    async def test_facade_sets_stuck_detector_when_evolution_enabled(
        self, tmp_path: Path
    ) -> None:
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))  # evolution=True default

        plan = _build_plan(agent)

        assert isinstance(plan.config.stuck_detector, StuckDetector)
        assert plan.config.evolution_enabled is True
        assert isinstance(plan.config.recovery_cascade, RecoveryCascade)

    async def test_facade_disables_evolution_when_flag_false(
        self, tmp_path: Path
    ) -> None:
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), evolution=False)

        plan = _build_plan(agent)

        assert plan.config.evolution_enabled is False
        assert plan.config.stuck_detector is None
        assert plan.config.recovery_cascade is None
