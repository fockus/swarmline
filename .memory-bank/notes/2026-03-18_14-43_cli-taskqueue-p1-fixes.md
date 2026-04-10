# cli-taskqueue-p1-fixes
Date: 2026-03-18 14:43

## Что сделано
- Исправлен `RuntimeRegistry` path для `runtime="cli"`: facade-only kwargs (`tool_executors`, `local_tools`) больше не пробрасываются в `CliAgentRuntime`.
- `CliAgentRuntime` теперь сериализует stdin как `System instructions` + `Conversation`; это покрыто unit и agent/conversation-level тестами с мокнутым subprocess.
- `execute_agent_tool()` теперь считает `RuntimeEvent.error` и stream без `final` ошибочными завершениями.
- `TaskQueue.get()` в InMemory/SQLite стал atomic claim: выбирает только `TODO`, без assignee фильтра берёт только unassigned, переводит задачу в `IN_PROGRESS` до возврата.

## Новые знания
- Для SQLite claim-семантики достаточно JSON-blob schema, если чтение+обновление делаются внутри одного `BEGIN IMMEDIATE` transaction.
- Repo-wide `ruff` и `mypy` сейчас шумят по старым проблемам вне diff; для локальной верификации полезно отдельно гонять changed-file lint.
