# Orchestration — Planning, Subagents, Team Mode

## Planning Mode

Агент декомпозирует сложную задачу на шаги и выполняет последовательно.

### Архитектура

```
PlanManager (app API)
    ├── PlannerMode Protocol (LLM logic)
    │   ├── ThinPlannerMode
    │   └── DeepAgentsPlannerMode
    └── PlanStore Protocol (persistence)
        └── InMemoryPlanStore
```

### State Machine

```
draft → approved → executing → completed
  └──────────────────────────→ cancelled
```

- `draft` — план создан, ждёт одобрения
- `approved` — одобрен (пользователем, системой или агентом)
- `executing` — шаги выполняются
- `completed` — все шаги завершены
- `cancelled` — отменён (из любого состояния)

### Агент сам запускает планирование

Когда включены planning tools, агент получает инструменты + промпт:

```
Агент: "Задача сложная, нужен план"
→ plan_create(goal="Подобрать вклад на 1 млн", auto_execute=true)
→ LLM генерирует шаги
→ Шаги выполняются: поиск → анализ → сравнение → рекомендация
```

### Программное управление

```python
# Из бизнес-кода (не через агента)
plan = await manager.create_plan("Задача", user_id="u1", topic_id="t1")
plan = await manager.approve_plan(plan.id, by="system")

async for step in manager.execute_plan(plan.id):
    notify_user(step)

await manager.cancel_plan(plan.id)  # если нужно остановить
```

---

## Subagents

Основной агент запускает дочерних агентов для параллельной работы.

### Архитектура

```
SubagentOrchestrator Protocol
    ├── ThinSubagentOrchestrator    (asyncio.Task)
    ├── DeepAgentsSubagentOrchestrator (asyncio.Task / LangGraph)
    └── ClaudeSubagentOrchestrator  (SDK Task tool)
```

### Lifecycle

```
pending → running → completed
                  → failed
                  → cancelled
```

### Использование

```python
from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator
from cognitia.orchestration.subagent_types import SubagentSpec

orch = ThinSubagentOrchestrator(max_concurrent=4)

spec = SubagentSpec(
    name="researcher",
    system_prompt="Ты исследователь. Найди информацию по запросу.",
    tools=[...],
)

agent_id = await orch.spawn(spec, task="Найди лучшие вклады в Сбербанке")
status = await orch.get_status(agent_id)
result = await orch.wait(agent_id)
print(result.output)  # "Найдено 5 вкладов..."

# Отмена
await orch.cancel(agent_id)

# Список активных
active = await orch.list_active()
```

### Безопасность

- `max_concurrent` ограничивает параллельные subagent'ы (default: 4)
- Crash subagent'а не крашит parent — graceful `status=failed`
- Каждый subagent может иметь свой `SandboxConfig` (изоляция)

---

## Team Mode

Lead-агент координирует команду worker-агентов. Workers работают параллельно и обмениваются сообщениями.

### Архитектура

```
TeamManager (app API)
    └── TeamOrchestrator Protocol
        ├── DeepAgentsTeamOrchestrator (supervisor pattern)
        └── ClaudeTeamOrchestrator (SDK Task-based)
            └── SubagentOrchestrator (workers)
            └── MessageBus (коммуникация)
```

### Коммуникация через MessageBus

```python
# Lead → Worker
await orch.send_message(team_id, TeamMessage(
    from_agent="lead", to_agent="researcher",
    content="Проанализируй вклады",
    timestamp=datetime.now(tz=timezone.utc),
))

# Worker → Lead
await orch.send_message(team_id, TeamMessage(
    from_agent="researcher", to_agent="lead",
    content="Найдено 5 вкладов, лучший — 18%",
    timestamp=datetime.now(tz=timezone.utc),
))

# Чтение inbox
bus = orch.get_message_bus(team_id)
lead_inbox = await bus.get_inbox("lead")
```

### Управление командой

```python
from cognitia.orchestration.team_manager import TeamManager
from cognitia.orchestration.team_types import TeamConfig

config = TeamConfig(
    lead_prompt="Ты тимлид. Координируй команду.",
    worker_specs=[
        SubagentSpec(name="researcher", system_prompt="Ищи данные"),
        SubagentSpec(name="analyst", system_prompt="Анализируй данные"),
    ],
    max_workers=4,
)

team_id = await manager.start_team(config, "Подготовить отчёт по портфелю")
status = await manager.get_status(team_id)
await manager.pause_agent(team_id, "researcher")
await manager.resume_agent(team_id, "researcher")
await manager.stop_team(team_id)
```
