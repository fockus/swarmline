# Phase 17: Parallel Agent Infrastructure - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Git worktree isolation for subagents and background agent execution with async notifications. Subagents can run in isolated git worktrees for safe parallel file operations, and background agents execute asynchronously with completion events and monitoring.

Requirements: WKTR-01..04 (worktree isolation), BGND-01..04 (background agents).

</domain>

<decisions>
## Implementation Decisions

### Worktree Integration in SubagentSpec
- **D-01:** Add `isolation: str | None = None` field to `SubagentSpec` (frozen dataclass in `orchestration/subagent_types.py`). Values: `None` (default, current behavior), `"worktree"` (git worktree isolation). Optional with None default per L-004.
- **D-02:** Bridge existing `multi_agent/LocalWorkspace` (GIT_WORKTREE strategy) into `ThinSubagentOrchestrator._run_agent()`. When `spec.isolation == "worktree"`, create workspace before runtime, pass `path` as cwd override, cleanup after completion/error.
- **D-03:** Max 5 active worktrees enforced in `ThinSubagentOrchestrator` (not LocalWorkspace) — domain-level limit check before spawn.

### Worktree Lifecycle
- **D-04:** Stale worktree cleanup runs once in `ThinSubagentOrchestrator.__init__` (or lazy on first spawn) using existing `WorktreeOrchestrator.cleanup_orphans()`. Non-blocking (fire-and-forget asyncio.Task).
- **D-05:** Worktree cleanup on subagent completion/error: `_run_agent` uses `try/finally` to ensure `LocalWorkspace.cleanup()` runs even on cancellation. Worktree is created with auto-generated branch name `swarmline/{agent_name}/{uuid_short}`.
- **D-06:** If worktree creation fails (not a git repo, no git, etc.) — fail fast with clear error, don't silently fall back to non-isolated execution.

### Background Agent Execution
- **D-07:** Add `run_in_background: bool = False` field to `SubagentSpec`. When True, `spawn_agent` tool returns immediately with `{"status": "running", "agent_id": "..."}` instead of waiting for completion.
- **D-08:** Add `RuntimeEvent.background_complete(agent_id, result, error)` static factory to `domain_types.py`. Emitted by `ThinSubagentOrchestrator` via a done callback on the asyncio.Task.
- **D-09:** Background agent notifications delivered to parent via event callback mechanism. `ThinSubagentOrchestrator` accepts `on_background_complete: Callable[[RuntimeEvent], Awaitable[None]] | None` in `__init__`. The parent runtime wires this to its event emission path.
- **D-10:** Background agents have mandatory timeout (default 300s from `SubagentToolConfig.timeout_seconds`). On timeout: cancel + emit `background_complete` with error.

### Monitor Tool
- **D-11:** New `monitor_agent` tool (ToolSpec) registered alongside `spawn_agent` when subagents are enabled. Parameters: `agent_id` (required). Returns current status + any accumulated output.
- **D-12:** Monitor tool is a polling tool (not streaming). LLM calls `monitor_agent` to check status — returns `{"status": "running|completed|failed", "output": "..."}`. No persistent streaming connection.
- **D-13:** Output accumulation: `ThinSubagentOrchestrator` buffers text output from background agents. Monitor tool returns accumulated output since last check (or all output on first check).

### spawn_agent Tool Extension
- **D-14:** `SUBAGENT_TOOL_SPEC` gets two new optional parameters: `isolation` (string, "worktree") and `run_in_background` (boolean). Both optional with no default visible to LLM.
- **D-15:** `create_subagent_executor` passes `isolation` and `run_in_background` through to `SubagentSpec` construction. Background flow: spawn + immediate return. Foreground flow (default): spawn + wait (current behavior).

### Claude's Discretion
- Exact branch naming pattern for worktrees (within `swarmline/` prefix)
- How accumulated output buffer is managed (list of strings, ring buffer, etc.)
- Whether `monitor_agent` returns full output or incremental diff

</decisions>

<specifics>
## Specific Ideas

- Worktree integration reuses existing `multi_agent/LocalWorkspace` and `WorktreeOrchestrator` — no new git abstraction layer
- Pattern follows Claude Code's `isolation: "worktree"` in Agent tool — familiar to users of Claude Code subagents
- Background completion events follow same pattern as `thinking_delta` — new RuntimeEvent type, domain-level factory

</specifics>

<canonical_refs>
## Canonical References

### Subagent infrastructure (existing)
- `src/swarmline/orchestration/subagent_types.py` — SubagentSpec, SubagentResult, SubagentStatus frozen dataclasses
- `src/swarmline/orchestration/subagent_protocol.py` — SubagentOrchestrator Protocol (5 methods, ISP-compliant)
- `src/swarmline/orchestration/thin_subagent.py` — ThinSubagentOrchestrator implementation + _ThinWorkerRuntime
- `src/swarmline/runtime/thin/subagent_tool.py` — spawn_agent ToolSpec + create_subagent_executor factory

### Worktree infrastructure (existing)
- `src/swarmline/multi_agent/workspace_types.py` — WorkspaceStrategy, WorkspaceSpec, WorkspaceHandle
- `src/swarmline/multi_agent/workspace.py` — ExecutionWorkspace Protocol + LocalWorkspace (3 strategies)
- `src/swarmline/multi_agent/worktree_orchestrator.py` — WorktreeOrchestrator (create/merge/cleanup/scan_orphans)
- `src/swarmline/multi_agent/worktree_strategy.py` — FactoryWorktreeStrategy, WorktreePolicy, MergeResult

### Domain types
- `src/swarmline/domain_types.py` — RuntimeEvent class with static factories (target for background_complete)

### Requirements
- `.planning/REQUIREMENTS.md` §WKTR-01..04 — Worktree isolation requirements
- `.planning/REQUIREMENTS.md` §BGND-01..04 — Background agent requirements

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **LocalWorkspace.create(GIT_WORKTREE)**: Already implements `git worktree add` + branch creation + async subprocess. Phase 17 reuses this directly.
- **WorktreeOrchestrator.cleanup_orphans()**: Already scans `git worktree list --porcelain` for untracked worktrees. Reuse for stale cleanup at init.
- **RuntimeEvent static factories**: Pattern established by `thinking_delta`, `assistant_delta`, `status` — `background_complete` follows same frozen dataclass convention.
- **SubagentToolConfig**: Already has `timeout_seconds: float = 300.0` — reuse for background timeout.

### Established Patterns
- **Optional None defaults** (L-004): All new fields on SubagentSpec must be `field: Type | None = None`
- **Fail fast** (L-008): Invalid isolation mode → explicit ValueError, not silent fallback
- **Contract-first** (L-001): Protocol → contract tests → implementation
- **ISP** (RULES): SubagentOrchestrator already at 5 methods — cannot add more. New capabilities via composition.
- **Async subprocess** for git: `asyncio.create_subprocess_exec` pattern established in LocalWorkspace

### Integration Points
- **ThinSubagentOrchestrator._run_agent()**: Primary integration point — add worktree create/cleanup around runtime execution
- **ThinSubagentOrchestrator.spawn()**: Background mode: fire-and-forget (don't await task in executor)
- **subagent_tool.py create_subagent_executor**: New parameters in spec construction + bifurcated flow (await vs immediate return)
- **ThinRuntime subagent wiring** (`runtime.py`): Wire `on_background_complete` callback from runtime event emission
- **domain_types.py RuntimeEvent**: Add `background_complete` static factory

</code_context>

<deferred>
## Deferred Ideas

- **WKTR-05**: Automatic merge-back from worktree → deferred to v1.6.0+
- **BGND-05**: Monitor tool min_interval throttling → deferred to v1.6.0+
- Worktree diff/status reporting tool → future phase
- Parallel agent result aggregation/voting → future phase

</deferred>

---

*Phase: 17-parallel-agent-infrastructure*
*Context gathered: 2026-04-13*
