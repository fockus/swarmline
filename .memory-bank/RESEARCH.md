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

### F-002: cognitia передаёт только 6 из 16 параметров create_deep_agent()
model, tools, system_prompt, interrupt_on, checkpointer, store, backend.
НЕ передаём: memory, subagents, skills, middleware, response_format, context_schema, debug, name, cache.

### F-003: OpenAI Agents SDK оценка (2026-03-17)

**Статус**: REJECTED для интеграции как runtime (ADR-001).
v0.12.3, pre-1.0, 3 примитива (Agent/Handoff/Guardrail), нативный MCP, 9 session backends, LiteLLM multi-provider. Дублирует cognitia абстракции, tracing lock-in в OpenAI, API нестабилен. Пересмотреть после v1.0.
См. `reports/2026-03-17_research_openai-agents-sdk.md`, `notes/2026-03-17_ADR-001_openai-agents-sdk.md`.
