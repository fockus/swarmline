"""Unit tests for universal typed pipeline primitives."""

from __future__ import annotations

from typing import Any

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.pipeline import FallbackPolicy, TypedPipeline, TypedPipelineStage


class TestTypedPipeline:
    async def test_runs_sequential_stages(self) -> None:
        pipeline = TypedPipeline(
            stages=[
                TypedPipelineStage("double", lambda value: value * 2),
                TypedPipelineStage("format", lambda value: f"value={value}"),
            ]
        )

        result = await pipeline.run(3)

        assert result.status == "completed"
        assert result.output == "value=6"
        assert result.failed_stage is None

    async def test_retries_stage_until_validator_passes(self) -> None:
        attempts = 0

        def generate(value: str) -> str:
            nonlocal attempts
            attempts += 1
            return "bad" if attempts == 1 else f"{value}-ok"

        pipeline = TypedPipeline(
            stages=[
                TypedPipelineStage(
                    "generate",
                    generate,
                    validator=lambda value: value.endswith("-ok"),
                    max_attempts=2,
                ),
            ]
        )

        result = await pipeline.run("draft")

        assert attempts == 2
        assert result.status == "completed"
        assert result.output == "draft-ok"

    async def test_returns_last_valid_output_when_fallback_enabled(self) -> None:
        pipeline = TypedPipeline(
            stages=[
                TypedPipelineStage("draft", lambda value: f"{value}-draft"),
                TypedPipelineStage(
                    "validate",
                    lambda value: f"{value}-invalid",
                    validator=lambda value: "never" in value,
                    max_attempts=1,
                ),
            ],
            fallback_policy=FallbackPolicy(mode="last_valid"),
        )

        result = await pipeline.run("report")

        assert result.status == "fallback"
        assert result.output == "report-draft"
        assert result.failed_stage == "validate"

    async def test_emits_stage_events(self) -> None:
        bus = InMemoryEventBus()
        observed: list[tuple[str, dict[str, Any]]] = []
        for event_type in ("pipeline_stage_start", "pipeline_stage_end"):
            bus.subscribe(event_type, lambda data, event_type=event_type: observed.append((event_type, data)))

        pipeline = TypedPipeline(
            stages=[TypedPipelineStage("draft", lambda value: f"{value}-draft")],
            event_bus=bus,
        )

        result = await pipeline.run("report")

        assert result.status == "completed"
        assert [name for name, _data in observed] == [
            "pipeline_stage_start",
            "pipeline_stage_end",
        ]
        assert observed[-1][1]["stage"] == "draft"
