# ThinRuntime Claude Code Parity

## What This Is

Доработка ThinRuntime модуля в swarmline (Python LLM-agnostic agent framework) до полноценного runtime, сравнимого по возможностям с Claude Code. Parity v1 (завершён): hooks, policy, subagents, commands, native tools, coding profile. Parity v2 (текущий): compaction, project instructions, session resume, web tools, multimodal, MCP resources, system reminders, worktree isolation, thinking events, background agents.

## Core Value

ThinRuntime должен обеспечивать безопасное и полнофункциональное выполнение агентов с контролем инструментов через hooks и policy, возможностью делегирования задач через субагентов, поддержкой native tool calling API провайдеров, и продвинутыми возможностями coding agent (context management, session persistence, multimodal input).

## Current Milestone: v1.5.0 ThinRuntime Parity v2

**Goal:** Закрыть оставшиеся capability gaps между ThinRuntime и Claude Code — compaction, project instructions, session resume, web tools, multimodal input, и инфраструктура для production coding agent.

**Target features:**
- Conversation Compaction (LLM-summarization вместо truncation)
- Project Instructions Loading (CLAUDE.md / AGENTS.md / GEMINI.md / RULES.md)
- Session Resume (conversation history persistence)
- Web Tools (WebSearch / WebFetch built-in)
- Multimodal Input (images, PDF, Jupyter notebooks)
- MCP Resource Reading
- System Reminders (dynamic context injection)
- Git Worktree Isolation for subagents
- Thinking Events (separate reasoning stream)
- Background Agents + Monitor Tool

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
- ✓ Hook dispatch в ThinRuntime — Parity v1 Phase 1
- ✓ Tool policy enforcement в ToolExecutor — Parity v1 Phase 2
- ✓ LLM-initiated subagent tool (spawn_agent) — Parity v1 Phase 3
- ✓ Command routing (/commands before LLM) — Parity v1 Phase 4
- ✓ Native tool calling API (3 providers) — Parity v1 Phase 5
- ✓ Coding profile foundation (10 canonical tools) — Parity v1 Phase 7
- ✓ Coding task runtime (persistent snapshots) — Parity v1 Phase 8
- ✓ Coding context assembly (budget-aware 6 slices) — Parity v1 Phase 9
- ✓ Coding subagent inheritance — Parity v1 Phase 10

### Active

- [ ] Conversation Compaction (LLM-суммаризация вместо truncation)
- [ ] Project Instructions Loading (CLAUDE.md / AGENTS.md / GEMINI.md / RULES.md)
- [ ] Session Resume (conversation history persistence between run() calls)
- [ ] Web Tools (WebSearch / WebFetch built-in)
- [ ] Multimodal Input (images, PDF, Jupyter notebooks)
- [ ] MCP Resource Reading (resources protocol, not just tools)
- [ ] System Reminders (dynamic conditional context injection)
- [ ] Git Worktree Isolation for subagents
- [ ] Thinking Events (separate reasoning stream, extended thinking)
- [ ] Background Agents + Monitor Tool (async notification, stdout streaming)

### Out of Scope

- Interactive permission modes (auto/default/plan) — binary policy sufficient for library
- Plan mode review gate — planner strategy exists, interactive review is UI concern
- MCP stdio/SSE transport — HTTP достаточно для v1.5
- Breaking changes в AgentConfig — все новые поля optional с None default
- Custom hook types — 4 типа покрывают все use cases

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
