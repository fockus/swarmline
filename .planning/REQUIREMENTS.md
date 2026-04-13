# Requirements: ThinRuntime Claude Code Parity

**Defined:** 2026-04-12 (v1), 2026-04-13 (v2)
**Core Value:** ThinRuntime обеспечивает безопасное и полнофункциональное выполнение агентов с продвинутым context management, session persistence и multimodal support

## v1 Requirements (COMPLETE -- Parity v1)

All v1 requirements completed and validated with Judge scores 4.25-4.40/5.0.

### Hook Dispatch
- [x] **HOOK-01** -- **HOOK-10**: All hook dispatch requirements -- Phase 1

### Tool Policy
- [x] **PLCY-01** -- **PLCY-04**: All policy enforcement requirements -- Phase 2

### Subagents
- [x] **SUBA-01** -- **SUBA-08**: All subagent requirements -- Phase 3

### Commands
- [x] **CMDR-01** -- **CMDR-04**: All command routing requirements -- Phase 4

### Native Tools
- [x] **NATV-01** -- **NATV-06**: All native tool calling requirements -- Phase 5

### Integration
- [x] **INTG-01** -- **INTG-04**: All integration validation requirements -- Phase 6

### Coding Profile
- [x] **CADG-01** -- **CADG-05**: All coding profile requirements -- Phase 7

### Coding Tasks
- [x] **CTSK-01** -- **CTSK-05**: All coding task requirements -- Phase 8

### Coding Context
- [x] **CCTX-01** -- **CCTX-02**, **COMP-01** -- **COMP-03**: All context/compat requirements -- Phase 9

### Coding Subagent
- [x] **CSUB-01** -- **CSUB-03**, **CVAL-01** -- **CVAL-03**: All inheritance requirements -- Phase 10

## v2 Requirements (Parity v2 -- Claude Code Gap Closure)

### Project Instructions

- [ ] **INST-01**: ThinRuntime автоматически загружает instruction files из cwd -> parent dirs -> home directory -- Phase 11
- [ ] **INST-02**: Поддержка нескольких форматов: CLAUDE.md, AGENTS.md, GEMINI.md, RULES.md (multi-agent universal) -- Phase 11
- [ ] **INST-03**: Приоритет загрузки: RULES.md > CLAUDE.md > AGENTS.md > GEMINI.md (первый найденный) -- Phase 11
- [ ] **INST-04**: Merge стратегия: home (lowest) -> parent dirs -> project root (highest priority) -- Phase 11
- [ ] **INST-05**: Инжект через существующий InputFilter pipeline без модификации run() -- Phase 11

### System Reminders

- [ ] **RMND-01**: Conditional context блоки инжектируются в messages по trigger conditions -- Phase 11
- [ ] **RMND-02**: Reminder budget ограничен (max 500 tokens) для предотвращения prompt bloat -- Phase 11
- [ ] **RMND-03**: Priority ordering: при бюджетном pressure высокоприоритетные reminders сохраняются -- Phase 11
- [ ] **RMND-04**: Реализация через InputFilter без модификации ThinRuntime.run() -- Phase 11

### Web Tools

- [ ] **WEBT-01**: WebSearch доступен как built-in tool в ThinRuntime (через существующие web провайдеры) -- Phase 12
- [ ] **WEBT-02**: WebFetch доступен как built-in tool для получения содержимого URL -- Phase 12
- [ ] **WEBT-03**: Domain allow/block list для контроля доступа к веб-ресурсам -- Phase 12
- [ ] **WEBT-04**: Интеграция через CodingToolPack как опциональные инструменты -- Phase 12

### MCP Resources

- [ ] **MCPR-01**: McpClient расширен для resources/list и resources/read JSON-RPC methods -- Phase 12
- [ ] **MCPR-02**: ReadMcpResource доступен как tool для чтения MCP ресурсов по URI -- Phase 12
- [ ] **MCPR-03**: Resource list кэшируется при подключении к серверу -- Phase 12

### Context Management

- [ ] **CMPCT-01**: ThinRuntime автоматически суммаризирует ранние сообщения через LLM при приближении к token budget вместо обрезки -- Phase 13
- [ ] **CMPCT-02**: Compaction сохраняет ключевые решения, tool results и project instructions в summary -- Phase 13
- [ ] **CMPCT-03**: 3-tier pipeline: tool result collapse -> LLM summarization -> emergency truncation (fallback) -- Phase 13
- [ ] **CMPCT-04**: Compaction strategy конфигурируется через RuntimeConfig (вкл/выкл, бюджет, модель) -- Phase 13

### Session Resume

- [ ] **SESS-01**: ThinRuntime сохраняет conversation history между вызовами run() через MessageStore -- Phase 14
- [ ] **SESS-02**: Resume по session_id загружает предыдущую историю и продолжает разговор -- Phase 14
- [ ] **SESS-03**: Auto-compaction при resume если восстановленная история превышает token budget -- Phase 14
- [ ] **SESS-04**: JSONL persistence format с roundtrip-clean сериализацией -- Phase 14

### Thinking Events

- [ ] **THNK-01**: RuntimeEvent.thinking_delta для streaming thinking blocks отдельно от ответа -- Phase 15
- [ ] **THNK-02**: Anthropic extended thinking API integration (budget_tokens config) -- Phase 15
- [ ] **THNK-03**: Multi-turn thinking signature preservation (non-compactable recent blocks) -- Phase 15
- [ ] **THNK-04**: Non-Anthropic провайдеры: status warning при включении thinking mode -- Phase 15

### Multimodal Input

- [ ] **MMOD-01**: Message поддерживает multi-part content (text + image + file) через additive content_blocks field -- Phase 16
- [ ] **MMOD-02**: Инструмент read возвращает ImageBlock при чтении PNG/JPG файлов -- Phase 16
- [ ] **MMOD-03**: Provider-specific конвертация: Anthropic vision blocks, OpenAI image_url, Google inline_data -- Phase 16
- [ ] **MMOD-04**: PDF extraction через опциональный pymupdf4llm extra -- Phase 16
- [ ] **MMOD-05**: Jupyter notebook extraction через опциональный nbformat extra -- Phase 16

### Git Worktree Isolation

- [ ] **WKTR-01**: SubagentSpec поддерживает isolation="worktree" для запуска в отдельном git worktree -- Phase 17
- [ ] **WKTR-02**: Worktree lifecycle: create -> use -> cleanup автоматически при завершении субагента -- Phase 17
- [ ] **WKTR-03**: Stale worktree detection и cleanup при инициализации orchestrator -- Phase 17
- [ ] **WKTR-04**: Max worktrees limit (default 5) для предотвращения disk space exhaustion -- Phase 17

### Background Agents

- [ ] **BGND-01**: Субагенты могут запускаться в background mode с async notification при завершении -- Phase 17
- [ ] **BGND-02**: RuntimeEvent.background_complete для уведомления parent agent -- Phase 17
- [ ] **BGND-03**: Monitor tool для async streaming stdout/stderr от background процессов -- Phase 17
- [ ] **BGND-04**: Mandatory timeout (5 min default) и error forwarding через done_callbacks -- Phase 17

## v1.6.0+ Requirements (Deferred)

- **CMPCT-05**: Anthropic compact API passthrough
- **INST-06**: @import syntax для cross-file includes
- **INST-07**: File watcher hot reload
- **MMOD-06**: Video/audio input support
- **MCPR-04**: Resource subscriptions (change notifications)
- **WKTR-05**: Automatic merge-back из worktree
- **BGND-05**: Monitor tool min_interval throttling

## Out of Scope

| Feature | Reason |
|---------|--------|
| Interactive permission modes (auto/default/plan) | Binary policy sufficient for library |
| Plan mode review gate | Planner strategy exists; interactive review is UI layer |
| tiktoken tokenizer | OpenAI-only; char heuristic sufficient for multi-provider |
| gitpython | Heavy; asyncio subprocess lighter |
| watchdog file watcher | Overkill; stat().st_mtime sufficient |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| HOOK-01..10 | Phase 1 | Complete |
| PLCY-01..04 | Phase 2 | Complete |
| SUBA-01..08 | Phase 3 | Complete |
| CMDR-01..04 | Phase 4 | Complete |
| NATV-01..06 | Phase 5 | Complete |
| INTG-01..04 | Phase 6 | Complete |
| CADG-01..05 | Phase 7 | Complete |
| CTSK-01..05 | Phase 8 | Complete |
| CCTX-01..02, COMP-01..03 | Phase 9 | Complete |
| CSUB-01..03, CVAL-01..03 | Phase 10 | Complete |
| INST-01..05 | Phase 11 | Pending |
| RMND-01..04 | Phase 11 | Pending |
| WEBT-01..04 | Phase 12 | Pending |
| MCPR-01..03 | Phase 12 | Pending |
| CMPCT-01..04 | Phase 13 | Pending |
| SESS-01..04 | Phase 14 | Pending |
| THNK-01..04 | Phase 15 | Pending |
| MMOD-01..05 | Phase 16 | Pending |
| WKTR-01..04 | Phase 17 | Pending |
| BGND-01..04 | Phase 17 | Pending |

**Coverage:**
- v1 requirements: 60 total -- Complete
- v2 requirements: 41 total
- Mapped to phases: 41
- Unmapped: 0

---
*Requirements defined: 2026-04-12 (v1), 2026-04-13 (v2)*
*Last updated: 2026-04-13 after roadmap creation*
