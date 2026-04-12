# Full Library Audit — swarmline v1.1.0

**Date:** 2026-03-29
**Scope:** Entire library (~37,600 LOC, 306 source files, 262 test files)
**Method:** 6 parallel reviewer agents (Security, Architecture, Multi-Agent, Pipeline+Daemon, Memory+Session+Observability, Runtime+Tools+Bootstrap)
**Baseline:** 3530 tests pass, 1 FAIL, coverage 86%, 8 ruff errors

## Summary

| Tier | Count | Description |
|------|-------|-------------|
| CRITICAL | 12 | Security (RCE, injection), Clean Architecture violations, data loss, race conditions |
| SERIOUS | 22 | SSRF, god classes, DIP violations, resource leaks, logic bugs |
| WARNING | 20+ | Scalability, DRY, validation, YAGNI |

## Tier 1: CRITICAL (12)

### Security — RCE / Injection

| ID | File | Issue |
|----|------|-------|
| C1 | mcp/_tools_code.py:13 | Unsandboxed `python -c` on host — full RCE |
| C2 | tools/sandbox_e2b.py:130 | Command injection in glob_files — no validate, no shlex.quote |
| C3 | tools/sandbox_docker.py:148 | Shell injection in write_file — provider bypasses own denylist via sh -c |
| C4 | tools/builtin.py:280 | ReDoS via unsanitized regex in grep executor |

### Architecture — Clean Architecture Violations

| ID | File | Issue |
|----|------|-------|
| C5 | types.py:11 | Domain imports from Infrastructure (runtime.types.RuntimeEvent) |
| C6 | protocols/multi_agent.py:15 | Protocol depends on runtime.types.ToolSpec |
| C7 | protocols/__init__.py:41 | Re-exports AgentRuntime from runtime/base.py |

### Data Integrity / Race Conditions

| ID | File | Issue |
|----|------|-------|
| C8 | session/manager.py:107 | monotonic clock serialized to backend — all sessions evict on restart |
| C9 | multi_agent/graph_task_board_sqlite.py:137 | Propagation race — no single transaction for complete + propagate |
| C10 | multi_agent/graph_task_board_postgres.py:313 | Propagation race — SELECT children without FOR UPDATE |
| C11 | multi_agent/graph_orchestrator.py:85 | start() doesn't launch root agent — dead start |
| C12 | observability/otel_exporter.py:164 | Span overwrite — hardcoded "llm_call" key, memory leak |

## Tier 2: SERIOUS (22)

### Security
- S1: tools/web_httpx.py:61 — SSRF, no private IP validation
- S2: a2a/server.py:47 — binds 0.0.0.0 without auth
- S3: todo/fs_provider.py:33 — path traversal via user_id/topic_id
- S4: memory/episodic_sqlite.py:106 — FTS5 operator injection
- S5: tools/sandbox_e2b.py:68 — denylist bypass via split() vs shlex.split

### Architecture — SOLID Violations
- S6: memory/{inmemory,sqlite,postgres}.py — God classes 17 methods, 480-556 LOC
- S7: orchestration/thin_subagent.py:18 — DIP: imports concrete ThinRuntime
- S8: runtime/types.py 563 LOC — mixed domain+infra types
- S9: protocols/session.py:36 — ISP violation (6 methods)
- S10: multi_agent/graph_store*.py — ISP violation (10-11 methods)

### Logic / Data
- S11: pipeline/pipeline.py:167 — accesses orchestrator private attrs
- S12: pipeline/pipeline.py:66 — FAILED phases don't record remaining as SKIPPED
- S13: pipeline/pipeline.py:128 — timeout_seconds defined but never used
- S14: graph_communication_nats.py:133 — reads from local cache, not JetStream
- S15: graph_communication_redis.py:86 — loses created_at and metadata
- S16: memory/procedural_postgres.py:112 — race: column vs JSONB desync
- S17: session/manager.py:214 — close_all() doesn't clean backend

### Resources
- S18: runtime/thin/mcp_client.py:82 — new HTTP client per call
- S19: runtime/thin/llm_providers.py:252 — global mutable cache, no thread safety
- S20: agent/agent.py:119 — thread-safety: query_structured mutates self._config
- S21: memory/inmemory.py:37 — unbounded _tool_events list
- S22: observability/event_bus_nats.py:78 — fire-and-forget subscribe

## Tier 3: WARNING (selection)
- W1: graph_task_board_postgres.py:178 — loads ALL tasks, filters in Python
- W2: graph_store_sqlite.py:184 — find_by_role full table scan
- W3: graph_orchestrator.py:326 — O(N*M) linear scan
- W4: graph_builder.py:85 — no graph validation
- W5: pipeline/builder.py:153 — build() with empty phases
- W6: pipeline/types.py:101 — PipelineResult.status str not Enum
- W7: daemon/health.py:179 — malformed HTTP returns defaults
- W8: daemon/cli_entry.py:152 — pause/resume no error handling
- W9: runtime/thin/planner_strategy.py:107 — step config loses retry_policy
- W10: session/manager.py:49 — no background TTL eviction

## Module Scores

| Module | Arch | Logic | Security | Code | Total |
|--------|------|-------|----------|------|-------|
| multi_agent/ | 8 | 5 | 7 | 6 | 6.5 |
| pipeline/ | 5 | 6 | 8 | 7 | 6.5 |
| daemon/ | 7 | 7 | 8 | 7 | 7.3 |
| memory/ | 8 | 5 | 7 | 7 | 6.8 |
| session/ | 7 | 5 | 7 | 6 | 6.3 |
| observability/ | 8 | 6 | 7 | 7 | 7.0 |
| runtime/ | 7 | 6 | 3 | 6 | 5.5 |
| tools/ | 6 | 6 | 3 | 6 | 5.3 |
| **Average** | 7.0 | 5.8 | 6.3 | 6.5 | **6.3** |

## Positive Findings
- ISP compliance in protocols (14+ protocols, mostly <=5 methods)
- Frozen dataclasses throughout domain layer
- SQL parameterization consistently used in all backends
- Timing-safe auth (hmac.compare_digest) in health server
- Excellent PidFile implementation (fcntl.flock, atomic write, stale detection)
- Sandbox isolation in LocalSandboxProvider (Path.resolve + is_relative_to)
- Cost tracking with budget checks in runtime
- Cycle detection in graph store update_node

## Infrastructure Issues
- 1 failing test: test_exception_does_not_kill_scheduler
- 8 ruff errors: unused imports in test files
- Coverage gaps: todo/db_provider.py 0%, todo/schema.py 0%, session/backends_postgres.py 50%
