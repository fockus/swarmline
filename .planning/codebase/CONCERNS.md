# Codebase Concerns

**Analysis Date:** 2026-04-12

---

## Security Gaps

**HookRegistry not wired to ThinRuntime:**
- Issue: `SecurityGuard.get_hooks()` returns a `HookRegistry` with `PreToolUse` callbacks. `merge_hooks()` collects them correctly. However, hooks are forwarded **only** in `stream_claude_one_shot` and `create_claude_conversation_adapter` — both `claude_sdk`-only code paths. `run_portable_runtime()` (the path used by `ThinRuntime` and `DeepAgents`) calls `build_portable_runtime_plan()` which passes zero hook state into `RuntimeConfig` or `create_kwargs`.
- Files: `src/swarmline/agent/runtime_dispatch.py` (line 176–215), `src/swarmline/agent/runtime_wiring.py`, `src/swarmline/agent/middleware.py` (line 64–85), `src/swarmline/runtime/thin/executor.py`
- Impact: `SecurityGuard(block_patterns=["rm -rf"])` is silently ineffective when `AgentConfig.runtime = "thin"`. A user can configure the guard and receive zero protection. Dangerous tools execute without being intercepted.
- Fix approach: Pass merged `HookRegistry` into `build_portable_runtime_plan()` → store on `RuntimeConfig` → `ThinRuntime.run()` must call pre/post hooks around `executor.execute()` calls in `react_strategy.py`.

**Tool policy (`DefaultToolPolicy`) not enforced in `ToolExecutor`:**
- Issue: `DefaultToolPolicy.can_use_tool()` exists and is tested in isolation, but `ToolExecutor.execute()` in `src/swarmline/runtime/thin/executor.py` performs no policy check before dispatching to local tools or MCP servers. `DefaultToolPolicy` is only instantiated in `SwarmlineStack` (`bootstrap/stack.py`) but is never passed to `ToolExecutor`.
- Files: `src/swarmline/runtime/thin/executor.py` (line 33–46), `src/swarmline/policy/tool_policy.py`, `src/swarmline/bootstrap/stack.py` (line 127–130)
- Impact: In `ThinRuntime` mode the deny list (`ALWAYS_DENIED_TOOLS`) and the MCP skill allowlist are completely bypassed. Any tool name the LLM emits is executed unconditionally.
- Fix approach: Accept `DefaultToolPolicy | None` parameter in `ToolExecutor.__init__`; call `can_use_tool()` before dispatching; return a JSON error string on `PermissionDeny`.

**`serve/app.py` allows query without auth:**
- Issue: `create_app()` accepts `allow_unauthenticated_query=True`, which exposes `POST /v1/query` with no authentication. The flag has no restriction to loopback-only hosts (unlike `A2AServer.allow_unauthenticated_local`).
- Files: `src/swarmline/serve/app.py` (line 139–160)
- Impact: Deploying the HTTP serve layer without an `auth_token` but with the flag set exposes agent execution to unauthenticated callers on any network interface.
- Fix approach: Add the same loopback-host guard that `A2AServer` and `HealthServer` use, or emit a `warnings.warn()` when the flag is set.

---

## Dead Code

**`stream_parser.py` — file with no production callers:**
- Issue: `src/swarmline/runtime/thin/stream_parser.py` defines two classes (`IncrementalEnvelopeParser`, `StreamParser`) that duplicate logic already present in `src/swarmline/runtime/thin/parsers.py`. Nothing in the `src/` tree imports either class. The file is tested in `tests/unit/test_thin_streaming.py` but the production call site does not exist.
- Files: `src/swarmline/runtime/thin/stream_parser.py`
- Impact: Maintenance cost; any bug fix must be applied in two places if `stream_parser.py` is later wired in; confused future developers.
- Fix approach: Delete `stream_parser.py` and update `test_thin_streaming.py` to test `parsers.py` directly, or replace `parsers.py` with `stream_parser.py` if incremental parsing is the desired approach.

**`commands/` module — never activated in any runtime:**
- Issue: `CommandRegistry` (`src/swarmline/commands/registry.py`) and YAML loader (`src/swarmline/commands/loader.py`) are complete and tested, but `CommandRegistry` is imported only in `src/swarmline/commands/__init__.py`. No runtime, session manager, agent, CLI, or Telegram handler instantiates or uses it. `auto_discover_commands()` is never called from production code.
- Files: `src/swarmline/commands/registry.py`, `src/swarmline/commands/loader.py`, `src/swarmline/commands/__init__.py`
- Impact: Feature exists in tests but delivers no value. `/topic.new` style commands cannot be dispatched.
- Fix approach: Wire `CommandRegistry` into the session manager or agent `before_query` middleware hook, or move to `BACKLOG.md` and delete from active source.

---

## Fragile Areas

**Pseudo tool-calling (JSON-in-text, not native API):**
- Issue: `ThinRuntime` in ReAct mode instructs the LLM to emit JSON envelopes of the form `{"type":"tool_call","tool":{"name":"...","args":{...}}}` inside freeform text. Parsing is done in `src/swarmline/runtime/thin/parsers.py` (`parse_envelope()` → `parse_json_dict()`) which strips markdown fences and scans for the first JSON object boundary. This is not a native LLM tool-calling API; it depends entirely on the model obeying a prompt schema.
- Files: `src/swarmline/runtime/thin/parsers.py`, `src/swarmline/runtime/thin/react_strategy.py` (line 97–133), `src/swarmline/runtime/thin/schemas.py`, `src/swarmline/runtime/thin/prompts.py`
- Impact: Model non-compliance causes `parse_envelope()` to return `None`, triggering a retry loop (up to `config.max_model_retries`). After retries are exhausted the runtime uses `extract_text_fallback()` which silently drops tool execution. Smaller models degrade in unpredictable ways.
- Fix approach: Migrate `ThinRuntime` to use native function-calling APIs (Anthropic tool_use, OpenAI functions) where the provider enforces the schema. Keep the JSON-envelope path as an explicit fallback for providers that lack native tool-calling.

**`_RuntimeEventAdapter` uses `hasattr` guards for missing attributes:**
- Issue: `_RuntimeEventAdapter.__init__()` (lines 540–558 of `src/swarmline/agent/agent.py`) populates `self.tool_name`, `self.tool_input`, etc. using `if not hasattr(self, ...)` checks, meaning the event object is initialized to defaults late. This pattern hides cases where an event type added a new field that the adapter doesn't map.
- Files: `src/swarmline/agent/agent.py` (line 489–584)
- Impact: Silent attribute-missing bugs if new event types are added and the adapter is not updated. Difficult to statically type-check.
- Fix approach: Refactor `_RuntimeEventAdapter` into a frozen dataclass or typed constructor that explicitly sets all fields with explicit defaults, removing `hasattr` guards.

---

## Tech Debt

**Deprecated `RuntimePort` still exported:**
- Issue: `RuntimePort` in `src/swarmline/protocols/runtime.py` is marked deprecated in favour of `AgentRuntime`, but is still re-exported from `src/swarmline/protocols/__init__.py`, `src/swarmline/runtime/__init__.py`, and `src/swarmline/__init__.py`. `SessionState.adapter` field still types it (line 36 of `src/swarmline/session/types.py`).
- Files: `src/swarmline/protocols/runtime.py`, `src/swarmline/session/types.py` (line 36)
- Impact: Public API surface contains a deprecated symbol with no removal milestone. Confusion between `RuntimePort` (sync-style `stream_reply`) and `AgentRuntime` (async generator `run`).
- Fix approach: Remove `adapter: RuntimePort | None = None` from `SessionState`; schedule `RuntimePort` removal in next major version. Add `DeprecationWarning` on import of `RuntimePort`.

**Deprecated `max_thinking_tokens` kept in `AgentConfig` and `ClaudeOptionsBuilder`:**
- Issue: `AgentConfig.max_thinking_tokens` (line 69 of `src/swarmline/agent/config.py`) is documented as "Deprecated: use thinking instead". It is still forwarded in `runtime_dispatch.py` (line 164) and resolved in `options_builder.py` (`_resolve_thinking`). No timeline for removal.
- Files: `src/swarmline/agent/config.py` (line 69), `src/swarmline/runtime/options_builder.py` (line 73, 151–175)
- Impact: Two parallel parameters for the same concern. Any documentation or autocomplete shows both; users may use the deprecated one by accident.
- Fix approach: Emit a `DeprecationWarning` on access to `max_thinking_tokens` in `AgentConfig.__post_init__`. Add a removal milestone comment.

**Deprecated `AgentConfig.resolved_model` property:**
- Issue: Property emits `DeprecationWarning` on access (line 89–92 of `src/swarmline/agent/config.py`), but there is no test verifying that no internal code calls it.
- Files: `src/swarmline/agent/config.py` (line 85–92)
- Impact: Internal callers could accidentally call it if copied from old examples.
- Fix approach: Add a test asserting that no `src/` code uses `.resolved_model`.

---

## MCP Limitations

**ThinRuntime MCP client: HTTP only, no stdio or SSE transport:**
- Issue: `McpClient` in `src/swarmline/runtime/thin/mcp_client.py` implements only `POST <url>` JSON-RPC over HTTP. `ToolExecutor._execute_mcp()` calls only `client.call_tool()` with an HTTP URL. The transport builder in `options_builder.py` supports `stdio` and `sse` types for the `claude_sdk` path, but `mcp_servers` passed to `ThinRuntime` / `ToolExecutor` must all be HTTP-addressable. Stdio-only MCP servers (e.g. local CLI tools) cannot be used with `ThinRuntime`.
- Files: `src/swarmline/runtime/thin/mcp_client.py`, `src/swarmline/runtime/thin/executor.py` (line 132–168), `src/swarmline/skills/types.py` (line 16: `transport: McpTransport = "url"`)
- Impact: Any skill YAML that specifies `transport: stdio` silently fails when using `ThinRuntime` because `resolve_mcp_server_url()` returns `None` for non-HTTP entries, returning a "server not found" error. Users discover the gap only at runtime.
- Fix approach: Implement a subprocess-based stdio MCP client and an SSE client; dispatch on `transport` type in `ToolExecutor._execute_mcp()`.

---

## Large Files (>400 lines)

**`src/swarmline/agent/agent.py` — 584 lines:**
- Issue: Combines `Agent` facade, `_RuntimeEventAdapter`, `_ErrorEvent`, `collect_stream_result`, `build_tools_mcp_server`, `merge_hooks`, and 5+ free functions. SRP violation: 3+ distinct responsibilities.
- Fix approach: Extract `_RuntimeEventAdapter` + `_ErrorEvent` + `collect_stream_result` to `src/swarmline/agent/event_adapter.py`.

**`src/swarmline/memory/postgres.py` — 554 lines, `src/swarmline/memory/sqlite.py` — 536 lines:**
- Issue: Both files implement 6 independent store protocols (MessageStore, FactStore, GoalStore, SummaryStore, SessionStateStore, ToolEventStore) in a single monolithic class. Adding a store requires editing the entire file.
- Fix approach: Split each protocol implementation into its own file under `src/swarmline/memory/postgres/` and `src/swarmline/memory/sqlite/` subdirectories.

**`src/swarmline/cli/init_cmd.py` — 505 lines:**
- Issue: All init scaffolding logic in one function-heavy file. No isolation between template generation, validation, and file I/O.
- Fix approach: Extract template rendering to a separate `src/swarmline/cli/templates.py` module.

---

## Test Coverage Gaps

**`ThinRuntime` + hooks integration never tested end-to-end:**
- What's not tested: That `SecurityGuard` registered in `AgentConfig.middleware` actually blocks a tool call when using `runtime="thin"`. The gap is structural: the wiring doesn't exist, so no test can catch it.
- Files: `tests/unit/test_thin_executor.py`, `tests/unit/test_agent_middleware.py`
- Risk: Security regression can be introduced silently.
- Priority: High

**`ToolExecutor` never tested with a policy:**
- What's not tested: `ToolExecutor.execute()` being blocked by `DefaultToolPolicy` (because it isn't wired). No test asserts that `ALWAYS_DENIED_TOOLS` are rejected when going through `ThinRuntime`.
- Files: `tests/unit/test_thin_executor.py`
- Risk: Policy bypass bugs.
- Priority: High

**`CommandRegistry` integration path (agent → command dispatch):**
- What's not tested: End-to-end flow of a user message being parsed as a command and dispatched via `CommandRegistry`. Only unit tests for the registry itself exist.
- Files: `tests/unit/test_commands.py`, `tests/integration/test_commands_pipeline.py`
- Risk: Commands wired in future code break silently.
- Priority: Medium

**`stream_parser.py` classes tested but not called from production code:**
- What's not tested: Whether `StreamParser` / `IncrementalEnvelopeParser` would work correctly if wired into the actual streaming loop (race conditions, buffer edge cases under real stream chunks).
- Files: `tests/unit/test_thin_streaming.py`
- Risk: Dead code accumulates separate test maintenance burden.
- Priority: Low

---

*Concerns audit: 2026-04-12*
