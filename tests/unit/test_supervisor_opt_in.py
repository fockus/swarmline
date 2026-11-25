"""Unit: REQ-012 — a plain agent/ThinRuntime path with no supervisor is
unaffected by H6 (scenario 4).

H6 supervisor-orchestrator, Task 5. Proves the supervisor stays 100% opt-in:
a bare `ThinRuntime` run touches no supervisor code, `create_finalize_tool`
without verifier/ledger stays the plain pre-Task-5 summary, and no
production module outside `orchestration/supervisor/` imports the package.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from swarmline.orchestration.supervisor.blackboard import Blackboard
from swarmline.orchestration.supervisor.finalize import create_finalize_tool
from swarmline.orchestration.supervisor.state import SupervisorState
from swarmline.orchestration.types import Plan, PlanStep
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeEvent

REPO_ROOT = Path(__file__).resolve().parents[2]


class _MockLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def __call__(self, messages: object, system_prompt: str) -> str:
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return json.dumps({"type": "final", "final_message": "fallback"})


def _make_state() -> SupervisorState:
    plan = Plan(
        id="plan-1",
        goal="ship it",
        steps=[PlanStep(id="s1", description="build", status="completed")],
        created_at=datetime(2026, 7, 3, tzinfo=UTC),
    )
    return SupervisorState(blackboard=Blackboard(plan=plan))


class TestSingleAgentUnchangedWithoutSupervisor:
    @pytest.mark.asyncio
    async def test_single_agent_unchanged_without_supervisor(self) -> None:
        """A plain ThinRuntime agent (no supervisor wiring at all) runs
        exactly as before H6, AND `create_finalize_tool(state)` with no
        verifier/ledger keeps returning the plain summary unchanged."""
        llm = _MockLLM([json.dumps({"type": "final", "final_message": "ok"})])
        runtime = ThinRuntime(llm_call=llm)

        events: list[RuntimeEvent] = []
        async for ev in runtime.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
            mode_hint="react",
        ):
            events.append(ev)

        assert events[-1].type == "final"
        assert events[-1].data.get("text") == "ok"

        # REQ-012 opt-in back-compat: finalize with no verifier/ledger.
        state = _make_state()
        execute = create_finalize_tool(state)
        summary = await execute({})
        assert "BLOCKED" not in summary
        assert "plan-1" in summary

    def test_default_agent_path_does_not_import_supervisor(self) -> None:
        """Guard: running the plain single-agent path in a fresh process
        must never pull in `orchestration.supervisor` as a side-effect."""
        code = (
            "import sys\n"
            "import asyncio\n"
            "import json\n"
            "from swarmline.runtime.thin.runtime import ThinRuntime\n"
            "from swarmline.runtime.types import Message\n"
            "\n"
            "class _LLM:\n"
            "    async def __call__(self, messages, system_prompt):\n"
            "        return json.dumps({'type': 'final', 'final_message': 'ok'})\n"
            "\n"
            "async def _run():\n"
            "    runtime = ThinRuntime(llm_call=_LLM())\n"
            "    async for _ in runtime.run(\n"
            "        messages=[Message(role='user', content='hi')],\n"
            "        system_prompt='sys', active_tools=[], mode_hint='react',\n"
            "    ):\n"
            "        pass\n"
            "\n"
            "asyncio.run(_run())\n"
            "assert 'swarmline.orchestration.supervisor' not in sys.modules, sorted(sys.modules)\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout

    def test_no_production_module_outside_supervisor_package_imports_it(self) -> None:
        """Static guard mirroring the reconnaissance note this task was
        dispatched with: `grep -r "from swarmline.orchestration.supervisor"
        outside orchestration/supervisor/` must stay empty.

        I-066 exception: ``harness/agent_assembly.py`` is now a SANCTIONED
        second outside caller (mirroring ``orchestration/supervisor/
        harness_composition.py``'s own documented "outside caller" role) —
        ``harness.agent_assembly.build_supervisor_agent`` constructs a
        ``SupervisorState``/``Blackboard`` to actually APPLY the supervisor
        composition ``build()`` resolves. The import stays lazy (inside that
        one function body, never at module scope) — see
        ``tests/unit/test_harness_supervisor_apply.py``'s
        ``TestHarnessBuilderSupervisorApplyImportLight`` for the import-light
        proof this exception does not regress.

        Epic-G exception: ``orchestration/autopilot/deploy_phase.py`` is a
        SANCTIONED third outside caller — per ADR-G the autopilot engine is a
        level-C generative layer *layered over the closed H6 supervisor*, and
        its deploy phase reuses the ``supervisor.handoff.handoff()`` execution
        seam to drive the graph (rather than reinventing a delegate/wait loop).
        The import stays lazy (inside ``deploy()`` only; ``GraphHandoffRunner``
        is TYPE_CHECKING-only) so importing ``swarmline.orchestration.autopilot``
        never pulls the supervisor package — proven by
        ``tests/integration/test_autopilot_e2e.py``'s import-light check.
        """
        src_root = REPO_ROOT / "src" / "swarmline"
        allowed = {
            "harness/agent_assembly.py",
            "orchestration/autopilot/deploy_phase.py",
        }
        offenders: list[str] = []
        for path in src_root.rglob("*.py"):
            rel = path.relative_to(src_root).as_posix()
            if rel.startswith("orchestration/supervisor/") or rel in allowed:
                continue
            text = path.read_text(encoding="utf-8")
            if (
                "from swarmline.orchestration.supervisor" in text
                or "import swarmline.orchestration.supervisor" in text
            ):
                offenders.append(rel)
        assert offenders == []
