# Architecture & Scalability Review — swarmline v1.5.0

Date: 2026-04-27
Scope: Full source tree analysis (`src/swarmline/` — 387 files, 52,980 LOC)
Reviewer: Backend Architect subagent (read-only)
Working directory: `/Users/fockus/Apps/swarmline`

---

## Executive Summary

- **Architecture health:** ✅ for layering / DIP / ISP, ⚠️ for production scalability defaults
- **Scalability ceiling estimate (out-of-box):** ~5–20 concurrent agents per process; bottleneck shifts to LLM provider rate limits and Postgres pool sizing well before CPU
- **Top 3 bottlenecks:**
  1. **Buffered streaming** in `runtime/thin/llm_client.py` — every streaming LLM response is collected into a list before being returned, eliminating the streaming benefit and creating O(response_tokens) memory per active turn
  2. **Per-request `httpx.AsyncClient`** in `runtime/thin/mcp_client.py` — no connection pooling for MCP calls; new TCP connection + TLS handshake per `tools/call`
  3. **Missing index on `messages(user_id, topic_id, created_at DESC)`** — the central message store has no shipped DDL; all `get_messages` calls degrade to seq-scan once the table grows beyond cache
- **Top 3 strengths:**
  1. Strict Clean Architecture: Domain (`protocols/`, `domain_types.py`) has zero non-stdlib imports; verified by grep
  2. ISP-perfect: 36 Protocols, all ≤5 methods (audited file by file)
  3. Lazy-import discipline: every optional dep (`anthropic`, `openai`, `google-genai`, `langchain`, `httpx-redis`, `nats`) imported inside the function that uses it; cold-start surface stays small

---

## Critical
*Must fix before claiming "production-scale" readiness.*

### C-1. Buffered streaming defeats the streaming contract
- **Where:** `src/swarmline/runtime/thin/llm_client.py` lines 64–67, 110–116, plus `react_strategy.py` line 220
- **Symptom:** `try_stream_llm_call` and `run_buffered_llm_call` both call `async for chunk in result: chunks.append(chunk)` and only return *after the entire response arrives*. The "streaming" path is buffered.
- **Impact:**
  - For a 100k-token answer at 50 t/s the consumer waits ~33 s with no token visible, while the runtime holds the full text in a Python list (~200 KB+) plus the upstream HTTP buffer.
  - When `_should_buffer_postprocessing` is True (`compaction`, `output_guardrails`, `output_type`, retry policy) we *must* buffer, but the same code path is used even when nothing downstream needs the buffered text.
  - Client agents that expect token-by-token UI updates degrade silently.
- **Fix direction:**
  - Split the API: keep `run_buffered_llm_call` for the validate/retry path; introduce `stream_llm_call` that yields `(chunk, raw_so_far)` so the strategy can emit `assistant_delta` immediately and still collect `raw` at the end.
  - Backpressure: bound the chunk queue (`asyncio.Queue(maxsize=64)`) so a slow consumer doesn't let the buffer grow unbounded if a tool blocks the loop.

### C-2. Per-request HTTP client in MCP path
- **Where:** `src/swarmline/runtime/thin/mcp_client.py` lines 125, 174, 270, 340 — all four operations (`call_tool`, `list_tools`, `list_resources`, `read_resource`) open a new `httpx.AsyncClient` inside an `async with`.
- **Impact:** ~30–80 ms TLS handshake added to every tool call. With `max_tool_calls=8` per turn that is 0.25–0.65 s wasted. For agents with 5+ MCP servers it amplifies linearly.
- **Fix direction:**
  - Hold one `httpx.AsyncClient(http2=True, timeout=self._timeout, limits=httpx.Limits(max_keepalive_connections=20))` per `McpClient` instance, opened lazily in `__aenter__` (or first call), closed in `cleanup()`.
  - Make `McpClient` an async context manager and have `ToolExecutor` own its lifecycle so the client is reused across the whole agent turn.

### C-3. No shipped Postgres DDL / index for `messages`
- **Where:** `src/swarmline/memory/postgres.py` — uses `users`, `messages`, `facts`, `topics`, `goals`, `summaries`, `phase_state`, `tool_events` tables but ships no migration. `docs/memory.md:65` literally says "Tables are managed by the application (via Alembic or raw SQL)."
- **Impact:**
  - `get_messages` does `WHERE user_id = (SELECT id FROM users WHERE external_id = :user_id) AND topic_id = :topic_id ORDER BY created_at DESC LIMIT :limit`. Without an index on `(user_id, topic_id, created_at DESC)` Postgres falls back to seq-scan once the table is past `shared_buffers`.
  - `delete_messages_before` runs the same predicate twice plus a subquery `COUNT(*)` — at 100 k messages that is ~3× the read amplification.
  - Memory module ships only some indexes (episodic, procedural). Main `messages`/`facts`/`topics` schemas are documented in prose only.
- **Fix direction:**
  - Add `migrations/postgres/` with Alembic-style numbered SQL: `001_init.sql` covering all tables + the indexes documented in code comments (`uq_facts_user_topic_key`, `uq_facts_user_global_key`, plus the missing `idx_messages_user_topic_created (user_id, topic_id, created_at DESC)`).
  - Optional helper `swarmline.memory.postgres.apply_migrations(engine)` that runs them idempotently — gated behind `swarmline[postgres]` extra so the main package stays small.

### C-4. `_get_lock` racy session-lock dictionary
- **Where:** `src/swarmline/session/manager.py:39-44` and 260-261. `_locks: dict[str, asyncio.Lock]` is read-and-write without holding any meta-lock.
- **Impact:** Two concurrent `run_turn` calls for the same `SessionKey` racing through `get_lock` may each create a fresh `asyncio.Lock` — and proceed concurrently inside the supposedly serialized critical section. Hard to hit on a single-loop event loop because it would require a context switch between `if ks not in self._locks` and `self._locks[ks] = asyncio.Lock()` (only `await` lets one happen). However, `aget` *does* await earlier, and any future change that introduces an `await` between the check and the assignment immediately breaks this. It is also broken under multi-thread access via the legacy sync bridge.
- **Fix direction:**
  - Use `self._locks.setdefault(ks, asyncio.Lock())` — single atomic dict op (CPython GIL guarantees it for a hashable key).
  - Add a regression test that registers 100 sessions in `asyncio.gather` and asserts only 100 distinct `Lock` objects exist.

---

## High Priority
*Fix in v1.5.x or v1.6.0.*

### H-1. `RuntimeConfig` is mutable and shared
- **Where:** `src/swarmline/runtime/types.py:147` — `@dataclass` (not frozen). Multiple agents in `ThinSubagentOrchestrator` share the *same* `RuntimeConfig` instance (`self._runtime_config = runtime_config`).
- **Impact:**
  - `runtime_config.input_filters.append(...)` in `agent/runtime_wiring.py:178` mutates a list that may be shared with parent orchestrator and sibling subagents.
  - Race: parent agent attaches a `CodingContextInputFilter`, sibling agent reads `input_filters` mid-mutation.
- **Fix:** make `RuntimeConfig` `@dataclass(frozen=True)`, replace `.append` with `dataclasses.replace(config, input_filters=(*old, new))`. The fields `input_filters`, `input_guardrails`, `output_guardrails`, `extra`, `native_config` are already typed as lists/dicts; convert to tuples / `Mapping`.

### H-2. Lazy `asyncio.Lock` allocation in `JsonlTelemetrySink`
- **Where:** `src/swarmline/observability/jsonl_sink.py:76,94-95` — `self._lock = None` then `if self._lock is None: self._lock = asyncio.Lock()` inside `record()`.
- **Impact:** Two concurrent `record()` calls before any have completed both see `_lock is None` and each create their own lock. With two locks, two writers append simultaneously and JSONL records can interleave at byte boundaries.
- **Fix:** initialize the lock in `__init__` (it does not bind to a loop until acquired), or guard creation with a `threading.Lock` for thread-safe lazy init.

### H-3. `RedisEventBus` subscribe/unsubscribe race
- **Where:** `src/swarmline/observability/event_bus_redis.py:79-93,95-103` — `subscribe` is sync but kicks off `asyncio.ensure_future(self._pubsub.subscribe(channel))` for the network step. `_subscribers` dict is mutated without a lock. NATS bus has the same shape (`event_bus_nats.py`).
- **Impact:** First `emit("foo")` may run before `subscribe("foo")` background task has actually told Redis to subscribe — local OK, distributed misses event. Concurrent subscribe on same event type from two coroutines may double-create. Concurrent unsubscribe + subscribe may corrupt the iterator inside `unsubscribe`.
- **Fix:**
  - Make `subscribe` async; await the Redis call inline.
  - Wrap `_subscribers` mutations in `asyncio.Lock`.
  - On `subscribe` while `_pubsub` is None, queue the channel and apply at `connect()`.

### H-4. No Prometheus metrics export
- **Where:** `observability/` — only `structlog` + OTel tracing (`otel_exporter.py`). No counters, no histograms.
- **Impact:** Operators cannot see `requests_total`, `tool_call_duration_seconds`, `llm_input_tokens_total`, `circuit_breaker_state` without writing custom subscribers.
- **Fix:** Add `observability/metrics.py` with a thin `Metrics` Protocol (≤5 methods: `counter`, `histogram`, `gauge_set`, `gauge_inc`, `gauge_dec`) and a `PrometheusMetricsExporter` adapter (optional `swarmline[prometheus]` extra).

### H-5. Adapter cache is module-global and unbounded
- **Where:** `src/swarmline/runtime/thin/llm_providers.py:550-558` — `_adapter_cache: dict[tuple[...], LlmAdapter] = {}` at module scope.
- **Impact:**
  - In a long-running process with many `(model, base_url)` combinations the cache grows without eviction.
  - Test isolation: `_adapter_cache` survives between test cases unless explicitly reset.
  - Each adapter holds a live `httpx`/`anthropic.AsyncAnthropic` client: leaking one keeps a TCP pool open.
- **Fix:** wrap in a small bounded LRU (functools.lru_cache won't work because adapters need cleanup). Add `clear_adapter_cache()` for tests; close clients on eviction.

### H-6. Subagent registry never reaps completed tasks
- **Where:** `src/swarmline/orchestration/thin_subagent.py:83-86` — `_tasks`, `_specs`, `_results`, `_output_buffers` are dicts that grow forever; only `_worktree_handles.pop` is called in `_run_agent`'s `finally`.
- **Impact:** Long-running parent (e.g. server-mode agent) accumulates results from every spawned subagent. With 1k subagents/day at 10 KB output each that is 10 MB/day of leak.
- **Fix:** add `cleanup_completed(retain_seconds=3600)` and call it from `ThinRuntime.cleanup()`. Optionally surface a "result already collected" semantics so callers can `await wait(agent_id)` and free memory.

### H-7. Sequential tool execution in JSON-in-text path
- **Where:** `src/swarmline/runtime/thin/react_strategy.py:309` — `result = await executor.execute(tc.name, tc.args)` is single-call per iteration. The native-tools branch (line 106) already does `asyncio.gather` for >1 tool.
- **Impact:** Models that emit multiple tool calls in a single response (Anthropic batched, OpenAI parallel_tool_calls) lose parallelism in the legacy path. With `max_tool_calls=8` this is up to 7× slower than necessary.
- **Fix:** when `parse_envelope` returns a list of tool calls (it currently picks the first), execute them with `asyncio.gather` like the native path. Need a small parser change.

### H-8. No prompt-caching for Anthropic
- **Where:** `runtime/thin/llm_providers.py:131-263` (`AnthropicAdapter`) — `system_prompt` is always a plain string; no `cache_control` block.
- **Impact:** For agents with large stable system prompts (skill catalogs, role definitions) every call re-bills the system prompt at full rate. Anthropic prompt caching gives 90% discount + ~85% latency reduction on cached prefixes. At 5 turns/session with a 2 k-token system prompt, missing caching = ~$0.0009/session of unnecessary spend (1.5× the token cost) plus 200 ms+ latency.
- **Fix:** detect long-stable prefixes (system + first N user messages are identical across turns) and emit them as `[{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}]` blocks. Behind a config flag `RuntimeConfig.use_prompt_caching = True`.

### H-9. `Agent._runtime` is set-once but never reused
- **Where:** `src/swarmline/agent/agent.py:46-52, 220-222` — `self._runtime: Any = None`. `cleanup` checks it, but no code path *assigns* it. Every `query` builds a fresh runtime via `_execute_stream → run_portable_runtime`.
- **Impact:** Every `agent.query()` re-instantiates `ThinRuntime`, re-builds `ToolExecutor`, re-resolves provider, re-allocates merged `local_tools` dict. For a chat-bot doing 100 turns/min this is 10–50 ms wasted per turn on object construction.
- **Fix:** cache the runtime per `AgentConfig` hash. Or expose `Agent.warm()` that creates the runtime eagerly and keeps it for the lifetime of the agent. Or document that callers should reuse `Agent` instance + verify the runtime path actually reuses heavy state.

### H-10. Manual memory provider doesn't expose bulk APIs
- **Where:** `protocols/memory.py` — `MessageStore` has no `get_messages_bulk(user_id, topic_ids: list[str], limit_per: int)` method.
- **Impact:** Multi-topic agents (e.g. summarizing 10 topics) issue 10 round-trips to Postgres. With ~5 ms RTT each = 50 ms purely for the trip.
- **Fix:** extend `MessageStore` (still ≤5 methods if we replace `count_messages` with a `MessageStats` Protocol) to add `get_messages_bulk`. Alternatively keep ISP and add a separate `BulkMessageReader` Protocol.

---

## Medium Priority
*v1.6.0+ improvements.*

### M-1. `count_messages` extra round-trip in `delete_messages_before`
- The DELETE includes `(SELECT GREATEST(COUNT(*) - :keep_last, 0) ...)` subquery — this is a second seq-scan on the same partition. Use a `OFFSET :keep_last` pattern over a windowed `ROW_NUMBER()` query for a single pass.

### M-2. SQLite global threading lock per provider
- All SQLite providers (`graph_task_board_sqlite.py:62`, `task_queue.py:153`, `agent_registry_sqlite.py`, `graph_store_sqlite.py:30`, `episodic_sqlite.py:20`, `procedural_sqlite.py:31`) share one `threading.Lock` per provider. With the WAL mode + `check_same_thread=False` SQLite *can* tolerate concurrent readers, but the lock serializes ALL ops. For an embedded multi-agent demo this is the right safety net; for production it is unnecessarily strict.
- Use `RWLock` or rely on SQLite's row-locking with shorter critical sections. Minor — most users will move to Postgres anyway.

### M-3. Hooks dispatched serially
- `hooks/dispatcher.py:97-124, 150-170` iterate `for entry in self._registry.get_hooks(...)`. Pre/Post/Stop/UserPrompt all serial.
- Acceptable because each hook may depend on the prior hook's modification. But for *Stop* hooks (no return value, no chaining) we could `asyncio.gather` them, ditto for *PostTool* hooks that return None.
- Doc note: explicit "serial-by-design" comment is missing.

### M-4. Circuit breaker not wired into MCP client
- `resilience/circuit_breaker.py` ships a clean breaker, but `runtime/thin/mcp_client.py` does not consult it. So a flapping MCP server keeps getting calls timeout-by-timeout instead of being short-circuited.
- Fix: inject `CircuitBreakerRegistry` into `McpClient.__init__`, gate `call_tool/list_tools/read_resource` on `breaker.allow_request()`, and call `record_success/record_failure` accordingly.

### M-5. EventBus has no overflow handling
- `InMemoryEventBus.emit` awaits each callback inline. A slow callback blocks the whole emit chain.
- Fix: detach callbacks via `asyncio.create_task` with a bounded task group or queue per subscriber. Document trade-off (lose events on shutdown vs. block emit).

### M-6. CLI `init_cmd` is 508 lines monolith
- `src/swarmline/cli/init_cmd.py` exceeds the 300-line SRP limit noted in `.memory-bank/codebase/CONCERNS.md`. Already flagged in tech-debt. No production impact but slows iteration.

### M-7. `runtime/registry.py` lock is `threading.Lock`, not `asyncio.Lock`
- The registry runs at import time / startup (lazy entry-point discovery). Using `threading.Lock` is fine for the singleton init, but `register/unregister/get` from async code holds a thread-blocking lock — trivial today but conceptually wrong.

### M-8. No timeout on individual LLM call
- `RuntimeConfig` has `request_options.timeout_sec` but `default_llm_call` doesn't enforce it. Each adapter passes through to provider SDK timeouts (30 s default for Anthropic). Cancellation token helps, but a hung TLS connection doesn't trigger the token.
- Fix: wrap `adapter.call(...)` in `asyncio.wait_for(timeout=request_options.timeout_sec or 60)`.

### M-9. `_subscribers` in `InMemoryEventBus` not lock-protected
- `event_bus.py:42-47` — concurrent subscribe/unsubscribe + emit could mutate `_subscribers` mid-iteration. The `list(...)` call in `emit` mitigates iteration corruption but `subscribe` racing with `emit` could still drop the new subscriber. Low impact.

### M-10. Health check is trivial
- `serve/app.py:_make_health_handler` just returns `{"status": "ok"}`. No DB ping, no event-bus liveness, no cancellation-token sample. Production deployments need readiness probes that actually verify upstream.

---

## Scalability Assessment

### Throughput estimate
- **ThinRuntime + Anthropic, single instance, no caching:** ~5–15 turns/sec for short responses, dominated by LLM latency
- **Multi-agent (Graph orchestrator with `max_concurrent=5`):** ~2–4 simultaneous chains; semaphore prevents fan-out blowup
- **Tool dispatch:** ~30 ms overhead per local tool call (timeout wrap + JSON serialization + hook dispatch). MCP tool: 50–100 ms minimum due to per-request `httpx.AsyncClient` (Bottleneck #2).

### Concurrency model
- Single asyncio event loop per process (no built-in worker pool)
- Tools that are not coroutines run in the default `asyncio.to_thread` executor (default 32 workers in CPython 3.13)
- SQLite ops bridged via `to_thread` — non-blocking but each connection is single-threaded
- Postgres via SQLAlchemy async + asyncpg — caller owns engine, can scale via `pool_size`

### Memory profile
- **Per agent turn:** O(response_tokens × 2) — once for the buffered chunk list, once for `lm_messages` after tool turns
- **Per session:** O(history_messages × avg_message_size) in InMemorySessionManager — no eviction beyond TTL
- **Per orchestrator run:** O(executions_in_run) — `_results` dict and `_bg_tasks` accumulate

### I/O bound vs CPU bound
- **CPU-bound:** JSON parsing in `parse_envelope`, regex in `extract_text_fallback`, Pydantic validation. All small.
- **I/O-bound (dominant):** LLM HTTP (1–10 s per call), MCP HTTP (50–500 ms), Postgres (1–10 ms), SQLite (1–5 ms via to_thread)

### Bottleneck #1: Buffered streaming → see C-1
### Bottleneck #2: MCP per-request httpx → see C-2
### Bottleneck #3: Missing message indexes → see C-3
### Bottleneck #4: Subagent state leak → see H-6
### Bottleneck #5: No prompt caching → see H-8

---

## Architecture Health Check

- **Layer adherence (Infra → App → Domain):** ✅
  - `protocols/runtime.py` imports `RuntimeConfig` only inside `if TYPE_CHECKING:` — clean
  - `protocols/memory.py` imports `swarmline.memory.types` (frozen dataclasses, stdlib only) — borderline but acceptable
  - `domain_types.py` has zero `from swarmline.*` imports — verified
- **ISP compliance (Protocol ≤5 methods):** ✅ — all 36 protocols audited; max is `SessionManager` at 5
- **DIP adherence:** ✅
  - Postgres/SQLite providers receive `session_factory` from caller (no engine creation in src)
  - Runtime registry is a port (`RuntimeFactoryPort`); concrete `RuntimeFactory` injected
  - Hook registry, tool policy, MCP servers — all injected via `ThinRuntime.__init__`
- **Coupling between runtimes:** ✅ for `claude_code ↔ thin ↔ deepagents`
  - All three implement `AgentRuntime` (4-method ISP). The `agent/runtime_dispatch.py` switches on `runtime_name == "claude_sdk"` only because Claude SDK has a one-shot subprocess shape that the portable adapters don't share. Acceptable — could collapse if Claude SDK ever supports the `messages/system_prompt/active_tools` shape.
- **Frozen dataclass adherence:** ⚠️
  - Most domain types (`Message`, `RuntimeEvent`, `ToolSpec`, `ContentBlock`) are `@dataclass(frozen=True)` ✅
  - **Violators:** `RuntimeConfig` (intentional? see H-1), `_RunState` in `graph_orchestrator_state.py`, `SessionState` in `session/types.py`
- **Lazy import compliance:** ✅
  - `anthropic`, `openai`, `google.genai`, `langchain`, `nats`, `redis`, `httpx-redis`, `opentelemetry` — all imported inside the function
  - Spot-check: `jsonl_sink.py` imports `swarmline.observability.redaction` at top — fine, both stdlib-only

---

## Concurrency Analysis

### Race conditions
1. **`session/manager.py:39-44`** — `get_lock` non-atomic dict creation (see C-4)
2. **`observability/jsonl_sink.py:94-95`** — lazy `asyncio.Lock` allocation (see H-2)
3. **`observability/event_bus_redis.py:_subscribers` and `event_bus_nats.py:_subscribers`** — unprotected dict mutations (see H-3)
4. **`runtime/thin/mcp_client.py:_tools_cache, _resources_cache`** — concurrent `list_tools` calls for the same `server_url` may race; both will hit the network and write the cache twice. Idempotent so low impact, but wastes one round-trip.
5. **`_adapter_cache` in `llm_providers.py:550`** — module-global dict, no lock. Concurrent first-call to the same `(model, provider, base_url)` may instantiate two adapters; one is leaked. Low impact (rare race + GC eventually closes the orphan), but noteworthy.

### Resource leaks
1. **`ThinSubagentOrchestrator._tasks/_results/_output_buffers`** — never reaped (see H-6)
2. **`_adapter_cache`** — adapters never closed; on test isolation, lingering `httpx`/`anthropic` clients hold TCP connections (see H-5)
3. **`McpClient._tools_cache`** — TTL but no max size; with many distinct `server_url`s the dict grows
4. **`InMemoryEventBus._subscribers`** — counter monotonically grows; unsubscribe doesn't decrement it. Sub_id space is fine (string keys), but the counter could overflow after billions of subscribes (~70-year lifetime so practical impact = 0)
5. **Worktree handles in `ThinSubagentOrchestrator`** — `_cleanup_worktree` swallows all exceptions; if cleanup repeatedly fails (e.g. permissions) the worktree leaks on disk

### Lock contention risks
- **`session/manager.py` lock-per-session** is good design — no contention across sessions
- **`graph_orchestrator.py` semaphore** bounds total concurrent agents (default 5) — could be too low for some workloads; should be configurable per-run rather than per-orchestrator
- **`runtime/registry.py` `threading.Lock`** is held only at startup — no contention
- **`pipeline/budget_store.py`** uses both `asyncio.Lock` and `threading.Lock` (lines 72, 245) — separate stores for sync/async paths, no shared state, OK

---

## Production Readiness Checklist

- [x] **Graceful shutdown** — `daemon/runner.py` has SIGTERM/SIGINT handlers; `Agent.cleanup()` is async-context-manager friendly. **But:** `serve/app.py` (Starlette) lacks lifespan handler that calls `agent.cleanup()` on shutdown — in-flight queries get cancelled abruptly.
- [⚠️] **Resource cleanup** — context managers and `cleanup()` exist; *but* `_adapter_cache` is never cleared and subagent registry leaks (see H-5, H-6).
- [⚠️] **Circuit breaker coverage** — `CircuitBreaker` exists, NOT wired into MCP, NOT wired into LLM provider calls. Only LangChain `deepagents` runtime uses it implicitly via LangChain's retry decorators.
- [⚠️] **Timeout policies** — per-tool 30 s default, per-MCP-call 30 s. **Missing:** per-LLM-call (relies on provider default 600 s+), per-stream (no idle timeout — a hung TLS connection holds the agent forever until cancellation token fires).
- [❌] **Observability completeness** — structlog ✅, OTel tracing ✅. **Missing:** metrics (Prometheus), no structured emit on circuit breaker state changes, no pool metrics (would need user's engine).
- [⚠️] **Health checks** — `/v1/health` returns `200 OK` unconditionally. Doesn't verify DB pool, event bus, LLM connectivity.
- [⚠️] **Multi-instance support** — Postgres/Redis/NATS backends exist, so state can be externalized. **But:** `RedisEventBus` does not deduplicate (own-message check is best-effort), `_results` dict in graph orchestrator is in-process (one instance can't see another instance's task results).

---

## API Stability

- **Public surface (`__init__.py`)** is curated to 12 names — narrow, stable. The other 25+ names are kept available via `from swarmline import X` (re-exports with `# noqa: F401`) — no breaking change vs v1.4.
- **Deprecation strategy** is in-place:
  - `RuntimePort` deprecated in favour of `AgentRuntime` (kept for SessionManager backcompat)
  - `AgentConfig.thinking=<dict>` deprecated → `ThinkingConfig` typed dataclass
  - `SessionState.adapter` (RuntimePort) deprecated → `SessionState.runtime`
  - `AgentConfig.resolved_model` deprecated → `swarmline.runtime.types.resolve_model_name()`
- **Breaking change risks (v2.0 candidates):**
  - Removing `RuntimePort` (5 places use it)
  - Renaming `dispatch_runtime` → `select_runtime` (would break `agent.runtime_dispatch` tests but no public callers)
  - Splitting `MessageStore` into `MessageWriter`/`MessageReader` for ISP cleanup
  - Tightening `RuntimeConfig` to frozen (would break callers that mutate `input_filters`)

---

## Recommendations (prioritized)

### v1.5.x patches (no API change)
1. **C-2**: Reuse `httpx.AsyncClient` in `McpClient` — single import, biggest perf win for MCP-heavy users
2. **C-4**: Replace `_locks[ks] = asyncio.Lock()` with `setdefault` — 1-line race fix
3. **H-2**: Move `JsonlTelemetrySink._lock = asyncio.Lock()` to `__init__`
4. **M-8**: Wrap `adapter.call` in `asyncio.wait_for(request_options.timeout_sec)` if set

### v1.6.0 minor (additive)
1. **C-3**: Ship `swarmline/migrations/postgres/*.sql` + `swarmline.memory.postgres.apply_migrations()` helper
2. **C-1**: New streaming API `stream_llm_call` with backpressure; keep buffered API for validation paths
3. **H-3**: Async `subscribe` + `_subscribers` lock for `RedisEventBus`/`NatsEventBus`
4. **H-4**: `observability/metrics.py` Protocol + Prometheus adapter (`swarmline[prometheus]`)
5. **H-5**: Bounded LRU on `_adapter_cache` with `clear_adapter_cache()` + `__del__` close
6. **H-6**: `ThinSubagentOrchestrator.cleanup_completed(retain_seconds)`
7. **H-7**: `asyncio.gather` for multi-tool envelopes in JSON-in-text path
8. **H-8**: Anthropic prompt caching opt-in (`RuntimeConfig.use_prompt_caching`)
9. **M-4**: Circuit breaker wired into `McpClient`
10. **M-10**: `/v1/health` performs DB + event-bus liveness checks

### v2.0.0 major refactor
1. **H-1**: `RuntimeConfig` → frozen, callers use `dataclasses.replace`
2. **H-10**: `MessageStore` adds `get_messages_bulk` (or new `BulkMessageReader` ISP-clean Protocol)
3. Remove deprecated `RuntimePort`, `AgentConfig.thinking=<dict>`, `SessionState.adapter`, `AgentConfig.resolved_model`
4. Split `MessageStore` into `MessageWriter` + `MessageReader` Protocols
5. Make `Agent` reuse runtime via `warm()` or implicit caching (H-9) — public method or behaviour change
6. `EventBus.subscribe` returns `Awaitable[str]` so distributed buses can await network confirmation

---

## Appendix

- **Files analyzed in detail:** 28 (runtime/thin, agent/, memory/, multi_agent/, orchestration/, hooks/, session/, observability/, protocols/, serve/, resilience/)
- **Files spot-checked (grep):** all 387 in `src/swarmline/`
- **LOC analyzed:** 52,980 source LOC (test suite excluded)
- **Largest files (top 5 by LOC):**
  - `memory/postgres.py` 662
  - `memory/sqlite.py` 650
  - `runtime/thin/runtime.py` 636
  - `multi_agent/graph_task_board_postgres.py` 633
  - `multi_agent/graph_task_board_sqlite.py` 590
- **Test suite status (per STATUS.md):** 5452 passed, 7 skipped, 5 deselected, 0 failed (~52 s)
- **ty (type checker):** 0 diagnostics, baseline locked = 0
- **ruff:** all green

### Dependency-direction snapshot
```
domain_types.py    →  (stdlib only)              ✅
protocols/*.py     →  domain_types, memory/types ✅ (memory/types is domain-pure)
agent/             →  protocols, runtime/types   ✅
bootstrap/         →  protocols, runtime/factory, policy, routing  ✅
runtime/thin/      →  runtime/types, third-party (httpx, anthropic, openai, google.genai)  ✅
memory/sqlite.py   →  sqlalchemy, aiosqlite       ✅
memory/postgres.py →  sqlalchemy, asyncpg         ✅
multi_agent/       →  protocols, sqlalchemy, sqlite3 (sync)  ⚠️ (uses sync sqlite3 instead of aiosqlite — to_thread workaround)
```

### Critical paths re-verified
- `Agent.query → dispatch_runtime → run_portable_runtime → ThinRuntime.run → run_react → ToolExecutor.execute → HookDispatcher → ToolPolicy → local/MCP call`
- All edges verified to respect Clean Architecture; no Domain → Infrastructure imports detected.

### Final assessment
swarmline v1.5.0 has **excellent architectural bones** — clean ISP/DIP, lazy imports, frozen domain types, swappable runtimes — but **production scalability requires opt-in tuning** that is not yet documented or wired by default. The most impactful single fix is C-2 (reuse `httpx.AsyncClient` in MCP), followed by C-3 (ship Postgres DDL with proper indexes) and C-1 (preserve streaming through the validation path).

The codebase is *ready* for production at small-to-medium scale (≤20 concurrent agents per process, ≤100 k messages per topic). To grow beyond that without rewriting, address the High-priority list in v1.6.0.
