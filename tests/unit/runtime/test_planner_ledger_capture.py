"""Tests for kernel-wiring spec, Task 2 — planner ledger auto-population (I-034).

TDD: written BEFORE ``_capture_plan_ledger`` is wired into
``run_planner`` (planner_strategy.py).

Covers Requirement 2 (REQ-005..008) and Scenario 2 of
``.memory-bank/specs/kernel-wiring/requirements.md``:

``ledger_from_plan`` (verification_capture.py) is green standalone but had
zero production call sites. This suite proves ``run_planner`` now
auto-populates ``config.verification_ledger`` from the plan's own
``success_criteria`` at the FINAL-assembly finalize call — but only when
the caller opted into verification (``config.verifier`` set) and did not
already supply a ledger — and never mutates the caller's ``RuntimeConfig``.

The finalize call is spied by monkeypatching ``finalize_with_validation``
in ``planner_strategy``'s own namespace: the fake captures the ``config``
argument it was called with (a real observable of the wiring) and yields a
minimal ``final`` event so the generator terminates normally.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from swarmline.runtime.thin import planner_strategy
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.parsers import parse_plan
from swarmline.runtime.thin.planner_strategy import _capture_plan_ledger, run_planner
from swarmline.runtime.thin.schemas import PlanSchema, PlanStep
from swarmline.runtime.thin.verification_capture import ledger_from_plan
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent
from swarmline.types import VerificationLedger

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class DummyVerifier:
    """Minimal ``Verifier``-shaped stand-in; never actually invoked in these
    tests because ``finalize_with_validation`` is spied/replaced before the
    gate would run it."""

    async def verify(
        self, ledger: VerificationLedger, ctx: object
    ) -> VerificationLedger:
        return ledger


_PLAN_JSON = json.dumps(
    {
        "type": "plan",
        "goal": "ship the feature",
        "steps": [
            {
                "id": "step-1",
                "title": "write code",
                "mode": "conversational",
                "max_iterations": 2,
                "success_criteria": ["all tests pass", "no linter warnings"],
            },
            {
                "id": "step-2",
                "title": "ship it",
                "mode": "conversational",
                "max_iterations": 2,
                "success_criteria": ["deployed to staging"],
            },
        ],
        "final_format": "summary",
    }
)


def _expected_plan() -> PlanSchema:
    plan = parse_plan(_PLAN_JSON)
    assert plan is not None
    return plan


def _make_llm_call() -> Any:
    """Returns the plan JSON, then a 'final' envelope for each conversational
    step, then a 'final' envelope for the final-assembly call."""
    responses = [
        _PLAN_JSON,
        json.dumps({"type": "final", "final_message": "step-1 done"}),
        json.dumps({"type": "final", "final_message": "step-2 done"}),
        json.dumps({"type": "final", "final_message": "assembled"}),
    ]
    calls: list[list[dict[str, str]]] = []

    async def llm_call(messages: list[dict[str, str]], system_prompt: str) -> str:
        calls.append(list(messages))
        return responses[len(calls) - 1]

    return llm_call


async def _run_and_capture_finalize_config(
    monkeypatch: pytest.MonkeyPatch, config: RuntimeConfig
) -> RuntimeConfig:
    """Drive run_planner end-to-end, spying the config finalize_with_validation
    actually receives (the real observable of the wiring)."""
    captured: dict[str, RuntimeConfig] = {}

    async def fake_finalize(
        text: str,
        finalize_config: RuntimeConfig,
        lm_messages: list[dict[str, str]],
        prompt: str,
        llm_call: Any,
        start_time: float,
        **kwargs: Any,
    ) -> AsyncIterator[RuntimeEvent]:
        captured["config"] = finalize_config
        yield RuntimeEvent.final(text=text, new_messages=[], metrics={}, usage={})

    monkeypatch.setattr(planner_strategy, "finalize_with_validation", fake_finalize)

    events = []
    async for event in run_planner(
        _make_llm_call(),
        ToolExecutor(),
        [Message(role="user", content="build it")],
        system_prompt="system",
        tools=[],
        config=config,
        start_time=0.0,
    ):
        events.append(event)

    assert any(e.type == "final" for e in events)
    assert "config" in captured
    return captured["config"]


# ---------------------------------------------------------------------------
# REQ-005 / Scenario 2: verifier set + no caller ledger -> ledger populated
# ---------------------------------------------------------------------------


class TestPlannerLedgerAutoPopulation:
    @pytest.mark.asyncio
    async def test_planner_populates_ledger_when_verifier_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = RuntimeConfig(
            runtime_name="thin", verifier=DummyVerifier(), verification_ledger=None
        )

        finalize_config = await _run_and_capture_finalize_config(monkeypatch, config)

        expected = ledger_from_plan(_expected_plan())
        assert finalize_config.verification_ledger == expected
        assert finalize_config.verification_ledger is not None
        assert len(finalize_config.verification_ledger.criteria) == 3
        assert finalize_config.verification_ledger.criteria[0].id == "step-1:sc0"

    @pytest.mark.asyncio
    async def test_caller_ledger_never_overridden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sentinel_ledger = VerificationLedger()
        config = RuntimeConfig(
            runtime_name="thin",
            verifier=DummyVerifier(),
            verification_ledger=sentinel_ledger,
        )

        finalize_config = await _run_and_capture_finalize_config(monkeypatch, config)

        assert finalize_config.verification_ledger is sentinel_ledger

    @pytest.mark.asyncio
    async def test_planner_no_ledger_when_verifier_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = RuntimeConfig(
            runtime_name="thin", verifier=None, verification_ledger=None
        )

        finalize_config = await _run_and_capture_finalize_config(monkeypatch, config)

        assert finalize_config.verification_ledger is None
        assert finalize_config is config

    @pytest.mark.asyncio
    async def test_planner_does_not_mutate_input_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = RuntimeConfig(
            runtime_name="thin", verifier=DummyVerifier(), verification_ledger=None
        )

        await _run_and_capture_finalize_config(monkeypatch, config)

        assert config.verification_ledger is None


# ---------------------------------------------------------------------------
# Direct unit coverage of the helper (cheap, parametrized over the 3 branches)
# ---------------------------------------------------------------------------


class TestCapturePlanLedgerHelper:
    def test_helper_returns_same_config_when_verifier_none(self) -> None:
        config = RuntimeConfig(runtime_name="thin")
        plan = _expected_plan()

        result = _capture_plan_ledger(config, plan)

        assert result is config

    def test_helper_returns_same_config_when_ledger_already_set(self) -> None:
        sentinel_ledger = VerificationLedger()
        config = RuntimeConfig(
            runtime_name="thin",
            verifier=DummyVerifier(),
            verification_ledger=sentinel_ledger,
        )
        plan = _expected_plan()

        result = _capture_plan_ledger(config, plan)

        assert result is config
        assert result.verification_ledger is sentinel_ledger

    def test_helper_replaces_ledger_with_plan_derived_one(self) -> None:
        config = RuntimeConfig(
            runtime_name="thin", verifier=DummyVerifier(), verification_ledger=None
        )
        plan = PlanSchema(
            goal="g",
            steps=[
                PlanStep(id="s1", title="t", success_criteria=["done"]),
            ],
        )

        result = _capture_plan_ledger(config, plan)

        assert result is not config
        assert config.verification_ledger is None
        assert result.verification_ledger == ledger_from_plan(plan)
