---
kind: report
tags: [task-board, progress, workflow, blocked-status, graph-agents]
importance: high
created: 2026-03-29
updated: 2026-03-29
---

# Task Progress, BLOCKED Status & Extensible Workflow Stages

**Дата:** 2026-03-29
**Коммит:** `163a98f`
**Тесты:** 3770 passed (+442 новых)

---

## Что реализовано

### 1. TaskStatus.BLOCKED

Новый статус в `task_types.py`:
```python
class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"          # NEW
    DONE = "done"
    CANCELLED = "cancelled"
```

**Семантика:** задача приостановлена по внешней причине. `blocked_reason: str` обязателен при переходе в BLOCKED.

**API:**
```python
await board.block_task("task-1", "Waiting for API key")   # → True
await board.unblock_task("task-1")                         # → True, status=TODO
```

**Правила:**
- Пустой reason → rejected (return False)
- Только TODO или IN_PROGRESS можно блокировать
- BLOCKED нельзя checkout
- BLOCKED не попадает в get_ready_tasks()
- BLOCKED child блокирует auto-completion parent'а
- Новый protocol `GraphTaskBlocker` (2 methods, ISP)

### 2. Progress Auto-Calculation

Новое поле `progress: float = 0.0` (0.0–1.0) на `GraphTaskItem`.

**Автоматика:**
- `complete_task()` ставит `progress=1.0`
- Parent progress = `avg(children.progress)` — пересчитывается при каждом complete
- Propagation рекурсивна вверх по дереву **всегда** (даже при partial completion)
- Если все children DONE → parent auto-complete (как раньше)

**Пример:**
```
Parent (progress=0.67)
  ├── Child 1: DONE (1.0)
  ├── Child 2: DONE (1.0)
  └── Child 3: TODO (0.0)    → complete → Parent progress = 1.0, status=DONE
```

**Ключевое изменение:** `_propagate_completion()` заменён на `_propagate_parent()` во всех 3 backend'ах. Новый метод всегда рекурсит (не только при full completion).

### 3. Extensible Workflow Stages

Новое поле `stage: str = ""` на `GraphTaskItem` — user-defined workflow label.

**Два уровня:**
- `status` (TaskStatus enum) — machine state для internal logic
- `stage` (str) — human workflow label для потребителя

**WorkflowConfig:**
```python
from cognitia.multi_agent import WorkflowConfig, WorkflowStage

stages = (
    WorkflowStage(name="backlog", maps_to=TaskStatus.TODO, order=0),
    WorkflowStage(name="design", maps_to=TaskStatus.IN_PROGRESS, order=1),
    WorkflowStage(name="review", maps_to=TaskStatus.IN_PROGRESS, order=2),
    WorkflowStage(name="deployed", maps_to=TaskStatus.DONE, order=3),
)
workflow = WorkflowConfig(name="SoftwareDev", stages=stages)
workflow.stage_for("review")           # → WorkflowStage
workflow.stages_for_status(TaskStatus.IN_PROGRESS)  # → (design, review)
```

**Интеграция:** `delegate_task` tool принимает `stage` → `DelegationRequest.stage` → `GraphTaskItem.stage`.

## Файлы (15 changed, +700 lines)

| Файл | Изменение |
|------|-----------|
| `task_types.py` | + BLOCKED |
| `graph_task_types.py` | + progress, stage, blocked_reason, WorkflowStage, WorkflowConfig |
| `protocols/graph_task.py` | + GraphTaskBlocker protocol |
| `graph_task_board.py` | block/unblock + _propagate_parent |
| `graph_task_board_sqlite.py` | ser/deser + block/unblock + propagation |
| `graph_task_board_postgres.py` | ser/deser + block/unblock + propagation |
| `graph_orchestrator_types.py` | + DelegationRequest.stage |
| `graph_orchestrator.py` | stage passthrough |
| `graph_tools.py` | stage в delegate_task |

## Backward Compatibility

- Все default values — существующий код не ломается
- Старые JSON без progress/stage/blocked_reason загружаются с defaults
- TaskStatus.BLOCKED — новый enum value, не конфликтует
- WorkflowConfig — optional, library не enforcement stage transitions
