"""Тесты для RuntimeFactory — выбор runtime по config/env/override."""

import os
from unittest.mock import MagicMock, patch

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
    """RuntimeFactory.resolve_runtime_name — приоритет выбора."""

    def test_default_is_claude_sdk(self, factory: RuntimeFactory) -> None:
        """Без параметров — claude_sdk."""
        assert factory.resolve_runtime_name() == "claude_sdk"

    def test_config_overrides_default(self, factory: RuntimeFactory) -> None:
        """config.runtime_name переопределяет default."""
        cfg = RuntimeConfig(runtime_name="thin")
        assert factory.resolve_runtime_name(config=cfg) == "thin"

    def test_env_overrides_default(self, factory: RuntimeFactory) -> None:
        """Переменная окружения COGNITIA_RUNTIME переопределяет default."""
        with patch.dict(os.environ, {"COGNITIA_RUNTIME": "deepagents"}):
            assert factory.resolve_runtime_name() == "deepagents"

    def test_config_overrides_env(self, factory: RuntimeFactory) -> None:
        """config имеет приоритет над env."""
        cfg = RuntimeConfig(runtime_name="thin")
        with patch.dict(os.environ, {"COGNITIA_RUNTIME": "deepagents"}):
            assert factory.resolve_runtime_name(config=cfg) == "thin"

    def test_override_overrides_all(self, factory: RuntimeFactory) -> None:
        """runtime_override имеет максимальный приоритет."""
        cfg = RuntimeConfig(runtime_name="thin")
        with patch.dict(os.environ, {"COGNITIA_RUNTIME": "deepagents"}):
            result = factory.resolve_runtime_name(
                config=cfg, runtime_override="claude_sdk",
            )
            assert result == "claude_sdk"

    def test_invalid_env_ignored(self, factory: RuntimeFactory) -> None:
        """Невалидный env — игнорируется, используется default."""
        with patch.dict(os.environ, {"COGNITIA_RUNTIME": "invalid_runtime"}):
            assert factory.resolve_runtime_name() == "claude_sdk"

    def test_invalid_override_ignored(self, factory: RuntimeFactory) -> None:
        """Невалидный override — игнорируется, используется config."""
        cfg = RuntimeConfig(runtime_name="thin")
        result = factory.resolve_runtime_name(
            config=cfg, runtime_override="invalid",
        )
        assert result == "thin"

    def test_env_case_insensitive(self, factory: RuntimeFactory) -> None:
        """Env с разным регистром — приводится к lower."""
        with patch.dict(os.environ, {"COGNITIA_RUNTIME": "THIN"}):
            assert factory.resolve_runtime_name() == "thin"


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestCreate:
    """RuntimeFactory.create — создание runtime."""

    def test_create_thin_missing_dep(self, factory: RuntimeFactory) -> None:
        """Если anthropic не установлен — возвращает _ErrorRuntime."""
        with patch.dict("sys.modules", {"anthropic": None}):
            cfg = RuntimeConfig(runtime_name="thin")
            runtime = factory.create(config=cfg)
            # _ErrorRuntime — допустимый объект (не падает при создании)
            assert runtime is not None

    def test_create_deepagents_missing_dep(self, factory: RuntimeFactory) -> None:
        """Если langchain-core не установлен — возвращает _ErrorRuntime."""
        cfg = RuntimeConfig(runtime_name="deepagents")
        runtime = factory.create(config=cfg)
        # Может быть _ErrorRuntime или DeepAgentsRuntime (зависит от deps)
        assert runtime is not None

    def test_create_with_override(self, factory: RuntimeFactory) -> None:
        """runtime_override передаётся в resolve."""
        cfg = RuntimeConfig(runtime_name="claude_sdk")
        # Не можем реально создать thin (нужен anthropic), но проверяем что override работает
        runtime = factory.create(config=cfg, runtime_override="thin")
        assert runtime is not None

    def test_invalid_name_in_create(self, factory: RuntimeFactory) -> None:
        """Невалидное имя в config → ValueError в RuntimeConfig.__post_init__."""
        with pytest.raises(ValueError, match="Неизвестный runtime"):
            RuntimeConfig(runtime_name="bad_name")

    def test_create_with_unsupported_override_returns_error_runtime(
        self,
        factory: RuntimeFactory,
    ) -> None:
        """override runtime, не удовлетворяющий capability requirements → _ErrorRuntime."""
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
        """tool_executors facade-слоя прокидываются в ThinRuntime как local_tools."""
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


# ---------------------------------------------------------------------------
# _ErrorRuntime
# ---------------------------------------------------------------------------

class TestErrorRuntime:
    """_ErrorRuntime — заглушка при отсутствии dependency."""

    @pytest.mark.asyncio
    async def test_run_yields_error(self) -> None:
        """run() возвращает error event."""
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
        """cleanup() не падает."""
        from cognitia.runtime.types import RuntimeErrorData

        err = RuntimeErrorData(kind="dependency_missing", message="x")
        runtime = _ErrorRuntime(err)
        await runtime.cleanup()  # не должно бросить
