# Proposal: Temporal Durable Runtime (`temporal`)

**Status:** All phases (1–4) implemented (experimental) — see [docs/runtimes/temporal.md](../runtimes/temporal.md)
**Date:** 2026-07-03
**Related:** [Runtimes](../runtimes.md), [Runtime Registry](../runtime-registry.md), [HITL](../hitl.md), [Observability](../observability.md), [Evaluation](../evaluation.md), [Sessions](../sessions.md), [Production Safety](../production-safety.md)

## Motivation

Swarmline runtimes today execute the agent loop **in-process**: if the process dies mid-run, the run dies with it. `TaskSessionStore` gives resume *between* sessions and the `daemon` module gives 24/7 scheduling, but neither gives:

- **Durability of a single run** — an agent that is 40 minutes into a multi-tool task survives a worker deploy, an OOM, or a host failure, and continues from the exact step it was on.
- **Distributed execution** — model calls, tool calls, and subagent runs fan out across a fleet of workers instead of one process; capacity scales horizontally per task queue.
- **Enterprise-grade transparency** — every model/tool call of every run recorded as replayable event history, inspectable in a UI, exportable into the `eval` module.
- **Durable human-in-the-loop** — an approval request that stays pending for three days, across deploys, and resumes the run the moment a human responds.

This proposal adds a seventh runtime, `temporal`, built on [temporal.io](https://temporal.io) — installed as `swarmline[temporal]`, registered in `RuntimeRegistry`, implementing the same `AgentRuntime` protocol. Business code does not change; the runtime is selected by config.

Prior art validates the shape: Yandex's agent platform (ATS) runs its entire multi-tenant agent fleet as Temporal workflows where the agent loop is a workflow and every model/tool/subagent call is an activity. Temporal itself ships an OpenAI Agents SDK integration following the same split.

## Inspiration

| System | Approach |
|--------|----------|
| **Yandex ATS (Jeeves)** | One Temporal workflow per request; `RunModelActivity` / `RunToolActivity` / `RunAgentActivity` per external call; dedicated writer activity streams events to the client via an external cache; state persisted by a state-manager activity |
| **Temporal + OpenAI Agents SDK** | Official integration: agent loop inside workflow, model invocations as activities |
| **LangGraph Platform** | Checkpoint-based durability (per-superstep), managed platform |
| **Swarmline (current)** | In-process loop; `CheckpointFn` hook in `run_react`, `TaskSessionStore` resume, `retry.py` backoff — durability primitives exist but are not composed into a durable runtime |

## Goals

1. `TemporalAgentRuntime` implements `AgentRuntime` — drop-in via `RuntimeRegistry.register("temporal", ...)` and the `swarmline.runtimes` entry point.
2. A single agent run survives worker crashes, deploys, and restarts; it resumes from the last completed step (not from turn 0).
3. Model calls, tool calls, and subagent runs execute as Temporal activities — independently retried, timed out, heartbeated, and routable to dedicated task queues (e.g. GPU-adjacent workers, sandbox hosts).
4. Streaming (`AsyncIterator[RuntimeEvent]`) is preserved end-to-end.
5. HITL approvals become durable: pending approval = workflow waiting on a signal, with optional expiry timer.
6. Event history is exportable into `eval` (`EvalRunner`) as a run trace.
7. Zero impact on the core: no Temporal import outside `runtime/temporal/`; the 3-line quick start stays zero-infra.

## Non-Goals

- Not the default runtime. `thin` remains the default; `temporal` is opt-in for deployments that already accept the operational cost of a Temporal cluster (self-hosted or Temporal Cloud).
- Not a rewrite of `thin`. The Temporal loop **reuses** thin's pure components (`prompts.py`, `parsers.py`, `schemas.py`, `ToolExecutor`) but keeps its own loop, because workflow code has determinism constraints thin's loop does not satisfy.
- Not a replacement for `daemon`/`serve`. Temporal cron/schedules become an *option* for routines when this runtime is active, not a migration.
- No multi-tenancy layer in v1 (namespace-per-tenant is a deployment concern, documented but not coded).

## Design

### High-level architecture

```text
┌───────────────────────────────┐
│ Client process (your app)     │
│  Agent.query()                │
│   └─ TemporalAgentRuntime     │  implements AgentRuntime
│       ├─ start workflow ──────┼───────────────┐
│       └─ subscribe run:<id> ◄─┼───┐           │
└───────────────────────────────┘   │           ▼
                                    │   ┌───────────────────┐
        EventBus (Redis/NATS)       │   │ Temporal Server    │
        channel per run_id ─────────┘   │ (or Temporal Cloud)│
                ▲                       └─────────┬─────────┘
                │ publish RuntimeEvent            │ dispatch
┌───────────────┴───────────────────────────────────────────┐
│ Worker fleet (`swarmline temporal-worker`)                 │
│  AgentLoopWorkflow          (deterministic loop)           │
│  ├─ llm_call activity       (LLM provider IO, retries)     │
│  ├─ tool_call activity      (ToolExecutor, sandbox)        │
│  ├─ subagent activity       (child AgentLoopWorkflow)      │
│  ├─ emit_events activity    (publish to EventBus)          │
│  └─ load/persist_state acts (MessageStore refs)            │
└────────────────────────────────────────────────────────────┘
```

`TemporalAgentRuntime.run()` is a thin client facade: it starts (or attaches to) a workflow, then yields `RuntimeEvent`s read from an external stream channel until a terminal event arrives. All real work happens on workers.

### Workflow / activity split

The determinism rule of Temporal (no IO, no wall clock, no randomness in workflow code) forces the same split ATS uses:

| Concern | Where | Swarmline code reused |
|---------|-------|------------------------|
| Loop control: iterations, tool budget, envelope decisions | `AgentLoopWorkflow` | loop logic modeled on `run_react` (`runtime/thin/react_strategy.py`), rewritten deterministic |
| Prompt assembly | workflow (pure) | `runtime/thin/prompts.py` |
| Envelope / tool-call parsing | workflow (pure) | `runtime/thin/parsers.py` |
| LLM invocation | `llm_call` activity | `runtime/thin/llm_client.py` providers |
| Tool execution | `tool_call` activity | `runtime/thin/executor.py` (`ToolExecutor`) |
| Subagent run | child workflow | `orchestration/` subagent specs |
| Event streaming | `emit_events` activity | `observability.event_bus` (Redis/NATS) |
| History persistence | `load_state` / `persist_state` activities | `MessageStore` providers (Postgres/SQLite) |

Retry/backoff moves out of `retry.py` into activity `RetryPolicy` — `ExponentialBackoff` and `ModelFallbackChain` semantics map onto per-activity retry policies plus an explicit fallback branch in the workflow (deterministic decision, IO in the activity).

### Streaming relay

This is the largest piece of net-new work. Temporal workflows cannot stream to a caller, so:

1. Every activity that produces user-visible output publishes `RuntimeEvent`s (serialized) to an EventBus channel keyed by `run_id`. For token-level streaming, the `llm_call` activity publishes text deltas directly as it consumes the provider stream — deltas do **not** transit the workflow.
2. The client facade subscribes to `run:<run_id>` before starting the workflow and yields events as they arrive; a terminal `result`/`error` event closes the iterator.
3. **Buffered fallback** (no Redis/NATS available): the facade polls a workflow query for accumulated events, or simply awaits the workflow result and replays events at completion. Degraded UX, zero extra infra — mirrors thin's existing `buffered_postprocessing` path.
4. Delivery is at-least-once; events carry a monotonic sequence number per run so the facade can deduplicate after activity retries.

### State & payload strategy

Temporal limits payloads (~2 MB) and history size (~50 MB). Conversations with tool output exceed both quickly:

- Message history lives in a worker-side `HistoryStore` (`MessageStoreHistoryAdapter` over Postgres/SQLite `MessageStore`s); the workflow carries **revision numbers**, materialized inside the LLM activity at call time. Deltas append through an idempotent history activity (expected-revision guard makes retries safe).
- `compaction.py` runs at history materialization inside the LLM activity when the referenced history crosses a token threshold (tiers 1+3; the store is never rewritten).
- Long sessions use `continue_as_new` at an iteration boundary, carrying only resume state (revision, counters, accumulated outputs) — the ATS pattern (their cap: 3 continues; ours configurable via `continue_as_new_after_iterations`).
- Tool outputs above a size threshold stored via `MemoryBankProvider`/artifact storage and passed by reference remain future work.

### Tool execution & worker affinity

Local tools run wherever the `tool_call` activity lands. Two consequences:

- **Stateless tools** (web, knowledge search, memory) work on any worker as long as workers share the same storage config — worker bootstrap reuses `SwarmlineStack.create()` wiring.
- **Stateful tools** (sandbox containers, filesystem workspaces) need affinity: the workflow records the sandbox/workspace handle in its state (the ATS `context_state` pattern) and routes subsequent `tool_call` activities to a host-specific task queue. v1 ships the task-queue routing hook; E2B/Docker handle serialization is per-provider work.

### HITL: durable approvals

The killer synergy. `ApprovalGate.check()` today awaits an in-process callback. Under Temporal:

- The `tool_call` activity consults the approval policy (`hitl/policies.py`); if approval is required it returns a `needs_approval` marker instead of executing.
- The workflow emits an `approval_request` event (surfaced to the client / `serve` API / any UI) and blocks on `workflow.wait_condition` for an **approval signal**, with an optional durable expiry timer (auto-deny after N hours).
- Approval arrives via `WorkflowHandle.signal()` — exposed as `TemporalApprovalClient` (`approve`/`deny`/`pending` by `run_id` + `correlation_id`); pending requests are also inspectable via a workflow query.
- The pending approval survives deploys, restarts, and weekends. This capability does not exist in any current runtime (`supports_hitl` today means in-process gating only).

### Cancellation & resume

- `AgentRuntime.cancel()` → `WorkflowHandle.cancel()`; activities observe cancellation via heartbeats; `tool_call` propagates it to `ToolExecutor` cooperative cancellation (`runtime/cancellation.py`).
- Resume is free: reattaching to a running workflow by `run_id` re-subscribes the event channel. `supports_resume=True`, `supports_interrupt=True` in `RuntimeCapabilities`.

### Capabilities entry

```python
RuntimeCapabilities(
    runtime_name="temporal",
    tier=RuntimeTier.FULL,
    supports_resume=True,          # reattach to running workflow
    supports_interrupt=True,       # workflow cancel
    supports_hitl=True,            # durable signals
    supports_provider_override=True,
    supports_mcp=True,             # via thin's MCP client inside activities
)
```

### Configuration & entry points

```python
config = AgentConfig(
    runtime="temporal",
    runtime_options=TemporalRuntimeOptions(
        address="temporal.internal:7233",   # or Temporal Cloud endpoint
        namespace="agents-prod",
        task_queue="swarmline-agents",
        tls=...,                            # mTLS / API key for Cloud
        stream_backend="redis",             # "redis" | "nats" | "buffered"
        history_store="postgres",           # reference-based history backing
        continue_as_new_after_turns=50,
    ),
)
```

Worker side:

```bash
pip install swarmline[temporal]
swarmline temporal-worker --task-queue swarmline-agents --config worker.yaml
```

The worker CLI bootstraps a `SwarmlineStack`, registers `AgentLoopWorkflow` + activities, and runs the Temporal worker loop — same operational shape as `swarmline serve` and `swarmline-daemon`.

## Observability & Eval

- **Event history = audit log.** Every activity input/output is recorded and replayable; Temporal Web UI gives per-run drill-down with zero Swarmline code.
- **Trace export**: a `TemporalRunExporter` converts workflow history into the `eval` module's run-trace format, so `EvalRunner`/scorers work on production runs, not just synthetic ones. This directly serves the "eval + debug transparency" production requirement.
- **OTel**: Temporal's Python SDK supports OpenTelemetry interceptors; spans join the existing `observability/otel_exporter.py` pipeline so a run shows as one trace across client → workflow → activities.
- **LLM observability platforms**: `LangfuseExporter` / `LangSmithExporter` (EventBus subscribers, already in `observability/`) work unchanged on workers — activities publish the same `llm_call_*` / `tool_call_*` events. The workflow's reference bundle carries the run/session id into every activity, so all calls of one durable run land in one Langfuse/LangSmith trace regardless of which worker executed them. Never call these SDKs from workflow code (IO breaks determinism) — activities and interceptors only.
- **Redaction**: activity payloads pass through `observability/redaction.py` via a Temporal `PayloadCodec`, so secrets never land in server-side history. This is mandatory, not optional — history is stored on the Temporal cluster.

## Module Structure

```text
src/swarmline/runtime/temporal/
  ├── __init__.py          # register("temporal", ...) + entry point
  ├── runtime.py           # TemporalAgentRuntime (client facade, AgentRuntime impl)
  ├── workflow.py          # AgentLoopWorkflow (deterministic loop)
  ├── activities.py        # llm_call, tool_call, emit_events, load/persist_state
  ├── stream.py            # event relay: publisher (worker) + subscriber (client), seq dedup
  ├── state.py             # HistoryStore port, in-memory store, MessageStore adapter
  ├── hitl.py              # TemporalApprovalClient, approval signal plumbing
  ├── client.py            # shared client connect (codec/OTel wiring) + workflow id scheme
  ├── codec.py             # redaction PayloadCodec
  ├── eval_export.py       # production run -> eval trace converters + scoring
  ├── worker.py            # worker bootstrap (SwarmlineStack wiring)
  └── options.py           # TemporalRuntimeOptions

(The `swarmline temporal-worker` command lives in `cli/_commands_temporal.py`,
alongside the other CLI commands.)
```

Dependency: `temporalio` under the `temporal` extra only. `grep temporalio src/` outside this package must return 0 matches (same isolation rule as other extras).

## Testing Strategy

- `temporalio.testing.WorkflowEnvironment` with time-skipping: loop logic, retries, continue-as-new, approval timers — all testable in-process, no server, CI-friendly.
- Replay tests: recorded histories checked against workflow code on every change (guards against non-deterministic edits — the #1 Temporal footgun).
- Activity unit tests reuse existing thin-runtime test fixtures (mock LLM, `ToolExecutor` fakes).
- One optional integration suite behind a marker (`-m temporal_server`) against `temporalite`/dev server, excluded from default CI.

## Rollout Phases

1. **Spike (validates the core risk):** `AgentLoopWorkflow` + `llm_call`/`tool_call` activities, buffered results only, in-memory history. Exit criteria: a multi-turn tool-using run survives a worker kill and completes; replay test passes.
2. **Streaming:** EventBus relay (Redis first), seq-number dedup, client facade implements full `AgentRuntime` streaming contract; runtime registered + capabilities.
3. **HITL + lifecycle:** approval signals, durable expiry timers, cancel/reattach, `swarmline temporal-worker` CLI.
4. **Scale hardening:** reference-based history via `MessageStore`, compaction activity, `continue_as_new`, redaction codec, OTel interceptors, eval trace exporter, docs (`docs/runtimes/temporal.md`).

Phases 1–2 make it usable; 3 makes it sellable; 4 makes it production-honest.

## Failure Modes

| Failure | Behavior |
|---------|----------|
| Worker crash mid-tool-call | Activity times out / heartbeat lapses → retried on another worker; workflow position preserved |
| LLM provider outage | Activity retry policy with backoff; after exhaustion, workflow takes fallback-model branch (deterministic) |
| Redis relay down | Events buffered by seq in history-adjacent store; client falls back to polling query; run itself unaffected |
| Temporal server unreachable (client) | `run()` fails fast with a typed error before any side effects — same contract as thin's connection errors |
| Poison run (non-deterministic bug) | Replay failure quarantines the run; replay test suite exists to prevent shipping these |

## Alternatives Considered

- **Durable-lite (no new infra):** compose the existing `CheckpointFn` + `TaskSessionStore` into per-turn checkpoint/resume on Postgres. Cheaper, zero new dependencies, and worth doing *anyway* for mid-tier deployments — but it yields at-turn-granularity resume without retries/timers/signals/UI, and every one of those would be reinvented incrementally. Documented as the recommended path for users who can't run Temporal.
- **LangGraph checkpointing:** couples the core to LangGraph's execution model; conflicts with the multi-runtime, protocol-first design.
- **DBOS / Restate:** lighter durable-execution engines; weaker ecosystem, no enterprise recognition, no first-class UI. Revisit if Temporal's operational weight blocks adoption.
- **Celery/RQ task queues:** distribution without durability semantics — no replay, no deterministic resume, HITL still in-process.

## Open Questions

1. **Subagents:** child workflow (durable, visible in UI, own history) vs subagent-inside-activity (simple, opaque). Leaning child workflow with a depth cap; needs a decision before phase 3.
2. **Token deltas through Redis at scale:** per-delta publish may be chatty; batch deltas per N ms in the `llm_call` activity? Measure in phase 2.
3. **MCP servers on workers:** stdio MCP servers are per-process; do workers own long-lived MCP sessions per task queue, or spawn per activity? Interacts with sandbox affinity.
4. **Routines convergence:** when `temporal` is active, should `daemon` routines map onto Temporal Schedules automatically, or stay separate? Proposal: separate in v1, convergence RFC later.
5. **Eval trace format:** extend the existing eval run schema or add a Temporal-specific adapter? Depends on `eval` module stabilization timeline.
