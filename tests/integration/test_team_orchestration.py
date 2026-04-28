"""Integration: ThinTeamOrchestrator + MessageBus + ThinSubagentOrchestrator. 2 workers spawn, run cherez fake LLM, zavershayutsya.
send_message cherez MessageBus: odin worker -> bus -> inbox drugogo.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.orchestration.team_types import TeamConfig, TeamMessage
from swarmline.orchestration.thin_team import ThinTeamOrchestrator
from swarmline.runtime.types import RuntimeConfig

pytestmark = pytest.mark.integration


class TestThinSubagentTeamMessageBus:
    """ThinTeamOrchestrator: start -> workers -> MessageBus -> completion."""

    @pytest.mark.asyncio
    async def test_thin_subagent_team_message_bus(self) -> None:
        """2 workers spawn, complete, team status = completed. MessageBus works."""

        async def fast_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            """Fake LLM: mgnovennyy final response."""
            await asyncio.sleep(0.05)
            return json.dumps({"type": "final", "final_message": "worker done"})

        orch = ThinTeamOrchestrator(
            llm_call=fast_llm,
            runtime_config=RuntimeConfig(runtime_name="thin"),
            max_concurrent=4,
        )

        config = TeamConfig(
            lead_prompt="You are a team lead",
            worker_specs=[
                SubagentSpec(name="researcher", system_prompt="Research the topic"),
                SubagentSpec(name="writer", system_prompt="Write the report"),
            ],
            max_workers=4,
        )

        team_id = await orch.start(config, task="Analyze market trends")

        # ZHdem zaversheniya workers (with timeout)
        for _ in range(50):
            status = await orch.get_team_status(team_id)
            if status.state == "completed":
                break
            await asyncio.sleep(0.1)

        status = await orch.get_team_status(team_id)

        # Workers populated and zaversheny
        assert status.state == "completed"
        assert "researcher" in status.workers
        assert "writer" in status.workers
        assert status.workers["researcher"].state == "completed"
        assert status.workers["writer"].state == "completed"

        # MessageBus: otpravlyaem message and verify inbox
        bus = orch.get_message_bus(team_id)
        assert bus is not None

        from datetime import UTC, datetime

        msg = TeamMessage(
            from_agent="researcher",
            to_agent="writer",
            content="Here are the findings",
            timestamp=datetime.now(tz=UTC),
        )
        await bus.send(msg)

        writer_inbox = await bus.get_inbox("writer")
        assert len(writer_inbox) == 1
        assert writer_inbox[0].content == "Here are the findings"
        assert writer_inbox[0].from_agent == "researcher"

        researcher_outbox = await bus.get_outbox("researcher")
        assert len(researcher_outbox) == 1
