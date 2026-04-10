# Runtime / Session / Orchestration Follow-up Audit

Date: 2026-03-18
Scope: read-only audit after the 4 confirmed review findings, focused on runtime/session/orchestration seams only.

## Verification Snapshot

- `pytest -q`: `2357 passed, 16 skipped, 5 deselected, 19 warnings`
- `ruff check src/ tests/ --statistics`: `60` errors
  - `27` `E402`
  - `26` `F401`
  - `6` `F841`
  - `1` `F541`
- `mypy src/cognitia/`: `27` errors in `17` files
- Additional manual reproductions were run for terminal-contract, history-roundtrip and workflow-runtime seams.

This report intentionally does **not** repeat the 4 already-confirmed review findings recorded separately in:
- `.memory-bank/notes/2026-03-18_17-10_2026-03-18review-findings-followup.md`

## Confirmed New Defects

### P1 — legacy runtime wrappers still synthesize success on silent EOF

Files:
- `src/cognitia/runtime/ports/base.py:275-308`
- `src/cognitia/session/manager.py:317-343`

Problem:
- `BaseRuntimePort.stream_reply()` and the runtime branch of `InMemorySessionManager.stream_reply()` still emit `done` even when the underlying `AgentRuntime` never produced terminal `final` or `error`.
- Manual repro with a fake runtime yielding only `assistant_delta("partial")` produces:
  - `text_delta("partial")`
  - `done("partial")`

Why this is a bug:
- `AgentRuntime` contract explicitly requires terminal `final` or `error`.
- These wrappers therefore re-introduce the exact “silent success on truncated stream” class of bug that was already hardened in `collect_runtime_output()` and SDK/CLI helpers.

Impact:
- Any caller using `RuntimePort` or `SessionManager.stream_reply()` can still accept incomplete runs as successful turns.

### P1 — ClaudeCodeRuntime emits both `error` and `final` for the same failed turn

File:
- `src/cognitia/runtime/claude_code.py:125-177`

Problem:
- If the underlying adapter yields `StreamEvent(type="error")`, `ClaudeCodeRuntime.run()` forwards it as `RuntimeEvent.error(...)` but then still falls through to the finalization block and emits `RuntimeEvent.final(...)`.

Manual repro:
- Fake adapter yielding a single `error("SDK crash")` produces:
  - `RuntimeEvent.error(...)`
  - `RuntimeEvent.final(text="", new_messages=[], ...)`

Why this is a bug:
- `AgentRuntime` terminal contract is `final` **or** `error`, not both.
- Consumers that do not short-circuit on the first terminal event can observe contradictory outcomes for the same turn.

### P1 — DeepAgents portable path cannot round-trip tool history across turns

Files:
- `src/cognitia/runtime/deepagents_langchain.py:41-48`
- `src/cognitia/runtime/deepagents.py:221-226`

Problem:
- `build_langchain_messages()` drops `tool` role messages entirely.
- `DeepAgentsRuntime.run()` then finalizes with `new_messages = [assistant_only]`, even if tool calls happened during the turn.

Manual repro:
- Passing `[user, assistant, tool, assistant]` into `build_langchain_messages()` yields only `SystemMessage`, `HumanMessage`, `AIMessage`, `AIMessage`; the tool payload disappears.

Why this is a bug:
- Even after facade/session layers started honoring canonical `final.new_messages`, the deepagents portable runtime still cannot preserve or replay tool context across turns.
- Multi-turn deepagents flows that depend on prior tool outputs remain semantically lossy.

### P2 — ThinWorkflowExecutor wires tools and MCP servers into the runtime but never advertises them

File:
- `src/cognitia/orchestration/workflow_executor.py:43-55`

Problem:
- `ThinWorkflowExecutor` accepts `local_tools` and `mcp_servers`, passes them into `ThinRuntime(...)`, but hardcodes `active_tools=[]` in `runtime.run(...)`.

Why this is a bug:
- The runtime may have executors available, but the LLM never sees tool specs, so workflow nodes cannot actually choose those tools.
- This is the same partially integrated pattern that previously existed in `ThinRuntimePort`, just in a different seam.

Impact:
- Workflow nodes that are expected to use tools/MCP can silently degrade to pure-text reasoning.

### P2 — MixedRuntimeExecutor does not perform runtime routing at all

File:
- `src/cognitia/orchestration/workflow_executor.py:88-95`

Problem:
- `MixedRuntimeExecutor` claims per-node runtime routing, but `_routed_interceptor()` just calls `wf._execute_node(node_id, state)` directly and records `runtime_name` into metadata.
- No runtime-specific executor is created or invoked.

Why this is a bug:
- `runtime_map` is effectively dead configuration: it changes observability metadata only, not execution behavior.

Impact:
- Users can believe nodes are routed to `deepagents`/`thin`/other runtimes while the graph still executes through the default direct-node path.

### P2 — RuntimePort tool result events lose the tool identity

File:
- `src/cognitia/runtime/ports/base.py:59-63`

Problem:
- `convert_event(RuntimeEvent.tool_call_finished(...))` maps only `result_summary` into `StreamEvent.tool_result` and leaves `tool_name=""`.

Manual repro:
- `convert_event(RuntimeEvent.tool_call_finished(name="calc", ...))` returns `StreamEvent(type="tool_use_result", tool_name="", tool_result="42")`.

Why this is a bug:
- Any consumer of `RuntimePort`/`StreamEvent` loses the ability to correlate a result event with the tool that produced it.
- This is especially problematic for UI/event-projection layers and any session/debug tooling built on `StreamEvent`.

## Architectural Debt / Gaps

These items are real gaps, but not all of them are framed as immediate defects above.

### 1. Runtime/session migration still keeps two execution models alive

Files:
- `src/cognitia/session/types.py:31-41`
- `src/cognitia/session/manager.py:210-350`

Observations:
- `SessionState` still carries both `adapter: RuntimePort | None` and `runtime: AgentRuntime | None`, plus `runtime_messages` for the legacy path.
- `SessionManager` therefore owns two different execution and history semantics in one class.

Why it matters:
- This is the main reason contract hardening keeps needing duplicate fixes in multiple wrappers.

### 2. ClaudeCodeRuntime still violates the declared input-ownership model

Files:
- `src/cognitia/runtime/claude_code.py:3-10`
- `src/cognitia/runtime/claude_code.py:103-116`

Observations:
- The docstring says canonical history lives outside the runtime, but implementation still extracts only the last user message and relies on hidden SDK session state.

Why it matters:
- This is behaviour drift from the `AgentRuntime` contract and makes the claude runtime a special case that does not truly consume canonical `messages`.

### 3. Workflow runtime tests validate metadata, not actual routing semantics

Files:
- `tests/unit/test_workflow_executor.py:150-204`

Observations:
- Current tests for `MixedRuntimeExecutor` only assert that `__runtime_executions__` metadata is written.
- They do not verify that different runtimes are actually invoked.

Why it matters:
- This explains how the dead `runtime_map` path stayed green.

### 4. DeepAgents subagent default path appears tool-incomplete

Files:
- `src/cognitia/orchestration/deepagents_subagent.py:32-37`
- `src/cognitia/runtime/deepagents_tools.py:22-39`

Observations:
- Default `DeepAgentsSubagentOrchestrator` creates `DeepAgentsRuntime(..., tool_executors={})`.
- If a `SubagentSpec` advertises tools and no custom `runtime_factory` is injected, those tools fall back to the `_noop()` executor returning JSON error payloads.

Why it matters:
- This looks like another partially integrated path: the tool surface can be advertised without a working execution path.

### 5. `Agent.cleanup()` remains mostly ceremonial

Files:
- `src/cognitia/agent/agent.py:94-105`
- `src/cognitia/agent/agent.py:176-197`

Observations:
- Real runtimes are instantiated as local variables inside execution methods and cleaned up in local `finally`.
- `self._runtime` is rarely the owner of anything meaningful in the production path.

Why it matters:
- Public lifecycle API suggests persistent ownership that the class no longer actually has.

## Static Gate Context

The repo is still functionally green but not static-clean:

- `ruff` repo-wide remains red (`60` issues)
- `mypy` repo-wide remains red (`27` issues in `17` files)

Important nuance:
- These static errors are mostly outside the newly confirmed runtime/session/orchestration defects above.
- The functional seams remain the higher-priority work because they affect real runtime semantics, not just gate hygiene.

## Suggested Next Fix Order

1. P1: stop synthetic success on silent EOF in `BaseRuntimePort` and `SessionManager.stream_reply()`
2. P1: make `ClaudeCodeRuntime` emit exactly one terminal event
3. P1: fix deepagents tool-history roundtrip (`tool` role conversion + canonical `new_messages`)
4. P2: fix workflow executors (`ThinWorkflowExecutor`, `MixedRuntimeExecutor`)
5. P2: preserve `tool_name` in `RuntimePort` result conversion
6. Then resume broader migration cleanup and repo-wide static debt
