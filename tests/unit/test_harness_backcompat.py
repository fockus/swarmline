"""Unit: backward-compat proof — REQ-011/REQ-013, harness is purely additive.

harness-composition spec, Task 5 (REQ-011, REQ-013). The whole harness
epic (H3, Tasks 1-4) must not have changed how the pre-existing ``Agent``
and ``SwarmlineStack`` construction paths behave. This file proves that
BEHAVIORALLY (construct + drive each the normal way, exactly as their own
pre-harness test suites already do — ``tests/unit/test_agent_facade.py`` /
``tests/unit/test_bootstrap_stack.py`` — unaffected by ``swarmline.harness``
being importable in the same process).

The BYTE-level half of REQ-011 (the actual source files — ``Agent``,
``AgentConfig``, ``SwarmlineStack``, ``runtime/thin/runtime.py``,
``orchestration/__init__.py``, ``orchestration/types.py``,
``swarmline/__init__.py`` — are untouched by the entire H3 epic) is proven
by ``git diff <pre-H3-commit> HEAD -- <those files>`` being empty; that is
a repository-history fact, not something a portable pytest run (which may
execute from an sdist with no ``.git`` present) can assert, so it is not
re-asserted here — it is verified once, out-of-band, and reported alongside
this test run's evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from swarmline.agent import Agent, AgentConfig
from swarmline.bootstrap import SwarmlineStack


def _create_fixture_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Minimal SwarmlineStack.create() fixture (mirrors test_bootstrap_stack.py)."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    prompts_dir = project_root / "prompts"
    prompts_dir.mkdir()
    skills_dir = project_root / "skills"
    skills_dir.mkdir()

    (prompts_dir / "identity.md").write_text(
        "You are a helpful assistant.", encoding="utf-8"
    )
    (prompts_dir / "role_skills.yaml").write_text(
        "default:\n  skills: []\n  local_tools: []\n", encoding="utf-8"
    )
    (prompts_dir / "role_router.yaml").write_text(
        "default_role: default\nkeywords: {}\n", encoding="utf-8"
    )
    return project_root, prompts_dir, skills_dir


class TestExistingAgentAndStackUnchanged:
    """REQ-011: pre-harness Agent + SwarmlineStack construction still works,
    unaffected by importing/using ``swarmline.harness`` in the same process.
    """

    def test_plain_agent_construction_unchanged(self) -> None:
        """The bare, no-harness ``Agent(AgentConfig(...))`` path constructs
        exactly as it did before H3 -- no harness field, no harness import
        required to use it."""
        # swarmline.harness is imported (proves co-existence, not isolation
        # via a separate process) yet changes nothing about plain Agent.
        import swarmline.harness  # noqa: F401

        config = AgentConfig(system_prompt="You are a helpful test agent.")
        agent = Agent(config)

        assert isinstance(agent, Agent)
        assert agent.config.system_prompt == "You are a helpful test agent."
        assert agent.config.runtime == "thin"
        # HarnessSpec/CompositionSpec/InfraSpec are absent from AgentConfig's
        # own field set - the harness attaches nothing to it.
        assert not hasattr(agent.config, "harness")
        assert not hasattr(agent.config, "kernel")

    @pytest.mark.asyncio
    async def test_plain_agent_query_end_to_end_unchanged(self) -> None:
        """Agent.query() still works exactly the way
        ``tests/unit/test_agent_facade.py`` (pre-harness) already asserts:
        driven through ``Agent._execute_stream`` -> ``Result``. Reusing that
        SAME established boundary-mock pattern (rather than a fresh
        ThinRuntime probe) is itself part of the proof -- the facade's own
        internal call shape has not changed."""
        from conftest import FakeStreamEvent

        config = AgentConfig(system_prompt="You are a helpful test agent.")
        agent = Agent(config)

        async def fake_stream(prompt: Any, **_kwargs: Any):
            yield FakeStreamEvent("text_delta", text="plain ")
            yield FakeStreamEvent(
                "done",
                text="plain agent reply",
                is_final=True,
                session_id="backcompat-s1",
            )

        with patch.object(agent, "_execute_stream", side_effect=fake_stream):
            result = await agent.query("hello")

        assert result.ok is True
        assert result.text == "plain agent reply"
        assert result.session_id == "backcompat-s1"

    def test_swarmline_stack_create_unchanged(self, tmp_path: Path) -> None:
        """SwarmlineStack.create() still produces the same ready-made
        component bundle it did before the harness existed."""
        from swarmline.config.role_router import RoleRouterConfig
        from swarmline.policy import DefaultToolIdCodec, DefaultToolPolicy
        from swarmline.routing import KeywordRoleRouter
        from swarmline.runtime.factory import RuntimeFactory
        from swarmline.runtime.model_policy import ModelPolicy
        from swarmline.runtime.types import RuntimeConfig
        from swarmline.skills import SkillRegistry

        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)

        stack = SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
        )

        assert isinstance(stack, SwarmlineStack)
        assert isinstance(stack.skill_registry, SkillRegistry)
        assert isinstance(stack.role_router, KeywordRoleRouter)
        assert isinstance(stack.role_router_config, RoleRouterConfig)
        assert isinstance(stack.tool_policy, DefaultToolPolicy)
        assert isinstance(stack.tool_id_codec, DefaultToolIdCodec)
        assert isinstance(stack.model_policy, ModelPolicy)
        assert isinstance(stack.runtime_factory, RuntimeFactory)
        assert isinstance(stack.runtime_config, RuntimeConfig)
        assert stack.local_tool_resolver is None
        # SwarmlineStack carries no harness field -- additive means additive.
        assert not hasattr(stack, "harness")

    def test_swarmline_stack_has_no_harness_coupling_in_its_dataclass_fields(
        self,
    ) -> None:
        """Static proof (no fixture I/O needed): SwarmlineStack's own field
        set never grew a harness-related field across the H3 epic."""
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(SwarmlineStack)}

        assert not any("harness" in name for name in field_names)
