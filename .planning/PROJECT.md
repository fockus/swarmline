# ThinRuntime Claude Code Parity

## What This Is

Доработка ThinRuntime модуля в swarmline (Python LLM-agnostic agent framework) до полноценного runtime, сравнимого по возможностям с Claude Code. Включает систему хуков (PreToolUse/PostToolUse/Stop/UserPromptSubmit), LLM-initiated субагентов, slash-команд, tool policy enforcement и native tool calling API. Целевая аудитория — разработчики, использующие swarmline с thin runtime для multi-provider AI агентов.

## Core Value

ThinRuntime должен обеспечивать безопасное и полнофункциональное выполнение агентов с контролем инструментов через hooks и policy, возможностью делегирования задач через субагентов, и поддержкой native tool calling API провайдеров.

## Requirements

### Validated

- ✓ Multi-provider LLM (Anthropic + OpenAI-compat + Google) — existing
- ✓ 3 стратегии выполнения (conversational, react, planner) — existing
- ✓ Tool execution (local_tools + MCP HTTP + @tool decorator) — existing
- ✓ Structured output (Pydantic output_type, retry) — existing
- ✓ Streaming (try_stream → buffered → fallback) — existing
- ✓ Cost tracking (CostBudget, budget_exceeded events) — existing
- ✓ Input/output guardrails — existing
- ✓ CancellationToken — existing
- ✓ RAG auto-wrap retriever — existing
- ✓ EventBus (llm_call/tool_call events) — existing
- ✓ HookRegistry (4 hook types, registration API) — existing
- ✓ CommandRegistry (parsing, YAML loader, aliases) — existing
- ✓ ThinSubagentOrchestrator (Python API, spawn/wait/cancel) — existing
- ✓ DefaultToolPolicy (4-step allow/deny logic) — existing

### Active

- [ ] Hook dispatch в ThinRuntime (PreToolUse/PostToolUse в ToolExecutor, Stop/UserPromptSubmit в run())
- [ ] Tool policy enforcement в ToolExecutor (allow/deny перед выполнением)
- [ ] LLM-initiated subagent tool (spawn_agent ToolSpec + executor)
- [ ] Command routing (intercept /commands перед LLM)
- [ ] Native tool calling API (Anthropic/OpenAI/Google native tools parameter)
- [ ] Parallel tool calls (batch multiple tool_use в одном ходе)

### Out of Scope

- MCP stdio/SSE transport — HTTP достаточно для v1.5, stdio сложнее и менее portable
- Persistent subagent state — субагенты stateless, state persistence в v2
- Custom hook types — 4 типа покрывают все use cases Claude Code
- Breaking changes в AgentConfig — все новые поля optional с None default
- Замена pseudo tool-calling — native tools opt-in, JSON-in-text остаётся default (Strangler Fig)

## Context

- **Кодовая база**: 355 .py файлов, ~220 source + ~135 tests, 4263 тестов passing
- **ThinRuntime**: 17 файлов, ~2800 строк в `src/swarmline/runtime/thin/`
- **Ключевая точка интеграции**: `ToolExecutor.execute()` (executor.py) — сюда добавляются hooks + policy
- **Существующие абстракции**: HookRegistry, DefaultToolPolicy, ThinSubagentOrchestrator, CommandRegistry — готовые, нужно wiring
- **Audit**: `.memory-bank/reports/2026-04-12_audit_thin-runtime-gaps.md`
- **Детальный план**: `.memory-bank/plans/2026-04-12_feature_thin-runtime-claude-code-parity.md`
- **Версия**: swarmline 1.4.1, target v1.5.0

## Constraints

- **Обратная совместимость**: все 4263 существующих тестов должны проходить на каждом этапе. Все новые поля optional с None default.
- **TDD**: тесты → реализация → рефакторинг. Каждая фаза начинается с red tests.
- **Contract-first**: Protocol/ABC → contract tests → implementation.
- **Clean Architecture**: Domain (protocols) → Application → Infrastructure. Hooks/policy = domain, wiring = infrastructure.
- **ISP**: Protocol ≤ 5 methods. HookDispatcher Protocol — max 5 methods.
- **Python 3.10+**: min version, type hints, async-first.
- **Versioning**: вся работа = один minor release v1.5.0. Без промежуточных бампов.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Strangler Fig для native tools | JSON-in-text работает, native tools opt-in через `use_native_tools=True` default False | — Pending |
| HookDispatcher как отдельный Protocol | ISP: dispatch logic отделена от registry. ToolExecutor зависит от dispatcher, не от registry | — Pending |
| Hook order: PreToolUse → Policy → Execute → PostToolUse | Policy проверяет после hook modify — hooks могут изменить args, policy проверяет результат | — Pending |
| SubagentTool max_depth enforcement | Защита от бесконечной рекурсии. max_depth=3 default | — Pending |
| Commands intercept перед LLM | /command → immediate response, не передаётся в LLM | — Pending |
| Hook error handling: fail-open | Баг в hook не должен парализовать агента — log + allow | — Pending |
| Subagent system_prompt из tool args | LLM контролирует prompt субагента, default "You are a helpful assistant" | — Pending |
| Native tools: Anthropic first | Снижение risk — один провайдер → проверить → добавить остальные | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-12 after initialization*
