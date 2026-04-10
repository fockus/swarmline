---
kind: report
tags: [code-review, graph-agents, knowledge-bank, governance]
importance: high
created: 2026-03-29
updated: 2026-03-29
---

# Code Review Report
Дата: 2026-03-29
Файлов проверено: 28 (17 src + 11 tests)
Строк изменено: +3656 / -11

## Критичное

Ничего критичного. Безопасность, frozen dataclasses, backward-compat — всё на месте.

## Серьёзное

### S1: delegate_task tool не вызывает check_delegate_allowed() — Plan A5 DoD нарушен
**Файл:** `src/cognitia/multi_agent/graph_tools.py:114-139`
**Проблема:** `check_delegate_allowed()` реализован в `graph_governance.py:72-86`, но `delegate_task` tool никогда его не вызывает. `hire_agent` проверяет governance (строка 77-80), а `delegate_task` — нет. Plan A5 DoD явно указывает: "delegate_task enforcement: can_delegate".
**Рекомендация:** Добавить governance check в начало `delegate_task`, аналогично `hire_agent`. Нужен параметр `caller_agent_id` для определения кто делегирует.

### S2: Root task не создаёт AgentExecution запись → run.executions неполный
**Файл:** `src/cognitia/multi_agent/graph_orchestrator.py:105-141`
**Проблема:** `start()` создаёт root task и запускает `_execute_agent()`, но не добавляет `AgentExecution` в `run.executions`. Внутри `_execute_agent()` при `_find_execution_index()` для root task всегда возвращается `None`, и все обновления состояния (RUNNING, COMPLETED, FAILED) пропускаются. `get_status()` покажет пустой список executions для root.
**Рекомендация:** Перед `asyncio.create_task()` добавить:
```python
run.executions.append(AgentExecution(agent_id=root.id, task_id=root_task_id))
```

### S3: Race condition в DefaultKnowledgeStore._update_index_entry при concurrent saves
**Файл:** `src/cognitia/memory_bank/knowledge_store.py:113-130`
**Проблема:** Два concurrent `save()` оба вызывают `_load_index()`, получают одинаковую копию, каждый добавляет свою entry и перезаписывает index. Второй save затрёт первый.
**Impact:** Низкий для single-agent, но в multi-agent сценарии (основной use case библиотеки) — потеря index entries.
**Рекомендация:** Либо in-memory кеш индекса с lock, либо атомарный read-modify-write.

### S4: InMemoryKnowledgeSearcher ломает инкапсуляцию через store._entries
**Файл:** `src/cognitia/memory_bank/knowledge_inmemory.py:66`
**Проблема:** `search()` и `search_by_tags()` обращаются к `self._store._entries` напрямую. Это приватный атрибут.
**Рекомендация:** Добавить public итератор в `InMemoryKnowledgeStore` или передавать entries dict через конструктор.

## Замечания

### W1: Лишний getattr для capabilities
**Файл:** `src/cognitia/multi_agent/graph_context.py:150`
`getattr(node, "capabilities", None)` — `capabilities` теперь обязательный field с default на AgentNode. Можно просто `node.capabilities`.

### W2: time.strftime() без timezone в 5 модулях
**Файлы:** `knowledge_store.py:97`, `knowledge_search.py:82`, `knowledge_inmemory.py:111,128`, `knowledge_consolidation.py:89`
Используется local time. При кросс-зонной работе timestamps будут несогласованы. Рекомендуется `datetime.now(UTC).strftime()`.

### W3: DRY — index JSON serialization дублируется
`DefaultKnowledgeStore._save_index()` и `DefaultKnowledgeSearcher.rebuild_index()` содержат одинаковую логику IndexEntry → dict → JSON. Вынести в shared helper.

### W4: DRY — IndexEntry construction дублируется
`InMemoryKnowledgeStore.list_entries`, `InMemoryKnowledgeSearcher.search`, `search_by_tags` — одинаковое 6-field конструирование IndexEntry из KnowledgeEntry. Кандидат на helper method.

### W5: DefaultKnowledgeStore.exists() читает весь файл
**Файл:** `knowledge_store.py:62-65`
`read_file(path)` загружает весь content для проверки exists. Для больших файлов на filesystem это wasteful.

### W6: frontmatter.py не обрабатывает BOM и leading whitespace
`text.startswith("---")` не сработает с UTF-8 BOM (`\ufeff`) или leading whitespace/newlines.

### W7: Redundant exception types в wait_for_task
**Файл:** `graph_orchestrator.py:215`
`except (TimeoutError, asyncio.CancelledError, Exception)` — `Exception` покрывает первые два. Оставить только `except Exception`.

## Тесты

- Unit: ✅ 246/246 passed (все связанные файлы)
- Ruff: ✅ 0 issues
- Интеграционные: ⚠️ Нет integration tests для DefaultKnowledgeStore + Database backend (SQLite)
- E2E: ⚠️ Нет E2E тестов для полного workflow "build graph → start → delegate → governance deny"
- Непокрытые сценарии:
  - delegate_task governance enforcement (не реализовано)
  - Root task state tracking в get_status()
  - Concurrent saves в DefaultKnowledgeStore
  - Knowledge Bank с DatabaseMemoryBankProvider

## Соответствие плану

### Реализовано:
- ✅ A1: AgentExecutionContext + AgentNode.mcp_servers
- ✅ A2: Skills/MCP inheritance + build_execution_context
- ✅ A3: Dual-dispatch runner (inspect.signature)
- ✅ A4: Builder API с capabilities, from_dict с capabilities
- ✅ A5: AgentCapabilities, GraphGovernanceConfig, hire_agent governance, capabilities в prompt
- ✅ B1: 9 domain types + frontmatter parser
- ✅ B2: 5 ISP protocols + InMemory backends
- ✅ B3: DefaultKnowledgeStore/Searcher/Checklist/Progress via MemoryBankProvider
- ✅ B4: knowledge tools (3) + KnowledgeConsolidator

### Не реализовано (план обещал):
- ❌ A5 DoD: "delegate_task enforcement: can_delegate" — check_delegate_allowed() создан, но не подключён к tool
- ⚠️ B3 DoD: "Тесты для Database (SQLite) backend" — есть только mock-based тесты, реальный SQLite backend не тестируется

### Вне плана:
- Ничего лишнего. Scope чистый.

## Итог

Архитектура отличная: чистое разделение слоёв, ISP-compliant protocols, frozen domain types, backward-compat. Единственный серьёзный пробел — **delegate_task governance не подключён** (S1), что прямо нарушает DoD плана. Root task tracking (S2) — менее критично, но ломает observability. Рекомендация: **доработать S1 и S2, остальное — minor и может ждать**.
