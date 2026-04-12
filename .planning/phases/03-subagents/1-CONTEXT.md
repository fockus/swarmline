# Phase 3: LLM-Initiated Subagents — Context

## Goal
LLM running inside ThinRuntime can spawn child agents to delegate subtasks via spawn_agent tool, with results returned as tool output and safety limits on depth, concurrency, and timeout.

## Requirements
- SUBA-01: LLM can call spawn_agent tool
- SUBA-02: Child runs in separate ThinRuntime via ThinSubagentOrchestrator
- SUBA-03: Result returned to parent as structured JSON tool result
- SUBA-04: max_depth enforcement (default 3)
- SUBA-05: max_concurrent enforcement
- SUBA-06: Timeout enforcement (asyncio.wait_for)
- SUBA-07: Child inherits configurable subset of parent tools
- SUBA-08: Errors return JSON, never crash parent

## Existing Infrastructure
- `ThinSubagentOrchestrator` (`orchestration/thin_subagent.py`) — spawn/wait/cancel, max_concurrent, per-worker ThinRuntime
- `SubagentSpec` — name, system_prompt, tools
- `SubagentResult` — agent_id, status, output
- max_concurrent already enforced (raises ValueError)

## What's Missing
- No `spawn_agent` ToolSpec (LLM can't invoke subagents)
- No max_depth tracking (recursion protection)
- No timeout on individual subagent runs
- No tool inheritance logic (subset of parent tools)
- Not wired into ThinRuntime as a builtin tool

## Design
New file: `src/swarmline/runtime/thin/subagent_tool.py`
- `SUBAGENT_TOOL_SPEC` — ToolSpec with JSON Schema: {task: str (required), system_prompt: str (optional), tools: list[str] (optional)}
- `SubagentToolConfig` — frozen dataclass: max_concurrent=4, max_depth=3, timeout_seconds=300
- `create_subagent_executor(orchestrator, config, parent_tools, current_depth)` → async callable
- Executor: parse args → build SubagentSpec → spawn → wait_for(timeout) → return JSON result

Config field: `AgentConfig.subagent_config: SubagentToolConfig | None = None`
Wiring: config → runtime_wiring → create_kwargs → ThinRuntime → builtin tool
