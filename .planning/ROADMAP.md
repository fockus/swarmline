# Roadmap: ThinRuntime Claude Code Parity

## Overview

Transform ThinRuntime from a lightweight LLM loop into a full-featured runtime with hook dispatch, tool policy enforcement, LLM-initiated subagents, slash-command routing, and native tool calling API -- achieving feature parity with Claude Code while remaining multi-provider. Six phases deliver incremental, independently verifiable capabilities on top of the existing swarmline codebase (v1.4.1 -> v1.5.0), with each phase maintaining backward compatibility across all 4263+ existing tests.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Hook Dispatch** - Wire HookRegistry into ThinRuntime/ToolExecutor for PreToolUse, PostToolUse, Stop, and UserPromptSubmit lifecycle events
- [ ] **Phase 2: Tool Policy Enforcement** - Enforce DefaultToolPolicy in ToolExecutor after hook dispatch, blocking denied tools with error responses
- [ ] **Phase 3: LLM-Initiated Subagents** - Register spawn_agent tool in ThinRuntime so LLM can delegate tasks to child agents with depth/concurrency/timeout limits
- [ ] **Phase 4: Command Routing** - Intercept /commands in user input before LLM, routing to CommandRegistry for immediate execution
- [ ] **Phase 5: Native Tool Calling** - Opt-in native tool calling API for Anthropic/OpenAI/Google with parallel execution and Strangler Fig fallback
- [ ] **Phase 6: Integration Validation** - Full-stack integration tests, cross-feature interaction validation, lint/type/coverage gates

## Phase Details

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
**Plans**: TBD

Plans:
- [ ] 01-01: HookDispatcher Protocol, HookResult types, DefaultHookDispatcher implementation
- [ ] 01-02: Hook integration into ToolExecutor (PreToolUse/PostToolUse)
- [ ] 01-03: Hook integration into ThinRuntime.run() (Stop/UserPromptSubmit) and Agent->RuntimeFactory wiring

### Phase 2: Tool Policy Enforcement
**Goal**: Developers can restrict which tools an agent is allowed to use via DefaultToolPolicy, with denied tools returning structured error messages instead of executing
**Depends on**: Phase 1 (policy check runs after PreToolUse hooks in the ToolExecutor pipeline)
**Requirements**: PLCY-01, PLCY-02, PLCY-03, PLCY-04
**Success Criteria** (what must be TRUE):
  1. A tool denied by DefaultToolPolicy does not execute and returns a JSON error with the denial reason
  2. Policy check runs after PreToolUse hooks, so hooks can modify tool name/args before policy evaluates
  3. Tool policy configured via AgentConfig reaches ThinRuntime's ToolExecutor through the RuntimeFactory chain
**Plans**: TBD

Plans:
- [ ] 02-01: Policy integration in ToolExecutor and Agent->RuntimeFactory wiring

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
**Plans**: TBD

Plans:
- [ ] 03-01: SubagentTool spec, types, and executor implementation
- [ ] 03-02: Subagent tool registration in ThinRuntime and Agent->RuntimeFactory wiring

### Phase 4: Command Routing
**Goal**: Users can type /commands that are intercepted and handled before reaching the LLM, providing instant responses for registered commands
**Depends on**: Phase 1 (command routing happens after UserPromptSubmit hooks in the run() pipeline)
**Requirements**: CMDR-01, CMDR-02, CMDR-03, CMDR-04
**Success Criteria** (what must be TRUE):
  1. A /command in user input is intercepted and executed via CommandRegistry without calling the LLM
  2. Non-command text passes through to the LLM unmodified
  3. Without a CommandRegistry configured, all input passes through unchanged (backward compatibility)
**Plans**: TBD

Plans:
- [ ] 04-01: CommandInterceptor implementation and ThinRuntime.run() integration

### Phase 5: Native Tool Calling
**Goal**: Developers can opt into provider-native tool calling API (Anthropic/OpenAI/Google) for structured tool invocation with parallel execution, while JSON-in-text remains the default (Strangler Fig)
**Depends on**: Nothing (independent Strangler Fig pattern, can execute in parallel with Phases 3-4)
**Requirements**: NATV-01, NATV-02, NATV-03, NATV-04, NATV-05, NATV-06
**Success Criteria** (what must be TRUE):
  1. With use_native_tools=True, ThinRuntime sends tools via the provider's native API parameter and parses tool calls from the structured response
  2. Parallel tool calls (multiple tool_use blocks in one response) are executed concurrently via asyncio.gather
  3. With use_native_tools=False (default), behavior is identical to current JSON-in-text parsing
  4. If native tool calling fails, runtime falls back to JSON-in-text automatically (Strangler Fig safety net)
**Plans**: TBD

Plans:
- [ ] 05-01: NativeToolCallAdapter protocol and Anthropic adapter
- [ ] 05-02: OpenAI and Google adapters
- [ ] 05-03: Integration into react strategy with parallel execution and fallback

### Phase 6: Integration Validation
**Goal**: All features work together correctly -- hooks, policy, subagents, commands, and native tools interact without conflicts, and all quality gates pass
**Depends on**: Phase 1, Phase 2, Phase 3, Phase 4, Phase 5
**Requirements**: INTG-01, INTG-02, INTG-03, INTG-04
**Success Criteria** (what must be TRUE):
  1. All 4263+ existing tests plus all new tests pass in a single pytest run
  2. All new fields in AgentConfig/RuntimeConfig are optional with None defaults (no breaking changes)
  3. Coverage on new files is >= 95%
  4. ruff check and mypy report zero errors on src/ and tests/
**Plans**: TBD

Plans:
- [ ] 06-01: Full-stack integration tests and final quality gate validation

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6
Note: Phases 4 and 5 are independent after their prerequisites and could execute in parallel.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Hook Dispatch | 0/3 | Not started | - |
| 2. Tool Policy Enforcement | 0/1 | Not started | - |
| 3. LLM-Initiated Subagents | 0/2 | Not started | - |
| 4. Command Routing | 0/1 | Not started | - |
| 5. Native Tool Calling | 0/3 | Not started | - |
| 6. Integration Validation | 0/1 | Not started | - |
