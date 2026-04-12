# Code Review Report
Дата: 2026-03-29 17:45
Файлов проверено: 24 (14 src + 10 tests)
Строк изменено: +2080 / -0 (все новые файлы) + 83 строки в __init__.py

## Критичное

*Нет критичных проблем.*

## Серьёзное

### S1. `list_active()` в LocalWorkspace не берёт lock
**Файл**: `src/swarmline/multi_agent/workspace.py:83`
```python
async def list_active(self) -> list[WorkspaceHandle]:
    return list(self._active.values())
```
`create()` и `cleanup()` используют `async with self._lock`, но `list_active()` читает `_active` без lock. При concurrent create/cleanup + list_active возможна race condition (итератор видит partial state).
**Рекомендация**: обернуть в `async with self._lock`.

### S2. EventBus method mismatch в TaskSessionStore
**Файл**: `src/swarmline/session/task_session_store.py:64,85,199,213`
InMemoryTaskSessionStore и SqliteTaskSessionStore вызывают `self._event_bus.publish(...)`, но стандартный `EventBus` protocol в Swarmline использует метод `emit()`, а не `publish()`. Это приведёт к `AttributeError` при подключении реального EventBus.
**Рекомендация**: заменить `.publish(` на `.emit(` (4 вхождения).

### S3. RoutineBridge.dedup загружает ВСЕ задачи
**Файл**: `src/swarmline/daemon/routine_bridge.py:101`
```python
existing_tasks = await self._task_board.list_tasks()
```
Dedup check вызывает `list_tasks()` без фильтра — загружает все задачи в память при каждом trigger'е рутины. С ростом задач это станет bottleneck.
**Рекомендация**: Приемлемо для MVP. В будущем — добавить `list_tasks(status=[TODO,IN_PROGRESS], metadata_key="dedup_key")` или отдельный dedup-index.

## Замечания

### M1. DRY: SQLite boilerplate повторяется
Паттерн `threading.Lock() + asyncio.to_thread() + PRAGMA WAL + _sync helper` идентичен в 4 модулях (task_session_store, activity_log, budget_store + existing backends.py). Извлечение `SqliteBase` mixin сократило бы ~30 строк на модуль.
**Рекомендация**: Не блокирует мерж. Potential refactor на будущее.

### M2. `_worker_shim.py` не логирует в stderr при ошибках dispatch'а
**Файл**: `src/swarmline/plugins/_worker_shim.py:109`
При `except Exception` ошибка уходит только в JSON-RPC response, но не в stderr. Для debugging в production полезно дублировать в stderr.
**Рекомендация**: добавить `sys.stderr.write(f"Plugin error in {method}: {exc}\n")` перед response.

### M3. SubprocessPluginRunner не делает cleanup при GC
**Файл**: `src/swarmline/plugins/runner.py`
Нет `__del__` или context manager. Если runner GC'ится без явного `stop()`, subprocesses остаются zombie.
**Рекомендация**: добавить `async def close(self)` + warning в `__del__` (match SessionManager pattern). Не блокирует мерж.

### M4. `_generate_id` экспортируется из budget_types (private convention)
**Файл**: `src/swarmline/pipeline/budget_types.py`
Функция `_generate_id` с underscore prefix импортируется в `budget_store.py`. По Python convention underscore = private.
**Рекомендация**: переименовать в `generate_id` или сделать inline `uuid.uuid4().hex[:12]`.

### M5. ActivityLogSubscriber жёстко привязан к 9 дефолтным топикам
**Файл**: `src/swarmline/observability/activity_subscriber.py`
Default topic map захардкожен. Если добавятся новые EventBus topics (workspace.created, plugin.started, etc.), подписчик их не увидит.
**Рекомендация**: Приемлемо — custom_topic_map уже поддерживается. Документировать необходимость расширения.

## Тесты
- Unit: ✅ 139/139 passed (новые) + 3491 total suite green
- Интеграционные: ✅ 3 passed (RoutineBridge с real Scheduler + TaskBoard)
- E2E: ⚠️ отсутствуют (acceptable — это library components, не user flows)
- Непокрытые сценарии:
  - Concurrent `list_active()` + `create()` на workspace (связано с S1)
  - EventBus wiring в TaskSessionStore (связано с S2 — `publish` vs `emit`)
  - PluginRunner memory leak при отсутствии explicit `stop()`

## Соответствие плану

План: `.claude/plans/floating-crunching-iverson.md`

- Реализовано: все 6 компонентов (1.1 TaskSessionStore, 1.2 ActivityLog, 1.3 PersistentBudgetStore, 2.1 RoutineBridge, 2.2 ExecutionWorkspace, 3.1 PluginRunner)
- Не реализовано: нет отклонений от плана
- Вне плана: нет scope creep

## Итог

Качественная реализация 6 компонентов по Paperclip-паттернам. Все ISP ≤5 methods, frozen dataclasses, protocol-first, contract tests parametrized over backends. **Два серьёзных issue (S1 lock + S2 publish/emit)** требуют fix перед мержем — оба простые однострочные правки. Остальные замечания — minor improvements, не блокируют. **Рекомендация: доработать S1+S2, затем мержить.**
