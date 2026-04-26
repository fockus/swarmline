# Architecture Audit — swarmline v1.4.1 → v1.5.0

**Verdict:** **CONDITIONAL — NEEDS WORK before v1.5.0 release.**

**Date:** 2026-04-25
**Auditor:** Backend Architect

## Executive Summary

swarmline is **architecturally serious** — Domain layer is genuinely pure stdlib, the Protocol-first approach is real and 25/39 of the central protocols are `@runtime_checkable`, ty strict-mode passes with zero diagnostics, no `eval/exec/shell=True` exists in the source tree, and 4500+ unit tests + 516 integration tests pass when run in their own files. This is well above LangChain's hygiene baseline.

However the claim "production-ready" is **not yet supportable**: 141 unit tests fail when the suite is run together (test-isolation pollution proven via repro), the JSONL telemetry sink performs synchronous file I/O from inside an `async` method, the structlog config writes to **stdout** which corrupts the CLI's `--format json` contract, the `ThinRuntime.run()` method is a 300-line god-method, and the codebase undercounts its own protocols by ~7× (101 actual vs. "14 ISP-compliant" advertised). All five are fixable in days, not weeks, but they should not ship under a "production-ready" v1.5.0 banner.

## Strengths (with evidence)

- ✅ **Domain layer is genuinely pure.** `src/swarmline/types.py` and `src/swarmline/domain_types.py` import only `dataclasses`, `typing`, `uuid`. `memory/types.py` imports only `dataclasses`, `typing`. No infrastructure leakage. `protocols/__init__.py:1-70` only re-exports from sibling protocol files.
- ✅ **DIP boundary at agent ↔ runtime is real.** `src/swarmline/agent/runtime_factory_port.py:14-49` defines `RuntimeFactoryPort` as a 5-method `@runtime_checkable Protocol`; `agent/agent.py:38` accepts it via constructor injection. Factory implementation only loaded inside `build_runtime_factory()` (line 51-60), so the Application layer doesn't import the concrete factory at module-load time.
- ✅ **Lazy optional dependencies** done right. `runtime/__init__.py:92-176` uses `__getattr__` with an `_OPTIONAL_EXPORTS` table to defer import errors with helpful `pip install …[extra]` hints. No top-level imports of `anthropic`, `openai`, `google.genai` — all 4 lazy in `runtime/thin/llm_providers.py:136,271,399,489`.
- ✅ **No insecure primitives.** Zero `eval(`, `exec(`, `shell=True`, `os.system` across `src/swarmline/`. (`grep -r "shell=True"` returns nothing.)
- ✅ **Thread-safe runtime registry.** `runtime/registry.py:34-80` consistently holds `threading.Lock` around all reads and writes. Module-level singleton uses `_default_lock` (line 245).
- ✅ **Type checker is green.** `ty check src/swarmline/` ⇒ `All checks passed!` (zero diagnostics in strict mode). 32 `tests/unit/test_protocol_contracts.py` pass.
- ✅ **TODO/FIXME debt = 0.** `grep -rE "(TODO|FIXME|XXX|HACK):" src/swarmline/` returns 3 hits, all of them `TaskStatus.TODO` enum references in business logic — not tech-debt markers. Actual debt comments: zero.
- ✅ **No top-level circular imports.** `python -c "import swarmline.{agent,runtime,bootstrap,protocols,multi_agent,session,memory}"` succeeds.
- ✅ **JsonlMessageStore is async-correct.** `session/jsonl_store.py:115-128` uses `asyncio.to_thread()` for file I/O — proper non-blocking pattern.
- ✅ **Protocol method counts compliant** (where it counts). Of 31 Protocols inside `protocols/`, every one has ≤5 methods, including the 5-method limit of `HostAdapter`, `AgentRuntime`, `GraphTaskBoard`, `MessageStore`, `AgentRegistry`, `TaskQueue`.

## Critical Issues (BLOCKERS for prod)

- ❌ **Test isolation is broken — 141/4641 unit tests fail when the suite is run together.** Severity: **CRITICAL**.
  - **Repro:** `pytest tests/unit/test_event_bus.py` ⇒ 26 passed alone. `pytest tests/unit/test_cli_commands.py` ⇒ 14 fail. `pytest tests/unit/test_event_bus.py tests/unit/test_cli_commands.py` ⇒ 14 fail (event_bus pollutes CLI tests).
  - **Root cause:** `observability/logger.py:22-27` — `logging.basicConfig(stream=sys.stdout, force=True)` resets the root logger every time anyone calls `configure_logging()`. Subsequent CLI tests that parse `result.output` see ANSI-escaped log lines like `[\x1b[32m\x1b[1minfo\x1b[0m] session_created mode=headless` mixed with their JSON output, breaking `json.loads()` (see `test_cli_commands.py::TestJsonOutput::test_json_format_team_agents` failure trace).
  - **Why it's a blocker:** "5352 offline tests pass" in STATUS.md is **only true when the suite is partitioned manually**. The CI you ship to public will run the full suite and fail.
  - **Fix:** (a) move log stream to `sys.stderr`, (b) drop `force=True` (or guard it), (c) auto-fixture `pytest_logging_disabled = True` for CLI tests.

- ❌ **Async correctness violated in observability sink.** Severity: **CRITICAL** for any user using JSONL telemetry under load.
  - `observability/jsonl_sink.py:49-60` — `async def record(...)` calls `self._path.open("a", encoding="utf-8")` and writes synchronously. This blocks the event loop on every event during disk I/O, defeating async benefits and serializing all concurrent agents.
  - For comparison: `session/jsonl_store.py:127` correctly wraps the same operation with `asyncio.to_thread(self._append_line, ...)`.
  - There is also no lock; concurrent `record()` calls rely on POSIX `O_APPEND` atomicity, which only holds for writes < `PIPE_BUF` (4096 on Linux, 512 on macOS). Larger redacted records will interleave.
  - **Fix:** wrap the file write in `asyncio.to_thread()` and add `self._lock = asyncio.Lock()` around the call.

- ❌ **CLI JSON contract is unreliable due to logger contamination.** Severity: **CRITICAL** for downstream tools parsing CLI output.
  - When a user invokes `swarmline --format json team agents`, structlog emits a `session_created` info log to **stdout** (configured at `observability/logger.py:22`). The JSON consumer (Python `json.loads`, jq, shell pipelines) breaks. This is exactly the bug surfaced by the 14 test_cli_commands failures.
  - **Fix:** logs to `stderr`. This is a **public-API behavioural contract** issue, not just a test problem — anyone piping `swarmline --format json` into `jq` will hit it on first invocation.

## Major Issues (warnings)

- ⚠️ **`ThinRuntime.run()` is a 300-line god method.** `runtime/thin/runtime.py:249-552` — single method handling: cancellation checks, budget tracking, structured output validation, MCP resource tooling, sub-agent registration, hook dispatch, command intercept, input guardrails, compaction, input filters, mode detection, thinking warnings, retry buffering, three strategy branches (conversational/react/planner), event-bus emission, cost tracking, output guardrails, postprocessing, background event drain, Stop hook. **17 distinct concerns in one method.** This is the single biggest SRP violation in the codebase.
  - **Refactor target:** extract `_setup_active_tools()`, `_run_input_pipeline()`, `_dispatch_strategy()`, `_handle_event_postprocessing()`. Aim for run() ≤ 80 lines.

- ⚠️ **Protocol counting in docs is misleading.** STATUS.md and CLAUDE.md claim "14 ISP-compliant protocols". Actual count: **101 Protocol classes** in `src/swarmline/` (`grep -rE "class \w+\(.*Protocol" src/`). `protocols/` package alone has 31 (not 14). One of them is **a 7-method Protocol** (`orchestration/coding_task_ports.py:89-128 CodingTaskBoardPort`) — formally ISP-violating. The docstring honestly admits "this is a *composition* of three narrow protocols" and explains the circular-import workaround (lines 90-112), but it still violates the stated ≤5 methods rule.
  - **Fix:** update docs to reflect reality OR refactor `CodingTaskBoardPort` to inherit from the three narrow ports (keeping `ty` happy may need `from __future__ import annotations` + `TYPE_CHECKING`).

- ⚠️ **`@runtime_checkable` applied inconsistently across `protocols/`.** Of 39 classes in `protocols/`: 25 marked `@runtime_checkable`, 14 not. Missing: `SessionFactory`, `SessionLifecycle`, `SessionManager`, `SessionRehydrator`, `RoleRouter`, `ContextBuilder`, `ModelSelector`, `RoleSkillsProvider`, `ToolIdCodec`, `LocalToolResolver`, `RuntimePort`. This means `isinstance(x, SessionFactory)` will raise `TypeError` and silently break duck-type registration patterns. Pick one convention; the codebase is split.

- ⚠️ **`PostgresMemoryProvider` is a single class implementing 6 protocols (17 methods).** `memory/postgres.py:46-650`. Same in `memory/sqlite.py`. The Protocol layer is correctly split, but the implementation centralises into a god-class. SRP violation: 17 methods of 6 different responsibilities (messages, facts, summaries, goals, session-state, users). Mitigated by `_session()` context manager (line 58), but the testability suffers — you cannot mock just `MessageStore` without dragging the rest.
  - **Fix is optional** (composition ports vs. composition root), but document the trade-off honestly.

- ⚠️ **`session/manager.py:264-290 _run_awaitable_sync` is an event-loop sync bridge that spawns a thread to call `asyncio.run()` from inside an existing loop.** This is a known anti-pattern (creates a fresh loop, can deadlock if the inner coroutine tries to acquire a lock held by the outer loop). The docstring at lines 303-304 warns "may block the event loop. Prefer aget" — but it's exposed publicly as `get()`, `register()`, `update_role()`. Given that v1.5.0 declares "async-first", remove the sync API or hide behind an explicit `swarmline.legacy_sync` namespace.

- ⚠️ **CircuitBreaker is not concurrency-safe.** `resilience/circuit_breaker.py:21-77` — `_consecutive_failures += 1` (line 67) is read-modify-write on shared state with no lock. In multi-threaded usage, breaker can fail to open. `CircuitBreakerRegistry.get()` (line 91-98) has a check-then-set race that can create two breakers for the same `server_id`. In single-event-loop async this is OK (await points are explicit), but the docstring claims "thread-safe via threading" patterns elsewhere and this one isn't. Be consistent.

- ⚠️ **Application layer imports concrete Infrastructure classes (deferred but direct).** `agent/runtime_dispatch.py:33` `from swarmline.runtime.sdk_tools import create_mcp_server, mcp_tool`; line 80-82 imports from `runtime.sdk_query` and `runtime.adapter`; line 128-130 from `runtime.options_builder`. These are inside-function lazy imports, so module-level dependency direction is preserved, but at runtime the agent layer is calling concrete infra without going through a port. Result: cannot swap MCP server impl without monkey-patching. Strict Clean Architecture would route everything through a `McpServerFactoryPort`. The current state is **pragmatically OK** but does not match the "Domain → Application → Infrastructure, never reverse" claim absolutely.

- ⚠️ **CHANGELOG.md unreleased section is empty.** v1.5.0 candidate has no documented user-facing changes summary — only "1.4.0" entry. Before tagging v1.5.0, populate `[Unreleased]` with the agent-pack, structured output, JSONL telemetry sink, typed pipeline additions visible in `git status`.

## Minor / Tech debt

- 📝 **Python version drift.** `pyproject.toml:requires-python = ">=3.11"` but CLAUDE.md says "Python 3.10+". Pick one. (Code compiles cleanly on 3.11+ — uses `match` statements? no, but uses modern union syntax `X | Y` that works in 3.10 only with `from __future__ import annotations`.)
- 📝 **171 `except Exception` blocks.** Most are at correct boundaries (top-level runtime crash handler, MCP tool wrappers). Spot-checked `runtime/thin/runtime.py:543` — fine because `asyncio.CancelledError` is `BaseException` in 3.11+. Still, **none of the 171 sites explicitly chain `except CancelledError: raise`** before `except Exception`, so a future bump to a library that subclasses `Exception` for cancellation could mask propagation. Defensive practice would be `except CancelledError: raise; except Exception: ...`. Only 10 files in the codebase reference `CancelledError` at all (`grep -rcE "asyncio\.CancelledError" src/`).
- 📝 **`Agent` class has 17 methods (574 lines).** `agent/agent.py`. Borderline by SRP-300-line rule. Bunch of `_execute_*` private helpers could be moved into a `RuntimeDispatcher` collaborator without breaking the facade.
- 📝 **`AgentRuntime` Protocol re-exported in two paths** — `swarmline.runtime.base.AgentRuntime` and `swarmline.protocols.AgentRuntime`. Kept as a re-export shim (`runtime/base.py` is 8 lines), but it expands the public API surface unnecessarily. Prefer a single canonical location and a deprecation in the other.
- 📝 **Missing examples extra in OTEL example.** `tests/integration/test_examples_smoke.py::test_examples_run_offline_without_stderr[28_opentelemetry_tracing.py]` fails because the smoke test invokes `examples/28_*.py` with a venv missing `swarmline[otel]`. Either the example should `try/except ImportError` and skip, or the test fixture should install `[otel]` before running. Currently a "permanently red" integration test.
- 📝 **`__init__.py` API surface size.** Top-level `swarmline.__init__` has **51 exports** in `__all__`. `swarmline.runtime.__init__` has **49**. By "30+ = noise" rule both are over budget. Consider stratifying — e.g. `swarmline.runtime.advanced` for things 99 % of users won't import.

## Section-by-section

### Clean Architecture compliance

| Layer | Reality |
|---|---|
| **Domain** (`protocols/`, `types.py`, `domain_types.py`, `memory/types.py`) | ✅ Pure stdlib. Verified: `grep -E "^from swarmline" src/swarmline/{types,domain_types}.py src/swarmline/memory/types.py` returns only `from swarmline.domain_types import RuntimeEvent` (intra-domain). |
| **Application** (`agent/`, `bootstrap/`, `orchestration/`) | ⚠ Mostly clean. `agent/agent.py:206`, `agent/runtime_dispatch.py:33,80,82,128-130` directly import concrete Infrastructure classes (lazy, but concrete). Acceptable pragmatic compromise but not strict CA. `bootstrap/stack.py:7-15` imports many infra modules — correct because Bootstrap **is** the composition root. |
| **Infrastructure** (`runtime/`, `memory/{sqlite,postgres}.py`, `tools/`, `multi_agent/*_sqlite.py` etc.) | ✅ Implements the abstract ports. No upward leakage detected. |

**Verdict:** layers exist and direction is mostly correct, but the strict "never reverse" pledge has small lazy-import escapes in `agent/`. The bootstrap pattern is implemented correctly.

### ISP compliance (protocols in `src/swarmline/protocols/`)

| Protocol | File | Methods | Compliant |
|---|---|---:|---|
| `MessageStore` | memory.py | 4 | ✅ |
| `FactStore` | memory.py | 2 | ✅ |
| `SummaryStore` | memory.py | 2 | ✅ |
| `GoalStore` | memory.py | 2 | ✅ |
| `SessionStateStore` | memory.py | 2 | ✅ |
| `UserStore` | memory.py | 2 | ✅ |
| `PhaseStore` | memory.py | 2 | ✅ |
| `ToolEventStore` | memory.py | 1 | ✅ |
| `SummaryGenerator` | memory.py | 1 | ✅ |
| `RoleRouter` | routing.py | 1 | ✅ |
| `ContextBuilder` | routing.py | 1 | ✅ |
| `ModelSelector` | routing.py | 2 | ✅ |
| `RoleSkillsProvider` | routing.py | 2 | ✅ |
| `RuntimePort` | runtime.py | 4 | ✅ |
| `AgentRuntime` | runtime.py | 5 (incl. context manager) | ✅ |
| `SessionFactory` | session.py | 2 (1 prop + 1 method) | ✅ |
| `SessionLifecycle` | session.py | 2 | ✅ |
| `SessionManager` | session.py | 4 (+ inherited 2) | ✅ |
| `SessionRehydrator` | session.py | 1 | ✅ |
| `AgentTool` | multi_agent.py | 1 | ✅ |
| `TaskQueue` | multi_agent.py | 5 | ✅ |
| `AgentRegistry` | multi_agent.py | 5 | ✅ |
| `HostAdapter` | host_adapter.py | 4 | ✅ |
| `ToolIdCodec` | tools.py | 3 | ✅ |
| `LocalToolResolver` | tools.py | 2 | ✅ |
| `GraphTaskBoard` | graph_task.py | 5 | ✅ |
| `GraphTaskScheduler` | graph_task.py | 2 | ✅ |
| `GraphTaskBlocker` | graph_task.py | 2 | ✅ |
| `TaskCommentStore` | graph_task.py | 3 | ✅ |
| `AgentGraphStore` | agent_graph.py | 5 | ✅ |
| `AgentGraphQuery` | agent_graph.py | 4 | ✅ |
| `AgentNodeUpdater` | agent_graph.py | 1 | ✅ |
| `GraphCommunication` | graph_comm.py | 5 | ✅ |
| `GraphOrchestrator` | graph_orchestrator.py | 5 | ✅ |
| `GraphTaskWaiter` | graph_orchestrator.py | 1 | ✅ |
| `PersistentOrchestrator` | graph_orchestrator.py | 5 | ✅ |
| **`CodingTaskBoardPort`** | orchestration/coding_task_ports.py | **7** | **❌** |

**31 protocols in `protocols/` package, all ≤5. One outside (`orchestration/coding_task_ports.py:CodingTaskBoardPort`) violates with 7.** Counting all `class X(Protocol)` in the entire src tree: **101 Protocols**, of which most are intra-module ports (e.g. `tools/web_protocols.py`, `memory/episodic_types.py`) — those are private contracts and ISP applies less strictly there.

### Scalability & async correctness

- **Async-first claim mostly holds.** No `time.sleep()` in `src/swarmline/` (`grep -rn "time\.sleep"` returns nothing). No synchronous `requests.*` HTTP. No `asyncio.run()` inside library hot paths except `cli/_app.py`, `cli/init_cmd.py`, `daemon/cli_entry.py`, `plugins/_worker_shim.py` — those are entry points, OK. **Exception:** `session/manager.py:273,280` uses `asyncio.run()` from a sync method — known anti-pattern for "sync bridge", documented but smelly.
- **Blocking I/O in async path** — see Critical issue #2: `observability/jsonl_sink.py:58-60`.
- **Locking strategy is mixed.** 23 lock instantiations: 11 `asyncio.Lock`, 12 `threading.Lock`. Mostly file-or-class-local — acceptable. Pattern: SQLite-backed stores use `threading.Lock` + `asyncio.to_thread()`, in-memory stores use `asyncio.Lock`.
- **Bottleneck candidates:**
  - `multi_agent/task_queue.py:84-126 InMemoryTaskQueue` — single `asyncio.Lock` around every operation. With many parallel agents claiming tasks (`get()` line 95-103), they serialise. Not a problem at <50 RPS, would be at >500 RPS.
  - Registry `runtime/registry.py:34` global `threading.Lock` for read paths too. Since reads are >>writes, an `RLock` or copy-on-read would be more scalable, but unmeasurable today.
- **Distributed deployment readiness:** ⚠ partial. Memory backends have Postgres impls, but `RuntimeRegistry`, `CircuitBreakerRegistry`, `ModelRegistry` are process-local singletons. Multiple processes won't share circuit-breaker state. Not a blocker for v1.5.0 (most users run single-process), but worth a note in docs.

### Robustness

- **171 `except Exception` blocks.** Top sources: `tools/builtin.py` (10), `runtime/thin/mcp_client.py` (6), `orchestration/thin_subagent.py` (6), `mcp/_tools_*` (5-6 each). All read like proper boundary catches (don't crash whole agent on tool error), not silent swallows. Spot check `runtime/thin/runtime.py:181 (native adapter creation)` — logs warning + falls back to JSON-in-text. Reasonable.
- **`asyncio.CancelledError` handling sparse** — only 10 files reference it. With Python ≥3.11 `CancelledError` is `BaseException`, so `except Exception` won't swallow it. But there's no defensive `except CancelledError: raise` pattern, so if a dependency ever emits a cancel-like `Exception` subclass it slips through.
- **Resource cleanup** — `async with` used 67 times in `memory/postgres.py`, 17 in `memory/sqlite.py`. SQLAlchemy session lifecycle handled correctly. `agent/agent.py:217-221` implements `__aenter__/__aexit__` calling `cleanup()`. `runtime/thin/runtime.py:241-247` same. **OK.**
- **Cancellation cooperative checks** — `runtime/thin/runtime.py:263, 388, 467` re-checks `cancellation_token` at multiple points during `run()`. Good. But cancellation is via custom token, not `asyncio.CancelledError` — if user cancels the wrapping `asyncio.Task`, no token is set. Hybrid model can leave a runtime in mid-state.

### Extensibility / SemVer risk

- **Adding a method to any of the 25 `@runtime_checkable` Protocols is a breaking change** for third-party implementers. There are 14 Protocols in `protocols/` *not* marked `@runtime_checkable` (see Major issue #4) — those are doubly-fragile because users can't even verify implementation at runtime.
- `swarmline.__init__.__all__` size = 51. Each element is a SemVer-public name. Removing one = MAJOR. Renaming = MAJOR. **Keep stable until v2.**
- `swarmline.runtime.AgentRuntime` and `swarmline.protocols.AgentRuntime` are aliases. Removing the legacy `runtime.base.AgentRuntime` re-export = MAJOR.
- The `_OPTIONAL_EXPORTS` pattern (runtime/__init__.py:92-176) is excellent for adding optional features without breaking existing wildcard imports.
- **101 internal `Protocol` classes** — only the ~30 in `protocols/` are publicly stable. The rest (e.g. `pipeline/protocols.py`, `tools/web_protocols.py`, `multi_agent/workspace.py`'s in-file Protocols) are implementation detail but **publicly importable**. If users find them, depending on them risks v1.6 breakage.

### Tech debt

- **TODO/FIXME: 0** (all 3 hits are `TaskStatus.TODO` enum references). Genuinely clean.
- **God classes:** `ThinRuntime` (17 methods, 616 lines, but `run()` is the real problem at 300 lines), `Agent` (17 methods, 574 lines — borderline), `PostgresMemoryProvider`/`SqliteMemoryProvider` (17 methods, 644/633 lines — multi-protocol implementations), `SessionManager` (23 methods, 367 lines).
- **Largest files:**
  - 644 `memory/postgres.py`
  - 633 `memory/sqlite.py`
  - 616 `runtime/thin/runtime.py`
  - 574 `agent/agent.py`
  - 568 `multi_agent/graph_task_board_sqlite.py`
  - 558 `runtime/thin/llm_providers.py`
  - 552 `multi_agent/graph_task_board_postgres.py`
  - 505 `cli/init_cmd.py`
  - All above the 300-line SRP heuristic.

### API surface

- **Top-level `swarmline.__init__.__all__`: 51 items.** Includes `AgentPackResolver` (new in this release), `JsonlMessageStore`, `SystemReminder`, `SystemReminderFilter`, `ProjectInstructionFilter` (recent additions), `ConversationCompactionFilter`. Mix of high-traffic (Agent, AgentConfig, Result) and rarely-used (`SkillSet`, `TurnContext`).
- **`swarmline.runtime.__init__.__all__`: 49 items + 14 deferred via `_OPTIONAL_EXPORTS`.** Many are internal types (`RUNTIME_CAPABILITY_FLAGS`, `RUNTIME_TIERS`, `VALID_FEATURE_MODES`) — should not be public.
- **Deprecated wrappers:** `RuntimePort` is documented as deprecated in `protocols/runtime.py:18-24` — explicit deprecation note, no `DeprecationWarning` raised at runtime. Add a `warnings.warn` for v1.5 cycle to encourage migration.

## Recommendations (sorted by priority)

| # | Action | Effort | Impact | Pre-v1.5.0? |
|---|---|---|---|---|
| 1 | Move structlog default stream to `sys.stderr`; drop `force=True` reset; isolate logging in CLI tests via fixture | 0.5 day | Fixes 14+ failing CLI tests, fixes user-visible CLI JSON output corruption | **YES** |
| 2 | Wrap `JsonlTelemetrySink.record` file-write in `asyncio.to_thread()` + add `asyncio.Lock` | 0.5 day | Removes event-loop blocking in observability path | **YES** |
| 3 | Investigate other 127 isolation failures (likely shared `_default_lock` / registry singletons polluted across tests). Run `pytest --random-order` to flush them | 1-2 days | "5352 tests pass" becomes a true statement, CI can run full suite | **YES** |
| 4 | Refactor `ThinRuntime.run()` into 4-5 private helpers (≤80 lines each) | 1 day | Makes the core runtime maintainable; reduces review burden for future PRs | YES if budget allows |
| 5 | Decide on `@runtime_checkable` policy and apply uniformly to all `protocols/` (or document why some don't have it) | 0.5 day | Removes API inconsistency; users get reliable `isinstance(x, Port)` everywhere | YES |
| 6 | Update STATUS.md / CLAUDE.md / docs to reflect actual protocol count (≥31 in `protocols/`, 101 in source tree). Drop or fix the "14 ISP-compliant" claim | 0.25 day | Honesty in marketing | YES |
| 7 | Populate `CHANGELOG.md [Unreleased]` with v1.5.0 features (agent-pack, JSONL sink, typed pipeline, agent runtime structured output, etc.) | 0.5 day | Required for any release | YES |
| 8 | Add `warnings.warn(DeprecationWarning)` to `RuntimePort` accessors | 0.25 day | Lets users see the deprecation at runtime | YES |
| 9 | Refactor `CodingTaskBoardPort` to compose 3 narrow Protocols (resolve circular import via `TYPE_CHECKING`) | 1 day | Restores ISP cleanliness | NO (post-v1.5.0) |
| 10 | Hide internal Protocols (`tools/web_protocols.py`, `pipeline/protocols.py`, etc.) behind `_internal/` namespace or document them as private | 1 day | Reduces SemVer surface for v2 | NO (post-v1.5.0) |
| 11 | Add `CancelledError` re-raise discipline to top-2 catch sites in runtimes | 0.5 day | Defensive: cancellation correctness even if Python rules change | NO |
| 12 | Stratify `__all__` — move `RUNTIME_CAPABILITY_FLAGS`, `VALID_*` constants to `swarmline.runtime.advanced` | 0.5 day | Cleaner public API | NO (v2 candidate) |
| 13 | Decide whether `SessionManager.get/register/update_role` sync API stays public or moves to `swarmline.legacy_sync.*` | 0.5 day | Removes deadlock-prone bridge from primary path | NO |
| 14 | Add load tests for `TaskQueue` to verify the single-`asyncio.Lock` doesn't cap throughput | 1-2 days | Confirms scalability claim under multi-agent workloads | NO |

## Sign-off

**Ready for v1.5.0 release: CONDITIONAL.**

Conditions to release a `v1.5.0` that justifies a "production-ready" tag:
1. Items 1, 2, 3 above (logger, JSONL sink, test isolation) — these are user-visible bugs.
2. Item 7 — populate CHANGELOG.
3. Items 5 and 6 — coherence of public statements with code (small but important for trust).

If items 1-3 cannot ship in time, **release as `v1.5.0-rc1`** and label as preview. The architecture is genuinely better than LangChain in three ways — Domain purity, Protocol-first ports with `@runtime_checkable`, and clean DIP at agent/runtime boundary — and that story deserves a clean release rather than a soft launch with broken JSON output and a flaky test suite.

Items 4 and 8-14 are quality-of-code work for v1.5.x patches and v1.6.0 minor.
