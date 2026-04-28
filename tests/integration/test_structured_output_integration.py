"""Integration: ThinRuntime + Pydantic structured output (validate + retry)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig

pytestmark = pytest.mark.integration


class WeatherReport(BaseModel):
    city: str
    temperature: float
    summary: str


class TestThinRuntimeStructuredOutputIntegration:
    """ThinRuntime with output_type - validate, retry, backward compat."""

    @pytest.mark.asyncio
    async def test_thin_runtime_structured_output_success(self) -> None:
        """Mock LLM returns valid JSON -> final event with parsed model."""
        valid_json = json.dumps(
            {"city": "Moscow", "temperature": -5.0, "summary": "Cold"}
        )

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            return json.dumps({"type": "final", "final_message": valid_json})

        config = RuntimeConfig(
            runtime_name="thin",
            output_type=WeatherReport,
            max_iterations=3,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather in Moscow")],
            system_prompt="You are a weather bot.",
            active_tools=[],
        ):
            events.append(event)

        final_events = [e for e in events if e.type == "final"]
        assert len(final_events) == 1

        final = final_events[0]
        structured = final.data.get("structured_output")
        assert structured is not None
        assert isinstance(structured, WeatherReport)
        assert structured.city == "Moscow"
        assert structured.temperature == -5.0

    @pytest.mark.asyncio
    async def test_thin_runtime_structured_output_retry(self) -> None:
        """Mock LLM: pervyy response invalid, vtoroy valid -> retry works."""
        call_count = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # Pervyy call - final with notvalidnym JSON
                return json.dumps({"type": "final", "final_message": "not a json"})
            # Retry - valid response
            valid = json.dumps({"city": "SPb", "temperature": 2.0, "summary": "Cloudy"})
            return json.dumps({"type": "final", "final_message": valid})

        config = RuntimeConfig(
            runtime_name="thin",
            output_type=WeatherReport,
            max_model_retries=2,
            max_iterations=6,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather in SPb")],
            system_prompt="You are a weather bot.",
            active_tools=[],
        ):
            events.append(event)

        final_events = [e for e in events if e.type == "final"]
        assert len(final_events) == 1

        structured = final_events[0].data.get("structured_output")
        assert isinstance(structured, WeatherReport)
        assert structured.city == "SPb"

    @pytest.mark.asyncio
    async def test_thin_runtime_native_structured_output_accepts_raw_json(self) -> None:
        """Native structured mode validates raw provider JSON without Swarmline envelope."""
        captured_kwargs: list[dict[str, Any]] = []

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            captured_kwargs.append(kwargs)
            return json.dumps(
                {"city": "Berlin", "temperature": 18.5, "summary": "Clear"}
            )

        config = RuntimeConfig(
            runtime_name="thin",
            model="openrouter:openai/gpt-oss-120b",
            output_type=WeatherReport,
            structured_mode="native",
            structured_schema_name="weather_report_v1",
            max_model_retries=1,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather in Berlin")],
            system_prompt="Return weather JSON.",
            active_tools=[],
        ):
            events.append(event)

        final = next(e for e in events if e.type == "final")
        structured = final.data["structured_output"]
        assert isinstance(structured, WeatherReport)
        assert structured.city == "Berlin"
        assert captured_kwargs[0]["response_format"]["type"] == "json_schema"
        assert (
            captured_kwargs[0]["response_format"]["json_schema"]["name"]
            == "weather_report_v1"
        )
        assert captured_kwargs[0]["extra_body"]["provider"] == {
            "require_parameters": True
        }

    @pytest.mark.asyncio
    async def test_thin_runtime_native_structured_output_retries_until_valid(
        self,
    ) -> None:
        """Native mode retries raw JSON responses until Pydantic validation passes."""
        call_count = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return '{"city": "Berlin"}'
            return json.dumps(
                {"city": "Berlin", "temperature": 18.5, "summary": "Clear"}
            )

        config = RuntimeConfig(
            runtime_name="thin",
            model="openrouter:openai/gpt-oss-120b",
            output_type=WeatherReport,
            structured_mode="native",
            max_model_retries=2,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather in Berlin")],
            system_prompt="Return weather JSON.",
            active_tools=[],
        ):
            events.append(event)

        final = next(e for e in events if e.type == "final")
        assert call_count == 2
        assert isinstance(final.data["structured_output"], WeatherReport)

    @pytest.mark.asyncio
    async def test_thin_runtime_native_structured_output_emits_validation_events(
        self,
    ) -> None:
        """Structured validation emits start, retry, and end observability events."""
        bus = InMemoryEventBus()
        observed: list[tuple[str, dict[str, Any]]] = []
        for event_type in (
            "structured_validation_start",
            "structured_retry",
            "structured_validation_end",
        ):
            bus.subscribe(
                event_type,
                lambda data, event_type=event_type: observed.append((event_type, data)),
            )

        call_count = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "{}"
            return json.dumps(
                {"city": "Berlin", "temperature": 18.5, "summary": "Clear"}
            )

        config = RuntimeConfig(
            runtime_name="thin",
            model="openrouter:openai/gpt-oss-120b",
            output_type=WeatherReport,
            structured_mode="native",
            structured_schema_name="weather_report_v1",
            max_model_retries=1,
            event_bus=bus,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        async for _event in runtime.run(
            messages=[Message(role="user", content="Weather in Berlin")],
            system_prompt="Return weather JSON.",
            active_tools=[],
        ):
            pass

        event_names = [name for name, _data in observed]
        assert event_names == [
            "structured_validation_start",
            "structured_retry",
            "structured_validation_end",
        ]
        assert observed[-1][1]["ok"] is True

    @pytest.mark.asyncio
    async def test_thin_runtime_native_structured_output_unsupported_provider_errors(
        self,
    ) -> None:
        """Native mode fails fast when provider capabilities do not support it."""
        called = False

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal called
            called = True
            return "{}"

        config = RuntimeConfig(
            runtime_name="thin",
            model="anthropic:claude-sonnet-4-20250514",
            output_type=WeatherReport,
            structured_mode="native",
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather")],
            system_prompt="Return JSON.",
            active_tools=[],
        ):
            events.append(event)

        assert called is False
        error = next(e for e in events if e.type == "error")
        assert error.data["kind"] == "capability_unsupported"
        assert "native structured output" in error.data["message"]

    @pytest.mark.asyncio
    async def test_thin_runtime_structured_output_streaming_retry_buffers_invalid_first_reply(
        self,
    ) -> None:
        """Streaming invalid reply is not emitted before structured-output retry succeeds."""
        call_count = 0
        valid = json.dumps({"city": "Paris", "temperature": 18.0, "summary": "Sunny"})

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> Any:
            nonlocal call_count
            call_count += 1

            if kwargs.get("stream"):

                async def _stream():
                    yield '{"type":"final","final_message":"not json"}'

                return _stream()

            return json.dumps({"type": "final", "final_message": valid})

        config = RuntimeConfig(
            runtime_name="thin",
            output_type=WeatherReport,
            max_model_retries=1,
            max_iterations=4,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather in Paris")],
            system_prompt="Return JSON.",
            active_tools=[],
        ):
            events.append(event)

        deltas = [
            event.data["text"] for event in events if event.type == "assistant_delta"
        ]
        final = next(event for event in events if event.type == "final")
        assert call_count == 2
        assert deltas == [valid]
        assert final.data["text"] == valid
        assert isinstance(final.data["structured_output"], WeatherReport)

    @pytest.mark.asyncio
    async def test_thin_runtime_structured_output_backward_compat(self) -> None:
        """output_format dict without output_type works kak ranshe."""

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            return json.dumps({"type": "final", "final_message": '{"x": 42}'})

        config = RuntimeConfig(
            runtime_name="thin",
            output_format={"type": "object", "properties": {"x": {"type": "integer"}}},
            max_iterations=3,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Give me x")],
            system_prompt="Return JSON.",
            active_tools=[],
        ):
            events.append(event)

        final_events = [e for e in events if e.type == "final"]
        assert len(final_events) == 1

        structured = final_events[0].data.get("structured_output")
        # S dict output_format (without output_type) - structured output eto dict, not model
        assert structured == {"x": 42}

    @pytest.mark.asyncio
    async def test_thin_runtime_structured_output_retry_exhausted(self) -> None:
        """Vse retry-popytki ischerpany -> error event."""

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            # Vsegda returns final with notvalidnym JSON for output_type
            return json.dumps({"type": "final", "final_message": "not valid json ever"})

        config = RuntimeConfig(
            runtime_name="thin",
            output_type=WeatherReport,
            max_model_retries=2,
            max_iterations=6,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather?")],
            system_prompt="Return JSON.",
            active_tools=[],
        ):
            events.append(event)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) >= 1
        assert error_events[0].data["kind"] == "bad_model_output"

    @pytest.mark.asyncio
    async def test_thin_runtime_structured_output_nested_model(self) -> None:
        """Nested Pydantic model as output_type — schema extracted, validation works."""
        from pydantic import BaseModel as PydanticBaseModel

        class Address(PydanticBaseModel):
            city: str
            country: str

        class Person(PydanticBaseModel):
            name: str
            address: Address

        valid_json = json.dumps(
            {"name": "Alice", "address": {"city": "Berlin", "country": "DE"}}
        )

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            return json.dumps({"type": "final", "final_message": valid_json})

        config = RuntimeConfig(
            runtime_name="thin",
            output_type=Person,
            max_iterations=3,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Who is Alice?")],
            system_prompt="Return person info.",
            active_tools=[],
        ):
            events.append(event)

        final_events = [e for e in events if e.type == "final"]
        assert len(final_events) == 1
        structured = final_events[0].data.get("structured_output")
        assert isinstance(structured, Person)
        assert structured.address.city == "Berlin"

    @pytest.mark.asyncio
    async def test_thin_runtime_no_output_type_no_validation(self) -> None:
        """Without output_type, no validation occurs — raw text returned."""

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            return json.dumps({"type": "final", "final_message": "Hello, world!"})

        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=3,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Say hi")],
            system_prompt="Be friendly.",
            active_tools=[],
        ):
            events.append(event)

        final_events = [e for e in events if e.type == "final"]
        assert len(final_events) == 1
        assert final_events[0].data["text"] == "Hello, world!"

    @pytest.mark.asyncio
    async def test_thin_runtime_structured_output_retry_in_react_mode(self) -> None:
        """React mode validates output_type and retries instead of silently dropping errors."""
        call_count = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps(
                    {
                        "type": "tool_call",
                        "tool": {"name": "lookup", "args": {"city": "Kazan"}},
                    }
                )
            if call_count == 2:
                return json.dumps({"type": "final", "final_message": "not json"})
            valid = json.dumps(
                {"city": "Kazan", "temperature": 10.0, "summary": "Warm"}
            )
            return json.dumps({"type": "final", "final_message": valid})

        config = RuntimeConfig(
            runtime_name="thin",
            output_type=WeatherReport,
            max_model_retries=2,
            max_iterations=6,
        )
        runtime = ThinRuntime(
            config=config,
            llm_call=fake_llm,
            local_tools={"lookup": lambda city: city},
        )

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather in Kazan")],
            system_prompt="You are a weather bot.",
            active_tools=[],
            mode_hint="react",
        ):
            events.append(event)

        final_events = [e for e in events if e.type == "final"]
        assert len(final_events) == 1
        structured = final_events[0].data.get("structured_output")
        assert isinstance(structured, WeatherReport)
        assert structured.city == "Kazan"
        assert any(event.type == "tool_call_started" for event in events)
        assert any(event.type == "tool_call_finished" for event in events)

    @pytest.mark.asyncio
    async def test_thin_runtime_structured_output_streaming_retry_in_react_mode_buffers_delta(
        self,
    ) -> None:
        """React mode does not emit invalid streaming payload before structured-output retry."""
        call_count = 0
        valid = json.dumps({"city": "Kazan", "temperature": 10.0, "summary": "Warm"})

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> Any:
            nonlocal call_count
            call_count += 1
            if kwargs.get("stream"):

                async def _stream():
                    yield '{"type":"final","final_message":"not json"}'

                return _stream()
            return json.dumps({"type": "final", "final_message": valid})

        config = RuntimeConfig(
            runtime_name="thin",
            output_type=WeatherReport,
            max_model_retries=1,
            max_iterations=4,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather in Kazan")],
            system_prompt="Return JSON.",
            active_tools=[],
            mode_hint="react",
        ):
            events.append(event)

        deltas = [
            event.data["text"] for event in events if event.type == "assistant_delta"
        ]
        final = next(event for event in events if event.type == "final")
        assert call_count == 2
        assert deltas == [valid]
        assert final.data["text"] == valid
        assert isinstance(final.data["structured_output"], WeatherReport)

    @pytest.mark.asyncio
    async def test_thin_runtime_structured_output_retry_exhausted_in_react_mode(
        self,
    ) -> None:
        """React mode returns bad_model_output when structured-output retries are exhausted."""

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            return json.dumps({"type": "final", "final_message": "still not json"})

        config = RuntimeConfig(
            runtime_name="thin",
            output_type=WeatherReport,
            max_model_retries=1,
            max_iterations=4,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather?")],
            system_prompt="Return JSON.",
            active_tools=[],
            mode_hint="react",
        ):
            events.append(event)

        assert not any(event.type == "final" for event in events)
        error_events = [event for event in events if event.type == "error"]
        assert len(error_events) == 1
        assert error_events[0].data["kind"] == "bad_model_output"

    @pytest.mark.asyncio
    async def test_thin_runtime_structured_output_retry_exhausted_in_planner_mode(
        self,
    ) -> None:
        """Planner final assembly uses the same structured-output retry/error semantics."""
        call_count = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps(
                    {
                        "type": "plan",
                        "goal": "Prepare weather report",
                        "steps": [
                            {
                                "id": "s1",
                                "title": "Collect context",
                                "mode": "conversational",
                            }
                        ],
                        "final_format": "Return JSON",
                    }
                )
            if call_count == 2:
                return json.dumps({"type": "final", "final_message": "step complete"})
            return json.dumps({"type": "final", "final_message": "not json"})

        config = RuntimeConfig(
            runtime_name="thin",
            output_type=WeatherReport,
            max_model_retries=1,
            max_iterations=6,
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[Any] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Weather in Kazan")],
            system_prompt="Return JSON.",
            active_tools=[],
            mode_hint="planner",
        ):
            events.append(event)

        assert not any(event.type == "final" for event in events)
        error_events = [event for event in events if event.type == "error"]
        assert len(error_events) == 1
        assert error_events[0].data["kind"] == "bad_model_output"
