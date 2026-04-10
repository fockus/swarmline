# Wave 2+ Release-Risk Audit

Date: 2026-03-18
Scope: read-only follow-up audit for the remaining waves after the Wave 0 / Wave 1 report. Focus areas: persistence parity, provider/runtime edge cases, workflow compilation/resume semantics, optional-deps/public surface, and examples/docs smoke.

Important note:
- `gpt-5.4` subagents were used for candidate discovery only.
- Findings below were promoted only after local reproduction and/or direct code inspection on the main workspace.
- This report contains only new findings beyond `2026-03-18_wave0-wave1_release-risk-audit.md`.

## Workspace Snapshot

- current worktree is dirty only in user-facing docs/changelog files:
  - `CHANGELOG.md`
  - `docs/api-reference.md`
  - `docs/getting-started.md`
  - `mkdocs.yml`
- no new code modifications were introduced during this audit

## Additional Smoke Performed

Examples that currently run successfully on this workspace:

- `python examples/09_memory_providers.py`
- `python examples/10_sessions.py`
- `python examples/20_workflow_graph.py`
- `python examples/21_agent_as_tool.py`
- `python examples/22_task_queue.py`
- `python examples/24_deep_research.py`
- `python examples/25_shopping_agent.py`
- `python examples/26_code_project_team.py`

These passes matter because they reduce the chance that the remaining findings are just superficial example/documentation drift.

## New Confirmed Code Defects

### P2 — `InMemoryMemoryProvider` aliases saved session state instead of snapshotting it

File:
- `src/cognitia/memory/inmemory.py:145-175`

Problem:
- `save_session_state()` stores `active_skill_ids` by reference inside `_session_states`
- `get_session_state()` returns the live stored dict, not a copy

Manual repro:
- save session state with `active_skill_ids = ["a"]`
- mutate the original list after `save_session_state()`
- `get_session_state()` returns `["a", "b"]`
- mutate the loaded state's `active_skill_ids`
- subsequent `get_session_state()` reflects that mutation too

Why this is a bug:
- the in-memory provider does not provide snapshot semantics
- session rehydration and backend parity become backend-dependent in exactly the place that should be storage-agnostic

### P3 — SQL fact-source precedence does not match the documented contract

Files:
- `src/cognitia/memory/sqlite.py:131-164`
- `src/cognitia/memory/postgres.py:131-160`

Problem:
- both SQL backends document source priority as `user > ai_inferred > mcp`
- both implementations only protect `user`
- an existing `ai_inferred` fact can still be overwritten by a later `mcp` fact

Manual repro:
- SQLite repro:
  - `upsert_fact(..., source="ai_inferred")`
  - then `upsert_fact(..., source="mcp")`
  - `get_facts()` returns the `mcp` value

Why this is a bug:
- the storage contract described by the implementations is false
- a weaker source can overwrite a stronger one, which can degrade profile/session correctness over time

### P1 — workflow checkpoint resume skips the failed node instead of replaying it

File:
- `src/cognitia/orchestration/workflow_graph.py:187-198`

Problem:
- when resuming from a checkpoint, `execute(..., resume=True)` loads `(last_node, saved_state)` and immediately advances to `_get_next(last_node, state)`
- this skips re-executing the checkpointed node itself

Manual repro:
- graph `a -> b -> c`
- `b` raises on first execution after the checkpoint is saved
- checkpoint contains `("b", {"a": True})`
- resuming yields `{"a": True, "c": True}` with no `b` result at all

Why this is a bug:
- crash recovery semantics are wrong
- resume can silently continue past work that never completed successfully

### P2 — LangGraph compilation helpers drop parallel-group semantics

Files:
- `src/cognitia/orchestration/workflow_executor.py:130-154`
- `src/cognitia/orchestration/workflow_langgraph.py:40-78`

Problem:
- `compile_to_langgraph_spec()` serializes only `nodes`, `edges`, and `conditional_edges`
- it completely omits `WorkflowGraph._parallel_groups`
- `compile_to_langgraph()` shows the same structural omission by iterating only `_nodes`, `_edges`, and `_conditional_edges`

Manual repro:
- create a workflow with `add_parallel(["a", "b", "c"], then="d")`
- set entry to `__parallel_a_b_c`
- `compile_to_langgraph_spec()` returns:
  - entry `__parallel_a_b_c`
  - no synthetic node for that entry
  - no fan-out / fan-in edges
  - no parallel metadata

Why this is a bug:
- the produced spec is not equivalent to the source workflow
- any runtime/compiler path built on this helper cannot faithfully execute or export workflows with parallel groups

### P2 — `CliAgentRuntime.cancel()` is reported as `runtime_crash` instead of `cancelled`

File:
- `src/cognitia/runtime/cli/runtime.py:142-155`
- `src/cognitia/runtime/cli/runtime.py:170-189`

Problem:
- `cancel()` just terminates the subprocess
- `run()` later interprets the non-zero exit code as `RuntimeEvent.error(kind="runtime_crash", ...)`

Manual repro:
- start `CliAgentRuntime` with a long-lived `python -c 'import time; ... sleep(60)'` subprocess
- call `rt.cancel()`
- observed terminal event:
  - `error`
  - `kind="runtime_crash"`
  - `message="Process exited with code -15: "`

Why this is a bug:
- callers cannot distinguish intentional cancellation from an actual subprocess failure
- cancellation-specific retry/UI behavior becomes impossible

### P2 — dict-style `mcp_servers` configs break on portable runtime wiring

Files:
- `src/cognitia/agent/runtime_wiring.py:51-52`
- `src/cognitia/runtime/thin/mcp_client.py:34-42`

Problem:
- portable runtime wiring forwards `agent_config.mcp_servers` as-is
- `resolve_mcp_server_url()` only supports:
  - plain string values
  - objects with a `.url` attribute
- plain dict configs are treated as missing

Manual repro:
- `resolve_mcp_server_url({"s": {"type": "http", "url": "http://localhost:9999/mcp"}}, "s")`
- observed result: `None`
- this matters because `AgentConfig.mcp_servers` is typed as `dict[str, Any]`, and tests already use dict-style input in `tests/unit/test_agent_config.py`

Why this is a bug:
- a public-looking config shape silently disables MCP discovery/execution on portable runtimes
- the failure mode is degraded behavior, not a clean validation error

### P2 — Claude SDK tool-result metadata is dropped and failures are masked as successful tool calls

Files:
- `src/cognitia/runtime/adapter.py:391-396`
- `src/cognitia/runtime/claude_code.py:218-223`

Problem:
- `RuntimeAdapter._process_message()` converts `ToolResultBlock` into `StreamEvent(type="tool_use_result")` with only `tool_result`
- `ClaudeCodeRuntime._convert_event()` then always maps that to:
  - `tool_call_finished`
  - `name=""`
  - `correlation_id=""`
  - `ok=True`

Manual repro:
- create a mocked `ToolResultBlock` with:
  - `tool_use_id = "tool-123"`
  - `is_error = True`
  - `content = "tool failed"`
- observed adapter output: `("tool_use_result", "", "tool failed")`
- observed runtime output: `tool_call_finished` with `ok=True`, empty `name`, empty `correlation_id`

Why this is a bug:
- failed tool executions are surfaced as successful
- observability, UI projection, and any correlation logic lose the link to the originating tool call

## Verified Safe In This Pass

- no new defendable bugs were confirmed in the optional-deps/public-surface wave
- the currently tested examples from workflow/memory/multi-agent surface run successfully
- current docs/examples smoke did not reveal another release blocker beyond the code issues listed above

## Suggested Next Fix Order

1. workflow checkpoint/resume semantics
2. CLI cancellation semantics
3. portable MCP config normalization or validation
4. Claude SDK tool-result metadata preservation
5. in-memory session-state snapshot semantics (`memory.inmemory` + `session.backends`)
6. workflow LangGraph export/compiler parity
7. fact-source precedence enforcement in SQL providers
