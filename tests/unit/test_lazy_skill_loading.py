"""Tests for lazy skill loading (REQ-RCA-040 / RCA Task 6 — G7).

The LIVE path:
    CodingProfileConfig.enable_lazy_skills
        -> runtime_wiring.build_portable_runtime_plan
            -> CodingContextInputFilter(lazy_skills=..., skill_registry=...)
                -> CodingContextAssembler (skill_profile slice = names+descriptions only)
            -> read_skill ToolSpec + executor added to active_tools / tool_executors

Contract:
- enable_lazy_skills=True  -> skill_profile slice has names+descriptions only (NO bodies)
- on-demand body           -> read_skill tool returns full instruction_md via registry
- bounded growth           -> prompt size scales with N x (name+desc), not N x body
- enable_lazy_skills=False -> OFF: filter behaviour byte-identical to pre-Task-6
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from swarmline.context.coding_input_filter import CodingContextInputFilter
from swarmline.domain_types import Message
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.skills.registry import SkillRegistry
from swarmline.skills.skill_tool import create_skill_read_tool
from swarmline.skills.types import LoadedSkill, SkillSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(
    skill_id: str,
    *,
    description: str = "",
    body: str = "",
) -> LoadedSkill:
    return LoadedSkill(
        spec=SkillSpec(
            skill_id=skill_id,
            title=f"Title-{skill_id}",
            description=description or f"Description for {skill_id}",
        ),
        instruction_md=body or f"BODY_CONTENT_OF_{skill_id}",
    )


def _user_message(text: str = "Fix the bug") -> Message:
    return Message(role="user", content=text)


async def _run_filter(
    filter_obj: CodingContextInputFilter,
    *,
    user_text: str = "Fix the bug",
    base_prompt: str = "",
) -> str:
    """Invoke filter and return the merged system prompt."""
    _, merged = await filter_obj.filter([_user_message(user_text)], base_prompt)
    return merged


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    """Existing directory used as workspace_cwd."""
    return tmp_path


@pytest.fixture
def skill_alpha() -> LoadedSkill:
    return _make_skill(
        "alpha",
        description="Alpha skill for testing",
        body="ALPHA_FULL_INSTRUCTION_BODY_UNIQUE_MARKER",
    )


@pytest.fixture
def skill_beta() -> LoadedSkill:
    return _make_skill(
        "beta",
        description="Beta skill for testing",
        body="BETA_FULL_INSTRUCTION_BODY_UNIQUE_MARKER",
    )


# ---------------------------------------------------------------------------
# F1 - LIVE PATH: CodingContextInputFilter with lazy_skills=True
# ---------------------------------------------------------------------------


class TestLazyFilter_NamesOnlyInSkillProfile:
    """CodingContextInputFilter with lazy_skills=True injects names+descs, not bodies."""

    @pytest.mark.asyncio
    async def test_lazy_on_prompt_has_skill_title_not_body(
        self, cwd: Path, skill_alpha: LoadedSkill
    ) -> None:
        """Lazy=True: skill title present in prompt; full body absent."""
        registry = SkillRegistry(skills=[skill_alpha])
        f = CodingContextInputFilter(
            workspace_cwd=str(cwd),
            skill_registry=registry,
            lazy_skills=True,
        )
        prompt = await _run_filter(f)
        assert "Title-alpha" in prompt
        assert "ALPHA_FULL_INSTRUCTION_BODY_UNIQUE_MARKER" not in prompt

    @pytest.mark.asyncio
    async def test_lazy_on_prompt_has_skill_description(
        self, cwd: Path, skill_alpha: LoadedSkill
    ) -> None:
        """Lazy=True: skill description is present in prompt."""
        registry = SkillRegistry(skills=[skill_alpha])
        f = CodingContextInputFilter(
            workspace_cwd=str(cwd),
            skill_registry=registry,
            lazy_skills=True,
        )
        prompt = await _run_filter(f)
        assert "Alpha skill for testing" in prompt

    @pytest.mark.asyncio
    async def test_lazy_on_multiple_skills_no_body_from_any(
        self,
        cwd: Path,
        skill_alpha: LoadedSkill,
        skill_beta: LoadedSkill,
    ) -> None:
        """Lazy=True with multiple skills: no body from any skill in prompt."""
        registry = SkillRegistry(skills=[skill_alpha, skill_beta])
        f = CodingContextInputFilter(
            workspace_cwd=str(cwd),
            skill_registry=registry,
            lazy_skills=True,
        )
        prompt = await _run_filter(f)
        assert "ALPHA_FULL_INSTRUCTION_BODY_UNIQUE_MARKER" not in prompt
        assert "BETA_FULL_INSTRUCTION_BODY_UNIQUE_MARKER" not in prompt
        assert "Title-alpha" in prompt
        assert "Title-beta" in prompt

    @pytest.mark.asyncio
    async def test_lazy_on_prompt_contains_read_skill_hint(
        self, cwd: Path, skill_alpha: LoadedSkill
    ) -> None:
        """Lazy=True: prompt hints the agent to call read_skill for the full body."""
        registry = SkillRegistry(skills=[skill_alpha])
        f = CodingContextInputFilter(
            workspace_cwd=str(cwd),
            skill_registry=registry,
            lazy_skills=True,
        )
        prompt = await _run_filter(f)
        assert "read_skill" in prompt


# ---------------------------------------------------------------------------
# F2 - TOOL WIRING: read_skill in active_tools + executor via runtime_wiring
# ---------------------------------------------------------------------------


class TestSkillToolWiring_InLiveRuntimePlan:
    """read_skill is wired into active_tools and tool_executors when flag is on."""

    def test_lazy_on_with_registry_adds_read_skill_to_active_tools(self) -> None:
        """enable_lazy_skills=True + registry -> read_skill ToolSpec in active_tools."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        registry = SkillRegistry(skills=[_make_skill("alpha")])
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enable_lazy_skills=True),
            cwd="/tmp/test-coding",
            native_config={"skill_registry": registry},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert "read_skill" in {t.name for t in plan.active_tools}

    def test_lazy_on_with_registry_adds_read_skill_executor(self) -> None:
        """enable_lazy_skills=True + registry -> read_skill executor in tool_executors."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        registry = SkillRegistry(skills=[_make_skill("alpha")])
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enable_lazy_skills=True),
            cwd="/tmp/test-coding",
            native_config={"skill_registry": registry},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert "read_skill" in plan.create_kwargs.get("tool_executors", {})

    def test_lazy_on_read_skill_executor_returns_body_via_registry(self) -> None:
        """The wired read_skill executor loads instruction_md from registry on call."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        skill = _make_skill("alpha", body="WIRED_BODY_CONTENT")
        registry = SkillRegistry(skills=[skill])
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enable_lazy_skills=True),
            cwd="/tmp/test-coding",
            native_config={"skill_registry": registry},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        executor = plan.create_kwargs["tool_executors"]["read_skill"]
        result = json.loads(executor({"skill_id": "alpha"}))
        assert result["instruction_md"] == "WIRED_BODY_CONTENT"

    def test_lazy_off_does_not_add_read_skill_to_active_tools(self) -> None:
        """enable_lazy_skills=False (default) -> read_skill NOT in active_tools."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enable_lazy_skills=False),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert "read_skill" not in {t.name for t in plan.active_tools}

    def test_lazy_on_without_registry_does_not_add_read_skill(self) -> None:
        """enable_lazy_skills=True but no registry -> read_skill NOT added (graceful)."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enable_lazy_skills=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        assert "read_skill" not in {t.name for t in plan.active_tools}

    def test_lazy_on_read_skill_allowed_in_tool_policy(self) -> None:
        """enable_lazy_skills=True -> read_skill is allowed by the coding tool policy."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.policy.tool_policy import PermissionAllow, ToolPolicyInput

        registry = SkillRegistry(skills=[_make_skill("alpha")])
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enable_lazy_skills=True),
            cwd="/tmp/test-coding",
            native_config={"skill_registry": registry},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        policy = plan.create_kwargs["tool_policy"]
        state = ToolPolicyInput(
            tool_name="",
            input_data={},
            active_skill_ids=[],
            allowed_local_tools=set(),
        )
        result = policy.can_use_tool("read_skill", {}, state)
        assert isinstance(result, PermissionAllow)


# ---------------------------------------------------------------------------
# On-demand body retrieval via read_skill tool factory (unit)
# ---------------------------------------------------------------------------


class TestSkillReadTool_OnDemandLoading:
    """create_skill_read_tool factory returns correct spec + executor."""

    def test_read_skill_returns_instruction_md_for_known_id(
        self, skill_alpha: LoadedSkill
    ) -> None:
        """read_skill executor returns full instruction_md for a known skill_id."""
        registry = SkillRegistry(skills=[skill_alpha])
        spec, executor = create_skill_read_tool(registry)
        result = json.loads(executor({"skill_id": "alpha"}))
        assert result["instruction_md"] == "ALPHA_FULL_INSTRUCTION_BODY_UNIQUE_MARKER"
        assert result["skill_id"] == "alpha"

    def test_read_skill_returns_title_alongside_body(
        self, skill_alpha: LoadedSkill
    ) -> None:
        """read_skill response includes skill title."""
        registry = SkillRegistry(skills=[skill_alpha])
        _, executor = create_skill_read_tool(registry)
        result = json.loads(executor({"skill_id": "alpha"}))
        assert result.get("title") == "Title-alpha"

    def test_read_skill_unknown_id_returns_error_json(self) -> None:
        """read_skill returns error JSON for an unknown skill_id."""
        _, executor = create_skill_read_tool(SkillRegistry())
        result = json.loads(executor({"skill_id": "nonexistent"}))
        assert "error" in result

    def test_read_skill_missing_skill_id_param_returns_error(self) -> None:
        """read_skill returns error when skill_id param is absent."""
        _, executor = create_skill_read_tool(SkillRegistry())
        result = json.loads(executor({}))
        assert "error" in result

    def test_read_skill_spec_name_is_read_skill(self) -> None:
        """ToolSpec.name == 'read_skill'."""
        spec, _ = create_skill_read_tool(SkillRegistry())
        assert spec.name == "read_skill"


# ---------------------------------------------------------------------------
# Bounded prompt growth: N x description, NOT N x body
# ---------------------------------------------------------------------------


class TestLazySkillLoading_BoundedPromptGrowth:
    """Lazy prompt grows with N x name+desc, not N x body."""

    @pytest.mark.asyncio
    async def test_fifty_skills_lazy_prompt_smaller_than_eager(self, cwd: Path) -> None:
        """50 large-body skills: lazy prompt is much smaller than an eager equivalent."""
        large_body = "X" * 2000
        skills = [
            _make_skill(f"skill_{i}", description=f"Desc {i}", body=large_body)
            for i in range(50)
        ]
        registry = SkillRegistry(skills=skills)

        lazy_f = CodingContextInputFilter(
            workspace_cwd=str(cwd),
            skill_registry=registry,
            lazy_skills=True,
        )
        eager_text = "\n".join(s.instruction_md for s in skills)
        eager_f = CodingContextInputFilter(
            workspace_cwd=str(cwd),
            skill_profile_text=eager_text,
            lazy_skills=False,
        )

        lazy_prompt = await _run_filter(lazy_f)
        eager_prompt = await _run_filter(eager_f)

        assert len(lazy_prompt) < len(eager_prompt)
        assert large_body not in lazy_prompt

    @pytest.mark.asyncio
    async def test_lazy_prompt_size_proportional_to_name_desc_not_body(
        self, cwd: Path
    ) -> None:
        """Lazy prompt with 50 skills stays well under 50 x body-size."""
        body = "B" * 500
        skills = [
            _make_skill(f"sk_{i}", description="D" * 20, body=body) for i in range(50)
        ]
        registry = SkillRegistry(skills=skills)
        f = CodingContextInputFilter(
            workspace_cwd=str(cwd),
            skill_registry=registry,
            lazy_skills=True,
        )
        prompt = await _run_filter(f)
        # Eager would be >= 50 * 500 = 25 000 chars just for bodies
        assert len(prompt) < 50 * 500


# ---------------------------------------------------------------------------
# Stage 3 (context-engineering-manus-parity): skill-listing budget + per-skill cap
# ---------------------------------------------------------------------------


class TestLazySkillListing_BudgetAndPerSkillCap:
    """The skill LISTING itself (names+descriptions) is capped:

    - per-skill: one skill's description can never crowd out the others
    - overall: the whole listing is capped to ~1% of the context window
      (``SKILL_LISTING_BUDGET_RATIO`` -- the same policy Claude Code applies
      to its own skill listing), via the existing ``truncate_to_budget``
      kernel primitive (context/budget.py) -- reused, not reimplemented.
    """

    @pytest.mark.asyncio
    async def test_single_long_description_is_truncated_per_skill(
        self, cwd: Path
    ) -> None:
        """One skill with an oversized description never appears in full."""
        long_description = "D" * 5000
        registry = SkillRegistry(
            skills=[_make_skill("alpha", description=long_description)]
        )
        f = CodingContextInputFilter(
            workspace_cwd=str(cwd), skill_registry=registry, lazy_skills=True
        )
        prompt = await _run_filter(f)
        assert long_description not in prompt
        assert "Title-alpha" in prompt  # the entry itself still appears, truncated

    @pytest.mark.asyncio
    async def test_normal_sized_listing_is_not_truncated(self, cwd: Path) -> None:
        """A handful of normal-sized skills fit comfortably; no truncation marker."""
        skills = [_make_skill(f"sk_{i}", description=f"Desc {i}") for i in range(5)]
        registry = SkillRegistry(skills=skills)
        f = CodingContextInputFilter(
            workspace_cwd=str(cwd), skill_registry=registry, lazy_skills=True
        )
        prompt = await _run_filter(f)
        assert "[обрезано]" not in prompt
        for i in range(5):
            assert f"Desc {i}" in prompt

    @pytest.mark.asyncio
    async def test_small_context_window_caps_overall_listing(self, cwd: Path) -> None:
        """A small context_window_tokens forces the WHOLE listing under budget,
        even though every individual skill's description is well under the
        per-skill cap on its own.

        Fix-cycle 1 (M-3, codex round 1): the chosen window (40_000) is well
        ABOVE the documented floor (1000, see
        ``test_context_window_below_floor_is_clamped_to_documented_minimum``
        below) -- the previous value (400) was silently clamped UP to the
        floor by ``max(context_window_tokens, 1000)``, so it never actually
        exercised the ~1% ratio math it claimed to.
        """
        skills = [_make_skill(f"sk_{i}", description=f"Desc {i}") for i in range(50)]
        registry = SkillRegistry(skills=skills)
        f = CodingContextInputFilter(
            workspace_cwd=str(cwd),
            skill_registry=registry,
            lazy_skills=True,
            context_window_tokens=40_000,  # ~1% => 400 tokens => ~1600 chars budget
        )
        prompt = await _run_filter(f)
        # Far fewer than all 50 "Desc {i}" markers can possibly survive.
        assert sum(1 for i in range(50) if f"Desc {i}" in prompt) < 50

    @pytest.mark.asyncio
    async def test_context_window_below_floor_is_clamped_to_documented_minimum(
        self, cwd: Path
    ) -> None:
        """Fix-cycle 1 (M-3, codex round 1): context_window_tokens below the
        documented floor (1000) is clamped to EXACTLY 1000 -- values 1, 500,
        and 1000 must all produce byte-identical output, making the floor an
        explicit, tested contract rather than an untested implementation detail."""
        skills = [_make_skill(f"sk_{i}", description=f"Desc {i}") for i in range(50)]
        registry = SkillRegistry(skills=skills)

        prompts = []
        for window in (1, 500, 1000):
            f = CodingContextInputFilter(
                workspace_cwd=str(cwd),
                skill_registry=registry,
                lazy_skills=True,
                context_window_tokens=window,
            )
            prompts.append(await _run_filter(f))

        assert prompts[0] == prompts[1] == prompts[2]

    @pytest.mark.asyncio
    async def test_context_window_tokens_threaded_from_native_config_in_runtime_wiring(
        self,
    ) -> None:
        """Fix-cycle 1 (M-3, codex round 1): the production call site
        (agent/runtime_wiring.py) must be able to override the default 200_000
        window via ``AgentConfig.native_config["coding_context_window_tokens"]``
        -- the same generic passthrough convention already used one line above
        for ``coding_context_budget_tokens``. Without this, the ~1% ratio is
        only ever correct for exactly-200k-context models in production."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            coding_profile=CodingProfileConfig(),
            native_config={"coding_context_window_tokens": 100_000},
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        filters = [
            f
            for f in plan.config.input_filters
            if isinstance(f, CodingContextInputFilter)
        ]
        assert filters, "CodingContextInputFilter not found in wired input_filters"
        assert filters[-1]._context_window_tokens == 100_000

    @pytest.mark.asyncio
    async def test_context_window_tokens_defaults_to_200000_in_runtime_wiring(
        self,
    ) -> None:
        """No coding_context_window_tokens override -> production default (200_000),
        matching CodingContextInputFilter's own constructor default."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/test-coding",
            coding_profile=CodingProfileConfig(),
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        filters = [
            f
            for f in plan.config.input_filters
            if isinstance(f, CodingContextInputFilter)
        ]
        assert filters, "CodingContextInputFilter not found in wired input_filters"
        assert filters[-1]._context_window_tokens == 200_000

    @pytest.mark.asyncio
    async def test_default_context_window_tokens_is_200000(self, cwd: Path) -> None:
        """Default context_window_tokens is large enough that a small listing
        is completely unaffected (backward-compat: no constructor arg needed)."""
        registry = SkillRegistry(skills=[_make_skill("alpha")])
        f = CodingContextInputFilter(
            workspace_cwd=str(cwd), skill_registry=registry, lazy_skills=True
        )
        prompt = await _run_filter(f)
        assert "[обрезано]" not in prompt


# ---------------------------------------------------------------------------
# REQ-RCA-070: OFF - lazy_skills=False is byte-identical to default
# ---------------------------------------------------------------------------


class TestLazySkillLoading_OffByteIdentical:
    """CodingContextInputFilter: lazy_skills=False is byte-identical to default."""

    @pytest.mark.asyncio
    async def test_no_flag_identical_to_lazy_false_no_registry(self, cwd: Path) -> None:
        """filter() with no lazy flags == filter() with lazy_skills=False (no registry)."""
        text = "Full body: SOME_INSTRUCTION_BODY_CONTENT"
        f_default = CodingContextInputFilter(
            workspace_cwd=str(cwd), skill_profile_text=text
        )
        f_explicit_off = CodingContextInputFilter(
            workspace_cwd=str(cwd), skill_profile_text=text, lazy_skills=False
        )
        assert await _run_filter(f_default) == await _run_filter(f_explicit_off)

    @pytest.mark.asyncio
    async def test_lazy_false_with_registry_uses_skill_profile_text_as_is(
        self, cwd: Path, skill_alpha: LoadedSkill
    ) -> None:
        """When lazy_skills=False, registry is ignored; skill_profile_text used as-is."""
        registry = SkillRegistry(skills=[skill_alpha])
        profile = "Full body: ALPHA_FULL_INSTRUCTION_BODY_UNIQUE_MARKER"
        f = CodingContextInputFilter(
            workspace_cwd=str(cwd),
            skill_profile_text=profile,
            skill_registry=registry,
            lazy_skills=False,
        )
        prompt = await _run_filter(f)
        assert "ALPHA_FULL_INSTRUCTION_BODY_UNIQUE_MARKER" in prompt
        assert "Title-alpha" not in prompt  # no lazy listing injected

    @pytest.mark.asyncio
    async def test_lazy_off_plan_active_tools_same_as_default(self) -> None:
        """build_portable_runtime_plan: enable_lazy_skills=False active_tools == default."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg_off = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enable_lazy_skills=False),
            cwd="/tmp/test-coding",
        )
        cfg_default = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(),
            cwd="/tmp/test-coding",
        )
        plan_off = build_portable_runtime_plan(cfg_off, "thin")
        plan_default = build_portable_runtime_plan(cfg_default, "thin")
        assert {t.name for t in plan_off.active_tools} == {
            t.name for t in plan_default.active_tools
        }
        assert "read_skill" not in {t.name for t in plan_off.active_tools}


# ---------------------------------------------------------------------------
# CodingProfileConfig flag
# ---------------------------------------------------------------------------


class TestCodingProfileConfig_EnableLazySkills:
    """CodingProfileConfig has enable_lazy_skills: bool = False."""

    def test_enable_lazy_skills_defaults_false(self) -> None:
        """enable_lazy_skills is False by default (OFF invariant)."""
        assert CodingProfileConfig().enable_lazy_skills is False

    def test_enable_lazy_skills_can_be_set_true(self) -> None:
        """enable_lazy_skills can be explicitly enabled."""
        assert CodingProfileConfig(enable_lazy_skills=True).enable_lazy_skills is True

    def test_enable_lazy_skills_frozen_raises_on_setattr(self) -> None:
        """CodingProfileConfig is frozen; setattr raises FrozenInstanceError.

        Using setattr() (not direct assignment) so static type checkers do not
        flag this as invalid-assignment on a read-only property.
        """
        cfg = CodingProfileConfig(enable_lazy_skills=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, "enable_lazy_skills", False)

    def test_config_with_lazy_skills_true_differs_from_default(self) -> None:
        """Config with enable_lazy_skills=True != default config."""
        assert CodingProfileConfig(enable_lazy_skills=True) != CodingProfileConfig()
