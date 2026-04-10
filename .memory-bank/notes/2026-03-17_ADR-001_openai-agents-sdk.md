# ADR-001: Интеграция OpenAI Agents SDK в cognitia

**Дата**: 2026-03-17
**Статус**: REJECTED (пересмотреть после v1.0)

## Контекст

Рассмотрена возможность интеграции OpenAI Agents SDK (v0.12.3, PyPI: `openai-agents`) как 4-го runtime в cognitia наряду с `claude_sdk`, `deepagents`, `thin`.

OpenAI Agents SDK — Python-first фреймворк с тремя примитивами (Agent, Handoff, Guardrail), встроенным agent loop, нативным MCP (5 транспортов), 9 session backends, structured output через Pydantic, multi-provider через LiteLLM.

Полный research report: `reports/2026-03-17_research_openai-agents-sdk.md`

## Решение

**Не интегрировать** openai-agents как runtime.

## Альтернативы

### A: Добавить `OpenAIAgentsRuntime` как 4-й runtime
- (+) Нативный MCP с approval policies, 9 session backends, guardrails из коробки
- (-) Дублирует cognitia абстракции (guardrails, sessions, MCP, HITL)
- (-) Pre-1.0: 13+ релизов за 3 недели, высокий maintenance burden
- (-) Tracing lock-in в OpenAI Traces
- (-) Flat handoffs, нет граф-оркестрации (не заменяет deepagents/LangGraph)

### B: Использовать отдельные компоненты
- (+) Session backends (Redis, Dapr, PostgreSQL) — production persistence без своего кода
- (+) MCP transport (StreamableHttp, Stdio) — reference для улучшения нашего MCP
- (+) griffe schema generation (docstring → JSON Schema) для ToolSpec
- (-) Тянем зависимость ради части функционала

### C: Ждать v1.0 (выбрано)
- (+) API стабилизируется, breaking changes прекратятся
- (+) Сможем оценить зрелый продукт, а не moving target
- (-) Теряем время если SDK окажется полезным

## Последствия

- cognitia остаётся на 3 runtime'ах: claude_sdk, deepagents, thin
- При необходимости production persistence — рассмотреть session backends отдельно
- При улучшении MCP слоя — использовать openai-agents MCP transport как reference
- Переоценить после выхода openai-agents v1.0 или если deepagents окажется недостаточным
