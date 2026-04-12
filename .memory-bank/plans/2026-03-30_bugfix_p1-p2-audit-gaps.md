# P1/P2 Audit Gaps — Correctness, Security, Concurrency Fixes
Дата: 2026-03-30
Тип: bugfix
Статус: 🟡 В работе

## Контекст

Полный аудит библиотеки v1.2.0 выявил 15 issues (3 P1, 8 P2, 4 P3/security). P1 — ошибки корректности в core execution path: ложное completion, игнорирование per-call config, неконсистентный task state. P2 — concurrency, security, resource management. Без исправления P1 нельзя доверять результатам pipeline/orchestrator.

## Scope

**Входит:** P1-1..P1-3 (correctness), P2-1..P2-9 (concurrency, security, resources), P3 observability bounds.
**НЕ входит:** новые фичи, рефакторинг архитектуры, PyPI release.

## Архитектурные решения

- Минимальные точечные фиксы — не менять API surface
- Каждый fix backward-compatible (default behavior не ломается)
- Security defaults: deny-by-default, explicit opt-in для опасного
- Все фиксы покрыты regression-тестами

---

## Этап 1: P1 — False-green completion + task state consistency

**Цель:** Pipeline и orchestrator корректно различают success/failure/timeout/cancel. Task board state всегда отражает реальное состояние.

**Файлы:**
- `src/swarmline/multi_agent/graph_orchestrator.py` — checkout tasks, mark failed/cancelled on board
- `src/swarmline/pipeline/pipeline.py` — check wait_for_task result, fail phase on None

**Реализация:**

1. **Orchestrator — checkout tasks:** `start()` и `delegate()` вызывают `checkout_task()` после `create_task()` чтобы перевести task в IN_PROGRESS и установить checkout_agent_id.

2. **Orchestrator — mark failed on board:** В `_execute_agent()` после исчерпания retries вызвать task_board update (set status=CANCELLED через replace + write, т.к. нет fail_task method). Либо добавить в GraphTaskBoard `cancel_task(task_id)` — уже есть `complete_task()`.

3. **Orchestrator — mark cancelled on board:** В `except asyncio.CancelledError` block — update task board status to CANCELLED.

4. **Pipeline — check wait_for_task result:** `_execute_phase_orchestration()` проверяет return value от `wait_for_task()`. Если None — фаза FAILED, не COMPLETED.

5. **wait_for_task — propagate errors:** Вместо swallow всех exceptions, различать timeout (return None) и success (return result). Или добавить отдельный метод `get_task_status(task_id)`.

**Тесты (TDD):**
- Unit: `test_start_checks_out_root_task` — после start, task на board в IN_PROGRESS
- Unit: `test_failed_agent_marks_task_cancelled_on_board` — после failure, task board status != TODO
- Unit: `test_cancelled_agent_marks_task_cancelled_on_board` — после cancel, board updated
- Unit: `test_pipeline_phase_fails_when_root_agent_fails` — pipeline phase status FAILED not COMPLETED
- Unit: `test_wait_for_task_returns_none_on_failure` — timeout/cancel → None

**DoD:**
- [ ] start() calls checkout_task() — task goes IN_PROGRESS on board
- [ ] delegate() calls checkout_task()
- [ ] Failed agent → task board CANCELLED + orchestrator FAILED
- [ ] Cancelled agent → task board CANCELLED
- [ ] Pipeline phase FAILED when wait_for_task returns None
- [ ] 5+ regression tests
- [ ] Все существующие тесты green
- [ ] ruff clean

---

## Этап 2: P1 — ThinRuntime per-call config for LLM path

**Цель:** Per-call RuntimeConfig override корректно применяется к LLM вызову, а не только к guardrails/cost.

**Файлы:**
- `src/swarmline/runtime/thin/runtime.py` — rebuild llm_call for per-call config

**Реализация:**

1. **Вместо closure, создавать llm_call per-call:** Если `config` передан в `run()` и отличается от `self._config`, создать temporary llm_call с новым config. Cache по identity config object.

2. **Или проще:** `_make_default_llm_call()` принимает config как параметр, а не захватывает self._config. В `run()` передавать effective_config.

3. **Event bus wrapping:** Если effective_config.event_bus отличается от constructor, wrap заново.

**Тесты (TDD):**
- Unit: `test_per_call_config_uses_different_model` — mock llm_call, verify config.model passed
- Unit: `test_per_call_config_uses_different_provider` — verify base_url from override
- Unit: `test_default_config_when_no_override` — без override используется constructor config
- Unit: `test_cancel_token_from_per_call_config` — cancel token из override, не из constructor

**DoD:**
- [ ] Per-call config.model применяется к LLM вызову
- [ ] Per-call config.base_url/provider применяется
- [ ] Per-call cancel token работает
- [ ] Default (no override) работает как раньше
- [ ] 4+ regression tests
- [ ] ruff clean

---

## Этап 3: P2 — Concurrency fixes (WorkflowGraph, SessionManager, Scheduler)

**Цель:** Concurrent execution безопасна: no shared mutable state, no event loop blocking, bounded concurrency.

**Файлы:**
- `src/swarmline/orchestration/workflow_graph.py` — per-execution interrupt tracking
- `src/swarmline/session/manager.py` — async backend calls
- `src/swarmline/daemon/scheduler.py` + `types.py` — honor max_concurrent_tasks

**Реализация:**

1. **WorkflowGraph.resume():** Заменить shared `self._interrupts: set` на per-execution context. Передавать `execution_id` в execute/resume, хранить interrupts в dict[execution_id, set].

2. **SessionManager:** Заменить `_run_awaitable_sync()` на `await` в async методах. Для sync-path — `asyncio.run_coroutine_threadsafe()` или `asyncio.to_thread()`.

3. **Scheduler:** Принять config в __init__, добавить `asyncio.Semaphore(config.max_concurrent_tasks)`, acquire перед _run_task.

**Тесты (TDD):**
- Unit: `test_concurrent_resume_isolated` — два concurrent execute, один resume не ломает другой
- Unit: `test_session_manager_async_backend_not_blocking` — verify await, not sync call
- Unit: `test_scheduler_honors_max_concurrent` — запустить 10 tasks, verify max N running

**DoD:**
- [ ] WorkflowGraph per-execution interrupt isolation
- [ ] SessionManager async backend calls (no event loop blocking)
- [ ] Scheduler uses Semaphore(max_concurrent_tasks)
- [ ] 3+ regression tests
- [ ] ruff clean

---

## Этап 4: P2 — SQLite thread safety + task queue performance

**Цель:** SQLite backends thread-safe. Task queue get() scales O(1) instead of O(N).

**Файлы:**
- `src/swarmline/memory/episodic_sqlite.py` — add threading.Lock or check_same_thread=False
- `src/swarmline/multi_agent/task_queue.py` — SQL WHERE instead of Python filter

**Реализация:**

1. **Episodic SQLite:** `check_same_thread=False` + `threading.Lock` вокруг всех conn operations. Или per-thread connection через threading.local().

2. **Task queue get():** Добавить indexed columns status/priority в SQL schema. Rewrite _claim_one_sync: `SELECT data FROM tasks WHERE json_extract(data, '$.status')='todo' ORDER BY ... LIMIT 1`. Или лучше: denormalize status+priority в SQL columns (как Postgres backend).

**Тесты (TDD):**
- Unit: `test_episodic_concurrent_store_recall` — parallel asyncio.to_thread calls
- Unit: `test_task_queue_get_with_large_queue` — 1000 tasks, get() should be fast
- Integration: `test_task_queue_indexed_claim` — verify only matching rows fetched

**DoD:**
- [ ] Episodic SQLite thread-safe (no SQLite thread errors under load)
- [ ] Task queue get() uses SQL-level filtering
- [ ] 3+ tests
- [ ] ruff clean

---

## Этап 5: P2 — Security hardening (sandbox, SSRF, workspace, A2A, Docker)

**Цель:** Security defaults safe-by-default. Untrusted input validated. Sandbox isolation enforced.

**Файлы:**
- `src/swarmline/tools/web_httpx.py` — DNS resolution + per-hop redirect validation
- `src/swarmline/multi_agent/workspace.py` — slug validation for IDs
- `src/swarmline/a2a/server.py` — auth middleware hook + request size limit
- `src/swarmline/tools/sandbox_docker.py` — cap-drop, network=none, memory/cpu limits
- `src/swarmline/mcp/_tools_code.py` — explicit trusted-only warning + opt-in flag
- `src/swarmline/daemon/health.py` — wire auth_token through config

**Реализация:**

1. **SSRF:** Resolve hostname → validate all A/AAAA records → block private/loopback. Disable follow_redirects, manually follow with per-hop validation. Or use httpx event hooks.

2. **Workspace:** `_validate_slug(id: str)` — alphanumeric + dash + underscore, max 64 chars. Apply to agent_id and task_id before path construction.

3. **A2A server:** Add optional `auth_middleware` parameter. Default: no auth (backward compat) but log warning if bound to non-localhost. Add `max_request_size` (default 1MB).

4. **Docker sandbox:** Add security_opt, cap_drop, mem_limit, cpu_quota, network_mode params to DockerSandboxConfig. Defaults: `cap_drop=["ALL"]`, `network_mode="none"`, `mem_limit="256m"`.

5. **MCP code exec:** Add `trusted_only: bool = True` flag. If True (default), refuse execution unless caller confirms trust. Log warning.

6. **Daemon health auth:** Add `auth_token` to DaemonConfig, wire through to HealthServer in runner.

**Тесты (TDD):**
- Unit: `test_ssrf_blocks_dns_resolved_private` — hostname resolving to 127.0.0.1 blocked
- Unit: `test_ssrf_blocks_redirect_to_private` — redirect chain to private IP blocked
- Unit: `test_workspace_rejects_path_traversal_id` — `../../` in agent_id rejected
- Unit: `test_a2a_auth_rejects_unauthenticated` — request without token → 401
- Unit: `test_docker_sandbox_default_cap_drop` — container started with cap_drop=ALL
- Unit: `test_mcp_code_exec_trusted_only` — execution refused without trust flag

**DoD:**
- [ ] SSRF validates DNS-resolved IPs + redirect hops
- [ ] Workspace IDs validated as slugs
- [ ] A2A server supports auth middleware
- [ ] Docker sandbox safe defaults (cap-drop, no-network, memory limit)
- [ ] MCP code exec trusted-only flag
- [ ] Daemon auth wired through config
- [ ] 6+ tests
- [ ] ruff clean

---

## Этап 6: P3 — Observability bounds + final verification

**Цель:** Observability state bounded. All tests pass. Gates green.

**Файлы:**
- `src/swarmline/observability/activity_log.py` — retention/max_entries
- `src/swarmline/observability/tracer.py` — prune ended spans

**Реализация:**

1. **Activity log:** Add `max_entries: int = 10000` to config. On append, if over limit, evict oldest. count() uses `SELECT COUNT(*)` instead of full materialization.

2. **Tracer:** ConsoleTracer prunes `_spans` dict on end_span (move to completed list with max size, or just delete).

**Тесты (TDD):**
- Unit: `test_activity_log_evicts_oldest` — append 10001, oldest evicted
- Unit: `test_tracer_prunes_ended_spans` — ended spans not retained indefinitely

**DoD:**
- [ ] Activity log bounded (max_entries)
- [ ] Tracer spans pruned
- [ ] Full test suite green (3909+)
- [ ] ruff clean
- [ ] mypy 0 real errors
- [ ] Все 15 audit gaps closed

---

## Этап 7: Integration Tests — новые модули

**Цель:** Покрыть integration-тестами все новые модули, у которых есть только unit-тесты. Проверить взаимодействие компонентов друг с другом и с реальными backends.

**Файлы (новые тесты):**
- `tests/integration/test_knowledge_bank_integration.py`
- `tests/integration/test_memory_lifecycle_integration.py`
- `tests/integration/test_pipeline_budget_integration.py`
- `tests/integration/test_hitl_integration.py`
- `tests/integration/test_plugin_registry_integration.py`
- `tests/integration/test_daemon_lifecycle_integration.py`
- `tests/integration/test_graph_task_progress_integration.py`

**7a. Knowledge Bank (store + search + consolidation)**
- `test_save_search_roundtrip` — save entry via DefaultKnowledgeStore (FS backend) → search via DefaultKnowledgeSearcher → verify found
- `test_save_updates_index_json` — save → verify index.json created on FS
- `test_consolidation_to_store` — create episodes → consolidate → save → search → verify notes found
- `test_checklist_progress_via_provider` — add items → toggle → get_items through real FS provider
- `test_knowledge_tools_e2e` — knowledge_search/save_note/get_context tools through InMemory store+searcher

**7b. Memory Lifecycle (episodic + procedural + SQLite)**
- `test_episodic_store_recall_sqlite` — store episode → recall by query via SQLite backend
- `test_procedural_store_get_sqlite` — store procedure → get_best → verify ranking
- `test_episodic_procedural_together` — агент store episode + procedure → recall both
- `test_consolidation_episodes_to_knowledge` — episodic episodes → consolidation → knowledge entries

**7c. Pipeline + Budget**
- `test_pipeline_two_phases_sequential` — build pipeline (2 phases) → run → verify both COMPLETED
- `test_pipeline_budget_gate_stops` — pipeline with budget gate → exceed budget → verify stopped
- `test_pipeline_phase_failure_skips_remaining` — phase 1 fails → phase 2 SKIPPED

**7d. HITL Gates**
- `test_hitl_approval_gate_blocks_until_approved` — create gate → trigger → verify blocked → approve → verify passed
- `test_hitl_auto_approve_policy` — auto-approve policy → gate passes immediately

**7e. Plugin Registry**
- `test_plugin_register_discover_call` — register plugin → discover → call method → verify response
- `test_plugin_runner_lifecycle` — start subprocess → ping → call → stop

**7f. Daemon Lifecycle**
- `test_scheduler_fires_tasks` — add periodic task → advance time → verify fired
- `test_routine_bridge_creates_board_tasks` — RoutineBridge creates GraphTaskItems from scheduled routines

**7g. Graph Task Progress**
- `test_progress_propagation_with_sqlite` — 3-level task tree via SQLite board → complete leaves → verify progress cascades
- `test_blocked_task_prevents_parent_completion_sqlite` — block child → parent NOT auto-complete
- `test_workflow_stage_roundtrip_sqlite` — create task with stage → checkout → complete → verify stage preserved

**Тесты:** ~22 integration tests

**DoD:**
- [ ] Knowledge Bank: 5 integration tests (store, search, consolidation, checklist, tools)
- [ ] Memory lifecycle: 4 integration tests (episodic SQLite, procedural SQLite, together, consolidation)
- [ ] Pipeline + budget: 3 integration tests (sequential, budget gate, failure skip)
- [ ] HITL: 2 integration tests (block/approve, auto-approve)
- [ ] Plugin: 2 integration tests (register/discover, subprocess lifecycle)
- [ ] Daemon: 2 integration tests (scheduler, routine bridge)
- [ ] Graph task progress: 3 integration tests (propagation, blocked, stage roundtrip)
- [ ] Все тесты green, ruff clean

---

## Этап 8: E2E Tests — ключевые user workflows

**Цель:** Покрыть e2e-тестами основные пользовательские сценарии новых фич. Проверить что компоненты работают вместе от начала до конца.

**Файлы (новые тесты):**
- `tests/e2e/test_knowledge_agent_e2e.py`
- `tests/e2e/test_graph_orchestration_e2e.py`
- `tests/e2e/test_pipeline_e2e.py`
- `tests/e2e/test_daemon_e2e.py`

**8a. Knowledge-Aware Agent**
- `test_agent_saves_and_recalls_knowledge` — агент через tools сохраняет заметку → в следующем turn ищет → находит. Проверяет: Knowledge Bank tools работают в агентном контексте.
- `test_agent_consolidates_episodes` — несколько episodes → consolidation → agent ищет consolidated notes

**8b. Graph Orchestration Full Cycle**
- `test_org_chart_delegation_e2e` — build 3-level org (CEO → CTO → 2 engineers) → start goal → CEO delegates → engineers execute → results bubble up → goal DONE. Проверяет: полный цикл hierarchical multi-agent.
- `test_governance_blocks_unauthorized_hire` — engineer tries hire → governance blocks → escalation. Проверяет: governance enforcement end-to-end.
- `test_progress_tracking_e2e` — start goal → partial completion → verify progress 0.5 → complete rest → progress 1.0 + auto-complete

**8c. Pipeline Full Cycle**
- `test_two_phase_pipeline_e2e` — define 2-phase pipeline → run → both phases complete → final result. Проверяет: pipeline builder → execution → result collection.
- `test_pipeline_with_budget_limit` — pipeline с budget → run → budget exceeded → pipeline stops gracefully

**8d. Daemon Lifecycle**
- `test_daemon_start_schedule_stop` — start daemon → add scheduled task → wait for execution → stop gracefully. Проверяет: daemon lifecycle end-to-end.

**Тесты:** ~9 e2e tests

**DoD:**
- [ ] Knowledge agent: 2 e2e tests (save/recall, consolidation)
- [ ] Graph orchestration: 3 e2e tests (delegation cycle, governance, progress)
- [ ] Pipeline: 2 e2e tests (full cycle, budget limit)
- [ ] Daemon: 1 e2e test (start/schedule/stop)
- [ ] Нет mock'ов внешних сервисов — всё через InMemory backends
- [ ] Все тесты green, ruff clean

---

## Риски и mitigation

| Риск | Вероятность | Влияние | Mitigation |
|------|-------------|---------|------------|
| checkout_task() ломает existing tests | Средняя | Тесты fail | Существующие тесты не проверяют board state explicitly; new tests needed |
| Per-call config rebuild llm_call — performance | Низкая | Latency на hot path | Cache по config identity; rebuild только при смене config |
| SSRF DNS validation — false positives | Средняя | Legitimate URLs blocked | Allowlist для known internal hosts |
| Docker cap-drop — breaks workloads needing NET | Средняя | Container network fails | Explicit opt-in `network_enabled=True` |

## Зависимости

```
Этап 1 (P1 correctness) → Этап 2 (P1 config) → Этап 3-5 (P2, параллельно) → Этап 6 (P3)
                                                                                    ↓
Этап 7 (integration tests) — после этапов 1-5 (тестируем зафиксированный код)
                                                                                    ↓
Этап 8 (e2e tests) — после этапа 7 (e2e строятся поверх integration)
```

Этапы 1-2 (P1) — blocking, делать первыми.
Этапы 3-5 (P2) — можно параллельно между собой.
Этап 6 — P3 bounds.
Этап 7 — integration tests (можно начать параллельно с 3-6 для модулей которые не меняются).
Этап 8 — e2e tests, финальный.

## Оценка

| Этап | Сложность | ~Файлов | ~Тестов |
|------|-----------|---------|---------|
| 1. P1 task state | Medium | 2 | 5 |
| 2. P1 per-call config | Medium | 1 | 4 |
| 3. P2 concurrency | Medium | 3 | 3 |
| 4. P2 SQLite + queue | Medium | 2 | 3 |
| 5. P2 security | High | 6 | 6 |
| 6. P3 observability | Low | 2 | 2 |
| 7. Integration tests | Medium | 7 | 22 |
| 8. E2E tests | Medium | 4 | 9 |
| **Total** | | **~27** | **~54** |
