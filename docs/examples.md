# Examples — примеры интеграции

## 1. Финансовый AI-коуч

Агент помогает пользователю с финансами: подбирает вклады, анализирует портфель, ведёт PF5-диагностику.

```python
from cognitia.bootstrap.stack import CognitiaStack
from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider
from cognitia.memory_bank.types import MemoryBankConfig
from cognitia.todo.inmemory_provider import InMemoryTodoProvider

# Memory bank для долгосрочного хранения предпочтений пользователя
memory = FilesystemMemoryBankProvider(
    MemoryBankConfig(enabled=True, root_path=Path("/data/memory")),
    user_id="client-123", topic_id="finance",
)

# Todo для tracking задач диагностики
todo = InMemoryTodoProvider(user_id="client-123", topic_id="finance")

stack = CognitiaStack.create(
    prompts_dir=Path("prompts"),       # identity: "Ты финансовый коуч"
    skills_dir=Path("skills"),         # MCP: finuslugi, iss, funds
    project_root=Path("."),
    runtime_config=RuntimeConfig(runtime_name="thin", model="sonnet"),
    memory_bank_provider=memory,       # агент запоминает предпочтения
    todo_provider=todo,                # агент ведёт чеклист диагностики
    thinking_enabled=True,             # CoT для анализа
)
# Агент: мыслит через thinking → ведёт чеклист → запоминает решения
```

---

## 2. Код-ревьюер

Агент читает код, находит проблемы, предлагает исправления. Работает в sandbox.

```python
from cognitia.tools.sandbox_local import LocalSandboxProvider
from cognitia.tools.types import SandboxConfig

sandbox = LocalSandboxProvider(SandboxConfig(
    root_path="/projects",
    user_id="dev-team",
    topic_id="pr-456",
    denied_commands=frozenset({"rm", "git push", "sudo"}),
))

stack = CognitiaStack.create(
    prompts_dir=Path("prompts"),       # identity: "Ты старший разработчик"
    skills_dir=Path("skills"),
    project_root=Path("."),
    runtime_config=RuntimeConfig(runtime_name="thin", model="opus"),
    sandbox_provider=sandbox,
    thinking_enabled=True,
    allowed_system_tools={"bash", "read", "glob", "grep"},  # читать можно, писать нельзя
)
# Агент: grep по коду → thinking → находит проблемы → отчёт
```

---

## 3. Исследовательский ассистент

Агент ищет информацию в интернете, структурирует знания, ведёт заметки.

```python
from cognitia.tools.web_httpx import HttpxWebProvider
from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider
from cognitia.memory_bank.types import MemoryBankConfig

web = HttpxWebProvider(timeout=30)
memory = FilesystemMemoryBankProvider(
    MemoryBankConfig(
        enabled=True,
        root_path=Path("/data/research"),
        default_folders=["sources", "notes", "summaries"],
    ),
    user_id="researcher-1", topic_id="ai-trends-2026",
)

stack = CognitiaStack.create(
    prompts_dir=Path("prompts"),       # identity: "Ты исследовательский ассистент"
    skills_dir=Path("skills"),
    project_root=Path("."),
    web_provider=web,                  # поиск и fetch
    memory_bank_provider=memory,       # заметки и источники
    thinking_enabled=True,
)
# Агент: web_search → web_fetch → thinking → memory_write("sources/...") → отчёт
```

---

## 4. DevOps-бот с Docker sandbox

Агент выполняет скрипты в изолированном Docker-контейнере. Продакшен.

```python
from cognitia.tools.sandbox_docker import DockerSandboxProvider
from cognitia.tools.types import SandboxConfig

sandbox = DockerSandboxProvider(
    SandboxConfig(
        root_path="/workspace",
        user_id="ops-team",
        topic_id="deploy-v2",
        timeout_seconds=120,
    ),
    _container=docker_client.containers.run("python:3.12-slim", detach=True),
)

stack = CognitiaStack.create(
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),
    sandbox_provider=sandbox,
    allowed_system_tools={"bash", "read", "write", "ls"},
    thinking_enabled=True,
)
# Агент: bash("pip install ...") → write("deploy.py", ...) → bash("python deploy.py")
```

---

## 5. Multi-agent команда для анализа рынка

Lead-агент координирует researcher'а и analyst'а.

```python
from cognitia.orchestration.team_manager import TeamManager
from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator
from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator
from cognitia.orchestration.subagent_types import SubagentSpec
from cognitia.orchestration.team_types import TeamConfig

sub_orch = ThinSubagentOrchestrator(max_concurrent=3)
team_orch = DeepAgentsTeamOrchestrator(sub_orch)
team_mgr = TeamManager(team_orch)

config = TeamConfig(
    lead_prompt="Ты тимлид. Координируй команду для анализа рынка.",
    worker_specs=[
        SubagentSpec(name="researcher", system_prompt="Ищи данные о рынке"),
        SubagentSpec(name="analyst", system_prompt="Анализируй данные и строй выводы"),
        SubagentSpec(name="writer", system_prompt="Пиши итоговый отчёт"),
    ],
)

team_id = await team_mgr.start_team(config, "Анализ рынка вкладов Q1 2026")
# Lead декомпозирует → workers работают параллельно → lead собирает отчёт
```

---

## 6. Минимальный агент (только thinking + todo)

Без sandbox, без MCP, без memory bank. Просто умный чат с чеклистами.

```python
from cognitia.todo.inmemory_provider import InMemoryTodoProvider

stack = CognitiaStack.create(
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),
    todo_provider=InMemoryTodoProvider(user_id="u", topic_id="t"),
    thinking_enabled=True,
    # Всё остальное = None
)
# Агент: thinking → todo_write → ответ
# Токены на tools: ~300 (минимум)
```

---

## Паттерны интеграции

### Добавить capability в существующее приложение

```python
# Было: только MCP skills
stack = CognitiaStack.create(prompts_dir=..., skills_dir=..., project_root=...)

# Стало: + memory bank + todo
stack = CognitiaStack.create(
    prompts_dir=..., skills_dir=..., project_root=...,
    memory_bank_provider=memory,
    todo_provider=todo,
    thinking_enabled=True,
)
```

### Переключить runtime без изменения кода

```python
# Dev
config = RuntimeConfig(runtime_name="thin")

# Staging  
config = RuntimeConfig(runtime_name="deepagents")

# Production
config = RuntimeConfig(runtime_name="claude_sdk")

# Один и тот же stack.create() — только config меняется
```

### Override builtin tools

```python
class MyToolResolver:
    def resolve(self, tool_name):
        if tool_name == "memory_read":
            return my_custom_memory_read  # своя реализация
        return None

stack = CognitiaStack.create(
    ...,
    local_tool_resolver=MyToolResolver(),
)
```
