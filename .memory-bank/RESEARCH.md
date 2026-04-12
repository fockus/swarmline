# Research

## Гипотезы
(пусто)

## Findings

### F-001: deepagents 0.5.0 middleware stack (2026-03-17)
Upstream `create_deep_agent()` автоматически добавляет:
1. TodoListMiddleware (always)
2. MemoryMiddleware (if memory= provided)
3. SkillsMiddleware (if skills= provided)
4. FilesystemMiddleware (always)
5. SubAgentMiddleware (always)
6. SummarizationMiddleware (always, auto-configured)
7. AnthropicPromptCachingMiddleware (always)
8. PatchToolCallsMiddleware (always)
9. User middleware (appended)
10. HumanInTheLoopMiddleware (if interrupt_on provided)

### F-002: swarmline передаёт только 6 из 16 параметров create_deep_agent()
model, tools, system_prompt, interrupt_on, checkpointer, store, backend.
НЕ передаём: memory, subagents, skills, middleware, response_format, context_schema, debug, name, cache.

### F-003: OpenAI Agents SDK оценка (2026-03-17)

**Статус**: REJECTED для интеграции как runtime (ADR-001).
v0.12.3, pre-1.0, 3 примитива (Agent/Handoff/Guardrail), нативный MCP, 9 session backends, LiteLLM multi-provider. Дублирует swarmline абстракции, tracing lock-in в OpenAI, API нестабилен. Пересмотреть после v1.0.
См. `reports/2026-03-17_research_openai-agents-sdk.md`, `notes/2026-03-17_ADR-001_openai-agents-sdk.md`.

### F-004: Thin coding-agent reuse strategy (2026-04-12)

Для развития `thin` как coding-agent не нужен новый runtime. Лучший путь — собрать уже существующие seams `swarmline` (sandbox tools, todo layer, graph task board, task session store, context builder) в отдельный coding-agent profile и точечно усилить его за счёт `aura`-style path/code-exec/context seams. `claw-code-agent` сейчас использовать как reference для task/context/tool UX, а не как source для literal copy, пока не подтверждена лицензия. См. `reports/2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md`.
