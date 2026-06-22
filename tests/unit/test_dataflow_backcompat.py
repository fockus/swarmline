"""Back-compat contract regressions for the TypedPipeline facade (audit-driven, M2).

The 3 legacy contract test files (test_typed_pipeline / test_workflow_chain_extensions /
test_workflow_adapters) assert only status/output/failed_stage on failure paths, which let several
observable behaviours drift when ``TypedPipeline`` was folded onto the registry engine. These tests
pin the FULL legacy observable surface — ``result.attempts`` and ``result.errors`` on failed stages,
the ``ok`` flag on ``pipeline_stage_end``, the ``fallback_selected`` event, the "no prior valid →
failed (not fallback)" boundary, and arity handling of ``*args`` / signature-less builtins — so the
"behaviour-preserving" claim is actually covered going forward.
"""

from __future__ import annotations

from typing import Any

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.pipeline import (
    FallbackPolicy,
    TypedPipeline,
    TypedStage,
)


def _raise(message: str):
    def handler(_value: Any) -> Any:
        raise RuntimeError(message)

    return handler


async def test_failed_stage_records_attempts_and_verbatim_error() -> None:
    """A failed leaf stage stays in result.attempts and its error is verbatim (no '{stage}:' prefix)."""
    pipeline = TypedPipeline(stages=[TypedStage("gen", _raise("boom"))])

    result = await pipeline.run("x")

    assert result.status == "failed"
    assert result.failed_stage == "gen"
    assert result.attempts == {"gen": 1}
    assert result.errors == ("boom",)


async def test_exhausted_retry_records_attempt_count() -> None:
    """A pure stage that fails every attempt records max_attempts in result.attempts."""
    pipeline = TypedPipeline(stages=[TypedStage("gen", _raise("nope"), max_attempts=3)])

    result = await pipeline.run("x")

    assert result.status == "failed"
    assert result.attempts == {"gen": 3}
    assert result.errors == ("nope",)


async def test_validator_failure_keeps_legacy_message_and_attempts() -> None:
    """A validator rejection reports the legacy message verbatim and records the attempt."""
    pipeline = TypedPipeline(
        stages=[TypedStage("validate", lambda v: v, validator=lambda _out: False)]
    )

    result = await pipeline.run("x")

    assert result.status == "failed"
    assert result.attempts == {"validate": 1}
    assert result.errors == ("stage 'validate' validator returned False",)


async def test_pipeline_stage_end_carries_ok_true_on_success() -> None:
    """The legacy pipeline_stage_end payload keeps its ``ok: True`` flag on success."""
    bus = InMemoryEventBus()
    seen: list[dict[str, Any]] = []
    bus.subscribe("pipeline_stage_end", lambda data: seen.append(data))

    pipeline = TypedPipeline(stages=[TypedStage("draft", lambda v: v)], event_bus=bus)
    await pipeline.run("x")

    assert seen == [{"stage": "draft", "ok": True}]


async def test_pipeline_stage_end_carries_ok_false_on_failure() -> None:
    """On failure the legacy pipeline_stage_end payload carries ``ok: False`` and the error."""
    bus = InMemoryEventBus()
    seen: list[dict[str, Any]] = []
    bus.subscribe("pipeline_stage_end", lambda data: seen.append(data))

    pipeline = TypedPipeline(stages=[TypedStage("boom", _raise("boom"))], event_bus=bus)
    await pipeline.run("x")

    assert seen == [{"stage": "boom", "ok": False, "error": "boom"}]


async def test_fallback_selected_event_emitted_on_last_valid_degrade() -> None:
    """A last_valid degrade re-emits the legacy ``fallback_selected`` event."""
    bus = InMemoryEventBus()
    seen: list[tuple[str, dict[str, Any]]] = []
    bus.subscribe(
        "fallback_selected", lambda data: seen.append(("fallback_selected", data))
    )

    pipeline = TypedPipeline(
        stages=[
            TypedStage("ok", lambda v: f"{v}-ok"),
            TypedStage("bad", _raise("boom")),
        ],
        fallback_policy=FallbackPolicy(mode="last_valid"),
        event_bus=bus,
    )
    result = await pipeline.run("x")

    assert result.status == "fallback"
    assert seen == [("fallback_selected", {"stage": "bad", "mode": "last_valid"})]


async def test_first_stage_failure_with_last_valid_is_failed_not_fallback() -> None:
    """With last_valid but NO prior successful stage, a failure is 'failed' (nothing to fall back to)."""
    bus = InMemoryEventBus()
    seen: list[str] = []
    bus.subscribe("fallback_selected", lambda _data: seen.append("fallback_selected"))

    pipeline = TypedPipeline(
        stages=[TypedStage("bad", _raise("boom"))],
        fallback_policy=FallbackPolicy(mode="last_valid"),
        event_bus=bus,
    )
    result = await pipeline.run("x")

    assert result.status == "failed"
    assert result.output is None
    assert seen == []  # no fallback_selected when there is no prior valid value


async def test_star_args_handler_is_called_with_two_args() -> None:
    """A ``*args`` handler keeps the legacy 2-arg (value, context) call shape."""

    def handler(*args: Any) -> str:
        value, context = args
        return f"{value}:{type(context).__name__}"

    pipeline = TypedPipeline(stages=[TypedStage("star", handler)])
    result = await pipeline.run("v")

    assert result.status == "completed"
    assert result.output == "v:PipelineContext"


async def test_signatureless_builtin_handler_works() -> None:
    """A signature-less builtin (e.g. ``str``) is called as a 1-arg handler, not crashed."""
    pipeline = TypedPipeline(stages=[TypedStage("strify", str)])

    result = await pipeline.run(123)

    assert result.status == "completed"
    assert result.output == "123"
