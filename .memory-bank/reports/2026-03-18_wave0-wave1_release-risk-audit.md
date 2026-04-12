# Wave 0 / Wave 1 Release-Risk Audit

Date: 2026-03-18
Scope: read-only full-project audit after the remediation commit, focused on current release risks rather than diff-only review.

Important note:
- Subagents were used for candidate discovery only.
- Final findings below were promoted only after local code inspection and/or manual reproduction on the main workspace.
- Earlier draft notes about runtime docs drift were removed from this final version because the current workspace already reflects the 4-runtime surface correctly.

## Verification Snapshot

- `git status --short` → clean worktree
- `python -m pytest -q` → `2366 passed, 16 skipped, 5 deselected, 19 warnings`
- `ruff check src/ tests/` → green
- `mypy src/swarmline/` → green
- additional manual smoke:
  - `python examples/17_runtime_switching.py` → passes
  - `python examples/19_cli_runtime.py` → passes

## Confirmed Code Defects

### P1 — `Conversation` persists partial assistant text even when the turn fails

Files:
- `src/swarmline/agent/conversation.py:63-67`
- `src/swarmline/agent/conversation.py:96-116`

Problem:
- `Conversation.say()` and `Conversation.stream()` append assistant text to `_history` whenever text deltas were seen, even if the terminal event is `error`.

Manual repro:
- monkeypatch `Conversation._execute()` to yield `text_delta("partial")`, then `error("boom")`
- observed:
  - `say("hello")` returns `ok=False`, `text="partial"`, `error="boom"`
  - `conv.history == [("user", "hello"), ("assistant", "partial")]`
  - `stream("hello")` yields `text_delta`, then `error`, and still persists `("assistant", "partial")`

Why this is a bug:
- failed turns pollute future conversation context with a reply that never completed successfully
- this is state corruption, not just presentation noise

### P1 — portable runtime exceptions escape instead of becoming typed runtime failures

Files:
- `src/swarmline/agent/conversation.py:166-180`
- `src/swarmline/session/manager.py:274-283`
- `src/swarmline/session/manager.py:305-310`

Problem:
- portable runtime paths iterate `runtime.run(...)` directly and do not normalize unexpected runtime exceptions into `Result(error=...)`, `RuntimeEvent.error(...)`, or `StreamEvent(type="error")`.

Manual repro:
- monkeypatch `RuntimeFactory.create()` to return a runtime whose `run()` raises `RuntimeError("boom-runtime")`
- `Conversation.say("x")` raises `RuntimeError boom-runtime` instead of returning a failed `Result`
- seed `InMemorySessionManager` with `SessionState(runtime=RaisingRuntime())`
- `run_turn(...)` raises `RuntimeError boom-runtime` instead of yielding `RuntimeEvent.error(...)`

Why this is a bug:
- these seams break the typed error contract and can crash callers on normal runtime failure paths

### P1 — `SqliteSessionBackend` is not safe for concurrent use

File:
- `src/swarmline/session/backends.py:72-120`

Problem:
- one shared `sqlite3.Connection(check_same_thread=False)` is used across multiple `asyncio.to_thread()` calls with no internal lock or serialized access.

Manual repro:
- run 20 concurrent tasks performing `save/load/list_keys/delete` against the same backend instance
- observed failure on the main workspace: `SystemError: error return without exception set`

Why this is a bug:
- the backend is exposed as an async persistence primitive but breaks under routine concurrent access

### P1 — `SessionKey` string serialization is collision-prone

Files:
- `src/swarmline/session/types.py:23-24`
- `src/swarmline/session/manager.py:54-55`

Problem:
- `SessionKey.__str__()` serializes keys as `"user_id:topic_id"`, and `SessionManager` uses that raw string as the storage key for `_sessions`, `_locks`, and backend persistence.

Manual repro:
- `SessionKey(user_id="a:b", topic_id="c")` and `SessionKey(user_id="a", topic_id="b:c")` both serialize to `a:b:c`
- registering both states leaves only one entry in `_sessions`
- both `mgr.get(k1)` and `mgr.get(k2)` return the second state

Why this is a bug:
- session isolation breaks for valid user/topic identifiers containing `:`
- collisions can overwrite another session's runtime state and lock

### P2 — `InMemorySessionBackend` stores mutable state by reference instead of snapshotting it

File:
- `src/swarmline/session/backends.py:50-54`

Problem:
- `save()` stores the original dict object, and `load()` returns the same underlying object.

Manual repro:
- save `{"x": 1, "nested": {"y": 2}}`
- mutate the original dict after `save()`
- `load()` returns `{"x": 9, "nested": {"y": 7}}`

Why this is a bug:
- persisted state changes without a second `save()`
- behavior diverges from every real persistence backend and breaks backend parity

### P2 — portable event adapter drops tool identity on `tool_call_finished`

File:
- `src/swarmline/agent/agent.py:402-405`

Problem:
- `_RuntimeEventAdapter` maps `tool_call_finished` into `tool_use_result` but never copies `data["name"]` into `tool_name`.

Manual repro:
- `_RuntimeEventAdapter(RuntimeEvent.tool_call_finished(name="calc", correlation_id="c1", result_summary="42"))`
- observed output: `type="tool_use_result", tool_name="", tool_result="42"`

Why this is a bug:
- consumers lose the ability to correlate a tool result with the tool that produced it

### P2 — team status reports `completed` even when all workers failed or were cancelled

File:
- `src/swarmline/orchestration/base_team.py:55-58`

Problem:
- `get_team_status()` treats any all-terminal set of workers as `completed`, including `failed` and `cancelled`.

Manual repro:
- inject worker statuses `failed` and `cancelled`
- observed aggregate state: `completed`

Why this is a bug:
- callers cannot distinguish successful completion from total failure of the team

### P2 — `DeepAgentsTeamOrchestrator` does not wire actual team semantics at start

Files:
- `src/swarmline/orchestration/deepagents_team.py:30-32`
- `src/swarmline/orchestration/deepagents_team.py:43-45`

Reference behavior:
- `src/swarmline/orchestration/claude_team.py:35-39`
- `src/swarmline/orchestration/thin_team.py:86-116`

Problem:
- deepagents team start passes the raw shared `task` to each worker instead of `compose_worker_task(...)`
- worker specs are forwarded unchanged, so they do not advertise the `send_message` tool used by the rest of the team abstraction

Manual repro:
- start a deepagents team with `lead_prompt="LEAD"` and worker `w1`
- first `spawn()` receives `task="TASK"` instead of a composed worker task
- first spawned spec has `tools == []`

Why this is a bug:
- deepagents workers lose lead instructions and worker-specific framing
- the class docstring promises MessageBus communication, but workers are not given the tool needed to use that bus

### P2 — default deepagents subagent path advertises tools but cannot execute them

Files:
- `src/swarmline/orchestration/deepagents_subagent.py:32-37`
- `src/swarmline/runtime/deepagents_tools.py:22-27`

Problem:
- `DeepAgentsSubagentOrchestrator` creates `DeepAgentsRuntime(..., tool_executors={})` by default
- worker runtime still passes `active_tools=self._spec.tools`
- missing executors are wrapped into a noop tool returning a JSON error payload

Manual repro:
- `create_langchain_tool(ToolSpec(name="calc", ...), executor=None).ainvoke({})`
- observed output: `{"error": "Tool calc не имеет executor"}`

Why this is a bug:
- the subagent path can advertise tools to the model while guaranteeing that local tool execution will fail

## Verified Safe In This Pass

- `runtime` / `hooks` / `runtime.ports` / `skills` package roots no longer show the earlier `__all__` optional-import regression pattern
- the currently checked docs surface reflects 4 runtimes, including `cli`
- `examples/17_runtime_switching.py` and `examples/19_cli_runtime.py` both run successfully on the current workspace
- repo-wide static gates are green, so this pass found logic/integration defects rather than hygiene regressions

## Held Back / Not Promoted To Findings

These candidates were intentionally not promoted in this report:

- fact-source precedence (`user > ai_inferred > mcp`) is internally inconsistent and reproducible in SQLite, but I did not find it established strongly enough as a project-level contract outside implementation comments/docstrings
- optional-dependency cold-start failures were not re-reproduced in a stripped environment during this pass
- mini-subagent suggestions that were not reproduced locally were discarded

## Suggested Next Fix Order

1. `Conversation` error-path history corruption
2. portable runtime exception normalization in `Conversation` and `SessionManager`
3. `SqliteSessionBackend` concurrency safety
4. `SessionKey` collision-proof serialization
5. team/deepagents orchestration correctness (`completed` vs failed, missing worker task composition, missing messaging/tool wiring)
6. `tool_call_finished` adapter metadata loss
7. `InMemorySessionBackend` snapshot semantics
