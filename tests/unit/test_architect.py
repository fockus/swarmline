"""Tests for ArchitectCoordinator — REQ-RCA-011/012 two-model plan→edit split.

TDD: tests written BEFORE implementation.
Naming: test_<what>_<condition>_<result>.
Arrangement: Arrange-Act-Assert.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from swarmline.runtime.model_settings import (
    ModelSettings,
    ModelSettingsResolverProtocol,
)


# ---------------------------------------------------------------------------
# Fakes (deterministic, no network)
# ---------------------------------------------------------------------------


class FakeLLMCall:
    """Records every LLM call; returns preset responses in order."""

    def __init__(self, returns: list[str]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._returns = returns

    async def __call__(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        *,
        config: Any = None,
    ) -> str:
        idx = len(self.calls)
        self.calls.append(
            {"messages": messages, "system_prompt": system_prompt, "config": config}
        )
        return self._returns[idx]


class FakeEditApplier:
    """Records every edit-apply call; returns a preset result."""

    def __init__(self, result: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = (
            result if result is not None else {"applied": True, "tokens": 100}
        )

    async def __call__(
        self,
        task: str,
        plan: str,
        edit_format: str | None,
        *,
        config: Any = None,
    ) -> Any:
        self.calls.append(
            {"task": task, "plan": plan, "edit_format": edit_format, "config": config}
        )
        return self._result


class FakeResolver(ModelSettingsResolverProtocol):
    """Returns preset ModelSettings per model name; falls back to a bare default.

    Inherits from ModelSettingsResolverProtocol for explicit ty compatibility
    (ty 0.0.31 does not support structural Protocol subtyping).
    """

    def __init__(self, settings_map: dict[str, Any]) -> None:
        self._settings_map = settings_map

    def resolve(self, raw: str | None) -> ModelSettings:
        if raw and raw in self._settings_map:
            return self._settings_map[raw]
        return ModelSettings(name=raw or "unknown")


def _base_config() -> Any:
    from swarmline.runtime.types import RuntimeConfig

    return RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")


# ---------------------------------------------------------------------------
# Tests — two-model path (editor_model set)
# ---------------------------------------------------------------------------


class TestArchitectCoordinatorTwoModelPath:
    @pytest.mark.asyncio
    async def test_phase1_uses_main_model_with_repo_map_disabled(self) -> None:
        """REQ-RCA-011: Phase 1 runs with main_model and repo-map disabled."""
        from swarmline.runtime.model_settings import ModelSettings
        from swarmline.runtime.thin.architect import ArchitectCoordinator

        llm = FakeLLMCall(returns=["Step 1: edit foo.py\nStep 2: add tests"])
        applier = FakeEditApplier()
        resolver = FakeResolver(
            {
                "editor-model": ModelSettings(
                    name="editor-model", edit_format="search_replace"
                )
            }
        )
        coord = ArchitectCoordinator(
            llm_call=llm,
            edit_applier=applier,
            resolver=resolver,
            base_config=_base_config(),
        )

        await coord.plan_then_edit(
            task="Add a login endpoint",
            main_model="main-model",
            editor_model="editor-model",
        )

        # Phase 1 LLM call used the main model
        assert len(llm.calls) == 1
        assert llm.calls[0]["config"] is not None
        assert llm.calls[0]["config"].model == "main-model"

        # Plan-call record captures repo_map_enabled=False
        assert len(coord.plan_calls) == 1
        assert coord.plan_calls[0].repo_map_enabled is False
        assert coord.plan_calls[0].model == "main-model"

        # F2: assert the ACTUAL planning call content excluded repo-map
        planning_sp = llm.calls[0]["system_prompt"]
        assert "intentionally omitted" in planning_sp, (
            "Planning turn system prompt must declare repo-map as intentionally omitted"
        )
        planning_msgs = llm.calls[0]["messages"]
        # Only the task was sent — no extra repo-map block injected
        assert len(planning_msgs) == 1, (
            "No extra messages (no repo-map) sent to planner"
        )
        assert planning_msgs[0]["role"] == "user"
        assert "login endpoint" in planning_msgs[0]["content"].lower()

    @pytest.mark.asyncio
    async def test_phase2_uses_editor_model_and_its_edit_format(self) -> None:
        """REQ-RCA-011: Phase 2 uses editor_model with its declared edit_format."""
        from swarmline.runtime.model_settings import ModelSettings
        from swarmline.runtime.thin.architect import ArchitectCoordinator

        llm = FakeLLMCall(returns=["Plan: edit bar.py"])
        applier = FakeEditApplier()
        resolver = FakeResolver(
            {"my-editor": ModelSettings(name="my-editor", edit_format="patch")}
        )
        coord = ArchitectCoordinator(
            llm_call=llm,
            edit_applier=applier,
            resolver=resolver,
            base_config=_base_config(),
        )

        await coord.plan_then_edit(
            task="Refactor utils",
            main_model="my-main",
            editor_model="my-editor",
        )

        assert len(applier.calls) == 1
        edit_call = applier.calls[0]
        # Editor model forwarded via config
        assert edit_call["config"] is not None
        assert edit_call["config"].model == "my-editor"
        # Editor's edit_format forwarded
        assert edit_call["edit_format"] == "patch"

    @pytest.mark.asyncio
    async def test_plan_passed_verbatim_to_phase2_context(self) -> None:
        """REQ-RCA-011: Phase-1 plan text is passed verbatim to Phase 2."""
        from swarmline.runtime.model_settings import ModelSettings
        from swarmline.runtime.thin.architect import ArchitectCoordinator

        plan_text = "Step 1: edit auth.py\nStep 2: write tests\nStep 3: lint"
        llm = FakeLLMCall(returns=[plan_text])
        applier = FakeEditApplier()
        resolver = FakeResolver({"ed": ModelSettings(name="ed", edit_format="diff")})
        coord = ArchitectCoordinator(
            llm_call=llm,
            edit_applier=applier,
            resolver=resolver,
            base_config=_base_config(),
        )

        await coord.plan_then_edit(
            task="Update auth", main_model="mn", editor_model="ed"
        )

        assert applier.calls[0]["plan"] == plan_text

    @pytest.mark.asyncio
    async def test_cost_metadata_propagates_into_outcome(self) -> None:
        """edit_applier result (with cost metadata) propagates verbatim into ArchitectOutcome."""
        from swarmline.runtime.model_settings import ModelSettings
        from swarmline.runtime.thin.architect import ArchitectCoordinator

        edit_result = {"applied": True, "tokens_used": 512, "cost_usd": 0.002}
        llm = FakeLLMCall(returns=["the plan"])
        applier = FakeEditApplier(result=edit_result)
        resolver = FakeResolver(
            {"ed": ModelSettings(name="ed", edit_format="search_replace")}
        )
        coord = ArchitectCoordinator(
            llm_call=llm,
            edit_applier=applier,
            resolver=resolver,
            base_config=_base_config(),
        )

        outcome = await coord.plan_then_edit(
            task="task", main_model="mn", editor_model="ed"
        )

        assert outcome.edit_result == edit_result
        assert outcome.plan == "the plan"
        assert outcome.model_used == "ed"

    @pytest.mark.asyncio
    async def test_outcome_carries_plan_and_edit_format(self) -> None:
        """ArchitectOutcome carries plan + edit_format from the editor model settings."""
        from swarmline.runtime.model_settings import ModelSettings
        from swarmline.runtime.thin.architect import ArchitectCoordinator

        llm = FakeLLMCall(returns=["Do X then Y"])
        applier = FakeEditApplier()
        resolver = FakeResolver({"ed": ModelSettings(name="ed", edit_format="whole")})
        coord = ArchitectCoordinator(
            llm_call=llm,
            edit_applier=applier,
            resolver=resolver,
            base_config=_base_config(),
        )

        outcome = await coord.plan_then_edit(
            task="Fix bug", main_model="mn", editor_model="ed"
        )

        assert outcome.plan == "Do X then Y"
        assert outcome.edit_format == "whole"
        assert outcome.model_used == "ed"


# ---------------------------------------------------------------------------
# Tests — fallback path (editor_model is None) — REQ-RCA-012
# ---------------------------------------------------------------------------


class TestArchitectCoordinatorFallback:
    @pytest.mark.asyncio
    async def test_editor_model_none_no_planning_llm_call(self) -> None:
        """REQ-RCA-012: editor_model=None → no planning LLM call (no architect split)."""
        from swarmline.runtime.thin.architect import ArchitectCoordinator

        llm = FakeLLMCall(returns=[])
        applier = FakeEditApplier()
        coord = ArchitectCoordinator(
            llm_call=llm,
            edit_applier=applier,
            resolver=FakeResolver({}),
            base_config=_base_config(),
        )

        await coord.plan_then_edit(
            task="Add feature", main_model="mn", editor_model=None
        )

        # No LLM call for planning
        assert llm.calls == []
        # Edit applier was called (single-model fallback)
        assert len(applier.calls) == 1

    @pytest.mark.asyncio
    async def test_editor_model_none_outcome_plan_empty_or_none(self) -> None:
        """REQ-RCA-012: fallback path → ArchitectOutcome.plan is empty/None."""
        from swarmline.runtime.thin.architect import ArchitectCoordinator

        applier = FakeEditApplier(result={"applied": True})
        coord = ArchitectCoordinator(
            llm_call=FakeLLMCall(returns=[]),
            edit_applier=applier,
            resolver=FakeResolver({}),
            base_config=_base_config(),
        )

        outcome = await coord.plan_then_edit(
            task="task", main_model="mn", editor_model=None
        )

        # plan must be empty (the invariant: no plan generated in fallback)
        assert outcome.plan == "" or outcome.plan is None

    @pytest.mark.asyncio
    async def test_editor_model_none_uses_main_model_for_edit(self) -> None:
        """REQ-RCA-012: fallback edit call uses main model config."""
        from swarmline.runtime.thin.architect import ArchitectCoordinator

        applier = FakeEditApplier()
        coord = ArchitectCoordinator(
            llm_call=FakeLLMCall(returns=[]),
            edit_applier=applier,
            resolver=FakeResolver({}),
            base_config=_base_config(),
        )

        await coord.plan_then_edit(task="task", main_model="my-main", editor_model=None)

        assert applier.calls[0]["config"].model == "my-main"

    @pytest.mark.asyncio
    async def test_editor_model_none_no_plan_calls_recorded(self) -> None:
        """REQ-RCA-012: fallback path records no plan calls."""
        from swarmline.runtime.thin.architect import ArchitectCoordinator

        coord = ArchitectCoordinator(
            llm_call=FakeLLMCall(returns=[]),
            edit_applier=FakeEditApplier(),
            resolver=FakeResolver({}),
            base_config=_base_config(),
        )

        await coord.plan_then_edit(task="task", main_model="mn", editor_model=None)

        assert coord.plan_calls == []


# ---------------------------------------------------------------------------
# Tests — gating: enable_architect=False → byte-identical OFF path
# ---------------------------------------------------------------------------


class TestArchitectGating:
    def test_wire_returns_none_when_enable_architect_false(self) -> None:
        """wire_architect_coordinator returns None when enable_architect=False (default)."""
        from swarmline.runtime.thin.architect import wire_architect_coordinator

        profile = CodingProfileConfig(enable_architect=False)
        result = wire_architect_coordinator(
            coding_profile=profile,
            llm_call=FakeLLMCall(returns=[]),
            edit_applier=FakeEditApplier(),
            resolver=FakeResolver({}),
            base_config=_base_config(),
        )
        assert result is None

    def test_wire_returns_none_when_profile_is_none(self) -> None:
        """wire_architect_coordinator returns None when coding_profile is None."""
        from swarmline.runtime.thin.architect import wire_architect_coordinator

        result = wire_architect_coordinator(
            coding_profile=None,
            llm_call=FakeLLMCall(returns=[]),
            edit_applier=FakeEditApplier(),
            resolver=FakeResolver({}),
            base_config=_base_config(),
        )
        assert result is None

    def test_wire_returns_none_when_no_editor_model_for_main(self) -> None:
        """wire_architect_coordinator returns None when main model has no editor_model_name."""
        from swarmline.runtime.model_settings import ModelSettings
        from swarmline.runtime.thin.architect import wire_architect_coordinator

        profile = CodingProfileConfig(enable_architect=True)
        resolver = FakeResolver(
            {"main": ModelSettings(name="main", editor_model_name=None)}
        )
        result = wire_architect_coordinator(
            coding_profile=profile,
            llm_call=FakeLLMCall(returns=[]),
            edit_applier=FakeEditApplier(),
            resolver=resolver,
            base_config=_base_config(),
            main_model="main",
        )
        assert result is None

    def test_wire_returns_coordinator_when_enabled_and_editor_model_present(
        self,
    ) -> None:
        """wire_architect_coordinator returns ArchitectCoordinator when fully activated."""
        from swarmline.runtime.model_settings import ModelSettings
        from swarmline.runtime.thin.architect import (
            ArchitectCoordinator,
            wire_architect_coordinator,
        )

        profile = CodingProfileConfig(enable_architect=True)
        resolver = FakeResolver(
            {
                "main-model": ModelSettings(
                    name="main-model", editor_model_name="editor-model"
                )
            }
        )
        result = wire_architect_coordinator(
            coding_profile=profile,
            llm_call=FakeLLMCall(returns=[]),
            edit_applier=FakeEditApplier(),
            resolver=resolver,
            base_config=_base_config(),
            main_model="main-model",
        )
        assert isinstance(result, ArchitectCoordinator)

    def test_coding_profile_enable_architect_default_false(self) -> None:
        """CodingProfileConfig.enable_architect defaults to False (byte-identical OFF)."""
        cfg = CodingProfileConfig()
        assert cfg.enable_architect is False

    def test_coding_profile_enable_architect_can_be_enabled(self) -> None:
        """CodingProfileConfig.enable_architect can be set to True."""
        cfg = CodingProfileConfig(enable_architect=True)
        assert cfg.enable_architect is True

    def test_coding_profile_with_enable_architect_is_still_frozen(self) -> None:
        """CodingProfileConfig remains frozen when enable_architect is used."""
        cfg = CodingProfileConfig(enable_architect=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, "enable_architect", False)


# ---------------------------------------------------------------------------
# Tests — ArchitectOutcome dataclass contract
# ---------------------------------------------------------------------------


class TestArchitectOutcome:
    def test_architect_outcome_is_frozen_dataclass(self) -> None:
        """ArchitectOutcome is a frozen dataclass (stdlib only, no framework deps)."""
        from swarmline.runtime.thin.architect import ArchitectOutcome

        assert dataclasses.is_dataclass(ArchitectOutcome)
        o = ArchitectOutcome(plan="p", edit_result={}, model_used="m", edit_format=None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(o, "plan", "new")

    def test_architect_outcome_carries_required_fields(self) -> None:
        """ArchitectOutcome carries plan, edit_result, model_used, edit_format."""
        from swarmline.runtime.thin.architect import ArchitectOutcome

        o = ArchitectOutcome(
            plan="plan text",
            edit_result={"applied": True},
            model_used="editor-x",
            edit_format="search_replace",
        )
        assert o.plan == "plan text"
        assert o.edit_result == {"applied": True}
        assert o.model_used == "editor-x"
        assert o.edit_format == "search_replace"

    def test_architect_outcome_optional_cost_fields_default_none(self) -> None:
        """ArchitectOutcome optional cost fields default to None."""
        from swarmline.runtime.thin.architect import ArchitectOutcome

        o = ArchitectOutcome(
            plan="", edit_result=None, model_used="m", edit_format=None
        )
        assert o.tokens_used is None
        assert o.cost_usd is None

    def test_architect_outcome_equality_value_based(self) -> None:
        """Two ArchitectOutcomes with the same fields are equal (frozen dataclass)."""
        from swarmline.runtime.thin.architect import ArchitectOutcome

        a = ArchitectOutcome(
            plan="p", edit_result=None, model_used="m", edit_format=None
        )
        b = ArchitectOutcome(
            plan="p", edit_result=None, model_used="m", edit_format=None
        )
        assert a == b


# Import at module level for gating tests
from swarmline.runtime.thin.coding_profile import CodingProfileConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Tests — run_architect_strategy end-to-end (F1: runtime wiring)
# ---------------------------------------------------------------------------


class TestRunArchitectStrategy:
    @pytest.mark.asyncio
    async def test_phase1_uses_main_model_phase2_uses_editor_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_architect_strategy Phase 1 calls main model; Phase 2 runs via editor model."""
        import swarmline.runtime.thin.architect as _arch_mod
        from swarmline.runtime.types import Message, RuntimeEvent

        llm_calls: list[dict[str, Any]] = []
        # Use a mutable container instead of function attributes (ty-clean)
        spy: dict[str, str] = {"received_sp": ""}

        async def fake_llm(
            messages: Any, system_prompt: str, *, config: Any = None
        ) -> str:
            llm_calls.append(
                {"model": getattr(config, "model", None), "sp": system_prompt}
            )
            return "Plan: edit foo.py"

        async def fake_run_react(
            llm_call: Any,
            executor: Any,
            messages: Any,
            system_prompt: str,
            *args: Any,
            **kwargs: Any,
        ) -> AsyncIterator[RuntimeEvent]:
            spy["received_sp"] = system_prompt
            yield RuntimeEvent.final("Phase 2 done")

        monkeypatch.setattr(_arch_mod, "run_react", fake_run_react)

        msgs = [Message(role="user", content="Add login endpoint")]
        events = [
            e
            async for e in _arch_mod.run_architect_strategy(
                raw_llm_call=fake_llm,
                executor=None,
                messages=msgs,
                system_prompt="You are a coder.",
                tools=[],
                base_config=_base_config(),
                start_time=0.0,
                main_model="main-model",
                editor_model="editor-model",
            )
        ]

        # Phase 1: LLM called with main model and planning system prompt
        assert len(llm_calls) == 1
        assert llm_calls[0]["model"] == "main-model"
        assert "intentionally omitted" in llm_calls[0]["sp"]

        # Phase 2: plan prepended to editor system prompt
        assert "Plan: edit foo.py" in spy["received_sp"]
        assert "Implementation Plan" in spy["received_sp"]

        # Phase 2 events forwarded
        assert any(e.is_final for e in events)

    def test_thin_runtime_architect_editor_model_none_when_disabled(self) -> None:
        """ThinRuntime._architect_editor_model is None when enable_architect=False (OFF path)."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        rt = ThinRuntime(coding_profile=CodingProfileConfig(enable_architect=False))
        assert rt._architect_editor_model is None

    def test_thin_runtime_architect_editor_model_none_when_no_profile(self) -> None:
        """ThinRuntime._architect_editor_model is None when coding_profile is None."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        rt = ThinRuntime(coding_profile=None)
        assert rt._architect_editor_model is None

    def test_thin_runtime_architect_editor_model_set_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ThinRuntime._architect_editor_model is set when enable_architect=True and model has editor."""
        from swarmline.runtime.model_settings import (
            ModelSettings,
            ModelSettingsResolver,
        )
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        fake_settings = ModelSettings(
            name="test-model", editor_model_name="test-editor"
        )
        monkeypatch.setattr(
            ModelSettingsResolver, "resolve", lambda self, raw: fake_settings
        )

        rt = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin", model="test-model"),
            coding_profile=CodingProfileConfig(enable_architect=True),
        )
        assert rt._architect_editor_model == "test-editor"

    @pytest.mark.asyncio
    async def test_run_architect_strategy_phase1_excludes_prior_repo_map_from_messages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Phase-1 planning call receives TASK-ONLY messages even when prior turns have repo-map.

        REQ-RCA-011: repo-map must be excluded from the planning turn. The full
        conversation ``messages`` list is NOT forwarded — only the task text from
        the last user message is sent, mirroring ArchitectCoordinator._two_phase_run.
        """
        import swarmline.runtime.thin.architect as _arch_mod
        from swarmline.runtime.types import Message, RuntimeEvent

        # Capture every call made to the planning LLM (Phase 1 only)
        phase1_received: list[list[Any]] = []

        async def fake_llm(
            messages: Any, system_prompt: str, *, config: Any = None
        ) -> str:
            if getattr(config, "model", None) == "main-model":
                phase1_received.append(list(messages))
            return "Plan: edit auth.py"

        async def fake_run_react(
            llm_call: Any,
            executor: Any,
            messages: Any,
            system_prompt: str,
            *args: Any,
            **kwargs: Any,
        ) -> AsyncIterator[RuntimeEvent]:
            yield RuntimeEvent.final("done")

        monkeypatch.setattr(_arch_mod, "run_react", fake_run_react)

        # Inject repo-map-like content in a prior assistant turn (simulates context injection)
        msgs = [
            Message(role="user", content="Add auth endpoint"),
            Message(
                role="assistant",
                content="<repo_map>\nauth.py\nmodels.py\n</repo_map>",
            ),
            Message(
                role="user", content="Add auth endpoint"
            ),  # actual task (last user msg)
        ]

        [
            e
            async for e in _arch_mod.run_architect_strategy(
                raw_llm_call=fake_llm,
                executor=None,
                messages=msgs,
                system_prompt="You are a coder.",
                tools=[],
                base_config=_base_config(),
                start_time=0.0,
                main_model="main-model",
                editor_model="editor-model",
            )
        ]

        # Phase-1 planning call must use TASK-ONLY messages — not the full conversation
        assert len(phase1_received) == 1, "Exactly one Phase-1 planning call"
        planning_msgs = phase1_received[0]
        assert len(planning_msgs) == 1, (
            f"Phase-1 must send ONE task-only message, got {len(planning_msgs)}"
        )
        assert planning_msgs[0]["role"] == "user"
        # Repo-map content from prior assistant turn must NOT appear in Phase-1
        assert "<repo_map>" not in planning_msgs[0]["content"], (
            "Repo-map content must be excluded from Phase-1 planning messages"
        )
        assert "auth endpoint" in planning_msgs[0]["content"]


# ---------------------------------------------------------------------------
# Required top-level imports for TestRunArchitectStrategy
# ---------------------------------------------------------------------------
from collections.abc import AsyncIterator  # noqa: E402
