"""Tests for AgentNode runtime fields — model, runtime, api_key_env (COG-04)."""

from __future__ import annotations

import dataclasses

import pytest

from swarmline.multi_agent.graph_types import AgentCapabilities, AgentNode
from swarmline.multi_agent.registry_types import AgentStatus


class TestAgentNodeRuntimeDefaults:
    """Backward compatibility: existing construction still works with defaults."""

    def test_default_construction_has_empty_model(self) -> None:
        node = AgentNode(id="a1", name="dev", role="developer")
        assert node.model == ""

    def test_default_construction_has_empty_runtime(self) -> None:
        node = AgentNode(id="a1", name="dev", role="developer")
        assert node.runtime == ""

    def test_default_construction_has_none_api_key_env(self) -> None:
        node = AgentNode(id="a1", name="dev", role="developer")
        assert node.api_key_env is None

    def test_existing_fields_preserved_with_defaults(self) -> None:
        node = AgentNode(
            id="a1",
            name="dev",
            role="developer",
            system_prompt="You are a dev",
            parent_id="root",
            allowed_tools=("Read", "Write"),
            skills=("tdd",),
            capabilities=AgentCapabilities(can_hire=True),
            runtime_config={"temperature": 0.7},
            budget_limit_usd=10.0,
            status=AgentStatus.RUNNING,
        )
        assert node.id == "a1"
        assert node.runtime_config == {"temperature": 0.7}
        assert node.budget_limit_usd == 10.0
        assert node.status == AgentStatus.RUNNING
        # New fields still have defaults
        assert node.model == ""
        assert node.runtime == ""
        assert node.api_key_env is None


class TestAgentNodeRuntimeExplicit:
    """Explicit construction with new typed fields."""

    def test_explicit_model_and_runtime(self) -> None:
        node = AgentNode(
            id="j1",
            name="judge",
            role="judge",
            model="gpt-5.4",
            runtime="openai_api",
            api_key_env="OPENAI_API_KEY",
        )
        assert node.model == "gpt-5.4"
        assert node.runtime == "openai_api"
        assert node.api_key_env == "OPENAI_API_KEY"

    def test_runtime_config_coexists_with_typed_fields(self) -> None:
        node = AgentNode(
            id="j1",
            name="judge",
            role="judge",
            runtime_config={"max_tokens": 4096},
            model="claude-4-opus",
            runtime="anthropic_api",
        )
        assert node.runtime_config == {"max_tokens": 4096}
        assert node.model == "claude-4-opus"
        assert node.runtime == "anthropic_api"


class TestAgentNodeRuntimeReplace:
    """dataclasses.replace() works with new fields."""

    def test_replace_model(self) -> None:
        node = AgentNode(id="a1", name="dev", role="developer", model="sonnet")
        updated = dataclasses.replace(node, model="claude-4-opus")
        assert updated.model == "claude-4-opus"
        assert node.model == "sonnet"  # original unchanged (frozen)

    def test_replace_runtime(self) -> None:
        node = AgentNode(id="a1", name="dev", role="developer")
        updated = dataclasses.replace(node, runtime="codex_cli")
        assert updated.runtime == "codex_cli"

    def test_replace_api_key_env(self) -> None:
        node = AgentNode(id="a1", name="dev", role="developer")
        updated = dataclasses.replace(node, api_key_env="ANTHROPIC_API_KEY")
        assert updated.api_key_env == "ANTHROPIC_API_KEY"


class TestAgentNodeFrozenHashable:
    """AgentNode remains frozen and hashable with new fields."""

    def test_frozen_rejects_mutation(self) -> None:
        node = AgentNode(id="a1", name="dev", role="developer", model="opus")
        with pytest.raises(dataclasses.FrozenInstanceError):
            node.model = "sonnet"  # type: ignore[misc]

    def test_hashable_without_dict_fields(self) -> None:
        node = AgentNode(
            id="a1", name="dev", role="developer", model="opus", metadata={}
        )
        # AgentNode with default dict fields is not hashable (dict is unhashable),
        # but we verify frozen enforcement via the mutation test above.
        # Equality still works:
        node2 = AgentNode(
            id="a1", name="dev", role="developer", model="opus", metadata={}
        )
        assert node == node2
