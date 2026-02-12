# Getting Started

## Установка

### Минимум (только типы, протоколы, in-memory)

```bash
pip install cognitia
```

### С конкретным runtime

```bash
# Claude Agent SDK
pip install cognitia[claude]

# ThinRuntime (собственная реализация)
pip install cognitia[thin]

# DeepAgents (LangChain/LangGraph)
pip install cognitia[deepagents]
```

### С хранилищем

```bash
# PostgreSQL
pip install cognitia[postgres]

# SQLite
pip install cognitia[sqlite]
```

### С capability

```bash
# Web tools (fetch/search)
pip install cognitia[web]

# E2B cloud sandbox
pip install cognitia[e2b]

# Docker sandbox
pip install cognitia[docker]
```

### Всё сразу (для разработки)

```bash
pip install cognitia[all,dev]
```

## Быстрый старт

### 1. Структура проекта

```
your_app/
├── prompts/
│   ├── identity.md        # Личность агента
│   ├── guardrails.md      # Ограничения безопасности
│   ├── role_router.yaml   # Правила переключения ролей
│   ├── role_skills.yaml   # Маппинг ролей на инструменты
│   └── roles/
│       └── assistant.md   # Промпт роли
├── skills/                # MCP skills (опционально)
└── main.py
```

### 2. Минимальный агент (ThinRuntime, без sandbox)

```python
from pathlib import Path
from cognitia.bootstrap.stack import CognitiaStack
from cognitia.runtime.types import RuntimeConfig
from cognitia.todo.inmemory_provider import InMemoryTodoProvider

stack = CognitiaStack.create(
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),
    runtime_config=RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514"),
    todo_provider=InMemoryTodoProvider(user_id="user-1", topic_id="general"),
    thinking_enabled=True,
)

# stack.capability_specs содержит: thinking, todo_read, todo_write
# stack.context_builder собирает system prompt
# stack.runtime_factory создаёт ThinRuntime
```

### 3. Агент с sandbox и memory bank

```python
from cognitia.tools.sandbox_local import LocalSandboxProvider
from cognitia.tools.types import SandboxConfig
from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider
from cognitia.memory_bank.types import MemoryBankConfig

sandbox = LocalSandboxProvider(SandboxConfig(
    root_path="/data/sandbox",
    user_id="user-1",
    topic_id="project-1",
    timeout_seconds=30,
    denied_commands=frozenset({"rm", "sudo"}),
))

memory_config = MemoryBankConfig(enabled=True, root_path=Path("/data/memory"))
memory = FilesystemMemoryBankProvider(memory_config, user_id="user-1", topic_id="project-1")

stack = CognitiaStack.create(
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),
    sandbox_provider=sandbox,
    memory_bank_provider=memory,
    thinking_enabled=True,
    allowed_system_tools={"bash", "read", "write"},
)

# stack.capability_specs содержит: sandbox tools + memory tools + thinking
```

### 4. Запуск runtime

```python
from cognitia.runtime.types import Message

runtime = stack.runtime_factory.create(
    runtime_name="thin",
    config=stack.runtime_config,
)

messages = [Message(role="user", content="Привет, помоги мне")]
system_prompt = "Ты полезный ассистент."

async for event in runtime.run(
    messages=messages,
    system_prompt=system_prompt,
    active_tools=list(stack.capability_specs.values()),
):
    if event.type == "assistant_delta":
        print(event.data["text"], end="")
    elif event.type == "final":
        new_messages = event.data["new_messages"]
```

## Следующие шаги

- [Capabilities](capabilities.md) — подробнее о каждой capability
- [Runtimes](runtimes.md) — сравнение runtime
- [Configuration](configuration.md) — настройка через конфиги
- [Examples](examples.md) — примеры для разных доменов

> Примечание по readiness: orchestration-команды `/plan_*` и `/team_*` доступны на уровне приложения.
> Для `team` включай `CAP_TEAM_ENABLED=1`; для `planning` — `CAP_PLANNING_ENABLED=1`.
