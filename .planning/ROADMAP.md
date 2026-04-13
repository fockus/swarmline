# Roadmap: ThinRuntime Claude Code Parity

## Overview

Transform ThinRuntime from a lightweight LLM loop into a full-featured runtime with hook dispatch, tool policy enforcement, LLM-initiated subagents, slash-command routing, and native tool calling API -- achieving feature parity with Claude Code while remaining multi-provider. After parity, extend ThinRuntime with an opt-in coding-agent profile that assembles canonical coding tools, persistent task/todo semantics, richer coding context, and inherited coding behavior for thin subagents. Ten phases deliver incremental, independently verifiable capabilities on top of the existing swarmline codebase, with each phase maintaining backward compatibility across the existing offline suite.

Parity v2 (Phases 11-17) closes the remaining capability gaps: context management (compaction + instructions + reminders), session persistence, expanded tool surface (web + MCP resources), multimodal input, thinking events, and parallel agent infrastructure (worktree isolation + background agents). Seven phases deliver these features in dependency order, from low-risk InputFilter additions through high-complexity parallel infrastructure.

## Milestones

- Complete **v1.5.0-alpha Parity v1** - Phases 1-10 (completed 2026-04-13)
- Current **v1.5.0 Parity v2** - Phases 11-17 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>Parity v1 (Phases 1-10) -- COMPLETE 2026-04-13</summary>

- [x] **Phase 1: Hook Dispatch** - Wire HookRegistry into ThinRuntime/ToolExecutor for PreToolUse, PostToolUse, Stop, and UserPromptSubmit lifecycle events
- [x] **Phase 2: Tool Policy Enforcement** - Enforce DefaultToolPolicy in ToolExecutor after hook dispatch, blocking denied tools with error responses
- [x] **Phase 3: LLM-Initiated Subagents** - Register spawn_agent tool in ThinRuntime so LLM can delegate tasks to child agents with depth/concurrency/timeout limits
- [x] **Phase 4: Command Routing** - Intercept /commands in user input before LLM, routing to CommandRegistry for immediate execution
- [x] **Phase 5: Native Tool Calling** - Opt-in native tool calling API for Anthropic/OpenAI/Google with parallel execution and Strangler Fig fallback
- [x] **Phase 6: Integration Validation** - Full-stack integration tests, cross-feature interaction validation, lint/type/coverage gates
- [x] **Phase 7: Coding Profile Foundation** - Opt-in coding-agent profile, canonical coding tool pack, and profile-scoped policy without changing non-coding ThinRuntime behavior
- [x] **Phase 8: Coding Task Runtime and Persistence** - Persistent task/todo/session semantics for coding runs using existing GraphTaskBoard and TaskSessionStore seams
- [x] **Phase 9: Coding Context and Compatibility** - Budgeted coding-context slices plus legacy alias compatibility and fail-fast wiring
- [x] **Phase 10: Coding Subagent Inheritance and Validation** - Coding-profile inheritance for thin subagents plus tranche-level regression and quality closure

</details>

### Parity v2 (Phases 11-17) -- IN PROGRESS

- [x] **Phase 11: Foundation Filters** - Load project instructions and inject system reminders via InputFilter pipeline without modifying ThinRuntime.run()
- [x] **Phase 12: Tool Surface Expansion** - Add WebSearch/WebFetch built-in tools and MCP resource reading to extend agent capabilities
- [x] **Phase 13: Conversation Compaction** - 3-tier context management pipeline (tool collapse, LLM summarization, emergency truncation) to replace naive truncation
- [x] **Phase 14: Session Resume** - Persist and restore conversation history between run() calls with auto-compaction on resume
- [ ] **Phase 15: Thinking Events** - Separate reasoning stream via thinking_delta events with Anthropic extended thinking integration
- [ ] **Phase 16: Multimodal Input** - Multi-part message content (images, PDF, Jupyter) with provider-specific vision block conversion
- [ ] **Phase 17: Parallel Agent Infrastructure** - Git worktree isolation for subagents and background agent execution with async notifications

## Phase Details

<details>
<summary>Parity v1 Phase Details (Phases 1-10) -- COMPLETE</summary>

### Phase 1: Hook Dispatch
**Goal**: Developers using ThinRuntime get real lifecycle control -- SecurityGuard blocks dangerous tools, ToolOutputCompressor compresses output, and custom hooks transform prompts and intercept tool calls
**Depends on**: Nothing (first phase)
**Requirements**: HOOK-01, HOOK-02, HOOK-03, HOOK-04, HOOK-05, HOOK-06, HOOK-07, HOOK-08, HOOK-09, HOOK-10
**Success Criteria** (what must be TRUE):
  1. PreToolUse hook fires before every tool call (local and MCP) and can block execution or modify arguments
  2. PostToolUse hook fires after every tool call and can modify the returned output
  3. Stop hook fires when ThinRuntime.run() completes (both normal exit and error)
  4. UserPromptSubmit hook fires at the start of run() and can transform the user prompt before LLM sees it
  5. SecurityGuard middleware registered via HookRegistry actually blocks tools when running in ThinRuntime (closing the existing security gap)
**Plans**: 3/3 complete

Plans:
- [x] 01-01: HookDispatcher Protocol, HookResult types, DefaultHookDispatcher implementation
- [x] 01-02: Hook integration into ToolExecutor (PreToolUse/PostToolUse)
- [x] 01-03: Hook integration into ThinRuntime.run() (Stop/UserPromptSubmit) and Agent->RuntimeFactory wiring

### Phase 2: Tool Policy Enforcement
**Goal**: Developers can restrict which tools an agent is allowed to use via DefaultToolPolicy, with denied tools returning structured error messages instead of executing
**Depends on**: Phase 1 (policy check runs after PreToolUse hooks in the ToolExecutor pipeline)
**Requirements**: PLCY-01, PLCY-02, PLCY-03, PLCY-04
**Success Criteria** (what must be TRUE):
  1. A tool denied by DefaultToolPolicy does not execute and returns a JSON error with the denial reason
  2. Policy check runs after PreToolUse hooks, so hooks can modify tool name/args before policy evaluates
  3. Tool policy configured via AgentConfig reaches ThinRuntime's ToolExecutor through the RuntimeFactory chain
**Plans**: 1/1 complete

Plans:
- [x] 02-01: Policy integration in ToolExecutor and Agent->RuntimeFactory wiring

### Phase 3: LLM-Initiated Subagents
**Goal**: LLM running inside ThinRuntime can spawn child agents to delegate subtasks, with results returned as tool output and safety limits on depth, concurrency, and timeout
**Depends on**: Phase 1, Phase 2 (hooks control subagent tools, policy can deny spawn_agent)
**Requirements**: SUBA-01, SUBA-02, SUBA-03, SUBA-04, SUBA-05, SUBA-06, SUBA-07, SUBA-08
**Success Criteria** (what must be TRUE):
  1. LLM can call spawn_agent tool and receive the child agent's result as structured JSON in the tool response
  2. Child agent runs in a separate ThinRuntime instance via ThinSubagentOrchestrator
  3. Depth limit (max_depth), concurrency limit (max_concurrent), and timeout are enforced -- exceeding any returns a JSON error without crashing the parent
  4. Child agent inherits a configurable subset of parent tools
  5. Subagent errors (exceptions, timeouts) are returned as JSON error responses, never propagated as parent crashes
**Plans**: 2/2 complete

Plans:
- [x] 03-01: SubagentTool spec, types, and executor implementation
- [x] 03-02: Subagent tool registration in ThinRuntime and Agent->RuntimeFactory wiring

### Phase 4: Command Routing
**Goal**: Users can type /commands that are intercepted and handled before reaching the LLM, providing instant responses for registered commands
**Depends on**: Phase 1 (command routing happens after UserPromptSubmit hooks in the run() pipeline)
**Requirements**: CMDR-01, CMDR-02, CMDR-03, CMDR-04
**Success Criteria** (what must be TRUE):
  1. A /command in user input is intercepted and executed via CommandRegistry without calling the LLM
  2. Non-command text passes through to the LLM unmodified
  3. Without a CommandRegistry configured, all input passes through unchanged (backward compatibility)
**Plans**: 1/1 complete

Plans:
- [x] 04-01: CommandInterceptor implementation and ThinRuntime.run() integration

### Phase 5: Native Tool Calling
**Goal**: Developers can opt into provider-native tool calling API (Anthropic/OpenAI/Google) for structured tool invocation with parallel execution, while JSON-in-text remains the default (Strangler Fig)
**Depends on**: Nothing (independent Strangler Fig pattern, can execute in parallel with Phases 3-4)
**Requirements**: NATV-01, NATV-02, NATV-03, NATV-04, NATV-05, NATV-06
**Success Criteria** (what must be TRUE):
  1. With use_native_tools=True, ThinRuntime sends tools via the provider's native API parameter and parses tool calls from the structured response
  2. Parallel tool calls (multiple tool_use blocks in one response) are executed concurrently via asyncio.gather
  3. With use_native_tools=False (default), behavior is identical to current JSON-in-text parsing
  4. If native tool calling fails, runtime falls back to JSON-in-text automatically (Strangler Fig safety net)
**Plans**: 1/1 complete

Plans:
- [x] 05-01: NativeToolCallAdapter protocol and Anthropic adapter
- [x] 05-02: OpenAI and Google adapters
- [x] 05-03: Integration into react strategy with parallel execution and fallback

### Phase 6: Integration Validation
**Goal**: All features work together correctly -- hooks, policy, subagents, commands, and native tools interact without conflicts, and all quality gates pass
**Depends on**: Phase 1, Phase 2, Phase 3, Phase 4, Phase 5
**Requirements**: INTG-01, INTG-02, INTG-03, INTG-04
**Success Criteria** (what must be TRUE):
  1. All 4263+ existing tests plus all new tests pass in a single pytest run
  2. All new fields in AgentConfig/RuntimeConfig are optional with None defaults (no breaking changes)
  3. Coverage on new files is >= 95%
  4. ruff check and mypy report zero errors on src/ and tests/
**Plans**: 1/1 complete

Plans:
- [x] 06-01: Full-stack integration tests and final quality gate validation

### Phase 7: Coding Profile Foundation
**Goal**: Developers can opt into a `coding-agent profile` on top of `ThinRuntime`, receiving one canonical coding tool surface and explicit coding-only policy without changing the default secure posture of non-coding runs
**Depends on**: Phase 2, Phase 3, Phase 6
**Requirements**: CADG-01, CADG-02, CADG-03, CADG-04, CADG-05
**Success Criteria** (what must be TRUE):
  1. `ThinRuntime` accepts an opt-in coding profile without introducing a new runtime hierarchy
  2. Visible tool surface in coding mode matches executable tool surface exactly
  3. `read/write/edit/multi_edit/bash/ls/glob/grep` are sourced from shared builtin implementations rather than a parallel thin-only implementation path
  4. Coding policy explicitly allows only the declared coding tool set
  5. Default-deny behavior outside coding profile remains unchanged
**Plans**: 1/1 complete

Plans:
- [x] 07-01-PLAN.md — Coding profile contracts, canonical tool pack, ThinRuntime wiring, and policy-scoped regressions

### Phase 8: Coding Task Runtime and Persistence
**Goal**: Coding runs get persistent task, todo, and session semantics built from existing Swarmline seams instead of shims or markdown placeholders
**Depends on**: Phase 7
**Requirements**: CTSK-01, CTSK-02, CTSK-03, CTSK-04, CTSK-05
**Success Criteria** (what must be TRUE):
  1. Coding-task lifecycle is backed by `GraphTaskBoard` rather than a parallel task engine
  2. `todo_read/todo_write` are provider-backed in coding mode
  3. Task state and session-to-task binding survive restart/resume in supported persistence modes
  4. Typed persistence snapshots roundtrip cleanly
  5. Missing provider or missing binding paths fail fast instead of degrading silently
**Plans**: 1/1 complete

Plans:
- [x] 08-01: Coding task runtime facade and persistent task/todo/session adapters

### Phase 9: Coding Context and Compatibility
**Goal**: Coding runs get bounded task-aware context and backward-compatible legacy tool aliases, with deterministic truncation and explicit fail-fast semantics
**Depends on**: Phase 7, Phase 8
**Requirements**: CCTX-01, CCTX-02, COMP-01, COMP-02, COMP-03
**Success Criteria** (what must be TRUE):
  1. Coding mode assembles task/board/workspace/search/session/skill-profile context slices and non-coding mode does not
  2. Budget pressure results in deterministic omission/truncation rather than unstable context drift
  3. Legacy aliases map to canonical implementations in coding mode with equivalent behavior
  4. Unsupported alias/profile/wiring states return explicit errors
  5. Compatibility layer does not become a second implementation path
**Plans**: 1/1 complete

Plans:
- [x] 09-01: Coding context assembler and compatibility/fail-fast wiring

### Phase 10: Coding Subagent Inheritance and Validation
**Goal**: Thin subagents inherit the coding-agent profile correctly, and the full coding-agent tranche closes with no regression to non-coding ThinRuntime behavior
**Depends on**: Phase 7, Phase 8, Phase 9
**Requirements**: CSUB-01, CSUB-02, CSUB-03, CVAL-01, CVAL-02, CVAL-03
**Success Criteria** (what must be TRUE):
  1. Thin subagents inherit coding profile, coding tool surface, policy, and task context from their parent run
  2. Incompatible inheritance state fails fast rather than degrading to generic thin behavior
  3. Non-coding thin runs remain behaviorally unchanged
  4. Targeted packs, broader regression, `ruff`, and `mypy` are green for the coding-agent tranche
  5. New interfaces remain contract-first, dependency-safe, and within project interface limits
**Plans**: 1/1 complete

Plans:
- [x] 10-01: Coding-profile subagent inheritance and tranche-level validation closure

</details>

### Phase 11: Foundation Filters
**Goal**: Agents automatically receive project-specific instructions and dynamic context reminders without any modification to ThinRuntime.run(), using the existing InputFilter pipeline
**Depends on**: Phase 10 (continues from Parity v1 completion)
**Requirements**: INST-01, INST-02, INST-03, INST-04, INST-05, RMND-01, RMND-02, RMND-03, RMND-04
**Success Criteria** (what must be TRUE):
  1. Agent running in a directory with CLAUDE.md (or AGENTS.md, GEMINI.md, RULES.md) automatically receives those instructions in its system context without explicit configuration
  2. Instructions from home directory, parent directories, and project root are merged with project root taking highest priority
  3. System reminders matching their trigger conditions appear in messages; reminders not matching are absent
  4. Total reminder content stays within the 500-token budget cap, with high-priority reminders preserved under budget pressure
  5. Neither feature requires changes to ThinRuntime.run() -- both are pure InputFilter implementations
**Plans**: TBD

Plans:
- [x] 11-01: ProjectInstructionFilter and SystemReminderFilter implementations

### Phase 12: Tool Surface Expansion
**Goal**: Agents can search the web, fetch URL content, and read MCP server resources as built-in capabilities, extending the tool surface without new infrastructure
**Depends on**: Phase 11 (foundation filters provide context for tool usage)
**Requirements**: WEBT-01, WEBT-02, WEBT-03, WEBT-04, MCPR-01, MCPR-02, MCPR-03
**Success Criteria** (what must be TRUE):
  1. Agent can call web_search tool and receive search results from configured web provider
  2. Agent can call web_fetch tool and receive rendered page content from a URL
  3. Domain allow/block lists control which URLs web_fetch can access
  4. Agent can call read_mcp_resource tool to read a resource by URI from a connected MCP server
  5. MCP resource list is cached per-connection and available for tool discovery
**Plans**: TBD

Plans:
- [x] 12-01: WebSearch and WebFetch built-in tools with domain filtering + MCP resource reading

### Phase 13: Conversation Compaction
**Goal**: Long-running agents maintain coherent context by automatically summarizing early conversation turns through LLM instead of losing them to naive truncation
**Depends on**: Phase 11 (instructions must survive compaction)
**Requirements**: CMPCT-01, CMPCT-02, CMPCT-03, CMPCT-04
**Success Criteria** (what must be TRUE):
  1. When conversation approaches token budget, early messages are automatically replaced with an LLM-generated summary
  2. Compaction summary preserves key decisions, tool results, and project instructions from the compacted region
  3. 3-tier pipeline activates in order: tool result collapse first, then LLM summarization, then emergency truncation as fallback
  4. Compaction behavior is configurable via RuntimeConfig (enable/disable, budget threshold, summarization model)
**Plans**: TBD

Plans:
- [x] 13-01: Compaction pipeline (tool collapse, LLM summarization, emergency truncation)

### Phase 14: Session Resume
**Goal**: Agents can persist their conversation state and resume where they left off across process restarts, with automatic compaction when restored history is too large
**Depends on**: Phase 13 (compaction required for auto-compact on resume)
**Requirements**: SESS-01, SESS-02, SESS-03, SESS-04
**Success Criteria** (what must be TRUE):
  1. Conversation history is persisted to MessageStore between run() calls and survives process restart
  2. Resuming by session_id loads the previous conversation and continues seamlessly
  3. When restored history exceeds token budget, auto-compaction triggers before the resumed run proceeds
  4. JSONL persistence format round-trips all message types (user, assistant, tool_call, tool_result) without data loss
**Plans**: TBD

Plans:
- [x] 14-01: Session persistence, resume-by-id, and auto-compaction on resume

### Phase 15: Thinking Events
**Goal**: Developers can observe the model's reasoning process as a separate event stream, with Anthropic extended thinking budget control and multi-turn signature preservation
**Depends on**: Phase 13 (thinking blocks must be marked non-compactable)
**Requirements**: THNK-01, THNK-02, THNK-03, THNK-04
**Success Criteria** (what must be TRUE):
  1. RuntimeEvent.thinking_delta events stream thinking content separately from text_delta events
  2. Anthropic extended thinking is activated via budget_tokens config and thinking blocks are returned in the response
  3. Recent thinking blocks are marked non-compactable so multi-turn thinking signatures survive compaction
  4. Non-Anthropic providers emit a status warning when thinking mode is enabled instead of silently ignoring it
**Plans**: TBD

Plans:
- [ ] 15-01: ThinkingEvent type, Anthropic extended thinking adapter, and compaction exclusion

### Phase 16: Multimodal Input
**Goal**: Agents can process images, PDFs, and Jupyter notebooks alongside text, with automatic provider-specific conversion for Anthropic, OpenAI, and Google vision APIs
**Depends on**: Phase 14 (multimodal changes Message serialization which session resume must handle)
**Requirements**: MMOD-01, MMOD-02, MMOD-03, MMOD-04, MMOD-05
**Success Criteria** (what must be TRUE):
  1. Message supports multi-part content via additive content_blocks field while keeping content: str untouched for backward compatibility
  2. The read tool returns an ImageBlock when reading PNG/JPG files, which the LLM can interpret visually
  3. Provider adapters convert content_blocks to the correct format: Anthropic vision blocks, OpenAI image_url, Google inline_data
  4. PDF files are extracted to markdown text via optional pymupdf4llm dependency
  5. Jupyter notebooks are extracted to cell text via optional nbformat dependency
**Plans**: TBD

Plans:
- [ ] 16-01: ContentBlock types, Message extension, and provider-specific conversion adapters
- [ ] 16-02: File-type detection in read tool and optional PDF/Jupyter extractors

### Phase 17: Parallel Agent Infrastructure
**Goal**: Subagents can run in isolated git worktrees for safe parallel file operations, and background agents execute asynchronously with completion notifications and monitoring
**Depends on**: Phase 16 (all Message/serialization changes must be stable before parallel agents serialize messages)
**Requirements**: WKTR-01, WKTR-02, WKTR-03, WKTR-04, BGND-01, BGND-02, BGND-03, BGND-04
**Success Criteria** (what must be TRUE):
  1. SubagentSpec with isolation="worktree" causes the child agent to execute in a dedicated git worktree directory
  2. Worktree lifecycle (create, use, cleanup) is automatic -- cleanup happens on subagent completion or error
  3. Stale worktrees from crashed agents are detected and cleaned up on orchestrator initialization; max 5 worktrees enforced
  4. Background-mode subagents run asynchronously and emit RuntimeEvent.background_complete when finished
  5. Monitor tool streams stdout/stderr from background processes as async events to the parent agent
**Plans**: TBD

Plans:
- [ ] 17-01: Git worktree lifecycle management and SubagentSpec isolation mode
- [ ] 17-02: Background agent execution, completion events, and monitor tool

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10 -> 11 -> 12 -> 13 -> 14 -> 15 -> 16 -> 17

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Hook Dispatch | Parity v1 | 3/3 | Complete | 2026-04-12 |
| 2. Tool Policy Enforcement | Parity v1 | 1/1 | Complete | 2026-04-12 |
| 3. LLM-Initiated Subagents | Parity v1 | 2/2 | Complete | 2026-04-12 |
| 4. Command Routing | Parity v1 | 1/1 | Complete | 2026-04-12 |
| 5. Native Tool Calling | Parity v1 | 1/1 | Complete | 2026-04-12 |
| 6. Integration Validation | Parity v1 | 1/1 | Complete | 2026-04-12 |
| 7. Coding Profile Foundation | Parity v1 | 1/1 | Complete | 2026-04-12 |
| 8. Coding Task Runtime and Persistence | Parity v1 | 1/1 | Complete | 2026-04-12 |
| 9. Coding Context and Compatibility | Parity v1 | 1/1 | Complete | 2026-04-13 |
| 10. Coding Subagent Inheritance and Validation | Parity v1 | 1/1 | Complete | 2026-04-13 |
| 11. Foundation Filters | Parity v2 | 1/1 | Complete | 2026-04-13 |
| 12. Tool Surface Expansion | Parity v2 | 1/1 | Complete | 2026-04-13 |
| 13. Conversation Compaction | Parity v2 | 1/1 | Complete | 2026-04-13 |
| 14. Session Resume | Parity v2 | 1/1 | Complete | 2026-04-13 |
| 15. Thinking Events | Parity v2 | 0/1 | Not started | - |
| 16. Multimodal Input | Parity v2 | 0/2 | Not started | - |
| 17. Parallel Agent Infrastructure | Parity v2 | 0/2 | Not started | - |
