# Attribution: adapted from aider (Apache-2.0)
# Upstream file: aider/coders/architect_coder.py
# Copyright: (c) Paul Gauthier and contributors
# Changes: reimplemented for swarmline as ArchitectCoordinator; the plan-then-edit
#          two-model split design is adapted from aider's architect/editor split
#          concept; repo-map suppression for the planning turn and the
#          ArchitectOutcome value object are original; no verbatim copy of aider
#          source.
"""Architect mode coordinator — REQ-RCA-011/012 two-model plan→edit split.

Phase 1 (plan): main model, repo-map DISABLED, returns NL plan.
Phase 2 (edit): editor model + plan as context, its own edit_format.
Fallback (REQ-RCA-012): editor_model=None → single-model edit, plan="".

Byte-identical OFF (REQ-RCA-071): ``wire_architect_coordinator`` returns ``None``
when ``enable_architect`` is False (default) or when the model has no
``editor_model_name``. Runtime MUST use normal coding path unchanged when None.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from swarmline.runtime.thin.react_strategy import run_react
from swarmline.runtime.thin.runtime_support import extract_last_user_text
from swarmline.runtime.types import RuntimeEvent

if TYPE_CHECKING:
    from swarmline.runtime.model_settings import ModelSettingsResolverProtocol
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig


# ---------------------------------------------------------------------------
# Module-level planning prompt (repo-map intentionally excluded)
# ---------------------------------------------------------------------------

_PLANNING_SYSTEM_PROMPT = (
    "You are an expert software architect. "
    "Produce a concise, actionable natural-language implementation plan for "
    "the task described below. Do NOT write code. Focus on which files to "
    "change, what logic to add/modify, and the order of operations.\n\n"
    "IMPORTANT: Repository map context is intentionally omitted for this "
    "planning turn — reason from first principles about the task structure."
)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PlanCallRecord:
    """Record of one planning-turn LLM invocation (observability/testing)."""

    model: str
    repo_map_enabled: bool  # Always False for planning turns (REQ-RCA-011)
    system_prompt: str  # Truncated to 200 chars


@dataclass(frozen=True)
class ArchitectOutcome:
    """Outcome of a two-phase architect plan→edit run.

    ``plan`` is empty when the fallback (no editor model) path was used.
    ``model_used`` is the editor model for two-phase, main model for fallback.
    """

    plan: str
    edit_result: Any
    model_used: str
    edit_format: str | None
    tokens_used: int | None = None
    cost_usd: float | None = None


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class ArchitectCoordinator:
    """Run a two-model plan→edit architect turn (REQ-RCA-011/012).

    All dependencies injected — fully unit-testable without network.
    ``resolver`` is typed as ``ModelSettingsResolverProtocol`` (DIP boundary).
    """

    def __init__(
        self,
        llm_call: Callable[..., Awaitable[Any]],
        edit_applier: Callable[..., Awaitable[Any]],
        resolver: ModelSettingsResolverProtocol,
        base_config: Any,
    ) -> None:
        self._llm_call = llm_call
        self._edit_applier = edit_applier
        self._resolver = resolver
        self._base_config = base_config
        self._plan_calls: list[_PlanCallRecord] = []

    @property
    def plan_calls(self) -> list[_PlanCallRecord]:
        """Read-only snapshot of planning-turn records (for observability/testing)."""
        return list(self._plan_calls)

    async def plan_then_edit(
        self,
        task: str,
        main_model: str,
        editor_model: str | None,
    ) -> ArchitectOutcome:
        """Plan then edit, or fall back to single-model edit when editor_model is None."""
        if editor_model is None:
            return await self._single_model_fallback(task, main_model)
        return await self._two_phase_run(task, main_model, editor_model)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _two_phase_run(
        self, task: str, main_model: str, editor_model: str
    ) -> ArchitectOutcome:
        """Full two-phase plan→edit split (REQ-RCA-011)."""
        # Phase 1: plan with main model — repo-map DISABLED
        main_config: Any = dataclasses.replace(self._base_config, model=main_model)
        planning_messages = [{"role": "user", "content": task}]
        plan_text: str = await self._llm_call(
            planning_messages,
            _PLANNING_SYSTEM_PROMPT,
            config=main_config,
        )
        self._plan_calls.append(
            _PlanCallRecord(
                model=main_model,
                repo_map_enabled=False,
                system_prompt=_PLANNING_SYSTEM_PROMPT[:200],
            )
        )

        # Phase 2: edit with editor model using its declared edit_format
        editor_settings = self._resolver.resolve(editor_model)
        edit_format = editor_settings.edit_format
        editor_config: Any = dataclasses.replace(self._base_config, model=editor_model)
        edit_result: Any = await self._edit_applier(
            task,
            plan_text,
            edit_format,
            config=editor_config,
        )
        return ArchitectOutcome(
            plan=plan_text,
            edit_result=edit_result,
            model_used=editor_model,
            edit_format=edit_format,
        )

    async def _single_model_fallback(
        self, task: str, main_model: str
    ) -> ArchitectOutcome:
        """Single-model fallback (REQ-RCA-012): byte-identical to pre-architect path."""
        main_config: Any = dataclasses.replace(self._base_config, model=main_model)
        edit_result: Any = await self._edit_applier(task, "", None, config=main_config)
        return ArchitectOutcome(
            plan="", edit_result=edit_result, model_used=main_model, edit_format=None
        )


# ---------------------------------------------------------------------------
# Gated factory — byte-identical OFF invariant
# ---------------------------------------------------------------------------


def wire_architect_coordinator(
    *,
    coding_profile: CodingProfileConfig | None,
    llm_call: Callable[..., Any],
    edit_applier: Callable[..., Any],
    resolver: ModelSettingsResolverProtocol,
    base_config: Any,
    main_model: str | None = None,
) -> ArchitectCoordinator | None:
    """Return an ``ArchitectCoordinator`` when architect mode is active, else ``None``.

    Returns ``None`` (OFF / byte-identical) when:
    - ``coding_profile`` is ``None`` or ``enable_architect`` is False, OR
    - the resolved main model has no ``editor_model_name``.
    """
    if coding_profile is None or not coding_profile.enable_architect:
        return None
    settings = resolver.resolve(main_model)
    if settings.editor_model_name is None:
        return None
    return ArchitectCoordinator(
        llm_call=llm_call,
        edit_applier=edit_applier,
        resolver=resolver,
        base_config=base_config,
    )


# ---------------------------------------------------------------------------
# Runtime strategy — two-phase async generator (F1: runtime wiring)
# ---------------------------------------------------------------------------


async def run_architect_strategy(
    *,
    raw_llm_call: Callable[..., Any],
    executor: Any,
    messages: list[Any],
    system_prompt: str,
    tools: list[Any],
    base_config: Any,
    start_time: float,
    main_model: str,
    editor_model: str,
    checkpoint: Any | None = None,
    on_retry: Any | None = None,
    native_adapter: Any | None = None,
    session_dispatcher: Any | None = None,
) -> AsyncIterator[RuntimeEvent]:
    """Two-phase architect strategy for ThinRuntime's react mode (REQ-RCA-011).

    Phase 1: LLM call with main_model + ``_PLANNING_SYSTEM_PROMPT`` (repo-map OFF).
    Phase 2: ``run_react`` with editor_model + plan appended to system_prompt.
    All Phase 2 events are forwarded unchanged.

    ``session_dispatcher`` (RCA Task 5): when provided, Phase-2 edit-family tool
    completions dispatch file.edited session events via ``run_react``.  Defaults
    to None (byte-identical OFF path).
    """
    # Phase 1: plan — task-only message set, repo-map intentionally excluded (REQ-RCA-011).
    # Do NOT forward the full `messages` list: prior turns may contain repo-map/context
    # blocks that would violate the repo-map-off invariant. Mirror _two_phase_run:
    # extract only the last user text and send it as a single-message planning request.
    yield RuntimeEvent.status("Architect: planning phase (main model)")
    main_config: Any = dataclasses.replace(base_config, model=main_model)
    task_text: str = extract_last_user_text(messages)
    planning_messages: list[dict[str, str]] = [{"role": "user", "content": task_text}]
    plan_raw: Any = await raw_llm_call(
        planning_messages, _PLANNING_SYSTEM_PROMPT, config=main_config
    )
    plan_text: str = (
        plan_raw if isinstance(plan_raw, str) else (getattr(plan_raw, "text", "") or "")
    )

    # Phase 2: edit — editor model, plan as additional context
    yield RuntimeEvent.status("Architect: edit phase (editor model)")
    editor_config: Any = dataclasses.replace(base_config, model=editor_model)
    editor_system_prompt = (
        system_prompt
        + "\n\n## Implementation Plan (from Architect Phase)\n\n"
        + plan_text
    )
    editor_llm_call = partial(raw_llm_call, config=editor_config)

    async for event in run_react(
        editor_llm_call,
        executor,
        messages,
        editor_system_prompt,
        tools,
        editor_config,
        start_time,
        checkpoint=checkpoint,
        on_retry=on_retry,
        native_adapter=native_adapter,
        session_dispatcher=session_dispatcher,
    ):
        yield event
