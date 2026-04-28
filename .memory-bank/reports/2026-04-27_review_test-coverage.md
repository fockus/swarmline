# Test Coverage & Quality Review — swarmline v1.5.0

Date: 2026-04-27
Scope: tests/ + coverage report (pytest --cov)
Reviewer: Test Results Analyzer subagent

## Executive Summary

| Metric | Value | Target | Status |
|--------|------:|-------:|:------:|
| Overall coverage | **85.17%** | 85% | met (just barely) |
| Core/business coverage | **92.0%** weighted | 95% | partial |
| Infra coverage | **86%** weighted | 70% | met (above target) |
| Total tests collected | **5527** | n/a | — |
| Tests at 100% coverage files | 172 / 385 (44.7%) | — | — |
| Files <70% (infra threshold) | **36** | 0 | gap |
| Files <95% (core/business threshold) | **128** | <30 | partial |

**Headline findings:**
1. Overall 85.17% meets minimum but **leaves zero margin** — a single new module without tests can drop us below threshold.
2. **143 tests fail / 69 errors** in full pytest run despite passing in isolation — test pollution / order dependency is a P0 quality bug.
3. Pyramid is **inverted** — 4385 unit / 525 integration / 93 e2e (88% unit) when Testing Trophy demands integration-heavy.
4. **Core/business modules below 95%:** `agent/runtime_dispatch.py` (58.6%), `orchestration/plan_store.py` (72.4%), `orchestration/workflow_langgraph.py` (51.2%) — these are agent loop and plan engine, P0 critical paths.
5. **Zero coverage** on 4 modules: `observability/otel_exporter.py` (113 stmts), `mcp/_types.py` (91 stmts), `multi_agent/persistent_graph.py` (76 stmts), `plugins/_worker_shim.py` (64 stmts).
6. Markers usage is **inconsistent**: only 2 module-level `pytest.mark.security` decorators despite a dedicated `tests/security/` tier; `requires_*` markers underused.
7. **No property-based, no benchmarks, no snapshot tests, no mutation testing.**

## Coverage Report

### Overall Distribution

| Layer | Coverage | Files | Stmts | Verdict |
|-------|---------:|------:|------:|:--------|
| `core_domain` (protocols, types) | **98.3%** | 27 | 941 | excellent |
| `core_agent` (agent/) | **87.8%** | 12 | 1016 | below 95% target |
| `core_orchestration` | **92.3%** | 35 | 1763 | below 95% target |
| `infra_runtime` | 86.3% | 68 | 5082 | well above 70% |
| `infra_memory` | 89.8% | 16 | 879 | excellent |
| `infra_tools` | 84.1% | 15 | 1104 | well above 70% |
| `infra_serve` | 97.5% | 1 | 81 | excellent |
| `infra_observability` | **70.0%** | 14 | 769 | borderline |
| `infra_session` | 91.9% | 10 | 629 | excellent |
| `infra_hooks` | 96.6% | 4 | 178 | excellent |
| `infra_policy` | 97.1% | 4 | 140 | excellent |
| `infra_skills` | 89.9% | 3 | 207 | good |
| `infra_other` | 81.4% | 147 | 9055 | good |

### Below Target (sorted by remediation priority)

| Module | Current | Target | Stmts | Missing | Priority |
|--------|--------:|-------:|------:|--------:|---------:|
| `observability/otel_exporter.py` | 0.0% | 70% | 113 | 113 | 79.1 |
| `mcp/_types.py` | 0.0% | 70% | 91 | 91 | 63.7 |
| `multi_agent/persistent_graph.py` | 0.0% | 70% | 76 | 76 | 53.2 |
| `plugins/_worker_shim.py` | 0.0% | 70% | 64 | 64 | 44.8 |
| `multi_agent/graph_communication_nats.py` | 21.3% | 70% | 94 | 74 | 36.1 |
| `a2a/client.py` | 22.0% | 70% | 82 | 64 | 30.8 |
| `memory_bank/db_provider.py` | 0.0% | 70% | 43 | 43 | 30.1 |
| `mcp/_server.py` | 29.4% | 70% | 102 | 72 | 29.2 |
| `agent/runtime_dispatch.py` | **58.6%** | **95%** | 181 | 75 | **27.3** |
| `multi_agent/graph_store_postgres.py` | 30.6% | 70% | 98 | 68 | 26.8 |
| `multi_agent/task_queue_postgres.py` | 30.1% | 70% | 83 | 58 | 23.1 |
| `multi_agent/graph_communication_redis.py` | 28.0% | 70% | 75 | 54 | 22.7 |
| `multi_agent/graph_task_board_postgres.py` | 51.6% | 70% | 252 | 122 | 22.5 |
| `orchestration/workflow_langgraph.py` | **51.2%** | **95%** | 43 | 21 | core gap |
| `daemon/health.py` | 53.5% | 70% | 129 | 60 | 16.3 |
| `runtime/agent_sdk_adapter.py` | 38.2% | 70% | 55 | 34 | 15.6 |
| `runtime/openai_agents/runtime.py` | 48.9% | 70% | 90 | 46 | 12.0 |
| `daemon/cli_entry.py` | 61.6% | 70% | 125 | 48 | 11.4 |
| `runtime/codex_adapter.py` | 52.8% | 70% | 53 | 25 | 7.6 |
| `runtime/thin/conversational.py` | **67.3%** | 70% | 165 | 54 | 5.4 |
| `runtime/thin/runtime.py` | **81.7%** | 70% | 279 | 51 | 0 (above target, but core) |

### Critical Uncovered Paths

**`runtime/thin/runtime.py:550-572` — error paths in main run loop:**
- `ThinLlmError` → flush retry events + emit error + Stop hook (not tested when retry buffer non-empty + ThinLlmError)
- Generic `Exception` → "ThinRuntime crash" event + Stop hook (no test on unexpected exception path)

**`runtime/thin/runtime.py:298-320` — guardrail / cancellation paths:**
- `_run_guardrails` failure mid-execution
- `_cancelled_event` emission timing

**`agent/agent.py:357-370` — facade error/finalization branches:** specific failure modes in `query()` finalization not exercised.

**`memory/postgres.py:554-651` — schema migration & error recovery:** fallback paths when DB transaction conflicts with schema mismatch.

**`hooks/__init__.py:23-34` — public API helper edges (4 lines uncovered).**

**`tools/extractors.py` (33.3%, 39 stmts, 26 missed)** — content extraction logic, but minimal current usage.

## Pyramid Balance

| Tier | Tests | Files | Notes |
|------|------:|------:|:------|
| **unit** | 4902 | 294 | 88.6% of total |
| **integration** | 525 | 67 | 9.5% of total |
| **e2e** | 93 | 14 | 1.7% of total |
| **security** | 4 | 1 | dedicated module |
| **architecture** | 3 | 1 | ty strict mode validation |
| **TOTAL** | 5527 | 377 | — |

**Verdict: inverted pyramid**, NOT Testing Trophy.

Testing Trophy expects: integration > unit > e2e (in test-count weight). Current ratio is unit:integration ≈ **9.3:1** while RULES guidance prefers integration as the primary focus. The unit-heavy bias comes from:
- Many `Mock`/`MagicMock` stubs replacing real components (78 files with ≥5 mocks)
- Each runtime adapter (claude-code, deepagents, thin, openai-agents, codex, pi_sdk) has its own >500-line unit test file with heavy mocking

Integration tests are present and well-structured (525 tests, 67 files), but they cover only ~10% of total volume.

## Test Quality

### Smells found

| Smell | Count | Examples |
|-------|------:|:---------|
| Brittle assertions (long literal strings) | 3 | `test_skills.py`: `iss.spec.description == "Search bonds and stocks on Moscow Exchange"`; `test_runtime_types.py`: `msg.name == "mcp__finuslugi__get_bank_deposits"` |
| **Test isolation / pollution** | 14+ | `test_cli_commands.py` — 14 tests fail when run as a file but pass individually; ValueError("I/O operation on closed file") indicates a leaked stdout/stderr handle from CliRunner |
| Hardcoded ports / hosts | ~15 | `test_a2a_adapter.py` — `http://localhost:9000`, `http://test:8000` repeated 13× without parametrize/fixture |
| Mock-heavy units (>5 mocks) | **78 files** | top: `test_llm_providers.py` (128), `test_runtime_adapter.py` (106), `test_hook_dispatcher.py` (79), `test_web_providers.py` (67), `test_deepagents_runtime.py` (67), `test_native_tools.py` (62) |
| Mock-very-heavy (>10 mocks) | **49 files** | indicates implementation coupling — change in private method signature breaks tests |
| Duplicated setup (no fixture) | numerous | `test_a2a_adapter.py` duplicates `SwarmlineA2AAdapter(agent, url=...)` 13× |
| `time.sleep()` in tests | 127 instances | candidate for `pytest-asyncio` `event_loop` patterns or `freezegun`/`time-machine` |

### Test naming compliance

Pattern: `test_<what>_<condition>_<result>`.

- Tests with explicit *condition* keyword (`when/with/after/on/if`): **395** of 4385 unit (≈9%)
- Tests with explicit *result* keyword (`returns/raises/emits/sends/fails/succeeds/skips/denies/allows`): **519** (≈12%)
- Strict 3-part compliance estimate: **~15-20%**

The vast majority follow `test_<what>_<noun>` (e.g., `test_main_help_shows_group_name`, `test_approval_request_creation`), which is acceptable but doesn't make condition vs result explicit.

### Parametrize usage

- **81** `@pytest.mark.parametrize` invocations across 105 files using mocks
- Most heavy parametrize is in `test_coding_profile_wiring.py` (works well — ~30 cases auto-generated)
- Files with copy-paste patterns that should parametrize: `test_a2a_adapter.py` (13× same constructor), `test_web_providers.py` (provider matrix), `test_llm_providers.py` (provider × model matrix)

## Missing Categories

| Category | Status | Recommendation |
|----------|:------:|:---------------|
| Concurrency tests | partial — `test_concurrency_bugs.py` has 9 tests; 224 grep hits but mostly `asyncio.gather` in non-concurrency assertions | add explicit race-condition tests for `SessionManager`, `MemoryProvider` (concurrent write/read), `Scheduler` |
| Performance benchmarks | **missing** — no `pytest-benchmark` | add for hot paths: `runtime/thin/runtime.py::run`, `memory/sqlite.py` upsert, context assembly |
| Property-based (hypothesis) | **missing** | add for `redact_secrets` regex, JSON schema parsers, model alias resolver |
| Mutation testing | **missing** (no mutmut/cosmic-ray) | post-coverage gap closure |
| Load/stress tests | **missing** | add for memory provider concurrent N writers, MCP server stress |
| Snapshot tests | **missing** (no syrupy) | could simplify large structured-output assertions |

## Markers Usage

| Marker | Defined | Used at module-level | Used per-test | Verdict |
|--------|:-------:|---------------------:|--------------:|:--------|
| `security` | yes | 2 (`test_security_provider_parity.py`, `test_security_regression.py`) | 0 individual decorators | underused — security tests in `tests/security/` count as 4, but security regression tests in integration tier (`test_security_regression.py`) duplicate |
| `requires_claude_sdk` | yes | 5 (correct: `test_runtime_adapter`, `test_options_builder`, `test_sdk_query`, `test_hooks_sdk_bridge`, `test_sdk_features_wiring`) | — | adequate |
| `requires_anthropic` | yes | **0** | 0 | not applied — but tests using `anthropic` use `pytest.importorskip` instead |
| `requires_langchain` | yes | **0** | 0 | not applied — `test_deepagents_runtime.py` should use this |
| `live` | yes | 1 (`test_web_search_live.py`) | 0 | adequate (5 live tests) |
| `integration` | yes | 2 (only `test_routine_bridge_integration.py`, `test_postgres_backends_integration.py`) | — | **inconsistent** — most files in `tests/integration/` lack the marker; pytest path includes them but `-m integration` only catches 40 of 525 |
| `slow` | yes | 0 | 0 | unused |

**Key issue**: `pytest -m integration` collects only **40** of 525 tests in `tests/integration/`. Either remove the marker (rely on path) or apply it consistently via `pytestmark = pytest.mark.integration` at every integration module top.

**Live tests**: properly isolated (only 5 collected with `-m live`). Default config `addopts = ["-m", "not live"]` correctly excludes them.

## Fixtures Hygiene

- `tests/conftest.py`: 57 lines, contains 2 fixtures (`_reset_root_logger` autouse, `coding_sandbox`) and one helper class `FakeStreamEvent`. **No tier-specific conftest** — all integration/e2e/security fixtures inline per file.
- 193 `@pytest.fixture` declarations across the suite — substantial but distributed.
- `_reset_root_logger` is good — addresses logging pollution between tests.
- `FakeStreamEvent` placed in `conftest.py` smells of test-helper-as-shared-module; should move to `tests/_factories.py` or similar.
- **Missing**: no `tests/_factories.py` for `Agent`/`RuntimeConfig`/`Message` builders despite 200+ tests constructing these manually.
- **Missing async cleanup discipline**: many tests open SQLite/DB connections without `async with`/teardown — partly explains test pollution observed in `test_cli_commands.py`.

## Coverage Gaps by Critical Component

| Component | Coverage | Comment |
|-----------|---------:|:--------|
| `agent/agent.py` | 95.5% | meets target; missing lines 317-318, 357-368 are error/finalization edges |
| `runtime/thin/runtime.py` | 81.7% | above 70% infra target but core ThinRuntime — should target 90%+; uncovered: error recovery, retry buffer flush, native tool adapter init failure |
| `memory/sqlite.py` | 95.8% | excellent |
| `memory/postgres.py` | 87.0% | good but missing migration/error paths (lines 554-585) |
| `tools/builtin.py` | 84.3% | adequate; uncovered: rare branch in tool registration |
| `tools/extractors.py` | **33.3%** | unused branch — either delete or test |
| `serve/app.py` | 97.5% | excellent; only loopback gates lines 110-111 missing |
| `observability/redaction.py` | 92.9% | excellent; line 83 uncovered (likely fallback) |
| `session/manager.py` | 93.9% | excellent |
| `session/runtime_bridge.py` | 82.6% | good |
| `session/backends_postgres.py` | **50.0%** | gap (32 stmts, 16 missed) — postgres integration light |
| `hooks/dispatcher.py` | 98.0% | excellent |
| `hooks/__init__.py` | 75.0% | only 16 stmts; lines 23, 27, 33, 34 uncovered (likely re-exports/edges) |
| `policy/tool_policy.py` | 98.2% | excellent |

## Top 10 Modules Needing Tests

| # | Module | Current | Target | Suggested test type | Priority |
|--:|--------|--------:|-------:|:--------------------|:---------|
| 1 | `observability/otel_exporter.py` | 0.0% | 70% | unit + integration with otel-test-collector | P0 |
| 2 | `agent/runtime_dispatch.py` | 58.6% | 95% | integration (real adapters) — core dispatch | P0 |
| 3 | `orchestration/workflow_langgraph.py` | 51.2% | 95% | integration with langgraph stub or skip-if-no-langgraph | P0 |
| 4 | `mcp/_types.py` | 0.0% | 70% | unit (likely just dataclass roundtrip) | P1 |
| 5 | `mcp/_server.py` | 29.4% | 70% | integration with MCP test client | P1 |
| 6 | `multi_agent/persistent_graph.py` | 0.0% | 70% | unit + integration | P1 |
| 7 | `multi_agent/graph_task_board_postgres.py` | 51.6% | 70% | integration (postgres testcontainer) | P1 |
| 8 | `daemon/health.py` | 53.5% | 70% | integration (HTTP test client) | P2 |
| 9 | `runtime/openai_agents/runtime.py` | 48.9% | 70% | unit + integration | P2 |
| 10 | `runtime/codex_adapter.py` | 52.8% | 70% | unit | P2 |

## Test Pollution / Failures Audit

**P0 quality issue**: 143 failed + 69 errors in full run despite passing in isolation:

```
test_cli_commands.py (14/34 fail in batch, 0 in isolation)
test_coding_profile_wiring.py (60+ fail in batch)
test_daemon_runner.py (10 fail)
test_event_bus.py (6 fail)
test_executor_policy.py (4 fail)
test_mcp_server.py + test_mcp_session.py + test_mcp_tools_*.py (60+ fail/error)
test_openai_agents_runtime.py (6 fail)
test_tool_policy.py (20 fail in batch — but ALL 20 PASS in isolation)
```

Root cause symptoms observed:
1. `ValueError("I/O operation on closed file.")` — Click `CliRunner` leaving stdout in unusable state across tests in the same file
2. Module-level state in policy/cli leaking between tests
3. Async event-loop teardown timing (asyncio "Task exception was never retrieved" warnings)

This is NOT a coverage gap — it's a **test contract violation** (RULES: "tests must pass for ANY correct implementation"). Tests have implicit ordering assumptions that the suite does not enforce.

## Recommendations

### v1.5.1 quick wins (≤ 1 day)

- [ ] **Fix test pollution in `test_cli_commands.py`** (14 failures): isolate `CliRunner` per-test or use `runner.isolated_filesystem()`. Same pattern likely applies to `test_coding_profile_wiring.py`, `test_daemon_*`.
- [ ] **Apply `pytestmark = pytest.mark.integration`** to all 67 files in `tests/integration/` so `-m integration` filtering works (currently catches 40/525).
- [ ] **Add `pytestmark = pytest.mark.requires_anthropic`** to tests using `anthropic` SDK and `pytestmark = pytest.mark.requires_langchain` to deepagents tests (~10 files).
- [ ] **Enable branch coverage** in `pyproject.toml`: `[tool.coverage.run] branch = true`. Currently statement-only — branch coverage typically reveals 5-10% additional gaps.
- [ ] **Delete `tools/extractors.py`** if unused (33% coverage suggests dead code) or write 3 tests for it.
- [ ] Move `FakeStreamEvent` from `conftest.py` to `tests/_factories.py`.

### v1.6.0 (≤ 1 week)

- [ ] **Refactor `test_a2a_adapter.py`** with parametrize fixture for the URL constructor (eliminates 13× duplication).
- [ ] **Bring `agent/runtime_dispatch.py` to 95%** — write 5 integration tests covering each runtime selection path.
- [ ] **Bring `orchestration/workflow_langgraph.py` to 90%+** or gate it behind `requires_langchain` and skip when not installed.
- [ ] **Cover zero-coverage modules** (`otel_exporter`, `_types.py`, `persistent_graph`, `_worker_shim`) — even basic happy-path tests get them to 60-80%.
- [ ] **Add 5 property-based tests via Hypothesis** for high-value invariants:
  - `redact_secrets()` — never includes secret characters in output
  - JSON schema parsers — roundtrip serialization
  - `tool_id_codec` — encode/decode is identity
  - Model alias resolver — alphabetical resolution order
  - Path isolation in sandbox — no traversal escape
- [ ] **Convert 10 mock-heavy unit tests to integration**: target files with 10+ mocks (e.g., `test_runtime_adapter.py`, `test_llm_providers.py`) — extract real-collaborator versions.
- [ ] **Add explicit concurrency tests** for memory providers (concurrent upsert + read), `Scheduler` (max_concurrent_tasks enforcement).

### v2.0.0 (long-term)

- [ ] **Pytest-benchmark integration** with regression budget on PR checks: ThinRuntime cold start, SQLite upsert/get, context assembly token count.
- [ ] **Mutation testing** with `mutmut` against `agent/`, `protocols.py`, `policy/` — score ≥ 70% mutation kill rate.
- [ ] **Snapshot tests via syrupy** for stable structured outputs (RuntimeEvent JSON, planning artifacts).
- [ ] **Test factories module** (`tests/_factories.py`) replacing manual construction of Agent/RuntimeConfig/Message.
- [ ] **Tier-specific conftest.py** with shared fixtures per `tests/integration/conftest.py` (postgres testcontainer, fake LLM).
- [ ] **Restore strict pyramid balance** — target 60% integration / 30% unit / 10% e2e by test count.
- [ ] **Split `tests/unit/test_deepagents_runtime.py` (1358 lines)** and `test_llm_providers.py` (1197 lines) — too large to navigate.

## Conclusion

swarmline v1.5.0 sits at **85.17% overall coverage** — exactly meeting the RULES minimum but with **zero margin** and several P0 issues that undermine the headline number: 143 tests fail in full pytest runs due to pollution despite passing individually, the pyramid is sharply inverted (88% unit / 10% integration), and 4 modules totaling 344 statements have 0% coverage. Core/business modules are below the 95% target — most critically `agent/runtime_dispatch.py` (58.6%) and `orchestration/workflow_langgraph.py` (51.2%), both of which are central to the agent loop. Markers are inconsistently applied; `-m integration` filters out 92% of integration tests because they lack the marker. Recommend prioritizing test isolation fixes and the top-10 module gaps before any new feature work — coverage debt compounds quickly when a single new module without tests can drop below the 85% gate.
