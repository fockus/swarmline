# Architecture Patterns: ThinRuntime Parity v2

**Domain:** LLM Agent Framework -- Runtime Feature Integration
**Researched:** 2026-04-13
**Overall confidence:** HIGH (based on direct codebase analysis)

---

## Existing Architecture Summary

### ThinRuntime.run() Pipeline

```
User calls run(messages, system_prompt, active_tools)
    |
    v
1. Subagent tool spec injection + executor update
2. UserPromptSubmit hooks (dispatch_user_prompt)
3. Command intercept (CommandRegistry.is_command -> execute)
4. Input guardrails (parallel check)
5. Input filters (sequential: MaxTokensFilter, SystemPromptInjector)
6. Mode detection (conversational / react / planner)
7. Strategy execution (run_conversational / run_react / run_planner)
    |
    +-- LLM call (llm_call callable, wraps provider adapter)
    +-- Tool execution (ToolExecutor.execute with hooks + policy)
    +-- Finalization (finalize_with_validation)
    |
8. EventBus emission (tool_call events)
9. Cost tracking on final event
10. Output guardrails on final event
11. Stop hooks (dispatch_stop)
```

### Key Extension Points

| Point | Mechanism | Current Users |
|-------|-----------|---------------|
| Input filters | `RuntimeConfig.input_filters: list[InputFilter]` | MaxTokensFilter, SystemPromptInjector |
| Pre-LLM messages | `messages` param mutated in filter pipeline | Filters modify messages list |
| System prompt | `system_prompt` param mutated by filters | SystemPromptInjector |
| Tool registration | `local_tools` dict in constructor | Sandbox tools, subagent tool |
| Tool execution | `ToolExecutor.execute()` with hook chain | PreToolUse -> Policy -> Execute -> PostToolUse |
| Event emission | `RuntimeEvent` yield from strategy | assistant_delta, tool_call_*, final, error, status |
| LLM response | Provider adapter `.call()` / `.stream()` | AnthropicAdapter, OpenAICompatAdapter, GoogleAdapter |
| Subagent spawn | `ThinSubagentOrchestrator` + `_ThinWorkerRuntime` | spawn_agent tool |

---

## Feature-by-Feature Architecture Analysis

### 1. Conversation Compaction

**Problem:** MaxTokensFilter drops oldest messages entirely. Compaction should summarize old messages via LLM instead of losing them.

**Integration point:** New `InputFilter` -- placed BEFORE `MaxTokensFilter` in the filter pipeline.

**New components:**
- `CompactionFilter` (InputFilter implementation) -- `src/swarmline/input_filters.py`
- `CompactionStrategy` protocol (domain) -- `src/swarmline/protocols/compaction.py` or inline in input_filters
- `LlmCompactionStrategy` (infrastructure) -- uses LLM to summarize

**Modified components:**
- NONE. InputFilter protocol already supports this. Users compose filters via `RuntimeConfig.input_filters`.

**Data flow:**
```
messages (full history)
    |
    v
CompactionFilter:
  - Count tokens in messages
  - If below threshold: pass through
  - If above: take oldest N messages, call LLM summarize
  - Replace oldest N messages with single Message(role="system", content=summary)
  - Return (compacted_messages, system_prompt)
    |
    v
MaxTokensFilter (safety net: truncate if still over budget)
```

**Key design decisions:**
- CompactionFilter depends on an LLM callable for summarization -- inject via constructor (not from RuntimeConfig, to avoid circular deps)
- `LlmSummaryGenerator` already exists in `memory/llm_summarizer.py` -- reuse the prompt pattern but the CompactionFilter needs its own async summarization path since it works on `Message` (not `MemoryMessage`)
- Compaction is triggered by token threshold, not message count (more precise)
- Summary message uses role="user" with a `[CONVERSATION SUMMARY]` prefix to remain compatible with all providers
- The compacted messages must preserve the most recent N messages verbatim (recency window)

**Configuration (new RuntimeConfig fields):**
```python
# RuntimeConfig additions (all optional, None defaults)
compaction_threshold: int | None = None  # Token count to trigger compaction
compaction_preserve_recent: int | None = None  # Messages to keep verbatim
```

**Complexity:** Medium. Existing filter protocol fits perfectly. Main work is the summarization logic and token counting.

---

### 2. Project Instructions Loading

**Problem:** Load CLAUDE.md / AGENTS.md / GEMINI.md / RULES.md files and inject them into the system prompt.

**Integration point:** New `InputFilter` -- `ProjectInstructionsFilter`. Or alternatively, a pre-run() setup step that populates `RuntimeConfig.input_filters`.

**New components:**
- `ProjectInstructionsLoader` -- discovers and reads instruction files from filesystem
- `ProjectInstructionsFilter(InputFilter)` -- injects loaded instructions into system_prompt

**Modified components:**
- NONE. Uses existing `InputFilter` protocol and `SystemPromptInjector` pattern.

**Data flow:**
```
ProjectInstructionsLoader.load(project_root: Path) -> str
    |  Reads CLAUDE.md, AGENTS.md etc. in priority order
    |  Concatenates with section headers
    v
ProjectInstructionsFilter (InputFilter):
    filter(messages, system_prompt):
        return messages, f"{system_prompt}\n\n{loaded_instructions}"
```

**Key design decisions:**
- This is essentially a specialized `SystemPromptInjector` with file discovery logic
- File search order: CLAUDE.md > .claude/CLAUDE.md > AGENTS.md > RULES.md (configurable)
- Files are loaded ONCE at construction time, not on every filter call (performance)
- Instructions are appended to system_prompt (not prepended -- system_prompt has priority)
- Could also be implemented as a standalone loader that produces a `SystemPromptInjector` -- simpler

**Configuration:**
```python
# RuntimeConfig or AgentConfig
project_instructions_paths: list[str] | None = None  # Explicit paths
project_root: str | None = None  # Auto-discover from this directory
```

**Complexity:** Low. File I/O + string concatenation. Straightforward InputFilter.

---

### 3. Session Resume

**Problem:** Persist conversation history between `run()` calls so an agent can resume after process restart.

**Integration point:** Wraps around `ThinRuntime.run()` -- either in the caller (Agent facade) or as a middleware layer.

**New components:**
- `ConversationStore` protocol (domain, ISP <=5 methods) -- save/load/list conversation messages
- `SqliteConversationStore` (infrastructure)
- `SessionResumeMiddleware` or integration into `Agent.query()` / `Agent.stream()`

**Modified components:**
- `Agent` class (or new `ResumedAgent` wrapper) -- loads history before run(), saves after
- `RuntimeEvent.final` -- already carries `new_messages` which can be persisted

**Relationship to existing SessionManager:**
- `InMemorySessionManager` handles session lifecycle (TTL, locking, runtime binding)
- `TaskSessionStore` handles task-bound session params
- `MessageStore` protocol exists in `protocols/memory.py` with save_message/get_messages
- Session Resume should leverage `MessageStore` -- it already has the right interface
- The gap: `MessageStore` uses `MemoryMessage` not `Message`. Need a thin adapter or extend `Message.from_memory_message()` (already exists)

**Data flow:**
```
Agent.query(prompt, session_id=...):
    1. If session_id: load messages from ConversationStore
    2. Prepend loaded messages to current messages
    3. Call runtime.run(messages=full_history, ...)
    4. Collect new_messages from final event
    5. Save new_messages to ConversationStore
    6. Return result
```

**Key design decisions:**
- Session ID is user-provided (not auto-generated) for deterministic resume
- Use existing `MessageStore` protocol where possible
- Conversation messages are stored as serialized `Message.to_dict()` / `Message(**dict)`
- Compaction (feature 1) should run AFTER resume loads the full history -- filter pipeline handles this naturally
- DO NOT store tool results in full (truncate to summary) to avoid storage bloat

**Complexity:** Medium. Protocol exists, main work is wiring + serialization.

---

### 4. Web Tools

**Problem:** Provide built-in web_search and web_fetch tools for the coding agent.

**Integration point:** Extend `CodingToolPack` or create parallel `WebToolPack`.

**New components:**
- `WebToolPack` -- bundle of web_search/web_fetch specs + executors (follows CodingToolPack pattern)
- OR just add to the existing `create_web_tools()` in `tools/builtin.py` -- THIS ALREADY EXISTS

**Modified components:**
- `tools/builtin.py` -- `create_web_tools()` already exists with web_fetch and web_search
- `CodingToolPack` or `ThinRuntime.__init__()` -- needs to wire web tools when WebProvider is given
- `RuntimeConfig` or `AgentConfig` -- needs `web_provider: WebProvider | None` field

**CRITICAL FINDING: Web tools already exist in the codebase.** The `create_web_tools()` factory in `tools/builtin.py` creates `web_fetch` and `web_search` executors. The `WebProvider`, `WebSearchProvider`, and `WebFetchProvider` protocols exist in `tools/web_protocols.py`. An httpx implementation exists in `tools/web_httpx.py`.

**Remaining work:**
1. Wire `create_web_tools()` into `ThinRuntime.__init__()` (same pattern as sandbox tools)
2. Add `web_provider` to `RuntimeConfig` or constructor
3. Add web tool names to `CODING_TOOL_NAMES` in `coding_toolpack.py` if coding mode should include them
4. Ensure tool policy allows web tools in coding profile

**Data flow:**
```
ThinRuntime.__init__(web_provider=...):
    if web_provider:
        web_specs, web_executors = create_web_tools(web_provider)
        merged_local_tools.update(web_executors)
        # web specs auto-added to active_tools or via CodingToolPack
```

**Complexity:** Low. Infrastructure exists. Wiring only.

---

### 5. Multimodal Input

**Problem:** Support images, PDFs, Jupyter notebooks in messages.

**Integration point:** `Message.content` type change + provider adapter changes.

**New components:**
- `ContentPart` union type (domain) -- `TextPart | ImagePart | FilePart`
- Multimodal content converters per provider (infrastructure)

**Modified components:**
- `Message.content` -- from `str` to `str | list[ContentPart]` (backward compatible: str is valid)
- `domain_types.py` -- add ContentPart types
- `llm_providers.py` -- all 3 adapters need to handle multimodal content in `_prepare()` / `_filter_chat_messages()`
- `_messages_to_lm()` helper in `helpers.py` -- needs to handle non-string content
- Tool `read()` executor -- could return structured content for binary files

**Data flow for images:**
```
Message(
    role="user",
    content=[
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]
)

Adapter converts to provider format:
- Anthropic: {"type": "image", "source": {"type": "base64", ...}}
- OpenAI: {"type": "image_url", "image_url": {"url": ...}}
- Google: {"inline_data": {"mime_type": ..., "data": ...}}
```

**Key design decisions:**
- `Message.content` becomes `str | list[dict[str, Any]]` -- the dict format follows OpenAI convention (most portable)
- Each adapter's `_prepare()` / `_filter_chat_messages()` converts to provider-native format
- PDF/Jupyter: pre-process to text + images before sending (not all providers support native PDF)
- `_messages_to_lm()` in `helpers.py` must handle both string and list content -- check `isinstance(m.content, str)`
- Backward compatibility: all code that accesses `message.content` as string must use a helper `get_text_content(message) -> str`

**Complexity:** High. Touches many components. Each provider has different multimodal API. Type change is viral through the codebase.

---

### 6. MCP Resources

**Problem:** Read MCP server resources (not just tools) -- e.g., file contents, configuration data.

**Integration point:** Extend `McpClient` with resource reading capabilities.

**New components:**
- `McpClient.read_resource(server_url, resource_uri)` -- new method
- `McpClient.list_resources(server_url)` -- new method
- `McpResourceSpec` dataclass (if needed for discovery)

**Modified components:**
- `McpClient` -- add 2 new methods (stays within ISP limits: call_tool + list_tools + read_resource + list_resources = 4 methods)
- `ToolExecutor` -- potentially needs to handle `mcp_resource__server__uri` patterns
- OR expose as a separate tool (read_mcp_resource)

**Data flow:**
```
McpClient.read_resource(server_url, resource_uri):
    POST {
        "jsonrpc": "2.0",
        "method": "resources/read",
        "params": {"uri": resource_uri}
    }
    -> parsed content text

McpClient.list_resources(server_url):
    POST {
        "jsonrpc": "2.0",
        "method": "resources/list",
        "params": {}
    }
    -> list[McpResourceSpec]
```

**Key design decisions:**
- Add methods to existing McpClient (not a separate client) -- same transport, same caching
- Expose as a tool: `read_mcp_resource` with params `{server: str, uri: str}` -- integrates naturally with ToolExecutor
- Resources can be used for context injection (InputFilter that reads MCP resources into system_prompt)

**Complexity:** Low-Medium. JSON-RPC calls follow exact same pattern as tool calls.

---

### 7. System Reminders

**Problem:** Inject dynamic, conditional context into conversations (e.g., time-based reminders, state-based instructions).

**Integration point:** New `InputFilter` -- `SystemReminderFilter`.

**New components:**
- `SystemReminder` dataclass (domain) -- condition + content
- `SystemReminderFilter(InputFilter)` -- evaluates conditions, injects matching reminders

**Modified components:**
- NONE. Uses existing InputFilter protocol.

**Data flow:**
```
SystemReminderFilter(reminders=[
    SystemReminder(condition=lambda ctx: True, content="Always remember..."),
    SystemReminder(condition=lambda ctx: ctx.turn > 5, content="Long conversation warning"),
])

filter(messages, system_prompt):
    active = [r for r in reminders if r.condition(context)]
    reminder_text = "\n".join(r.content for r in active)
    return messages, f"{system_prompt}\n\n<system-reminder>\n{reminder_text}\n</system-reminder>"
```

**Key design decisions:**
- Reminders are appended to system_prompt in a `<system-reminder>` tag (follows Claude Code convention)
- Conditions receive a context object (turn count, message count, elapsed time, etc.)
- Static reminders (always-on) are just SystemPromptInjector -- this feature adds conditional logic
- Reminders are evaluated on every filter call (they can change between turns)

**Complexity:** Low. Straightforward InputFilter with condition evaluation.

---

### 8. Worktree Isolation

**Problem:** Each subagent gets its own git worktree to avoid conflicts.

**Integration point:** `ThinSubagentOrchestrator._create_runtime()` and `SubagentSpec`.

**New components:**
- `WorktreeManager` -- creates/cleans git worktrees
- `WorktreeConfig` dataclass -- settings for worktree creation

**Modified components:**
- `SubagentSpec` -- add `worktree_config: WorktreeConfig | None = None` (optional, backward compatible)
- `ThinSubagentOrchestrator._create_runtime()` -- if worktree_config, create worktree and pass isolated sandbox to worker
- `_ThinWorkerRuntime` -- sandbox scoped to worktree directory

**Data flow:**
```
Orchestrator._create_runtime(spec):
    if spec.worktree_config:
        worktree_path = WorktreeManager.create(
            base_repo=spec.worktree_config.repo_path,
            branch=spec.worktree_config.branch,
        )
        sandbox = LocalSandbox(root=worktree_path)
    else:
        sandbox = <inherited from parent>
    
    return _ThinWorkerRuntime(sandbox=sandbox, ...)
    
# Cleanup in Orchestrator.cancel() / after completion:
    WorktreeManager.cleanup(worktree_path)
```

**Key design decisions:**
- Worktree creation is synchronous (git worktree add) -- wrap in asyncio.to_thread
- Each worktree gets a unique branch name (e.g., `worktree/agent-{uuid}`)
- Cleanup must be reliable -- use try/finally in _run_agent
- Worktree inherits the parent repo's state at creation time
- SandboxConfig already exists in SubagentSpec -- worktree_config is additional

**Complexity:** Medium. Git operations + cleanup lifecycle management.

---

### 9. Thinking Events

**Problem:** Stream LLM's reasoning/thinking separately from text output.

**Integration point:** New `RuntimeEvent` type + provider adapter response parsing.

**New components:**
- `RuntimeEvent.thinking_delta(text)` factory method -- new event type `"thinking_delta"`
- Add `"thinking_delta"` to `RUNTIME_EVENT_TYPES`

**Modified components:**
- `domain_types.py` -- add `thinking_delta` to `RUNTIME_EVENT_TYPES` + factory method
- `llm_providers.py` -- `AnthropicAdapter` needs to parse `thinking` content blocks (Anthropic extended thinking)
- `llm_client.py` -- streaming needs to distinguish thinking chunks from text chunks
- `NativeToolCallResult` -- add `thinking: str = ""` field
- Strategy code (react_strategy, conversational) -- yield thinking events

**Data flow for Anthropic extended thinking:**
```
Anthropic API response.content = [
    {"type": "thinking", "thinking": "Let me analyze..."},
    {"type": "text", "text": "Here's my answer..."}
]

AnthropicAdapter.call() / .stream():
    for block in response.content:
        if block.type == "thinking":
            yield ThinkingEvent(text=block.thinking)  # or accumulate
        elif hasattr(block, "text"):
            yield text as before

Strategy yields:
    RuntimeEvent.thinking_delta(thinking_text)
    RuntimeEvent.assistant_delta(response_text)
```

**Key design decisions:**
- Thinking events are optional -- callers that don't handle them just ignore the event type
- For non-Anthropic providers that don't have native thinking: no thinking events emitted
- Extended thinking requires `anthropic-beta: extended-thinking` header -- add to adapter config
- Thinking tokens counted separately in TurnMetrics (new field: `thinking_tokens: int = 0`)
- `NativeToolCallResult.thinking` captures thinking text from native tool call responses

**Complexity:** Medium. Provider-specific API changes + new event type plumbing.

---

### 10. Background Agents + Monitor Tool

**Problem:** Spawn agents that run asynchronously with stdout notification streaming.

**Integration point:** Extend `ThinSubagentOrchestrator` + new `monitor` tool.

**New components:**
- `monitor` tool (ToolSpec + executor) -- streams stdout from a background agent
- `BackgroundAgentManager` -- or extend orchestrator with background mode
- `RuntimeEvent.background_notification(agent_id, text)` -- new event type

**Modified components:**
- `ThinSubagentOrchestrator.spawn()` -- add `background: bool = False` parameter
- `SubagentSpec` -- add `background: bool = False` field
- `SubagentStatus` -- add `stdout_lines: list[str] = []` for captured output
- `RUNTIME_EVENT_TYPES` -- add `"background_notification"`

**Data flow:**
```
Background spawn:
    agent_id = orchestrator.spawn(spec, task, background=True)
    # Returns immediately. Agent runs as asyncio.Task.
    # stdout/events accumulated in SubagentStatus.stdout_lines

Monitor tool:
    monitor(agent_id=...) -> streams accumulated stdout since last check
    
    async def monitor_executor(args):
        agent_id = args["agent_id"]
        status = await orchestrator.get_status(agent_id)
        # Return new lines since last read (cursor-based)
        return json.dumps({"state": status.state, "new_lines": lines})

Background notification events:
    When background agent completes:
        yield RuntimeEvent.background_notification(
            agent_id=id,
            text="Background agent completed: <summary>"
        )
```

**Key design decisions:**
- Background agents use the same `_run_agent` mechanism but don't block the parent
- `monitor` is a tool the LLM can call to check on background work
- Notifications are pushed via RuntimeEvent when background agents complete
- stdout capture requires intercepting RuntimeEvents from the background agent's run()
- Background agents inherit the same tool set but run non-blocking
- The parent agent's event loop must yield background notifications between its own turns

**Complexity:** High. Async task management + event forwarding + new tool + new event type.

---

## Dependency Graph

```
Independent (no cross-feature deps):
  [2] Project Instructions  -- standalone InputFilter
  [7] System Reminders      -- standalone InputFilter
  [6] MCP Resources         -- McpClient extension

Linear dependencies:
  [1] Compaction depends on nothing, but benefits from [3] Session Resume
  [3] Session Resume depends on nothing, but Compaction should run after resume
  [4] Web Tools depends on nothing (infra already exists)
  [9] Thinking Events depends on nothing

Cross-feature dependencies:
  [5] Multimodal depends on nothing but affects tool read() + all adapters
  [8] Worktree Isolation depends on [10] Background Agents conceptually
      (worktrees are most useful for parallel background agents)
  [10] Background Agents extends orchestrator (depends on subagent infra)
       Monitor tool works with [8] Worktree Isolation

Feature -> Existing Component dependencies:
  [1] -> InputFilter, LlmSummaryGenerator pattern
  [2] -> InputFilter (SystemPromptInjector pattern)
  [3] -> MessageStore, SessionState, Agent facade
  [4] -> create_web_tools (existing), CodingToolPack
  [5] -> Message, all LLM adapters, _messages_to_lm
  [6] -> McpClient
  [7] -> InputFilter
  [8] -> SubagentSpec, ThinSubagentOrchestrator, LocalSandbox
  [9] -> RuntimeEvent, LLM adapters (Anthropic primarily)
  [10] -> ThinSubagentOrchestrator, RuntimeEvent, ToolExecutor
```

---

## Suggested Build Order

### Phase 1: Foundation Filters (low risk, high value, zero deps)
**Features:** [2] Project Instructions, [7] System Reminders

**Rationale:** Both are pure InputFilter implementations. Zero modifications to existing code. Establishes the pattern for [1] Compaction. Immediately useful for coding agent workflows.

**Components:**
- New: `ProjectInstructionsFilter`, `SystemReminderFilter` in `input_filters.py`
- New: `ProjectInstructionsLoader` (file discovery)
- Modified: None

### Phase 2: Web Tools + MCP Resources (low risk, infra already exists)
**Features:** [4] Web Tools, [6] MCP Resources

**Rationale:** Web tools factory already exists -- this is just wiring into ThinRuntime. MCP Resources follow the same JSON-RPC pattern as existing MCP tools. Both add immediate capability with minimal risk.

**Components:**
- New: `McpClient.read_resource()`, `McpClient.list_resources()`
- New: `read_mcp_resource` tool spec + executor
- Modified: `ThinRuntime.__init__()` -- web_provider parameter
- Modified: `CodingToolPack` -- optional web tool inclusion

### Phase 3: Conversation Compaction (medium risk, high value)
**Features:** [1] Compaction

**Rationale:** Depends on understanding filter pipeline (established in Phase 1). Needs LLM summarization -- the `LlmSummaryGenerator` pattern exists but compaction-specific logic is new. Should be built before Session Resume so that resumed sessions can be compacted.

**Components:**
- New: `CompactionFilter(InputFilter)` in `input_filters.py`
- New: `CompactionStrategy` protocol (optional, for testability)
- Modified: `RuntimeConfig` -- `compaction_threshold`, `compaction_preserve_recent`

### Phase 4: Session Resume (medium risk, high value)
**Features:** [3] Session Resume

**Rationale:** Depends on having a stable message format (no type changes from [5] yet). Uses existing `MessageStore` protocol. Works naturally with Compaction (Phase 3) -- resumed sessions that exceed context get compacted automatically.

**Components:**
- New: `ConversationPersistence` in `session/` or `agent/`
- Modified: `Agent.query()` / `Agent.stream()` -- session_id parameter
- Modified: `RuntimeEvent.final` -- session persistence hook

### Phase 5: Thinking Events (low-medium risk)
**Features:** [9] Thinking Events

**Rationale:** New RuntimeEvent type is additive. Only Anthropic adapter needs changes for extended thinking. Non-breaking: callers that don't handle thinking events just ignore them.

**Components:**
- Modified: `domain_types.py` -- `RUNTIME_EVENT_TYPES` + `RuntimeEvent.thinking_delta()`
- Modified: `llm_providers.py` -- `AnthropicAdapter` thinking block parsing
- Modified: `NativeToolCallResult` -- `thinking` field
- Modified: `TurnMetrics` -- `thinking_tokens` field

### Phase 6: Multimodal Input (high risk, high value)
**Features:** [5] Multimodal

**Rationale:** Type change to `Message.content` is the most invasive change. Should be done after Session Resume (Phase 4) is stable. Requires changes to all 3 provider adapters + helpers. Schedule after other features are stable to minimize blast radius.

**Components:**
- Modified: `domain_types.py` -- `Message.content` type union
- Modified: `llm_providers.py` -- all 3 adapters
- Modified: `helpers.py` -- `_messages_to_lm()`
- New: Content conversion utilities per provider
- New: File preprocessors (PDF -> text+images, ipynb -> text+images)

### Phase 7: Worktree Isolation + Background Agents (high risk)
**Features:** [8] Worktree Isolation, [10] Background Agents

**Rationale:** Both features extend the subagent orchestrator and are conceptually linked. Worktrees are most valuable for parallel background agents. Both require async lifecycle management. Highest complexity -- schedule last.

**Components:**
- New: `WorktreeManager` in `orchestration/`
- New: `monitor` tool spec + executor
- New: `BackgroundAgentManager` or extended orchestrator
- Modified: `SubagentSpec` -- `worktree_config`, `background` fields
- Modified: `ThinSubagentOrchestrator` -- background spawn mode
- Modified: `domain_types.py` -- `RUNTIME_EVENT_TYPES` + `background_notification`

---

## Component Boundaries

### Domain Layer Changes

| Component | Changes | ISP Impact |
|-----------|---------|------------|
| `domain_types.py` | Add thinking_delta + background_notification event types; Message.content type union | 0 new protocols |
| `protocols/compaction.py` | New CompactionStrategy protocol (1 method) | ISP compliant |
| `orchestration/subagent_types.py` | SubagentSpec gains worktree_config, background fields | No protocol change |

### Application Layer Changes

| Component | Changes |
|-----------|---------|
| `input_filters.py` | 3 new InputFilter implementations (CompactionFilter, ProjectInstructionsFilter, SystemReminderFilter) |
| `Agent` facade | Session resume wiring (session_id param) |

### Infrastructure Layer Changes

| Component | Changes |
|-----------|---------|
| `runtime/thin/runtime.py` | web_provider constructor param, thinking event forwarding |
| `runtime/thin/llm_providers.py` | Multimodal content in all adapters, thinking blocks in Anthropic |
| `runtime/thin/mcp_client.py` | read_resource(), list_resources() methods |
| `runtime/thin/executor.py` | No changes needed (tools register through existing mechanism) |
| `orchestration/thin_subagent.py` | Worktree creation, background spawn mode |
| `session/` | ConversationPersistence for resume |

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Modifying ThinRuntime.run() Inline
**What:** Adding feature logic directly into run() method body.
**Why bad:** run() is already ~130 lines. More logic makes it untestable.
**Instead:** Use InputFilter for pre-processing, RuntimeEvent for output, constructor injection for new dependencies.

### Anti-Pattern 2: Breaking Message.content Type Without Helpers
**What:** Changing `content: str` to `content: str | list` and letting every consumer figure it out.
**Why bad:** Viral breakage across codebase. Every `message.content` access needs checking.
**Instead:** Add `Message.text_content` property that always returns str (extracts from list if needed). Use this in all existing code.

### Anti-Pattern 3: Coupling Compaction to Session Resume
**What:** Making CompactionFilter depend on session store or vice versa.
**Why bad:** Violates SRP. Each should work independently.
**Instead:** CompactionFilter is a pure InputFilter. Session resume loads messages. Filter pipeline handles both.

### Anti-Pattern 4: Separate McpResourceClient
**What:** Creating a new client class for MCP resources.
**Why bad:** Same transport, same JSON-RPC protocol, same caching. Duplication.
**Instead:** Add methods to existing McpClient.

### Anti-Pattern 5: Background Agents as Separate System
**What:** Building a new background execution engine outside ThinSubagentOrchestrator.
**Why bad:** Duplicates task lifecycle, cancellation, status tracking.
**Instead:** Extend orchestrator with background=True mode on spawn().

---

## Scalability Considerations

| Concern | Current (v1.4) | After v1.5 |
|---------|-----------------|------------|
| Long conversations | MaxTokensFilter truncates (lossy) | CompactionFilter summarizes (preserves context) |
| Session persistence | InMemory only (lost on restart) | SQLite/Postgres via ConversationStore |
| Multimodal messages | Not supported | Base64 images increase message size -- compaction must handle |
| Parallel agents | Sequential or max_concurrent sync | Background agents with async notification |
| MCP resources | Tools only | Tools + resources (read protocol) |

---

## Sources

All analysis based on direct codebase reading:
- `src/swarmline/runtime/thin/runtime.py` -- ThinRuntime pipeline
- `src/swarmline/runtime/thin/executor.py` -- ToolExecutor hook chain
- `src/swarmline/input_filters.py` -- InputFilter protocol + implementations
- `src/swarmline/domain_types.py` -- Message, RuntimeEvent, ToolSpec
- `src/swarmline/runtime/types.py` -- RuntimeConfig
- `src/swarmline/runtime/thin/llm_providers.py` -- Provider adapters
- `src/swarmline/runtime/thin/mcp_client.py` -- MCP client
- `src/swarmline/orchestration/thin_subagent.py` -- Subagent orchestrator
- `src/swarmline/tools/builtin.py` -- Existing web_tools factory
- `src/swarmline/tools/web_protocols.py` -- Web provider protocols
- `src/swarmline/memory/llm_summarizer.py` -- LLM summarization pattern
- `src/swarmline/protocols/memory.py` -- MessageStore, SessionStateStore
- `src/swarmline/session/` -- Session management infrastructure
- `src/swarmline/runtime/thin/coding_toolpack.py` -- Coding tool surface
