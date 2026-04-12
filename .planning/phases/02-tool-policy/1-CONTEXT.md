# Phase 2: Tool Policy Enforcement — Context

## Goal
Enforce DefaultToolPolicy in ToolExecutor after hook dispatch, blocking denied tools with structured JSON error responses.

## Requirements
- PLCY-01: DefaultToolPolicy checked in ToolExecutor before tool execution
- PLCY-02: Denied tools do not execute, return JSON error with denial reason
- PLCY-03: Policy check runs after PreToolUse hooks (hooks can modify args)
- PLCY-04: Tool policy propagates through Agent -> RuntimeFactory -> ThinRuntime

## Key Decision
- Hook order: PreToolUse -> **Policy** -> Execute -> PostToolUse
- Policy sees the hook-modified args, not original

## Existing Infrastructure
- `DefaultToolPolicy` (`policy/tool_policy.py`) — fully implemented, 4-step logic
- `ToolPolicyInput` — frozen dataclass: tool_name, input_data, active_skill_ids, allowed_local_tools
- `PermissionAllow` / `PermissionDeny` — result types
- `ToolExecutor` already has hook_dispatcher from Phase 1

## Design
ToolExecutor can auto-construct ToolPolicyInput from its own state:
- `allowed_local_tools = set(self._local_tools.keys())`
- `active_skill_ids = list(self._mcp_servers.keys())`

This means ToolExecutor receives ONLY the policy, no external state needed.

## Constraints
- All 4313+ existing tests must pass
- All new fields optional with None default
- TDD: tests first
- Policy runs AFTER PreToolUse hooks, BEFORE execution
