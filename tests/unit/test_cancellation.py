"""Unit tests: CancellationToken — cancel, callbacks, thread safety."""

from __future__ import annotations

import asyncio
import threading

from swarmline.runtime.cancellation import CancellationToken


class TestCancellationTokenBasics:
    """Core CancellationToken behavior."""

    def test_initial_not_cancelled(self) -> None:
        token = CancellationToken()
        assert token.is_cancelled is False

    def test_cancel_sets_flag(self) -> None:
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True

    def test_cancel_idempotent(self) -> None:
        token = CancellationToken()
        token.cancel()
        token.cancel()
        assert token.is_cancelled is True

    def test_callback_invoked_on_cancel(self) -> None:
        token = CancellationToken()
        called = []
        token.on_cancel(lambda: called.append(True))
        token.cancel()
        assert called == [True]

    def test_multiple_callbacks_invoked(self) -> None:
        token = CancellationToken()
        results: list[int] = []
        token.on_cancel(lambda: results.append(1))
        token.on_cancel(lambda: results.append(2))
        token.cancel()
        assert results == [1, 2]

    def test_callback_after_cancel_invoked_immediately(self) -> None:
        token = CancellationToken()
        token.cancel()
        called = []
        token.on_cancel(lambda: called.append(True))
        assert called == [True]

    def test_callback_not_invoked_before_cancel(self) -> None:
        token = CancellationToken()
        called = []
        token.on_cancel(lambda: called.append(True))
        assert called == []

    def test_callback_exception_does_not_break_other_callbacks(self) -> None:
        token = CancellationToken()
        results: list[int] = []

        def bad_callback() -> None:
            raise ValueError("boom")

        token.on_cancel(bad_callback)
        token.on_cancel(lambda: results.append(1))
        token.cancel()
        assert results == [1]


class TestCancellationTokenThreadSafety:
    """Thread safety for concurrent cancel/on_cancel."""

    def test_thread_safe_cancel(self) -> None:
        token = CancellationToken()
        results: list[int] = []
        barrier = threading.Barrier(10)

        def worker(idx: int) -> None:
            barrier.wait()
            token.on_cancel(lambda i=idx: results.append(i))
            token.cancel()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert token.is_cancelled is True
        # All callbacks should have been invoked (either during cancel or on_cancel after cancel)
        assert len(results) == 10


class TestCancellationTokenInRuntimeConfig:
    """CancellationToken field in RuntimeConfig."""

    def test_runtime_config_default_no_token(self) -> None:
        from swarmline.runtime.types import RuntimeConfig

        cfg = RuntimeConfig(runtime_name="thin")
        assert cfg.cancellation_token is None

    def test_runtime_config_with_token(self) -> None:
        from swarmline.runtime.types import RuntimeConfig

        token = CancellationToken()
        cfg = RuntimeConfig(runtime_name="thin", cancellation_token=token)
        assert cfg.cancellation_token is token


class TestThinRuntimeCancel:
    """ThinRuntime cancel() and context manager."""

    async def test_thin_runtime_cancel_yields_cancelled_error(self) -> None:
        """cancel() before run() yields cancelled error event."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        token = CancellationToken()
        cfg = RuntimeConfig(runtime_name="thin", cancellation_token=token)
        runtime = ThinRuntime(config=cfg, llm_call=_noop_llm)

        token.cancel()

        events = []
        async for event in runtime.run(
            messages=[Message(role="user", content="hello")],
            system_prompt="test",
            active_tools=[],
            config=cfg,
        ):
            events.append(event)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert error_events[0].data["kind"] == "cancelled"

    async def test_thin_runtime_cancel_method(self) -> None:
        """ThinRuntime.cancel() triggers the config token."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        token = CancellationToken()
        cfg = RuntimeConfig(runtime_name="thin", cancellation_token=token)
        runtime = ThinRuntime(config=cfg, llm_call=_noop_llm)

        assert not token.is_cancelled
        runtime.cancel()
        assert token.is_cancelled

    async def test_thin_runtime_context_manager(self) -> None:
        """ThinRuntime works as async context manager."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        cfg = RuntimeConfig(runtime_name="thin")
        async with ThinRuntime(config=cfg, llm_call=_noop_llm) as rt:
            assert rt is not None
        # cleanup() called — no exception

    async def test_thin_runtime_context_manager_calls_cleanup(self) -> None:
        """__aexit__ calls cleanup()."""
        from unittest.mock import AsyncMock

        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        cfg = RuntimeConfig(runtime_name="thin")
        rt = ThinRuntime(config=cfg, llm_call=_noop_llm)
        rt.cleanup = AsyncMock()  # type: ignore[method-assign]

        async with rt:
            pass

        rt.cleanup.assert_awaited_once()

    async def test_thin_runtime_cancel_during_conversational_call(self) -> None:
        """Cancel after run() starts suppresses final and returns cancelled error."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_llm(messages: list, system_prompt: str, **kwargs) -> str:  # type: ignore[override]
            started.set()
            await release.wait()
            return '{"type":"final","final_message":"slow"}'

        token = CancellationToken()
        cfg = RuntimeConfig(runtime_name="thin", cancellation_token=token)
        runtime = ThinRuntime(config=cfg, llm_call=slow_llm)

        events = []

        async def consume() -> None:
            async for event in runtime.run(
                messages=[Message(role="user", content="hello")],
                system_prompt="test",
                active_tools=[],
                config=cfg,
            ):
                events.append(event)

        task = asyncio.create_task(consume())
        await started.wait()
        token.cancel()
        release.set()
        await task

        assert not any(event.type == "final" for event in events)
        assert any(event.type == "error" and event.data["kind"] == "cancelled" for event in events)

    async def test_thin_runtime_cancel_during_react_loop(self) -> None:
        """Cancel between tool execution and final emit stops the react loop."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        second_call_started = asyncio.Event()
        release_second_call = asyncio.Event()
        call_count = 0

        async def react_llm(messages: list, system_prompt: str, **kwargs) -> str:  # type: ignore[override]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    '{"type":"tool_call","tool":{"name":"calc","args":{"x": 2}},'
                    '"assistant_message":"Calculating"}'
                )
            second_call_started.set()
            await release_second_call.wait()
            return '{"type":"final","final_message":"done"}'

        token = CancellationToken()
        cfg = RuntimeConfig(runtime_name="thin", cancellation_token=token)
        runtime = ThinRuntime(
            config=cfg,
            llm_call=react_llm,
            local_tools={"calc": lambda x: str(x)},
        )

        events = []

        async def consume() -> None:
            async for event in runtime.run(
                messages=[Message(role="user", content="compute")],
                system_prompt="test",
                active_tools=[],
                config=cfg,
                mode_hint="react",
            ):
                events.append(event)

        task = asyncio.create_task(consume())
        await second_call_started.wait()
        token.cancel()
        release_second_call.set()
        await task

        assert not any(event.type == "final" for event in events)
        assert any(event.type == "error" and event.data["kind"] == "cancelled" for event in events)

    async def test_thin_runtime_cancel_during_retry_backoff(self) -> None:
        """Cancellation during retry sleep exits quickly instead of waiting full delay."""
        from swarmline.retry import ExponentialBackoff
        from swarmline.runtime.thin.errors import ThinLlmError
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig, RuntimeErrorData

        first_call_done = asyncio.Event()

        async def failing_llm(messages: list, system_prompt: str, **kwargs) -> str:  # type: ignore[override]
            first_call_done.set()
            raise ThinLlmError(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message="temporary failure",
                    recoverable=False,
                )
            )

        token = CancellationToken()
        cfg = RuntimeConfig(
            runtime_name="thin",
            cancellation_token=token,
            retry_policy=ExponentialBackoff(max_retries=3, base_delay=0.5, jitter=False),
        )
        runtime = ThinRuntime(config=cfg, llm_call=failing_llm)

        events = []

        async def consume() -> None:
            async for event in runtime.run(
                messages=[Message(role="user", content="hello")],
                system_prompt="test",
                active_tools=[],
                config=cfg,
            ):
                events.append(event)

        task = asyncio.create_task(consume())
        await first_call_done.wait()
        token.cancel()
        await asyncio.wait_for(task, timeout=0.2)

        assert any(event.type == "error" and event.data["kind"] == "cancelled" for event in events)


async def _noop_llm(messages: list, system_prompt: str, **kwargs) -> str:  # type: ignore[override]
    return '{"type": "final", "final_message": "noop"}'


class TestCancelledErrorKind:
    """'cancelled' is a valid RUNTIME_ERROR_KINDS."""

    def test_cancelled_in_error_kinds(self) -> None:
        from swarmline.runtime.types import RUNTIME_ERROR_KINDS

        assert "cancelled" in RUNTIME_ERROR_KINDS

    def test_cancelled_error_data_valid(self) -> None:
        from swarmline.runtime.types import RuntimeErrorData

        err = RuntimeErrorData(kind="cancelled", message="Operation cancelled")
        assert err.kind == "cancelled"
