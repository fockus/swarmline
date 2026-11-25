"""Tests for RuntimeFactory - select runtime by config/env/override."""

import os
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from swarmline.runtime.capabilities import CapabilityRequirements
from swarmline.runtime.factory import RuntimeFactory, _ErrorRuntime
from swarmline.runtime.types import RuntimeConfig


@pytest.fixture
def factory() -> RuntimeFactory:
    return RuntimeFactory()


# ---------------------------------------------------------------------------
# resolve_runtime_name
# ---------------------------------------------------------------------------


class TestResolveRuntimeName:
    """RuntimeFactory.resolve_runtime_name - selection priority."""

    def test_default_is_thin(self, factory: RuntimeFactory) -> None:
        """Without parameters — thin, unified with the Agent facade default."""
        assert factory.resolve_runtime_name() == "thin"

    def test_config_overrides_default(self, factory: RuntimeFactory) -> None:
        """config.runtime_name overrides default."""
        cfg = RuntimeConfig(runtime_name="thin")
        assert factory.resolve_runtime_name(config=cfg) == "thin"

    def test_env_overrides_default(self, factory: RuntimeFactory) -> None:
        """The SWARMLINE_RUNTIME environment variable overrides default."""
        with patch.dict(os.environ, {"SWARMLINE_RUNTIME": "deepagents"}):
            assert factory.resolve_runtime_name() == "deepagents"

    def test_config_overrides_env(self, factory: RuntimeFactory) -> None:
        """config takes precedence over env."""
        cfg = RuntimeConfig(runtime_name="thin")
        with patch.dict(os.environ, {"SWARMLINE_RUNTIME": "deepagents"}):
            assert factory.resolve_runtime_name(config=cfg) == "thin"

    def test_override_overrides_all(self, factory: RuntimeFactory) -> None:
        """runtime_override has maximum priority."""
        cfg = RuntimeConfig(runtime_name="thin")
        with patch.dict(os.environ, {"SWARMLINE_RUNTIME": "deepagents"}):
            result = factory.resolve_runtime_name(
                config=cfg,
                runtime_override="claude_sdk",
            )
            assert result == "claude_sdk"

    def test_invalid_env_ignored(self, factory: RuntimeFactory) -> None:
        """Invalid env - is ignored, uses default."""
        with patch.dict(os.environ, {"SWARMLINE_RUNTIME": "invalid_runtime"}):
            assert factory.resolve_runtime_name() == "thin"

    def test_invalid_override_ignored(self, factory: RuntimeFactory) -> None:
        """Invalid override - is ignored, uses config."""
        cfg = RuntimeConfig(runtime_name="thin")
        result = factory.resolve_runtime_name(
            config=cfg,
            runtime_override="invalid",
        )
        assert result == "thin"

    def test_env_case_insensitive(self, factory: RuntimeFactory) -> None:
        """Env with different case - converted to lower."""
        with patch.dict(os.environ, {"SWARMLINE_RUNTIME": "THIN"}):
            assert factory.resolve_runtime_name() == "thin"


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    """RuntimeFactory.create - creation of runtime."""

    def test_create_thin_missing_dep(self, factory: RuntimeFactory) -> None:
        """If anthropic is not installed - returns _ErrorRuntime."""
        with patch.dict("sys.modules", {"anthropic": None}):
            cfg = RuntimeConfig(runtime_name="thin")
            runtime = factory.create(config=cfg)
            # _ErrorRuntime - valid object (not crashed on creation)
            assert runtime is not None

    def test_create_deepagents_missing_dep(self, factory: RuntimeFactory) -> None:
        """If langchain-core is not installed - returns _ErrorRuntime."""
        cfg = RuntimeConfig(runtime_name="deepagents")
        runtime = factory.create(config=cfg)
        # Can be _ErrorRuntime or DeepAgentsRuntime (depends on deps)
        assert runtime is not None

    def test_create_with_override(self, factory: RuntimeFactory) -> None:
        """runtime_override is passed in resolve."""
        cfg = RuntimeConfig(runtime_name="claude_sdk")
        # We can't really create thin (we need anthropic), but verify that override works
        runtime = factory.create(config=cfg, runtime_override="thin")
        assert runtime is not None

    def test_invalid_name_in_create(self, factory: RuntimeFactory) -> None:
        """Invalid name in config -> ValueError in RuntimeConfig.__post_init__."""
        with pytest.raises(ValueError, match="Unknown runtime"):
            RuntimeConfig(runtime_name="bad_name")

    def test_create_with_unsupported_override_returns_error_runtime(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """override runtime, not satisfying capability requirements -> _ErrorRuntime."""
        cfg = RuntimeConfig(
            runtime_name="claude_sdk",
            required_capabilities=CapabilityRequirements(tier="full"),
        )
        runtime = factory.create(config=cfg, runtime_override="thin")
        assert isinstance(runtime, _ErrorRuntime)

    def test_create_thin_maps_tool_executors_to_local_tools(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """tool_executors of the facade layer are thrown in ThinRuntime as local_tools."""
        cfg = RuntimeConfig(runtime_name="thin")
        fake_runtime = object()
        fake_cls = MagicMock(return_value=fake_runtime)
        tool_exec = {"calc": object()}

        with patch("swarmline.runtime.thin.ThinRuntime", fake_cls):
            runtime = factory.create(config=cfg, tool_executors=tool_exec)

        assert runtime is fake_runtime
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["local_tools"] == tool_exec
        assert "tool_executors" not in kwargs

    def test_create_thin_preserves_local_tools_without_tool_executors(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """Regression: local_tools must survive when tool_executors is empty/
        absent. RuntimeFactory.create() consults the registry FIRST, so this
        exercises registry.py::_create_thin (the production path). Before the
        fix, local_tools was popped off kwargs and only restored inside
        `if tool_executors:`, so a caller passing ONLY local_tools (e.g.
        HarnessBuilder().supervisor(...).build()) silently lost every tool."""
        cfg = RuntimeConfig(runtime_name="thin")
        fake_runtime = object()
        fake_cls = MagicMock(return_value=fake_runtime)
        local = {"foo": object()}

        with patch("swarmline.runtime.thin.ThinRuntime", fake_cls):
            runtime = factory.create(config=cfg, local_tools=local)

        assert runtime is fake_runtime
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["local_tools"] == local
        assert "tool_executors" not in kwargs

    def test_create_thin_merges_local_tools_and_tool_executors_when_both_present(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """Backcompat: the pre-existing merge behavior (both kwargs present)
        stays unchanged by the fix (registry path)."""
        cfg = RuntimeConfig(runtime_name="thin")
        fake_runtime = object()
        fake_cls = MagicMock(return_value=fake_runtime)
        local = {"foo": object()}
        tool_exec = {"calc": object()}

        with patch("swarmline.runtime.thin.ThinRuntime", fake_cls):
            runtime = factory.create(
                config=cfg, local_tools=local, tool_executors=tool_exec
            )

        assert runtime is fake_runtime
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["local_tools"] == {**local, **tool_exec}

    def test_factory_create_thin_fallback_preserves_local_tools_without_tool_executors(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """Same regression, exercised directly against the legacy fallback
        method (factory.py::RuntimeFactory._create_thin), used when the
        registry is unavailable."""
        cfg = RuntimeConfig(runtime_name="thin")
        fake_runtime = object()
        fake_cls = MagicMock(return_value=fake_runtime)
        local = {"foo": object()}

        with patch("swarmline.runtime.thin.ThinRuntime", fake_cls):
            runtime = factory._create_thin(cfg, local_tools=local)

        assert runtime is fake_runtime
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["local_tools"] == local
        assert "tool_executors" not in kwargs

    def test_factory_create_thin_fallback_merges_when_both_present(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """Backcompat: the pre-existing merge behavior (both kwargs present)
        stays unchanged by the fix (legacy fallback path)."""
        cfg = RuntimeConfig(runtime_name="thin")
        fake_runtime = object()
        fake_cls = MagicMock(return_value=fake_runtime)
        local = {"foo": object()}
        tool_exec = {"calc": object()}

        with patch("swarmline.runtime.thin.ThinRuntime", fake_cls):
            runtime = factory._create_thin(
                cfg, local_tools=local, tool_executors=tool_exec
            )

        assert runtime is fake_runtime
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["local_tools"] == {**local, **tool_exec}

    def test_create_cli_rejects_local_tools(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """CLI runtime fails fast on tool_executors/local_tools instead of
        silently dropping them (RUNTIME-PARITY-PLAN E2)."""
        cfg = RuntimeConfig(runtime_name="cli")
        fake_cls = MagicMock(return_value=object())
        cli_config = MagicMock()

        with patch("swarmline.runtime.cli.runtime.CliAgentRuntime", fake_cls):
            with pytest.raises(ValueError, match="does not support custom @tool"):
                factory.create(
                    config=cfg,
                    tool_executors={"calc": object()},
                    local_tools={"calc": object()},
                    cli_config=cli_config,
                )

    def test_create_cli_rejects_mcp_servers(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """CLI runtime fails fast on mcp_servers instead of silently dropping."""
        cfg = RuntimeConfig(runtime_name="cli")
        fake_cls = MagicMock(return_value=object())

        with patch("swarmline.runtime.cli.runtime.CliAgentRuntime", fake_cls):
            with pytest.raises(
                ValueError, match="does not support AgentConfig.mcp_servers"
            ):
                factory.create(
                    config=cfg,
                    mcp_servers={"srv": {"url": "http://localhost:1"}},
                )

    def test_create_cli_without_tools_succeeds(
        self,
        factory: RuntimeFactory,
    ) -> None:
        cfg = RuntimeConfig(runtime_name="cli")
        fake_runtime = object()
        fake_cls = MagicMock(return_value=fake_runtime)
        cli_config = MagicMock()

        with patch("swarmline.runtime.cli.runtime.CliAgentRuntime", fake_cls):
            runtime = factory.create(config=cfg, cli_config=cli_config)

        assert runtime is fake_runtime
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["config"] == cfg
        assert kwargs["cli_config"] is cli_config
        assert "tool_executors" not in kwargs
        assert "local_tools" not in kwargs

    def test_create_cli_uses_legacy_fallback_when_registry_unavailable(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """If registry is not available, the cli is still created via legacy fallback."""
        cfg = RuntimeConfig(runtime_name="cli")
        fake_runtime = object()
        fake_cls = MagicMock(return_value=fake_runtime)

        with patch.object(
            RuntimeFactory, "_effective_registry", new_callable=PropertyMock
        ) as mock_registry:
            mock_registry.return_value = None
            with patch("swarmline.runtime.cli.runtime.CliAgentRuntime", fake_cls):
                runtime = factory.create(config=cfg)

        assert runtime is fake_runtime
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["config"] == cfg


class TestCapabilities:
    """RuntimeFactory capability-aware helpers."""

    def test_get_capabilities_returns_descriptor(self, factory: RuntimeFactory) -> None:
        caps = factory.get_capabilities(RuntimeConfig(runtime_name="thin"))
        assert caps.runtime_name == "thin"
        assert caps.tier == "light"

    def test_validate_capabilities_returns_typed_error(
        self,
        factory: RuntimeFactory,
    ) -> None:
        cfg = RuntimeConfig(runtime_name="claude_sdk")
        err = factory.validate_capabilities(
            config=cfg,
            runtime_override="thin",
            required_capabilities=CapabilityRequirements(tier="full"),
        )
        assert err is not None
        assert err.kind == "capability_unsupported"
        assert "tier:full" in err.details["missing"]

    def test_get_capabilities_for_custom_runtime(self) -> None:
        from swarmline.runtime.capabilities import RuntimeCapabilities
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        custom_caps = RuntimeCapabilities(
            runtime_name="custom_factory_rt", tier="light"
        )
        registry.register(
            "custom_factory_rt",
            lambda config, **kwargs: object(),
            capabilities=custom_caps,
        )

        factory = RuntimeFactory(registry=registry)
        cfg = RuntimeConfig.__new__(RuntimeConfig)
        object.__setattr__(cfg, "runtime_name", "custom_factory_rt")
        object.__setattr__(cfg, "feature_mode", "portable")
        object.__setattr__(cfg, "required_capabilities", None)
        object.__setattr__(cfg, "output_type", None)
        object.__setattr__(cfg, "output_format", None)
        object.__setattr__(cfg, "max_iterations", 6)
        object.__setattr__(cfg, "max_tool_calls", 8)
        object.__setattr__(cfg, "max_model_retries", 2)
        object.__setattr__(cfg, "model", "claude-sonnet-4-20250514")
        object.__setattr__(cfg, "base_url", None)
        object.__setattr__(cfg, "extra", {})
        object.__setattr__(cfg, "allow_native_features", False)
        object.__setattr__(cfg, "native_config", {})
        caps = factory.get_capabilities(cfg)
        assert caps is custom_caps


# ---------------------------------------------------------------------------
# _ErrorRuntime
# ---------------------------------------------------------------------------


class TestErrorRuntime:
    """_ErrorRuntime - stub if there is no dependency."""

    @pytest.mark.asyncio
    async def test_run_yields_error(self) -> None:
        """run() returns error event."""
        from swarmline.runtime.types import RuntimeErrorData

        err = RuntimeErrorData(
            kind="dependency_missing",
            message="test dep missing",
        )
        runtime = _ErrorRuntime(err)

        events = []
        async for event in runtime.run():
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].data["kind"] == "dependency_missing"
        assert "test dep missing" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_cleanup_noop(self) -> None:
        """cleanup() doesn't crash."""
        from swarmline.runtime.types import RuntimeErrorData

        err = RuntimeErrorData(kind="dependency_missing", message="x")
        runtime = _ErrorRuntime(err)
        await runtime.cleanup()  # shouldn't quit


class TestConfigCapabilityValidation:
    """E1: AgentConfig options unsupported by the runtime fail fast."""

    def _factory(self) -> RuntimeFactory:
        return RuntimeFactory()

    def test_structured_output_on_cli_passes_via_dispatch_emulation(self) -> None:
        """cli structured output is emulated at the dispatch layer (D1)."""
        from swarmline.agent.config import AgentConfig

        config = AgentConfig(
            system_prompt="x",
            runtime="cli",
            output_format={"type": "object", "properties": {}},
        )
        self._factory().validate_agent_config(config)

    def test_permissions_callback_on_cli_raises(self) -> None:
        from swarmline.agent.config import AgentConfig

        async def _cb(tool_name, input_data, context):  # pragma: no cover
            return None

        config = AgentConfig(
            system_prompt="x",
            runtime="cli",
            can_use_tool=_cb,
            permission_mode="default",
        )
        with pytest.raises(ValueError, match="permissions"):
            self._factory().validate_agent_config(config)

    def test_permissions_callback_on_cli_warns_when_not_strict(self) -> None:
        import warnings

        from swarmline.agent.config import AgentConfig

        async def _cb(tool_name, input_data, context):  # pragma: no cover
            return None

        config = AgentConfig(
            system_prompt="x",
            runtime="cli",
            can_use_tool=_cb,
            permission_mode="default",
            strict_capabilities=False,
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self._factory().validate_agent_config(config)
        assert any("permissions" in str(w.message) for w in caught)

    def test_resume_session_on_thin_raises(self) -> None:
        from swarmline.agent.config import AgentConfig

        config = AgentConfig(system_prompt="x", runtime="thin", resume_session_id="s-1")
        with pytest.raises(ValueError, match="resume"):
            self._factory().validate_agent_config(config)

    def test_project_instructions_on_cli_raises(self) -> None:
        from swarmline.agent.config import AgentConfig

        config = AgentConfig(
            system_prompt="x", runtime="cli", project_instructions=True
        )
        with pytest.raises(ValueError, match="project_instructions"):
            self._factory().validate_agent_config(config)

    def test_project_instructions_supported_everywhere_else(self) -> None:
        from swarmline.agent.config import AgentConfig

        for runtime in ("thin", "claude_sdk", "deepagents", "openai_agents", "pi_sdk"):
            config = AgentConfig(
                system_prompt="x", runtime=runtime, project_instructions=True
            )
            self._factory().validate_agent_config(config)

    def test_thinking_on_pi_sdk_passes_and_on_cli_raises(self) -> None:
        from swarmline.agent.config import AgentConfig
        from swarmline.runtime.types import ThinkingConfig

        ok = AgentConfig(
            system_prompt="x",
            runtime="pi_sdk",
            thinking=ThinkingConfig(budget_tokens=1024),
        )
        self._factory().validate_agent_config(ok)

        bad = AgentConfig(
            system_prompt="x",
            runtime="cli",
            thinking=ThinkingConfig(budget_tokens=1024),
        )
        with pytest.raises(ValueError, match="thinking_stream"):
            self._factory().validate_agent_config(bad)

    def test_error_message_lists_capable_runtimes(self) -> None:
        from swarmline.agent.config import AgentConfig
        from swarmline.runtime.types import ThinkingConfig

        config = AgentConfig(
            system_prompt="x",
            runtime="cli",
            thinking=ThinkingConfig(budget_tokens=1024),
        )
        with pytest.raises(ValueError, match="supported by:"):
            self._factory().validate_agent_config(config)


class TestCreateTemporalFacade:
    """I-096: the Agent facade path to temporal must fail loud, never TypeError
    (runtime-parity re-audit 2026-07-04, blocker finding)."""

    def _factory(self) -> RuntimeFactory:
        return RuntimeFactory()

    def test_create_temporal_tolerates_empty_tool_executors(self) -> None:
        """build_portable_runtime_plan always emits tool_executors={} — the
        temporal factory must swallow the empty wiring artifact."""
        from swarmline.runtime.temporal.runtime import TemporalAgentRuntime

        cfg = RuntimeConfig(runtime_name="temporal")
        runtime = self._factory().create(config=cfg, tool_executors={})
        assert isinstance(runtime, TemporalAgentRuntime)

    def test_create_temporal_rejects_nonempty_tool_executors(self) -> None:
        cfg = RuntimeConfig(runtime_name="temporal")
        with pytest.raises(ValueError, match="worker"):
            self._factory().create(config=cfg, tool_executors={"calc": object()})

    def test_create_temporal_rejects_hook_registry_loudly(self) -> None:
        cfg = RuntimeConfig(runtime_name="temporal")
        with pytest.raises(ValueError, match="temporal"):
            self._factory().create(config=cfg, hook_registry=object())

    def test_create_temporal_rejects_command_registry_loudly(self) -> None:
        cfg = RuntimeConfig(runtime_name="temporal")
        with pytest.raises(ValueError, match="temporal"):
            self._factory().create(config=cfg, command_registry=object())

    def test_portable_plan_to_temporal_creates_runtime(self) -> None:
        """THE blocker repro: Agent(config) facade path end-to-end."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan
        from swarmline.runtime.temporal.runtime import TemporalAgentRuntime

        plan = build_portable_runtime_plan(
            AgentConfig(system_prompt="s", runtime="temporal"), "temporal"
        )
        runtime = self._factory().create(config=plan.config, **plan.create_kwargs)
        assert isinstance(runtime, TemporalAgentRuntime)

    def test_portable_plan_forwards_mcp_servers_to_temporal_fail_fast(self) -> None:
        """mcp_servers must reach the temporal factory so its documented
        'tools live on workers' guard actually fires (was: silent drop)."""
        from swarmline.agent.config import AgentConfig
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        plan = build_portable_runtime_plan(
            AgentConfig(
                system_prompt="s",
                runtime="temporal",
                mcp_servers={"srv": {"url": "https://mcp.example.com/sse"}},
            ),
            "temporal",
        )
        assert "mcp_servers" in plan.create_kwargs
        with pytest.raises(ValueError, match="worker"):
            self._factory().create(config=plan.config, **plan.create_kwargs)
