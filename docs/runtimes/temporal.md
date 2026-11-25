# Temporal Runtime (experimental)

Durable, distributed agent execution on [temporal.io](https://temporal.io). The agent loop runs as a deterministic Temporal **workflow**; every LLM call and tool call executes as a Temporal **activity** on a worker fleet. A single agent run survives worker crashes, deploys, and restarts — it resumes from the last completed step, not from turn 0.

Design doc: [Temporal Durable Runtime proposal](../proposals/temporal-runtime.md). Status: all four proposal phases implemented — durable loop, streaming relay, durable HITL + reattach + worker CLI, and scale hardening (reference-based history, continue-as-new, compaction, redaction codec, OTel interceptors, eval trace export).

## When to use

- Long-running, expensive agent runs where "the deploy killed my 40-minute run" is unacceptable
- Horizontal scaling of model/tool execution across a worker fleet (per task queue)
- Enterprise transparency: every step of every run recorded as replayable event history, visible in Temporal Web UI
- You already operate a Temporal cluster (self-hosted or Temporal Cloud) — this runtime does not make sense without one

For everything else, `thin` remains the zero-infrastructure default.

## Architecture

```text
Client process                     Temporal Server            Worker fleet
TemporalAgentRuntime.run() ──────▶ AgentLoopWorkflow ────────▶ swarmline_llm_step   (LLM IO, retries)
  └─ yields RuntimeEvents ◀─┐        (deterministic loop)  └─▶ swarmline_tool_step  (ToolExecutor)
                            └── EventBus relay (Redis/NATS) ◀── activities publish events
```

The client holds **no tools and no LLM credentials** — those live on workers. Retries, timeouts, and recovery are Temporal activity policies, not application code.

## Install

```bash
pip install swarmline[temporal]
```

## Client side

```python
from swarmline.runtime.temporal import TemporalAgentRuntime, TemporalRuntimeOptions

runtime = TemporalAgentRuntime(
    config,  # RuntimeConfig: model, max_iterations, max_tool_calls
    options=TemporalRuntimeOptions(
        address="temporal.internal:7233",
        namespace="agents-prod",
        task_queue="swarmline-agents",
    ),
)

async for event in runtime.run(
    messages=messages, system_prompt="...", active_tools=tools
):
    ...
```

Or via the registry, like any other runtime:

```python
config = RuntimeConfig(
    runtime_name="temporal",
    model="claude-sonnet-5",
    extra={"temporal": {"address": "temporal.internal:7233", "task_queue": "agents"}},
)
```

Note: `local_tools` / `mcp_servers` on the client are rejected with an error — configure them on the worker.

## Worker side

```python
from swarmline.runtime.temporal import TemporalRuntimeOptions
from swarmline.runtime.temporal.worker import run_worker
from swarmline.runtime.types import RuntimeConfig

await run_worker(
    TemporalRuntimeOptions(address="temporal.internal:7233", task_queue="agents"),
    local_tools={"search": search_fn, "calc": calc_fn},
    mcp_servers={...},                                # optional MCP servers
    base_config=RuntimeConfig(                        # LLM credentials/provider
        runtime_name="temporal", api_key="...", base_url=None
    ),
)
```

The worker reuses the thin runtime's `ToolExecutor` (hooks + policy) and provider-resolving LLM client, so the model contract is identical to `runtime="thin"` (JSON-in-text ReAct envelope). The per-run model comes from the client's config; credentials come from the worker's `base_config`.

### Worker CLI

The same bootstrap as a command (`pip install swarmline[temporal,cli]`):

```bash
swarmline temporal-worker \
    --address temporal.internal:7233 --namespace agents-prod --task-queue agents \
    --model claude-sonnet-5 \
    --tools myapp.tools:LOCAL_TOOLS \
    --event-bus redis://redis.internal:6379/0 \
    --require-approval execute_code --require-approval send_email
```

`--tools` imports a `dict[str, callable]` by `module:attribute` path; `--event-bus` enables the live-streaming relay (`redis://` or `nats://`); `--require-approval` (repeatable) builds a `ToolApprovalPolicy` — those tools pause on durable human approval (below). `--history-store module:attr` plugs in a shared `HistoryStore` for reference-based history, and `--compaction-threshold <tokens>` enables compaction at materialization. For Temporal Cloud pass `--api-key-env TEMPORAL_API_KEY`. LLM provider credentials come from the environment, same as the thin runtime.

## Durable HITL (approval signals)

When the worker runs with an approval policy, a gated tool call does **not** execute: the activity returns a `needs_approval` marker, the client (in streaming mode) receives an `approval_requested` event, and the workflow parks on a Temporal signal — durably. The pending approval survives worker deploys, restarts, and weekends; an optional expiry timer (`approval_timeout_seconds`, default 24h) auto-denies stale requests.

Any process holding a Temporal client resolves it by `run_id` + `correlation_id` (both are in the `approval_requested` event and in the pending query):

```python
from swarmline.runtime.temporal import TemporalApprovalClient

approvals = TemporalApprovalClient(options=options)

await approvals.pending(run_id)               # [{"correlation_id": ..., "name": ..., "args": ...}]
await approvals.approve(run_id, correlation_id, reason="looks safe")
await approvals.approve(run_id, correlation_id, modifications={"path": "/tmp/safe"})  # edit args
await approvals.deny(run_id, correlation_id, reason="too risky")
```

Outcomes mirror the rest of the failure model: an approved call executes normally (with `modifications` merged over the tool args); a denial or expiry becomes a **failed tool result** — the model sees the reason and reacts, the run never dies. Both paths emit an `approval_resolved` event.

In buffered mode there is no live `approval_requested` event — poll `approvals.pending(run_id)` (a Temporal query) or watch the run in Temporal Web UI.

## Reattach to a running run

`attach(run_id)` re-joins a run started elsewhere (or before a client crash) and yields events exactly like `run()` — live from the relay in streaming mode, or the buffered replay + final once the workflow completes:

```python
async for event in runtime.attach(run_id):
    ...
```

Durability lives in the workflow, so this is safe from any process at any time; the workflow id is `{workflow_id_prefix}{run_id}`.

## Long runs: reference-based history + continue-as-new

Temporal caps payloads (~2 MB) and workflow history (~50 MB). With the default inline mode, every LLM step carries the whole growing conversation, so long tool-heavy runs eventually hit those limits. Reference mode moves the conversation into a **worker-side history store**; workflow payloads carry only revision numbers:

```python
# client
options = TemporalRuntimeOptions(
    use_reference_history=True,
    continue_as_new_after_iterations=25,   # roll workflow history per 25 iterations
)

# worker — the store MUST be shared by every worker on the task queue
from swarmline.runtime.temporal.state import MessageStoreHistoryAdapter

await run_worker(
    options,
    local_tools={...},
    history_store=MessageStoreHistoryAdapter(postgres_message_store),
)
```

How it works:

- The workflow seeds the store once, then appends per-turn deltas through an idempotent `history_append` activity (retries can't duplicate messages — appends carry an expected revision).
- LLM activities materialize the conversation from the store at call time. With `compaction_config` (worker-side, `swarmline.compaction.CompactionConfig`), over-threshold histories are compacted at materialization — old tool pairs collapse, oldest messages drop; the store itself is never rewritten.
- At the `continue_as_new_after_iterations` boundary the workflow rolls over via continue-as-new: fresh workflow history, same run id (reattach, signals, and queries keep working), state carried in a payload of bounded size. `max_iterations` / `max_tool_calls` stay global across segments.

`InMemoryHistoryStore` exists for tests and single-worker development; production needs `MessageStoreHistoryAdapter` over a shared `MessageStore` (Postgres/SQLite) or your own `HistoryStore` implementation (two methods: `append`, `load`).

## Payload redaction (on by default)

Every workflow input, activity input/output, and result lands in Temporal's **server-side** history. The runtime therefore ships a redaction `PayloadCodec` (`redact_payloads=True` by default): `observability.redaction.redact_secrets` runs over every JSON payload at encode time, so Bearer tokens, `sk-*` keys, URL userinfo, and `KEY=value` secrets leaking through tool results or error messages never reach the server in plaintext. Decode is a passthrough — clients/workers connected without the codec still read redacted payloads, so mixed deployments degrade safely. Disable with `redact_payloads=False` if your patterns collide with legitimate content.

## OpenTelemetry

Set `otel_interceptor=True` (requires `swarmline[otel]` + `opentelemetry-sdk` on client and workers) to attach temporalio's `TracingInterceptor` to the connection: client → workflow → activity spans join one trace, alongside the existing `OTelExporter` events pipeline.

## Eval on production runs

Completed workflows are scoreable with the `eval` module — no re-execution:

```python
from swarmline.runtime.temporal.eval_export import (
    fetch_run_result, run_to_eval_result, score_run_results,
)

result = await fetch_run_result(client, options, run_id)   # from Temporal history
trace = run_to_eval_result(run_id, original_question, result)
report = await score_run_results([trace], scorers=[correctness_scorer])
```

Tool-call counts, iteration counts, and event types ride along in `case.context` for scorers that inspect behavior, not just the final text.

## Streaming vs buffered

| Mode | Setup | Behavior |
|------|-------|----------|
| **Buffered** (default) | nothing extra | `run()` awaits the workflow result, then replays events + final. Simple, no extra infra. |
| **Streaming** | `stream_events=True` + shared EventBus | Activities publish `RuntimeEvent`s to a channel keyed by run id; the client yields them live. Requires an EventBus reachable from both workers and the client (Redis/NATS backends in `swarmline.observability`). |

```python
from swarmline.observability.event_bus_redis import RedisEventBus

bus = RedisEventBus(url="redis://...")
runtime = TemporalAgentRuntime(
    config,
    options=TemporalRuntimeOptions(stream_events=True, task_queue="agents"),
    event_bus=bus,   # client subscriber side
)
# worker: run_worker(options, ..., event_bus=RedisEventBus(url="redis://..."))
```

Delivery is at-least-once (activity retries republish); events carry deterministic ids and the client deduplicates.

## Failure semantics

| Failure | Behavior |
|---------|----------|
| Worker dies mid-run | Activity retried on another worker; loop position preserved by the workflow |
| Transient LLM provider error | Activity retry policy (`llm_retry_attempts`, default 3) |
| Tool activity exhausts retries | Surfaces to the model as a failed tool result — the run continues |
| Unparseable model output | `bad_model_output` error event (after text fallback) |
| `max_iterations` / `max_tool_calls` | `loop_limit` / `budget_exceeded` error events |
| `runtime.cancel()` | Workflow cancellation → `cancelled` error event |
| Approval denied / expired | Failed tool result with the reason — the model reacts, the run continues |

## Options reference

| Option | Default | Description |
|--------|---------|-------------|
| `address` | `localhost:7233` | Temporal server / Cloud endpoint |
| `namespace` | `default` | Temporal namespace |
| `task_queue` | `swarmline-agents` | Queue workers listen on |
| `tls` / `api_key` | off | Temporal Cloud auth (api_key implies TLS) |
| `stream_events` | `False` | Live event relay (needs `event_bus`) |
| `llm_timeout_seconds` | 300 | LLM activity start-to-close timeout |
| `tool_timeout_seconds` | 120 | Tool activity start-to-close timeout |
| `llm_retry_attempts` | 3 | Temporal retries for LLM activity |
| `tool_retry_attempts` | 1 | Temporal retries for tool activity (tools may be non-idempotent) |
| `approval_timeout_seconds` | 86400 (24h) | Durable expiry for HITL approvals; `0` waits indefinitely |
| `use_reference_history` | `False` | Conversation lives in the workers' shared history store; payloads carry revisions |
| `continue_as_new_after_iterations` | 0 (off) | Workflow rollover per N iterations; requires reference history |
| `redact_payloads` | `True` | Secret-pattern redaction before payloads reach server-side history |
| `otel_interceptor` | `False` | temporalio `TracingInterceptor` on the connection (needs OTel packages) |

## Current limitations (experimental)

- In the default inline mode, very long conversations can hit Temporal's payload/history limits — switch to `use_reference_history=True` (+ `continue_as_new_after_iterations`) for long runs.
- Multimodal `content_blocks` are not carried through payloads.
- One tool call per loop iteration (JSON-in-text envelope, same as thin's portable path); native parallel tool calling is not used.
- The `approval_resolved` event is recorded in the workflow result (buffered replay) but is not published live to the streaming relay — the subsequent tool events (approved) or the failed tool result (denied) are.
- History compaction at materialization uses tiers 1 and 3 (tool-pair collapse + oldest-drop); LLM summarization (tier 2) is not wired into the activity path.

## Observability

- Temporal Web UI shows every run: activity inputs/outputs, retries, timings — replayable.
- `LangfuseExporter` / `LangSmithExporter` / `OTelExporter` work on workers unchanged: give the worker's `AgentActivities` an event-bus-backed publisher and attach exporters to the same bus, or attach them to the bus your `base_config.event_bus` points at.
