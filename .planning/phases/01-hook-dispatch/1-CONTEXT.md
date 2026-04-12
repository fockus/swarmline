# Phase 1: Hook Dispatch — Context

## Goal

Wire HookRegistry into ThinRuntime/ToolExecutor for PreToolUse, PostToolUse, Stop, and UserPromptSubmit lifecycle events. Closes P0 security gap: SecurityGuard middleware currently does nothing for thin runtime.

## Requirements

- HOOK-01: PreToolUse hook fires before every tool call (local + MCP) in ToolExecutor
- HOOK-02: PreToolUse hook can block tool execution (action: block)
- HOOK-03: PreToolUse hook can modify tool arguments (action: modify)
- HOOK-04: PostToolUse hook fires after every tool call in ToolExecutor
- HOOK-05: PostToolUse hook can modify tool output
- HOOK-06: Stop hook fires when ThinRuntime.run() completes (normal + error)
- HOOK-07: UserPromptSubmit hook fires at start of run() and can transform user prompt
- HOOK-08: HookRegistry propagates through Agent -> RuntimeFactory -> ThinRuntime -> ToolExecutor
- HOOK-09: SecurityGuard middleware actually blocks tools in thin runtime
- HOOK-10: ToolOutputCompressor middleware actually compresses output in thin runtime

## Key Decisions

- **Hook order**: PreToolUse -> Policy -> Execute -> PostToolUse (hooks can modify args, policy checks the result)
- **HookDispatcher as separate Protocol** from HookRegistry (ISP: dispatch logic separated from registration)
- **Hook error handling: fail-open** — bug in hook must not paralyze agent, log + allow
- **HookDispatcher Protocol <= 5 methods** (ISP compliance)

## Existing Infrastructure

### Already Built (reuse, don't rebuild)
- `HookRegistry` — registration API for 4 hook types
- `HookType` enum — PreToolUse, PostToolUse, Stop, UserPromptSubmit
- `PreToolUseHook`, `PostToolUseHook` — hook type definitions
- `SecurityGuard` middleware — has `get_hooks()` method
- `ToolOutputCompressor` middleware — has `get_hooks()` method

### Needs Creation
- `HookDispatcher` Protocol (new) — dispatch interface
- `DefaultHookDispatcher` (new) — concrete implementation using HookRegistry
- `HookResult` type (new) — action: allow/block/modify

### Needs Modification
- `ToolExecutor.execute()` — add pre/post hook dispatch
- `ThinRuntime.__init__()` / `run()` — accept registry, wire dispatcher, dispatch Stop/UserPromptSubmit
- `RuntimeFactory._create_thin()` — pass hook_registry kwarg
- `Agent` / runtime wiring — propagate hooks from config

## Constraints

- All 4263+ existing tests must pass at every step
- All new fields optional with None default
- TDD: tests first, implementation second
- Contract-first: Protocol -> contract tests -> implementation
- Python 3.10+, async-first

## Success Criteria

1. PreToolUse hook fires before every tool call and can block/modify
2. PostToolUse hook fires after every tool call and can modify output
3. Stop hook fires on run() completion (normal + error)
4. UserPromptSubmit hook fires at start of run() and can transform prompt
5. SecurityGuard middleware registered via HookRegistry actually blocks tools in ThinRuntime

## Source

Context gathered from: PROJECT.md, REQUIREMENTS.md, ROADMAP.md, MB plan (2026-04-12_feature_thin-runtime-claude-code-parity.md)
