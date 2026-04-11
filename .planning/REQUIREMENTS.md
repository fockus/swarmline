# Requirements: ThinRuntime Claude Code Parity

**Defined:** 2026-04-12
**Core Value:** ThinRuntime обеспечивает безопасное и полнофункциональное выполнение агентов с контролем инструментов, делегированием задач и native tool calling.

## v1 Requirements

### Hook Dispatch

- [ ] **HOOK-01**: PreToolUse hook вызывается перед каждым tool call (local + MCP) в ToolExecutor
- [ ] **HOOK-02**: PreToolUse hook может заблокировать выполнение инструмента (action: block)
- [ ] **HOOK-03**: PreToolUse hook может модифицировать аргументы инструмента (action: modify)
- [ ] **HOOK-04**: PostToolUse hook вызывается после каждого tool call в ToolExecutor
- [ ] **HOOK-05**: PostToolUse hook может модифицировать output инструмента
- [ ] **HOOK-06**: Stop hook вызывается при завершении ThinRuntime.run() (нормальное + ошибка)
- [ ] **HOOK-07**: UserPromptSubmit hook вызывается в начале run() и может трансформировать prompt
- [ ] **HOOK-08**: HookRegistry пробрасывается через Agent → RuntimeFactory → ThinRuntime → ToolExecutor
- [ ] **HOOK-09**: SecurityGuard middleware реально блокирует tools в thin runtime
- [ ] **HOOK-10**: ToolOutputCompressor middleware реально сжимает output в thin runtime

### Tool Policy

- [ ] **PLCY-01**: DefaultToolPolicy проверяется в ToolExecutor перед выполнением инструмента
- [ ] **PLCY-02**: Denied tools не выполняются, возвращается JSON error с причиной
- [ ] **PLCY-03**: Policy check выполняется после PreToolUse hooks (hooks могут modify args)
- [ ] **PLCY-04**: Tool policy пробрасывается через Agent → RuntimeFactory → ThinRuntime

### Subagent Tool

- [ ] **SUBA-01**: LLM внутри ThinRuntime может вызвать spawn_agent tool
- [ ] **SUBA-02**: Субагент запускается в отдельном ThinRuntime instance через ThinSubagentOrchestrator
- [ ] **SUBA-03**: Субагент возвращает результат parent агенту через tool result
- [ ] **SUBA-04**: max_depth enforcement — субагент не может spawn'ить глубже лимита
- [ ] **SUBA-05**: max_concurrent enforcement — ограничение параллельных субагентов
- [ ] **SUBA-06**: Timeout enforcement — субагент прерывается по таймауту
- [ ] **SUBA-07**: Субагент наследует subset tools из parent
- [ ] **SUBA-08**: Ошибки субагента возвращаются как JSON error, не crash parent

### Command Routing

- [ ] **CMDR-01**: /command в user input перехватывается перед отправкой в LLM
- [ ] **CMDR-02**: Известные команды выполняются через CommandRegistry
- [ ] **CMDR-03**: Handled commands возвращают immediate response без вызова LLM
- [ ] **CMDR-04**: Non-command text проходит в LLM без изменений

### Native Tool Calling

- [ ] **NATV-01**: Anthropic native tool calling через tools parameter API
- [ ] **NATV-02**: OpenAI native tool calling через functions/tools parameter
- [ ] **NATV-03**: Google native tool calling через function declarations
- [ ] **NATV-04**: Parallel tool calls — batch multiple tool_use в одном response
- [ ] **NATV-05**: use_native_tools=False (default) сохраняет JSON-in-text поведение
- [ ] **NATV-06**: Fallback при ошибке native → JSON-in-text

### Integration

- [ ] **INTG-01**: Все существующие 4263+ тестов проходят на каждом этапе
- [ ] **INTG-02**: Все новые поля в AgentConfig/RuntimeConfig optional с None default
- [ ] **INTG-03**: Coverage новых файлов >= 95%
- [ ] **INTG-04**: ruff check + mypy clean

## v2 Requirements

### Extended Hooks

- **HOOK-V2-01**: Custom hook types (beyond 4 standard types)
- **HOOK-V2-02**: Hook priority ordering
- **HOOK-V2-03**: Async hook dispatch with timeout

### Subagent Enhancements

- **SUBA-V2-01**: Persistent subagent state across turns
- **SUBA-V2-02**: Subagent-to-subagent communication (MessageBus)
- **SUBA-V2-03**: Subagent progress streaming to parent

### MCP

- **MCP-V2-01**: MCP stdio transport (local servers)
- **MCP-V2-02**: MCP SSE transport (event streaming)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Breaking changes в AgentConfig | Обратная совместимость — все поля optional |
| MCP stdio/SSE transport | HTTP достаточно для v1.5, stdio сложнее и менее portable |
| Замена JSON-in-text как default | Strangler Fig — native tools opt-in, JSON-in-text проверен |
| Custom hook types | 4 стандартных типа покрывают все use cases Claude Code |
| Subagent state persistence | Stateless субагенты достаточны для v1, persistence в v2 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| HOOK-01 | Phase 1 | Pending |
| HOOK-02 | Phase 1 | Pending |
| HOOK-03 | Phase 1 | Pending |
| HOOK-04 | Phase 1 | Pending |
| HOOK-05 | Phase 1 | Pending |
| HOOK-06 | Phase 1 | Pending |
| HOOK-07 | Phase 1 | Pending |
| HOOK-08 | Phase 1 | Pending |
| HOOK-09 | Phase 1 | Pending |
| HOOK-10 | Phase 1 | Pending |
| PLCY-01 | Phase 2 | Pending |
| PLCY-02 | Phase 2 | Pending |
| PLCY-03 | Phase 2 | Pending |
| PLCY-04 | Phase 2 | Pending |
| SUBA-01 | Phase 3 | Pending |
| SUBA-02 | Phase 3 | Pending |
| SUBA-03 | Phase 3 | Pending |
| SUBA-04 | Phase 3 | Pending |
| SUBA-05 | Phase 3 | Pending |
| SUBA-06 | Phase 3 | Pending |
| SUBA-07 | Phase 3 | Pending |
| SUBA-08 | Phase 3 | Pending |
| CMDR-01 | Phase 4 | Pending |
| CMDR-02 | Phase 4 | Pending |
| CMDR-03 | Phase 4 | Pending |
| CMDR-04 | Phase 4 | Pending |
| NATV-01 | Phase 5 | Pending |
| NATV-02 | Phase 5 | Pending |
| NATV-03 | Phase 5 | Pending |
| NATV-04 | Phase 5 | Pending |
| NATV-05 | Phase 5 | Pending |
| NATV-06 | Phase 5 | Pending |
| INTG-01 | Phase 6 | Pending |
| INTG-02 | Phase 6 | Pending |
| INTG-03 | Phase 6 | Pending |
| INTG-04 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 36 total
- Mapped to phases: 36
- Unmapped: 0

---
*Requirements defined: 2026-04-12*
*Last updated: 2026-04-12 after initial definition*
