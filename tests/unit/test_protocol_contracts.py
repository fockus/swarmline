"""Contract tests - Protocol compliance verification for portable components. Iteration 0 Baseline: fixing contracts BEFORE transfers begin.
Verifies that implementations satisfy the ISP Protocol (≤5 methods)."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import Any, get_type_hints

import pytest
from swarmline.protocols import (
    ModelSelector,
    RoleSkillsProvider,
    RuntimePort,
    SummaryGenerator,
)

# ---------------------------------------------------------------------------
# ISP: all Protocols ≤5 public methods
# ---------------------------------------------------------------------------


class TestProtocolISP:
    """Check ISP: Protocols have ≤5 public methods/properties."""

    @pytest.mark.parametrize(
        "protocol_cls,max_methods",
        [
            (RuntimePort, 5),
            (RoleSkillsProvider, 5),
            (SummaryGenerator, 5),
            (ModelSelector, 5),
        ],
    )
    def test_protocol_method_count(self, protocol_cls: type, max_methods: int) -> None:
        """Protocol has ≤ max_methods public methods/properties."""
        public = [
            name
            for name in dir(protocol_cls)
            if not name.startswith("_")
            and name
            not in {
                "register",
                "mro",  # built-in stuff
            }
        ]
        # Removing what came from Protocol/ABC
        protocol_builtins = {"register"}
        public = [n for n in public if n not in protocol_builtins]
        assert len(public) <= max_methods, (
            f"{protocol_cls.__name__} имеет {len(public)} методов: {public}. "
            f"ISP допускает ≤{max_methods}."
        )


# ---------------------------------------------------------------------------
# RuntimePort contract
# ---------------------------------------------------------------------------


class TestRuntimePortContract:
    """Contract RuntimePort: connect/disconnect/is_connected/stream_reply."""

    def test_has_connect(self) -> None:
        """RuntimePort defines connect()."""
        assert hasattr(RuntimePort, "connect")

    def test_has_disconnect(self) -> None:
        """RuntimePort defines disconnect()."""
        assert hasattr(RuntimePort, "disconnect")

    def test_has_is_connected(self) -> None:
        """RuntimePort defines the is_connected property."""
        assert hasattr(RuntimePort, "is_connected")

    def test_has_stream_reply(self) -> None:
        """RuntimePort defines stream_reply(user_text)."""
        assert hasattr(RuntimePort, "stream_reply")
        sig = inspect.signature(RuntimePort.stream_reply)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "user_text" in params

    def test_stream_reply_returns_async_iterator(self) -> None:
        """stream_reply returns AsyncIterator."""
        hints = get_type_hints(RuntimePort.stream_reply)
        assert hints.get("return") is not None

    def test_dummy_implementation_satisfies_protocol(self) -> None:
        """A simple implementation passes the isinstance check."""

        class DummyPort:
            @property
            def is_connected(self) -> bool:
                return False

            async def connect(self) -> None:
                pass

            async def disconnect(self) -> None:
                pass

            async def stream_reply(self, user_text: str) -> AsyncIterator[Any]:
                yield {"type": "done"}  # pragma: no cover

        port = DummyPort()
        # Structural subtyping - verify presence of attributes
        assert hasattr(port, "is_connected")
        assert hasattr(port, "connect")
        assert hasattr(port, "disconnect")
        assert hasattr(port, "stream_reply")


# ---------------------------------------------------------------------------
# RoleSkillsProvider contract
# ---------------------------------------------------------------------------


class TestRoleSkillsProviderContract:
    """Contract RoleSkillsProvider: get_skills + get_local_tools."""

    def test_has_get_skills(self) -> None:
        """RoleSkillsProvider defines get_skills(role_id)."""
        assert hasattr(RoleSkillsProvider, "get_skills")
        sig = inspect.signature(RoleSkillsProvider.get_skills)
        assert "role_id" in sig.parameters

    def test_has_get_local_tools(self) -> None:
        """RoleSkillsProvider defines get_local_tools(role_id)."""
        assert hasattr(RoleSkillsProvider, "get_local_tools")
        sig = inspect.signature(RoleSkillsProvider.get_local_tools)
        assert "role_id" in sig.parameters

    def test_method_count_is_2(self) -> None:
        """RoleSkillsProvider has exactly 2 methods (ISP)."""
        methods = [n for n in dir(RoleSkillsProvider) if not n.startswith("_") and n != "register"]
        assert len(methods) == 2

    def test_dummy_implementation_satisfies_protocol(self) -> None:
        """A simple implementation satisfies Protocol."""

        class DummyProvider:
            def get_skills(self, role_id: str) -> list[str]:
                return []

            def get_local_tools(self, role_id: str) -> list[str]:
                return []

        provider = DummyProvider()
        assert provider.get_skills("coach") == []
        assert provider.get_local_tools("coach") == []


# ---------------------------------------------------------------------------
# SummaryGenerator contract
# ---------------------------------------------------------------------------


class TestSummaryGeneratorContract:
    """Contract SummaryGenerator: summarize (1 method, ISP)."""

    def test_has_summarize(self) -> None:
        """SummaryGenerator defines summarize(messages)."""
        assert hasattr(SummaryGenerator, "summarize")
        sig = inspect.signature(SummaryGenerator.summarize)
        assert "messages" in sig.parameters

    def test_is_runtime_checkable(self) -> None:
        """SummaryGenerator — @runtime_checkable."""
        from swarmline.memory.types import MemoryMessage

        class DummySummarizer:
            def summarize(self, messages: list[MemoryMessage]) -> str:
                return "summary"

        assert isinstance(DummySummarizer(), SummaryGenerator)

    def test_non_conforming_class_fails_check(self) -> None:
        """The class without summarize not passes the isinstance check."""

        class NotASummarizer:
            pass

        assert not isinstance(NotASummarizer(), SummaryGenerator)


# ---------------------------------------------------------------------------
# ModelSelector contract
# ---------------------------------------------------------------------------


class TestModelSelectorContract:
    """Contract ModelSelector: select + select_for_turn."""

    def test_has_select(self) -> None:
        """ModelSelector defines select(role_id, tool_failure_count)."""
        assert hasattr(ModelSelector, "select")
        sig = inspect.signature(ModelSelector.select)
        assert "role_id" in sig.parameters
        assert "tool_failure_count" in sig.parameters

    def test_has_select_for_turn(self) -> None:
        """ModelSelector defines select_for_turn(...)."""
        assert hasattr(ModelSelector, "select_for_turn")
        sig = inspect.signature(ModelSelector.select_for_turn)
        params = list(sig.parameters.keys())
        assert "role_id" in params
        assert "user_text" in params

    def test_model_policy_satisfies_contract(self) -> None:
        """ModelPolicy implements the ModelSelector Protocol."""
        from swarmline.runtime.model_policy import ModelPolicy

        policy = ModelPolicy()
        # Verify presence of both methods
        assert hasattr(policy, "select")
        assert hasattr(policy, "select_for_turn")
        # Calling
        model = policy.select("coach")
        assert isinstance(model, str)
        assert len(model) > 0


# ---------------------------------------------------------------------------
# BaseRuntimePort contract (from freedom_agent, will be transferred)
# ---------------------------------------------------------------------------


class TestBaseRuntimePortContract:
    """Contract BaseRuntimePort: check that it satisfies RuntimePort."""

    def _make_config(self) -> Any:
        from swarmline.runtime.types import RuntimeConfig

        return RuntimeConfig(runtime_name="thin")

    def test_satisfies_runtime_port_interface(self) -> None:
        """BaseRuntimePort implements all RuntimePort methods."""
        from swarmline.runtime.ports.base import BaseRuntimePort

        port = BaseRuntimePort(system_prompt="test", config=self._make_config())
        assert hasattr(port, "is_connected")
        assert hasattr(port, "connect")
        assert hasattr(port, "disconnect")
        assert hasattr(port, "stream_reply")

    def test_has_history_management(self) -> None:
        """BaseRuntimePort has a sliding window history."""
        from swarmline.runtime.ports.base import BaseRuntimePort

        port = BaseRuntimePort(
            system_prompt="test",
            config=self._make_config(),
            history_max=5,
        )
        assert hasattr(port, "_append_to_history")
        assert hasattr(port, "_maybe_summarize")

    @pytest.mark.asyncio
    async def test_connect_sets_is_connected(self) -> None:
        """connect() sets is_connected = True."""
        from swarmline.runtime.ports.base import BaseRuntimePort

        port = BaseRuntimePort(system_prompt="test", config=self._make_config())
        assert not port.is_connected
        await port.connect()
        assert port.is_connected

    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self) -> None:
        """disconnect() resets is_connected and history."""
        from swarmline.runtime.ports.base import BaseRuntimePort

        port = BaseRuntimePort(system_prompt="test", config=self._make_config())
        await port.connect()
        port._append_to_history("user", "test")
        await port.disconnect()
        assert not port.is_connected
        assert len(port._history) == 0


# ---------------------------------------------------------------------------
# ThinRuntimePort contract
# ---------------------------------------------------------------------------


class TestThinRuntimePortContract:
    """Contract ThinRuntimePort: inherits BaseRuntimePort and implements RuntimePort."""

    def test_is_subclass_of_base(self) -> None:
        """ThinRuntimePort inherits from BaseRuntimePort."""
        from swarmline.runtime.ports.base import BaseRuntimePort
        from swarmline.runtime.ports.thin import ThinRuntimePort

        assert issubclass(ThinRuntimePort, BaseRuntimePort)

    def test_satisfies_runtime_port_interface(self) -> None:
        """ThinRuntimePort implements the RuntimePort interface."""
        from swarmline.runtime.ports.thin import ThinRuntimePort

        port = ThinRuntimePort(system_prompt="test")
        assert hasattr(port, "is_connected")
        assert hasattr(port, "connect")
        assert hasattr(port, "disconnect")
        assert hasattr(port, "stream_reply")


# ---------------------------------------------------------------------------
# DeepAgentsRuntimePort contract
# ---------------------------------------------------------------------------


class TestDeepAgentsRuntimePortContract:
    """Contract DeepAgentsRuntimePort: inherits BaseRuntimePort, implements RuntimePort."""

    def test_is_subclass_of_base(self) -> None:
        """DeepAgentsRuntimePort inherits from BaseRuntimePort."""
        from swarmline.runtime.ports.base import BaseRuntimePort
        from swarmline.runtime.ports.deepagents import (
            DeepAgentsRuntimePort,
        )

        assert issubclass(DeepAgentsRuntimePort, BaseRuntimePort)

    def test_satisfies_runtime_port_interface(self) -> None:
        """DeepAgentsRuntimePort implements the RuntimePort interface."""
        from swarmline.runtime.ports.deepagents import (
            DeepAgentsRuntimePort,
        )

        port = DeepAgentsRuntimePort(system_prompt="test")
        assert hasattr(port, "is_connected")
        assert hasattr(port, "connect")
        assert hasattr(port, "disconnect")
        assert hasattr(port, "stream_reply")

    def test_accepts_tool_executors(self) -> None:
        """DeepAgentsRuntimePort accepts tool_executors."""
        from swarmline.runtime.ports.deepagents import (
            DeepAgentsRuntimePort,
        )

        async def dummy_exec(**kwargs: Any) -> str:
            return "ok"

        port = DeepAgentsRuntimePort(
            system_prompt="test",
            tool_executors={"my_tool": dummy_exec},
        )
        assert "my_tool" in port._tool_executors


# ---------------------------------------------------------------------------
# RoleSkillsLoader → RoleSkillsProvider contract
# ---------------------------------------------------------------------------


class TestRoleSkillsLoaderContract:
    """RoleSkillsLoader from freedom_agent satisfies the RoleSkillsProvider Protocol."""

    def test_satisfies_provider_interface(self, tmp_path: Any) -> None:
        """RoleSkillsLoader implements get_skills + get_local_tools."""
        from swarmline.config.role_skills import YamlRoleSkillsLoader

        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text(
            "coach:\n  skills: [iss]\n  local_tools: [calculate_goal_plan]\n",
            encoding="utf-8",
        )
        loader = YamlRoleSkillsLoader(yaml_file)
        assert loader.get_skills("coach") == ["iss"]
        assert loader.get_local_tools("coach") == ["calculate_goal_plan"]

    def test_missing_role_returns_empty(self, tmp_path: Any) -> None:
        """For a not existing role returns empty list."""
        from swarmline.config.role_skills import YamlRoleSkillsLoader

        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text("coach:\n  skills: []\n", encoding="utf-8")
        loader = YamlRoleSkillsLoader(yaml_file)
        assert loader.get_skills("nonexistent") == []
        assert loader.get_local_tools("nonexistent") == []

    def test_has_list_roles(self, tmp_path: Any) -> None:
        """RoleSkillsLoader has list_roles() - a bonus method (not in Protocol)."""
        from swarmline.config.role_skills import YamlRoleSkillsLoader

        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text(
            "coach:\n  skills: []\ndiagnostician:\n  skills: []\n",
            encoding="utf-8",
        )
        loader = YamlRoleSkillsLoader(yaml_file)
        assert set(loader.list_roles()) == {"coach", "diagnostician"}
