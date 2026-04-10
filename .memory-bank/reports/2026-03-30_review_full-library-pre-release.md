---
kind: report
tags: [code-review, pre-release, full-library, v1.2.0]
importance: high
created: 2026-03-30
updated: 2026-03-30
---

# Full Library Pre-Release Review — v1.2.0
Дата: 2026-03-30
Файлов проверено: ~40 (4 domain reviews)
Тесты: 3972 passed, 0 failed, ruff clean, mypy clean

## Gates

| Gate | Статус |
|------|--------|
| Tests | 3972 pass, 0 fail |
| Ruff | All checks passed |
| Mypy | 0 real errors |

## Критичное (6 findings)

### C1: MCP code exec blocklist тривиально обходится
**File:** `mcp/_tools_code.py:20-38`
String blocklist обходится через eval, getattr, importlib, __import__, пробелы/переносы. MCP server прошивает `trusted=True` — любой клиент получает host execution.
**Rec:** Заменить blocklist на real sandbox (Docker/E2B) или RestrictedPython. Blocklist fundamentally insecure.

### C2: FTS5 index drift — отсутствуют UPDATE/DELETE triggers
**File:** `memory/episodic_sqlite.py:52-56`
При `INSERT OR REPLACE` (=DELETE+INSERT) нет BEFORE DELETE trigger. FTS5 накапливает stale entries, recall() возвращает дубликаты.
**Rec:** Добавить `episodes_bd` (BEFORE DELETE) и `episodes_bu`/`episodes_au` (UPDATE) triggers.

### C3: SSRF через DNS rebinding (TOCTOU)
**File:** `tools/web_httpx.py:73-122`
DNS resolution в `_validate_url` и httpx fetch используют разные DNS-запросы. DNS rebinding позволяет bypass. Также нет scheme whitelist (`file://` не блокирован).
**Rec:** Подставлять resolved IP в URL для httpx, добавить scheme whitelist `("http", "https")`.

### C4: Orchestrator retry storm — semaphore monopolization
**File:** `graph_orchestrator.py:282-354`
Retry без backoff немедленно re-acquire semaphore, блокируя новые задачи при массовых сбоях.
**Rec:** Exponential backoff (`2 ** attempt * base_delay`) перед `async with self._semaphore`.

### C5: Task board read methods без lock — dict iteration race
**File:** `graph_task_board.py:86-109`
`get_ready_tasks()`, `get_subtasks()`, `list_tasks()` читают `self._tasks` без lock. Concurrent mutation → `RuntimeError: dictionary changed size during iteration`.
**Rec:** Обернуть read-методы в `async with self._lock`.

### C6: SessionManager.run_turn() вызывает sync get() в async контексте
**File:** `session/manager.py:299, 358`
`run_turn` и `stream_reply` вызывают `self.get()` (sync+thread.join) вместо `await self.aget()`. Блокирует event loop при наличии backend.
**Rec:** Заменить на `await self.aget(key)`.

## Серьёзное (9 findings)

### S1: Denied delegation оставляет orphaned task на board
**File:** `graph_orchestrator.py:192-198`
Task создан + checked out, но при denial не отменяется. Stays IN_PROGRESS forever.

### S2: CANCELLED children блокируют parent auto-completion
**File:** `graph_task_board.py:213`
`all(c.status == TaskStatus.DONE)` не учитывает CANCELLED. Parent stuck.

### S3: Scheduler task overlap — нет проверки running instance
**File:** `daemon/scheduler.py:170-196`
Slow periodic task + next tick = duplicate instances. Нет `task.running` check.

### S4: Docker sandbox shell injection в glob_files
**File:** `tools/sandbox_docker.py:199-208`
`sh -c` в контейнере — sandbox запрещает `sh` пользователям, но использует сам.

### S5: Knowledge Bank index race condition (concurrent save)
**File:** `memory_bank/knowledge_store.py:113-130`
Read-modify-write без lock. Concurrent saves теряют index entries.

### S6: LocalSandboxProvider — host execution без env filtering
**File:** `tools/sandbox_local.py:130-166`
Процесс наследует все env vars (secrets). Нет CPU/memory limits.

### S7: Episodic SQLite _get_conn без lock на инициализацию
**File:** `memory/episodic_sqlite.py:22-29`
Race при первой инициализации (два потока создают два connection).

### S8: Redis/NATS EventBus — asyncio.ensure_future в sync subscribe
**File:** `event_bus_redis.py:89, event_bus_nats.py:78`
Fire-and-forget subscription. Race с первым emit, crash вне event loop.

### S9: Orchestrator _runs/_results unbounded growth
**File:** `graph_orchestrator.py:94-98`
Dictionaries never cleaned. Memory leak в long-running daemon.

## Замечания (15 findings)

- W1: Pipeline hardcodes `root-{run_id}` task ID format (fragile coupling)
- W2: escalate tool — unreachable code branch, duplicate get_chain_of_command
- W3: consolidation.py uses `Any` instead of EpisodicMemory Protocol
- W4: consolidation._stored_facts unbounded list growth
- W5: episodic_sqlite recall_by_tag false positives via LIKE
- W6: A2A server _build_task mutates input dict via pop()
- W7: Knowledge searcher _index never invalidated (stale cache)
- W8: TracingSubscriber/_spans orphaned spans grow unbounded (no TTL)
- W9: Workflow parallel node state merge — last writer wins, no conflict detection
- W10: SessionManager monotonic→wall-clock conversion fragile on NTP drift
- W11: InMemoryActivityLog eviction via list slice (use deque)
- W12: SqliteActivityLog no __aenter__/__aexit__ (connection leak)
- W13: OTelExporter dual bus paths (constructor + attach)
- W14: InMemoryActivityLog.count() does full sort for len()
- W15: Dispatch callback errors silently swallowed in Redis/NATS bus

## Тесты
- Unit: ✅ 3972/3972
- Ruff: ✅ Clean
- Mypy: ✅ 0 real errors
- Интеграционные: ⚠️ Gaps в Knowledge Bank, Memory lifecycle, Pipeline budget
- E2E: ⚠️ Gaps в graph orchestration full cycle, daemon lifecycle

## Положительное

- **ISP compliance** — все 34 протокола <= 5 методов
- **Docker sandbox hardening** — cap_drop=ALL, no-network, mem_limit, no-new-privileges
- **SSRF multi-layer defense** — DNS check + metadata blocklist + private IP + no redirects
- **Path traversal protection** — resolve() + is_relative_to() + slug validation
- **Atomic operations** — checkout_task under lock, file writes via tempfile+replace
- **Dual sync/async API** — SessionManager get/aget, register/aregister
- **Per-execution workflow isolation** — _skip_interrupts + _start_node (no shared mutation)
- **Timing-safe auth** — hmac.compare_digest в A2A server

## Итог

**6 CRITICAL, 9 SERIOUS, 15 WARNINGS.** Для v1.2.0 release — C1 (MCP blocklist) самый высокий риск, но он документирован как "trusted only". C2 (FTS5 triggers) — data corruption risk. C4-C6 — production correctness. Рекомендация: **C2, C4, C5, C6 исправить до release** (они в our code, minimal effort). C1, C3 — документировать как known limitations, fix в v1.3.0.
