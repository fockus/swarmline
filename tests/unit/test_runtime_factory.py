"""Tests for RuntimeFactory - select runtime by config/env/override."""

import os
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from cognitia.runtime.capabilities import CapabilityRequirements
from cognitia.runtime.factory import RuntimeFactory, _ErrorRuntime
from cognitia.runtime.types import RuntimeConfig


@pytest.fixture
def factory() -> RuntimeFactory:
    return RuntimeFactory()


# ---------------------------------------------------------------------------
# resolve_runtime_name
# ---------------------------------------------------------------------------


class TestResolveRuntimeName:
    """RuntimeFactory.resolve_runtime_name - selection priority."""

    def test_default_is_claude_sdk(self, factory: RuntimeFactory) -> None:
        """Without parameters - cloud_sdk."""
        assert factory.resolve_runtime_name() == "claude_sdk"

    def test_config_overrides_default(self, factory: RuntimeFactory) -> None:
        """config.runtime_name overrides default."""
        cfg = RuntimeConfig(runtime_name="thin")
        assert factory.resolve_runtime_name(config=cfg) == "thin"

    def test_env_overrides_default(self, factory: RuntimeFactory) -> None:
        """The COGNITIA_RUNTIME environment variable overrides default."""
        with patch.dict(os.environ, {"COGNITIA_RUNTIME": "deepagents"}):
            assert factory.resolve_runtime_name() == "deepagents"

    def test_config_overrides_env(self, factory: RuntimeFactory) -> None:
        """config takes precedence over env."""
        cfg = RuntimeConfig(runtime_name="thin")
        with patch.dict(os.environ, {"COGNITIA_RUNTIME": "deepagents"}):
            assert factory.resolve_runtime_name(config=cfg) == "thin"

    def test_override_overrides_all(self, factory: RuntimeFactory) -> None:
        """runtime_override has maximum priority."""
        cfg = RuntimeConfig(runtime_name="thin")
        with patch.dict(os.environ, {"COGNITIA_RUNTIME": "deepagents"}):
            result = factory.resolve_runtime_name(
                config=cfg,
                runtime_override="claude_sdk",
            )
            assert result == "claude_sdk"

    def test_invalid_env_ignored(self, factory: RuntimeFactory) -> None:
        """Invalid env - is ignored, uses default."""
        with patch.dict(os.environ, {"COGNITIA_RUNTIME": "invalid_runtime"}):
            assert factory.resolve_runtime_name() == "claude_sdk"

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
        with patch.dict(os.environ, {"COGNITIA_RUNTIME": "THIN"}):
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

        with patch("cognitia.runtime.thin.ThinRuntime", fake_cls):
            runtime = factory.create(config=cfg, tool_executors=tool_exec)

        assert runtime is fake_runtime
        kwargs = fake_cls.call_args.kwargs
        assert kwargs["local_tools"] == tool_exec
        assert "tool_executors" not in kwargs

    def test_create_cli_ignores_facade_only_kwargs(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """CLI runtime path drops tool_executors/local_tools before constructor."""
        cfg = RuntimeConfig(runtime_name="cli")
        fake_runtime = object()
        fake_cls = MagicMock(return_value=fake_runtime)
        cli_config = MagicMock()

        with patch("cognitia.runtime.cli.runtime.CliAgentRuntime", fake_cls):
            runtime = factory.create(
                config=cfg,
                tool_executors={"calc": object()},
                local_tools={"calc": object()},
                cli_config=cli_config,
            )

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

        with patch.object(RuntimeFactory, "_effective_registry", new_callable=PropertyMock) as mock_registry:
            mock_registry.return_value = None
            with patch("cognitia.runtime.cli.runtime.CliAgentRuntime", fake_cls):
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
        from cognitia.runtime.capabilities import RuntimeCapabilities
        from cognitia.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        custom_caps = RuntimeCapabilities(runtime_name="custom_factory_rt", tier="light")
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
        from cognitia.runtime.types import RuntimeErrorData

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
        from cognitia.runtime.types import RuntimeErrorData

        err = RuntimeErrorData(kind="dependency_missing", message="x")
        runtime = _ErrorRuntime(err)
        await runtime.cleanup()  # shouldn't quit
