# Code Audit: Uncommitted Code (2026-03-29)

## Статистика
- 39 файлов, ~5200 строк кода, ~2040 строк тестов, 373 теста (все passed)
- ruff check: All passed
- 4 параллельных ревьюера: daemon, pipeline, multi_agent, misc

## Общий вердикт: NEEDS_CHANGES (5.6/10)

| Модуль | CRITICAL | SERIOUS | WARNING | Оценка |
|--------|----------|---------|---------|--------|
| daemon | 3 | 4 | 6 | 6.5/10 |
| pipeline | 3 | 4 | 5 | 5/10 |
| multi_agent | 3 | 5 | 6 | 6/10 |
| misc (memory/obs/session) | 2 | 5 | 5 | 5/10 |
| **ИТОГО** | **11** | **18** | **22** | **5.6/10** |

## CRITICAL findings (11)

### Security (3)
- C1: daemon health.py:117 — timing attack на auth_token (нет hmac.compare_digest)
- C2: misc procedural_sqlite.py:90 — FTS5 SQL injection (спецсимволы не escaped)
- C3: misc procedural_postgres.py:132 — f-string в SQL query (latent injection)

### Correctness (6)
- C4: daemon cli_entry.py:152-159 — CLI pause/resume без --token (401 при auth daemon)
- C5: daemon runner.py:171-176 — signal handler restore сломан (add_signal_handler returns None)
- C6: pipeline pipeline.py:167-177 — доступ к приватным attrs orchestrator (_graph, _bg_tasks)
- C7: pipeline budget.py:84-122 — wrap_runner записывает cost_usd=0.0 (budget enforcement мёртвый)
- C8: pipeline budget.py:59-64 — is_exceeded() не проверяет per-phase/per-agent limits
- C9: multi_agent graph_orchestrator.py:163 — `max_retries or` bug (0 falsy → игнорируется)

### Data Loss (2)
- C10: multi_agent graph_communication_postgres.py — metadata + created_at теряются при round-trip
- C11: multi_agent graph_communication_nats.py — get_inbox/get_thread на local cache only (durability false guarantee)

## SERIOUS findings (18)

### Architecture/DIP (4)
- S1-S4: Массовое использование Any вместо Protocol types (pipeline builder, orchestrator, graph_tools, runner)

### Correctness (7)
- S5: CLI defaults перезаписывают YAML config
- S6: scheduler fire-and-forget tasks без tracking при shutdown
- S7: pipeline inconsistent goal passing
- S8: timeout_seconds мёртвое поле
- S9: SQLite task board non-atomic completion propagation
- S10: SQLite find_by_role full table scan + Python filter
- S11: semaphore re-acquire на каждый retry

### Code Quality (4)
- S12: 6 мест manual GraphTaskItem construction вместо replace()
- S13: Postgres backends без ensure_schema()
- S14: ensure_future в sync контексте (event_bus_nats/redis)
- S15: Нет [nats]/[redis] extras в pyproject.toml

### Testing (3)
- S16: Postgres tests — 0 behavioral tests
- S17: Contract tests GraphTaskBoard не параметризованы по SQLite
- S18: Pipeline — нет тестов concurrent run, timeout, cost, warning

## Системные паттерны
1. **Any epidemic** — 15+ мест вместо Protocol types
2. **Data loss в distributed backends** — metadata/created_at теряются
3. **Отсутствие schema lifecycle** — Postgres DDL не вызывается
4. **Timing-dependent tests** — asyncio.sleep flaky

## Приоритеты фиксов
- Tier 1 (блокеры): C1, C2, C4, C7, C9, C10
- Tier 2 (серьёзные): S2/S3/S4 Any→Protocol, S5, S6, S12, S15
- Tier 3 (backlog): WARNING-level, test parametrization, schema lifecycle
