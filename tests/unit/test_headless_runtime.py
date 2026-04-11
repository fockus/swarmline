"""Tests for HeadlessRuntime."""

from __future__ import annotations

import pytest

from swarmline.runtime.headless import HeadlessRuntime
from swarmline.runtime.registry import get_default_registry, reset_default_registry
from swarmline.runtime.types import Message, RuntimeConfig


class TestHeadlessRuntime:
    """HeadlessRuntime unit tests."""

    def _make_runtime(self) -> HeadlessRuntime:
        return HeadlessRuntime(RuntimeConfig(runtime_name="headless"))

    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self) -> None:
        rt = self._make_runtime()
        with pytest.raises(NotImplementedError, match="HeadlessRuntime does not support LLM"):
            async for _ in rt.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
                active_tools=[],
            ):
                pass  # pragma: no cover

    def test_cancel_is_noop(self) -> None:
        rt = self._make_runtime()
        rt.cancel()  # should not raise

    @pytest.mark.asyncio
    async def test_cleanup_is_noop(self) -> None:
        rt = self._make_runtime()
        await rt.cleanup()  # should not raise

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        async with HeadlessRuntime(RuntimeConfig(runtime_name="headless")) as rt:
            assert rt is not None

    def test_registered_in_default_registry(self) -> None:
        reset_default_registry()
        try:
            registry = get_default_registry()
            assert registry.is_registered("headless")
        finally:
            reset_default_registry()

    def test_factory_creates_instance(self) -> None:
        reset_default_registry()
        try:
            registry = get_default_registry()
            factory = registry.get("headless")
            assert factory is not None
            instance = factory(RuntimeConfig(runtime_name="headless"))
            assert isinstance(instance, HeadlessRuntime)
        finally:
            reset_default_registry()
