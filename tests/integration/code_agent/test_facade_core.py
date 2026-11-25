"""Integration tests -- `CodeAgent` facade core (code-agent-facade plan, Stage 2).

Verifies `CodeAgent.run`/`.stream`/`.close` actually drive a thin runtime
built via `build_portable_runtime_plan` + `RuntimeFactoryPort`, with the
canonical coding tool surface enabled. Fully offline: exercises a scripted
`FakeRuntimeFactory` (see `conftest.py`), no live LLM call.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

from swarmline.code_agent import CodeAgent

from .conftest import FakeCodeRuntime, FakeRuntimeFactory


class TestRunYieldsEventsFromFakeRuntime:
    async def test_run_yields_final_event_with_fake_runtime(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        events = [event async for event in agent.run("hi")]

        assert len(events) >= 1
        assert any(event.type == "final" for event in events)

    async def test_stream_is_alias_for_run(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        events = [event async for event in agent.stream("hi")]

        assert any(event.type == "final" for event in events)

    async def test_run_forwards_error_only_stream_without_crashing(
        self, tmp_path: Path
    ) -> None:
        """A runtime that only ever emits an `error` event must be forwarded
        as-is -- the facade does not crash or swallow it."""
        from swarmline.domain_types import RuntimeEvent

        factory = FakeRuntimeFactory(
            events=[RuntimeEvent(type="error", data={"message": "boom"})]
        )
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)

        events = [event async for event in agent.run("hi")]

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].data["message"] == "boom"
        assert factory.created[0].cleanup_calls == 1


class TestRunPassesUserPrompt:
    async def test_run_passes_user_prompt_as_first_message(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        async for _event in agent.run("fix the typo in README.md"):
            pass

        assert len(fake_runtime_factory.created) == 1
        run_kwargs = fake_runtime_factory.created[0].run_kwargs
        assert run_kwargs is not None
        first_message = run_kwargs["messages"][0]
        assert first_message.role == "user"
        assert first_message.content == "fix the typo in README.md"

    async def test_run_forwards_empty_prompt_as_empty_user_message(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        async for _event in agent.run(""):
            pass

        first_message = fake_runtime_factory.created[0].run_kwargs["messages"][0]
        assert first_message.role == "user"
        assert first_message.content == ""


class TestFacadeEnablesCodingProfile:
    async def test_facade_enables_coding_profile_in_plan(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        async for _event in agent.run("hi"):
            pass

        active_tool_names = {
            spec.name
            for spec in fake_runtime_factory.created[0].run_kwargs["active_tools"]
        }
        assert {"read", "write", "bash"} <= active_tool_names

    async def test_facade_passes_coding_tool_executors_to_factory_create(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        async for _event in agent.run("hi"):
            pass

        create_kwargs = fake_runtime_factory.create_calls[0]
        executor_names = set(create_kwargs["tool_executors"])
        assert {"read", "write", "bash"} <= executor_names


class TestCloseCleansUpRuntime:
    async def test_close_calls_runtime_cleanup(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )
        stream = agent.run("hi")
        await stream.__anext__()  # advance to first yield: runtime created, still open

        await agent.close()

        assert fake_runtime_factory.created[0].cleanup_calls == 1

    async def test_run_cleanup_runs_on_normal_completion(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        async for _event in agent.run("hi"):
            pass

        assert fake_runtime_factory.created[0].cleanup_calls == 1

    async def test_run_cleanup_runs_when_iteration_raises(self, tmp_path: Path) -> None:
        """The underlying runtime's own `run()` raising mid-stream must still
        trigger `CodeAgent.run`'s `finally: await runtime.cleanup()`."""

        class _Boom(Exception):
            pass

        factory = FakeRuntimeFactory(raise_after=_Boom("runtime blew up"))
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)

        with pytest.raises(_Boom):
            async for _event in agent.run("hi"):
                pass

        assert factory.created[0].cleanup_calls == 1

    async def test_close_without_prior_run_is_a_noop(self, tmp_path: Path) -> None:
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))

        await agent.close()  # must not raise


class TestCleanupIsIdempotentPerRun:
    async def test_close_then_generator_finalize_cleans_up_exactly_once(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        """`close()` while the stream is suspended, then the generator's own
        finalization (`aclose()`), must clean the runtime exactly once."""
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )
        stream = agent.run("hi")
        await stream.__anext__()

        await agent.close()
        await stream.aclose()  # generator `finally` must not double-clean

        assert fake_runtime_factory.created[0].cleanup_calls == 1

    async def test_early_break_then_aclose_then_close_cleans_up_exactly_once(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        """Early `break` + explicit `aclose()` + a later `close()` -- the
        runtime is cleaned exactly once across all three paths."""
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )
        stream = agent.run("hi")
        async for _event in stream:
            break

        await stream.aclose()
        await agent.close()

        assert fake_runtime_factory.created[0].cleanup_calls == 1

    async def test_stream_stops_after_close_mid_iteration(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        """A caller that keeps consuming after `close()` must get a finished
        stream, not events pulled from an already-cleaned runtime."""
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )
        stream = agent.run("hi")
        await stream.__anext__()

        await agent.close()
        remaining = [event async for event in stream]

        assert remaining == []
        assert fake_runtime_factory.created[0].cleanup_calls == 1

    async def test_close_while_awaiting_next_event_yields_no_post_cleanup_event(
        self, tmp_path: Path
    ) -> None:
        """`close()` racing an in-flight `await` on the NEXT runtime event
        (one event already delivered): the facade must not deliver the event
        that arrives after the runtime was cleaned."""
        import asyncio

        gate = asyncio.Event()
        gate.set()  # let the first event through
        factory = FakeRuntimeFactory(emit_gate=gate)
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)
        received: list[object] = []

        async def _consume() -> None:
            async for event in agent.run("hi"):
                received.append(event)
                gate.clear()  # block emission of the following event

        task = asyncio.create_task(_consume())
        for _ in range(10):  # first event consumed; consumer awaits the second
            await asyncio.sleep(0)
        assert len(received) == 1

        await agent.close()
        gate.set()  # second event now emits -- but the runtime is cleaned
        await task

        assert len(received) == 1
        assert factory.created[0].cleanup_calls == 1

    async def test_unhashable_runtime_still_runs_and_cleans_up_once(
        self, tmp_path: Path
    ) -> None:
        """`RuntimeFactoryPort.create()` returns `Any` -- nothing requires the
        runtime to be hashable. The facade must not blow up (or leak cleanup)
        on an unhashable-but-valid runtime."""

        class _UnhashableRuntime(FakeCodeRuntime):
            __hash__ = None  # type: ignore[assignment]

        factory = FakeRuntimeFactory(runtime_cls=_UnhashableRuntime)
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path), runtime_factory=factory)

        events = [event async for event in agent.run("hi")]

        assert any(event.type == "final" for event in events)
        assert factory.created[0].cleanup_calls == 1

    async def test_concurrent_runs_close_cleans_each_runtime_exactly_once(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        """Two overlapping runs each own their runtime; `close()` cleans both
        exactly once, and later generator finalization adds nothing."""
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )
        first = agent.run("a")
        second = agent.run("b")
        await first.__anext__()
        await second.__anext__()

        await agent.close()
        await first.aclose()
        await second.aclose()

        assert [runtime.cleanup_calls for runtime in fake_runtime_factory.created] == [
            1,
            1,
        ]


class TestCustomToolsReachRuntime:
    async def test_constructor_tools_reach_active_tools_and_executors(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        """`tools=` passed to the public constructor is not a silent no-op:
        the custom tool must reach both the runtime's `active_tools` and the
        factory's `tool_executors`."""
        from swarmline.agent.tool import ToolDefinition

        async def _handler(**_kwargs: object) -> str:
            return "ok"

        custom = ToolDefinition(
            name="my_custom_tool",
            description="test-only custom tool",
            parameters={"type": "object", "properties": {}},
            handler=_handler,
        )
        agent = CodeAgent(
            model="sonnet",
            cwd=str(tmp_path),
            tools=(custom,),
            runtime_factory=fake_runtime_factory,
        )

        async for _event in agent.run("hi"):
            pass

        active_tool_names = {
            spec.name
            for spec in fake_runtime_factory.created[0].run_kwargs["active_tools"]
        }
        assert "my_custom_tool" in active_tool_names
        executor_names = set(fake_runtime_factory.create_calls[0]["tool_executors"])
        assert "my_custom_tool" in executor_names

    async def test_decorated_tool_function_is_unwrapped(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        """An `@tool`-decorated function (the project's idiomatic way to
        define tools) must be accepted and unwrapped to its definition."""
        from swarmline import tool

        @tool("greet_tool", "greets")
        def greet(name: str) -> str:
            return f"hi {name}"

        agent = CodeAgent(
            model="sonnet",
            cwd=str(tmp_path),
            tools=(greet,),
            runtime_factory=fake_runtime_factory,
        )

        async for _event in agent.run("hi"):
            pass

        active_tool_names = {
            spec.name
            for spec in fake_runtime_factory.created[0].run_kwargs["active_tools"]
        }
        assert "greet_tool" in active_tool_names

    async def test_invalid_tools_entry_raises_typeerror_at_construction(
        self, tmp_path: Path
    ) -> None:
        """A `tools` entry that is neither a `ToolDefinition` nor decorated
        with `@tool` must fail fast with a clear `TypeError` -- not with an
        obscure `AttributeError` deep inside runtime wiring."""
        with pytest.raises(TypeError, match="tools"):
            CodeAgent(model="sonnet", cwd=str(tmp_path), tools=("not a tool",))


class TestFacadeReusesRuntimeFactoryPort:
    def test_code_agent_package_has_no_direct_thinruntime_import(self) -> None:

        import swarmline.code_agent as pkg

        for module_info in pkgutil.iter_modules(pkg.__path__):
            module = importlib.import_module(f"{pkg.__name__}.{module_info.name}")
            source = inspect.getsource(module)
            # Any mention of the concrete class or its module path -- not just
            # a direct `ThinRuntime(` call -- would break the DIP boundary.
            assert "ThinRuntime" not in source, (
                f"{module.__name__} references ThinRuntime directly -- "
                "the facade must depend on RuntimeFactoryPort only"
            )
            assert "runtime.thin.runtime" not in source, (
                f"{module.__name__} imports the concrete thin runtime module -- "
                "the facade must depend on RuntimeFactoryPort only"
            )
