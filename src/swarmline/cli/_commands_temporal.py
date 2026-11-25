"""Temporal worker CLI command (``swarmline temporal-worker``).

Bootstraps a worker for the Temporal durable runtime: connects to the
Temporal server, registers ``AgentLoopWorkflow`` + activities, and serves a
task queue until interrupted. The worker owns the non-deterministic side of
the agent loop — LLM credentials (resolved from the environment, as in the
thin runtime), local tools, the optional streaming relay, and the optional
approval policy. Requires ``swarmline[temporal]``.
"""

from __future__ import annotations

import importlib
from typing import Any

import click


def _load_object(path: str) -> Any:
    """Import ``package.module:attribute`` (e.g. a dict of local tools)."""
    module_name, sep, attr = path.partition(":")
    if not sep or not module_name or not attr:
        raise click.BadParameter(f"expected 'package.module:attribute', got {path!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise click.BadParameter(
            f"cannot import module {module_name!r}: {exc}"
        ) from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise click.BadParameter(
            f"module {module_name!r} has no attribute {attr!r}"
        ) from exc


def _build_event_bus(url: str) -> Any:
    """Streaming-relay bus from a URL (``redis://`` or ``nats://``)."""
    if url.startswith(("redis://", "rediss://")):
        from swarmline.observability.event_bus_redis import RedisEventBus

        return RedisEventBus(redis_url=url)
    if url.startswith(("nats://", "tls://")):
        from swarmline.observability.event_bus_nats import NatsEventBus

        return NatsEventBus(nats_url=url)
    raise click.BadParameter(
        f"unsupported event bus URL {url!r} (expected redis:// or nats://)"
    )


@click.command(name="temporal-worker")
@click.option("--address", default="localhost:7233", show_default=True)
@click.option("--namespace", default="default", show_default=True)
@click.option("--task-queue", default="swarmline-agents", show_default=True)
@click.option("--tls", is_flag=True, help="Enable TLS (implied by --api-key-env).")
@click.option(
    "--api-key-env",
    default=None,
    help="Name of the env var holding a Temporal Cloud API key.",
)
@click.option("--model", default=None, help="Default model for LLM activities.")
@click.option(
    "--tools",
    "tools_path",
    default=None,
    help="Import path 'pkg.module:attr' of a dict[str, callable] of local tools.",
)
@click.option(
    "--event-bus",
    "event_bus_url",
    default=None,
    help="redis:// or nats:// URL for the live-streaming relay (optional).",
)
@click.option(
    "--require-approval",
    "approval_tools",
    multiple=True,
    help="Tool name that needs human approval before executing (repeatable).",
)
@click.option(
    "--history-store",
    "history_store_path",
    default=None,
    help=(
        "Import path 'pkg.module:attr' of a HistoryStore instance backing "
        "reference-based history (must be shared by all workers on the queue)."
    ),
)
@click.option(
    "--compaction-threshold",
    "compaction_threshold",
    type=int,
    default=0,
    help=(
        "Token threshold for compacting referenced history at LLM-step "
        "materialization (0 = compaction off)."
    ),
)
@click.pass_context
def temporal_worker(
    ctx: click.Context,  # noqa: ARG001 — click contract
    address: str,
    namespace: str,
    task_queue: str,
    tls: bool,
    api_key_env: str | None,
    model: str | None,
    tools_path: str | None,
    event_bus_url: str | None,
    approval_tools: tuple[str, ...],
    history_store_path: str | None,
    compaction_threshold: int,
) -> None:
    """Run a Temporal worker serving swarmline agent workflows."""
    import os

    from swarmline.cli._app import _run_async
    from swarmline.runtime.temporal.options import TemporalRuntimeOptions
    from swarmline.runtime.types import RuntimeConfig

    api_key = os.environ.get(api_key_env) if api_key_env else None
    if api_key_env and not api_key:
        raise click.BadParameter(f"environment variable {api_key_env!r} is not set")

    options = TemporalRuntimeOptions(
        address=address,
        namespace=namespace,
        task_queue=task_queue,
        tls=tls,
        api_key=api_key,
    )

    local_tools = _load_object(tools_path) if tools_path else None
    if local_tools is not None and not isinstance(local_tools, dict):
        raise click.BadParameter(
            f"--tools must resolve to a dict, got {type(local_tools).__name__}"
        )

    base_config = RuntimeConfig(runtime_name="temporal", model=model) if model else None

    approval_policy = None
    if approval_tools:
        from swarmline.hitl.policies import ToolApprovalPolicy

        approval_policy = ToolApprovalPolicy(tools=frozenset(approval_tools))

    history_store = _load_object(history_store_path) if history_store_path else None

    compaction_config = None
    if compaction_threshold > 0:
        from swarmline.compaction import CompactionConfig

        compaction_config = CompactionConfig(threshold_tokens=compaction_threshold)

    async def _serve() -> None:
        from swarmline.runtime.temporal.worker import run_worker

        bus = _build_event_bus(event_bus_url) if event_bus_url else None
        if bus is not None:
            await bus.connect()
        try:
            await run_worker(
                options,
                local_tools=local_tools,
                base_config=base_config,
                event_bus=bus,
                approval_policy=approval_policy,
                history_store=history_store,
                compaction_config=compaction_config,
            )
        finally:
            if bus is not None:
                await bus.close()

    click.echo(
        f"swarmline temporal-worker: {address} ns={namespace} queue={task_queue}",
        err=True,
    )
    _run_async(_serve())
