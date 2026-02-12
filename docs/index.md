# Cognitia — Documentation

Cognitia — LLM-агностичная библиотека для построения AI-агентов на Python.

Модульная архитектура: подключай только то, что нужно.
Три runtime, шесть capability, protocol-driven design.

## Содержание

- [Architecture](architecture.md) — архитектура, слои, принципы
- [Getting Started](getting-started.md) — установка, быстрый старт
- [Capabilities](capabilities.md) — sandbox, tools, todo, memory bank, planning, thinking
- [Runtimes](runtimes.md) — Claude SDK, ThinRuntime, DeepAgents
- [Orchestration](orchestration.md) — subagent'ы, team mode, планирование
- [Configuration](configuration.md) — CognitiaStack, конфиги, tool budget
- [Examples](examples.md) — примеры интеграции в разных бизнес-доменах

## Быстрый обзор

```python
from cognitia.bootstrap.stack import CognitiaStack

stack = CognitiaStack.create(
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),
    thinking_enabled=True,
)
# stack.capability_specs — все доступные инструменты
# stack.runtime_factory — создание runtime
# stack.context_builder — сборка system prompt
```

## Требования

- Python 3.10+
- Core: без внешних зависимостей кроме structlog, pyyaml, pydantic
- Runtime и storage: устанавливаются через extras
