"""Typed data-flow pipeline — the registry-dispatch engine and its stage primitives.

Demonstrates: run_pipeline, TypedStage, ParallelStage, LoopStage, ConditionalStage, a custom stage
kind registered via @stage_runner (OCP), event observation, and the declarative YAML loader.
Pure-python, fully offline — no API keys required. Every step asserts, so this file also runs as a
smoke test (``python examples/31_typed_dataflow_pipeline.py``).
"""

import asyncio
import dataclasses
import tempfile
from pathlib import Path

from swarmline.pipeline import (
    ConditionalStage,
    LoopStage,
    ParallelStage,
    PipelineRegistries,
    StageOutcome,
    TypedStage,
    load_pipeline_from_yaml,
    run_pipeline,
    stage_runner,
)


async def demo_sequential() -> None:
    """A linear chain of typed steps — the engine dispatches each stage by its TYPE."""
    print("=== 1. Sequential TypedStage chain ===")
    stages = [
        TypedStage("double", lambda v: v * 2),
        TypedStage("label", lambda v: f"value={v}"),
    ]
    result = await run_pipeline(stages, 3)
    print(f"  status={result.status} output={result.output!r}")
    assert result.status == "completed"
    assert result.output == "value=6"


async def demo_parallel() -> None:
    """Static fork/join — named branches run concurrently, then a joiner merges their outputs."""
    print("=== 2. ParallelStage fork/join ===")
    stage = ParallelStage(
        "compare",
        branches={
            "fast": TypedStage("fast", lambda q: f"fast:{q}"),
            "deep": TypedStage("deep", lambda q: f"deep:{q}"),
        },
        joiner=lambda outputs: f"{outputs['fast']} | {outputs['deep']}",
    )
    result = await run_pipeline([stage], "query")
    print(f"  output={result.output!r} attempts={result.attempts}")
    assert result.status == "completed"
    assert result.output == "fast:query | deep:query"


async def demo_loop() -> None:
    """Bounded reviewer loop — re-run the body until the reviewer approves or the limit is hit."""
    print("=== 3. LoopStage bounded reviewer loop ===")
    attempts = 0

    def draft(value: str) -> str:
        nonlocal attempts
        attempts += 1
        return "rough" if attempts < 3 else f"{value}: approved"

    stage = LoopStage(
        "review",
        body=TypedStage("draft", draft),
        reviewer=lambda candidate: "approved" in candidate,
        max_iterations=5,
    )
    result = await run_pipeline([stage], "report")
    print(f"  output={result.output!r} iterations={result.attempts['review']}")
    assert result.status == "completed"
    assert result.attempts["review"] == 3


async def demo_conditional() -> None:
    """Route the value to one of N sub-chains by a selector (here a dotted path off the value)."""
    print("=== 4. ConditionalStage routing ===")
    stage = ConditionalStage(
        "route",
        selector="kind",
        cases={
            "search": [TypedStage("do_search", lambda v: f"searched:{v['q']}")],
            "chat": [TypedStage("do_chat", lambda v: f"chatted:{v['q']}")],
        },
    )
    result = await run_pipeline([stage], {"kind": "search", "q": "boots"})
    print(f"  output={result.output!r}")
    assert result.status == "completed"
    assert result.output == "searched:boots"


@dataclasses.dataclass(frozen=True)
class DelayStage:
    """A custom stage kind — added without touching the engine (open/closed principle)."""

    name: str
    seconds: float = 0.0


@stage_runner(DelayStage)
async def _run_delay(stage: DelayStage, value: object, ctx: object, event_sink: object) -> StageOutcome:
    await asyncio.sleep(stage.seconds)
    return StageOutcome(value=value)


async def demo_custom_stage() -> None:
    """A user-registered stage type dispatches exactly like the built-ins."""
    print("=== 5. Custom stage kind (OCP via @stage_runner) ===")
    stages = [DelayStage("wait", seconds=0.0), TypedStage("shout", lambda v: str(v).upper())]
    result = await run_pipeline(stages, "ready")
    print(f"  output={result.output!r}")
    assert result.output == "READY"


async def demo_events() -> None:
    """Observe the engine's lifecycle events through an async event sink."""
    print("=== 6. Event observation ===")
    seen: list[str] = []

    async def sink(name: str, data: dict) -> None:
        seen.append(name)

    await run_pipeline([TypedStage("step", lambda v: v)], "x", event_sink=sink)
    print(f"  events={seen}")
    assert "stage_start" in seen and "stage_end" in seen


_YAML = """
name: compose
events: [drafting, polishing]
stages:
  - {name: draft, kind: llm, handler: draft, status_label: drafting}
  - {name: polish, kind: llm, handler: polish, status_label: polishing}
"""


async def demo_yaml_loader() -> None:
    """Declarative YAML: structure validated by a pydantic spec, names resolved against registries."""
    print("=== 7. Declarative YAML loader ===")
    registries = PipelineRegistries(
        handlers={"draft": lambda topic: f"draft about {topic}", "polish": lambda d: f"{d} (polished)"},
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pipeline.yaml"
        path.write_text(_YAML, encoding="utf-8")
        stages = load_pipeline_from_yaml(path, registries=registries)
        result = await run_pipeline(stages, "kpis")
    print(f"  output={result.output!r}")
    assert result.status == "completed"
    assert result.output == "draft about kpis (polished)"


async def main() -> None:
    await demo_sequential()
    await demo_parallel()
    await demo_loop()
    await demo_conditional()
    await demo_custom_stage()
    await demo_events()
    await demo_yaml_loader()
    print("\nAll typed data-flow pipeline demos passed.")


if __name__ == "__main__":
    asyncio.run(main())
