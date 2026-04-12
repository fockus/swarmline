# Unified Release-Risk Remediation Backlog

Date: 2026-03-18
Inputs:
- `.memory-bank/reports/2026-03-18_wave0-wave1_release-risk-audit.md`
- `.memory-bank/reports/2026-03-18_wave2-plus_release-risk-audit.md`

Scope:
- unify all confirmed findings from both audit reports into one executable remediation backlog
- optimize for fast implementation through parallel low-risk slices
- keep bugfix work separate from wider architectural cleanup

Important constraints:
- TDD first: every confirmed defect becomes a failing regression before code changes
- low-risk slices: one seam / one contract family / one verification block
- no public API signature changes unless strictly required by correctness
- do not touch currently user-dirty docs/changelog files in early code waves unless a fix explicitly requires docs sync later

## Consolidated Defect List

### Must-fix now

1. `Conversation` persists partial assistant text after terminal `error`
2. portable runtime exceptions escape from `Conversation` and `SessionManager`
3. `SqliteSessionBackend` is unsafe under concurrent access
4. `SessionKey.__str__()` is collision-prone and breaks session isolation
5. workflow checkpoint resume skips the checkpointed node
6. `CliAgentRuntime.cancel()` surfaces as `runtime_crash` instead of `cancelled`
7. dict-style `mcp_servers` silently fail on portable runtime wiring
8. Claude SDK tool-result metadata is dropped and failures are masked as successful

### Next batch

9. `BaseTeamOrchestrator` reports `completed` for all-failed/all-cancelled teams
10. `DeepAgentsTeamOrchestrator` skips worker task composition and does not wire worker messaging tool
11. default `DeepAgentsSubagentOrchestrator` advertises tools that cannot execute
12. `WorkflowGraph` LangGraph compile/export helpers drop parallel-group semantics
13. `_RuntimeEventAdapter` drops `tool_name` on `tool_call_finished`
14. `InMemorySessionBackend` aliases mutable state instead of snapshotting
15. `InMemoryMemoryProvider` aliases session state instead of snapshotting

### Tracked debt / lower urgency

16. SQL fact-source precedence implementation does not match the documented `user > ai_inferred > mcp` contract

## Execution Strategy

Implement in 5 batches.

- Batch 1 closes the runtime/session contract violations on the critical path.
- Batch 2 closes persistence identity and snapshot semantics.
- Batch 3 fixes orchestration/team correctness.
- Batch 4 fixes workflow crash-recovery and export semantics.
- Batch 5 closes remaining storage contract drift and final docs sync.

Each batch ends with targeted verification. Broader regression happens after Batches 2, 4, and 5.

## Parallel Ownership

### Worker A — runtime/session contract

Ownership:
- `src/swarmline/agent/conversation.py`
- `src/swarmline/session/manager.py`
- `src/swarmline/runtime/cli/runtime.py`
- `src/swarmline/runtime/adapter.py`
- `src/swarmline/runtime/claude_code.py`
- `src/swarmline/agent/agent.py`

Responsibilities:
- error-path history integrity
- exception normalization
- CLI cancellation semantics
- SDK tool-result metadata preservation
- portable event adapter metadata parity

### Worker B — session persistence + keying

Ownership:
- `src/swarmline/session/types.py`
- `src/swarmline/session/backends.py`

Responsibilities:
- collision-proof session key serialization
- SQLite backend concurrency safety
- in-memory session backend snapshot semantics

### Worker C — runtime wiring + MCP config normalization

Ownership:
- `src/swarmline/agent/runtime_wiring.py`
- `src/swarmline/runtime/thin/mcp_client.py`
- related portable runtime wiring tests

Responsibilities:
- normalize dict-style `mcp_servers` or fail-fast validate them
- preserve existing behavior for `str` and `McpServerSpec` inputs

### Worker D — orchestration/team correctness

Ownership:
- `src/swarmline/orchestration/base_team.py`
- `src/swarmline/orchestration/deepagents_team.py`
- `src/swarmline/orchestration/deepagents_subagent.py`

Responsibilities:
- aggregate team state correctness
- worker task composition parity
- send-message tool advertising/wiring
- tool-execution fail-fast vs actual executor wiring for deepagents subagents

### Worker E — workflow semantics + memory provider parity

Ownership:
- `src/swarmline/orchestration/workflow_graph.py`
- `src/swarmline/orchestration/workflow_langgraph.py`
- `src/swarmline/orchestration/workflow_executor.py`
- `src/swarmline/memory/inmemory.py`
- `src/swarmline/memory/sqlite.py`
- `src/swarmline/memory/postgres.py`

Responsibilities:
- checkpoint/resume semantics
- parallel-group LangGraph/export fidelity
- in-memory session-state snapshot semantics
- fact-source precedence enforcement or explicit contract downgrade

## Batch Plan

## Batch 1 — Runtime/Session Contract Integrity

Scope:
- findings 1, 2, 6, 8, 13

Steps:
1. Add failing regressions for `Conversation.say()` and `Conversation.stream()` when the turn ends in `error`.
2. Add failing regressions for portable runtime exceptions in:
   - `Conversation.say()`
   - `SessionManager.run_turn()`
   - `SessionManager.stream_reply()` if that path also leaks exceptions during implementation review.
3. Add failing regression for `CliAgentRuntime.cancel()` expecting terminal `cancelled` semantics.
4. Add failing regressions for Claude SDK tool-result metadata:
   - preserve tool identity or correlation data when available
   - propagate failure semantics instead of unconditional `ok=True`
5. Add failing regression for `_RuntimeEventAdapter` preserving `tool_name` on `tool_call_finished`.
6. Implement minimal fixes without widening public surface.

DoD:
- failed turns no longer append partial assistant text to conversation history
- unexpected runtime exceptions become typed error events/results instead of crashing callers
- CLI cancel path yields a cancellation-class terminal error/event, not `runtime_crash`
- Claude SDK tool-result path preserves enough metadata to avoid masking failures as successful
- `_RuntimeEventAdapter` preserves `tool_name` on tool result events

Verification:
- targeted unit/integration tests for conversation, session manager, CLI runtime, adapter, claude code runtime
- `ruff check` on touched files
- `mypy --follow-imports=silent` on touched modules

## Batch 2 — Persistence Identity and Snapshot Semantics

Scope:
- findings 3, 4, 14, 15, 7

Steps:
1. Add failing regression for `SqliteSessionBackend` concurrent `save/load/list/delete`.
2. Add failing regression for session-key collision with colon-containing IDs.
3. Add failing regressions for:
   - `InMemorySessionBackend`
   - `InMemoryMemoryProvider.save_session_state()/get_session_state()`
4. Add failing regression for dict-style `mcp_servers` on portable runtime path.
5. Implement:
   - serialized access or per-operation connection discipline for `SqliteSessionBackend`
   - collision-proof session key encoding
   - snapshot/copy semantics for in-memory persistence paths
   - MCP config normalization or validation boundary in portable wiring

DoD:
- SQLite session backend survives concurrent access in the supported async usage model
- no `SessionKey` collisions for delimiter-containing user/topic IDs
- in-memory persistence paths behave like snapshot stores, not live aliases
- dict-style `mcp_servers` either work correctly or fail fast with explicit validation

Verification:
- targeted backend/session/runtime wiring tests
- fast broader regression on session + memory + portable runtime subsets
- `ruff` / `mypy` on touched modules

Merge point:
- after Batch 2, rerun the original Wave 0/1 + Wave 2 persistence repros to confirm those critical defects are closed

## Batch 3 — Orchestration / Team Correctness

Scope:
- findings 9, 10, 11

Steps:
1. Add failing regression for aggregate team state when all workers are `failed` / `cancelled`.
2. Add failing regression for DeepAgents team start task composition parity against the existing team abstractions.
3. Add failing regression for worker messaging tool advertising/wiring in DeepAgents team mode.
4. Add failing regression for default DeepAgents subagent tools:
   - either real executors are wired
   - or unsupported tool execution is blocked/fails fast before model exposure
5. Implement the smallest consistent semantics across team/subagent variants.

DoD:
- team aggregate state distinguishes success from total failure
- DeepAgents team workers receive composed tasks consistent with the team abstraction
- if MessageBus communication is promised, workers can actually use the advertised messaging path
- deepagents subagents no longer advertise guaranteed-broken tools

Verification:
- targeted team/subagent/orchestration tests
- smoke of the most representative multi-agent examples if affected

## Batch 4 — Workflow Recovery and Export Fidelity

Scope:
- findings 5 and 12

Steps:
1. Add failing regression for checkpoint/resume on a graph where the checkpointed node fails before completion.
2. Add failing regression for `compile_to_langgraph_spec()` with parallel groups.
3. If feasible without optional dependency friction, add a structure-level regression around `compile_to_langgraph()` as well.
4. Implement:
   - resume semantics that replay or correctly recover the checkpointed node
   - parallel-group serialization/compilation fidelity

DoD:
- checkpoint resume no longer skips uncompleted work
- exported/compiled workflow representation preserves parallel-group semantics
- example `20_workflow_graph.py` still works after the fix

Verification:
- targeted workflow tests
- smoke-run `python examples/20_workflow_graph.py`

Merge point:
- after Batch 4, run broader regression over workflow/orchestration suites because this slice touches core execution semantics

## Batch 5 — Storage Contract Closure and Sync

Scope:
- finding 16

Decision gate:
- choose one of:
  - enforce documented precedence `user > ai_inferred > mcp`
  - or explicitly downgrade the documented contract if stronger precedence is not desired

Preferred path:
- enforce the documented precedence, because both SQL providers already describe it as intended behavior.

Steps:
1. Add failing regression for `ai_inferred` followed by `mcp`.
2. Mirror the regression for SQLite and Postgres provider behavior.
3. Implement precedence enforcement with matching behavior across providers.
4. Only after code/test verification, sync any provider docstrings and docs that describe fact-source priority.

DoD:
- storage behavior and documented precedence agree
- SQLite and Postgres behave consistently for fact-source overwrite rules

Verification:
- targeted SQL provider tests
- `ruff` / `mypy` on touched memory provider files

## Final Acceptance Gates

The unified remediation program is considered complete when all of the following are true:

1. Every finding from both release-risk audit reports is either:
   - fixed in code, or
   - explicitly downgraded with an intentional contract decision recorded in docs/notes.
2. All new defects were covered by failing tests before implementation.
3. No remaining known reproduction from either audit report still reproduces.
4. `ruff check src/ tests/` is green.
5. `mypy src/swarmline/` is green.
6. `python -m pytest -q` is green.
7. Representative example smoke remains green for the touched surfaces:
   - `examples/10_sessions.py`
   - `examples/20_workflow_graph.py`
   - `examples/21_agent_as_tool.py`
   - plus any additional example directly affected by the fixes.
8. Only after verification, Memory Bank status/checklists may be updated to mark the remediation closed.

## Plan Acceptance Criteria

This unified backlog is ready to execute if:

1. every confirmed finding from both audit reports is mapped into a batch
2. each batch has an objective DoD and verification block
3. worker write-sets are mostly non-overlapping
4. ordering follows risk and contract criticality rather than directory order
5. final gates are measurable and match project rules
