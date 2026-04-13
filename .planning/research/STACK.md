# Technology Stack: ThinRuntime Parity v2

**Project:** Swarmline ThinRuntime v1.5.0 -- 10 New Features
**Researched:** 2026-04-13
**Scope:** Stack ADDITIONS only. Existing stack (anthropic, openai, google-genai, httpx, structlog, pydantic, pyyaml) is validated and not re-evaluated.

---

## 1. Conversation Compaction

**Goal:** Replace naive oldest-message truncation (MaxTokensFilter) with intelligent summarization-based compaction.

### What Exists Already

- `MaxTokensFilter` in `input_filters.py` -- char-based estimation, drops oldest messages. Simple but lossy.
- `LlmSummaryGenerator` in `memory/llm_summarizer.py` -- async LLM-based summarization with template fallback. Already accepts `llm_call: Callable`.
- `SummaryStore` protocol in `protocols/memory.py` -- `save_summary()` / `get_summary()`. Ready for persistence.
- `InputFilter` protocol -- the compaction strategy should implement this same protocol for drop-in integration.

### Recommended Approach: Layered Pipeline (no new dependencies)

Implement a 3-tier compaction pipeline as a new `InputFilter`:

| Tier | Strategy | When | Cost |
|------|----------|------|------|
| 1. Tool result collapse | Replace verbose tool outputs with `[Tool: name -> summary]` | Always, on older tool results | Zero (string manipulation) |
| 2. LLM summarization | Summarize older messages, preserve recent window | Token count > threshold | 1 LLM call (use cheap model) |
| 3. Truncation | Drop oldest groups as emergency backstop | After summarization still over budget | Zero |

**Token counting:**

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| (none -- stdlib) | -- | Character-based estimation (4 chars/token) | Already used in `MaxTokensFilter` and `ContextBudget`. Good enough for compaction triggers. Avoids adding tiktoken as a dependency for a framework that must work with Anthropic/Google/OpenAI models with different tokenizers. |

**Rationale for NO tiktoken:** Swarmline is multi-provider. tiktoken only covers OpenAI tokenizers. For Anthropic/Google there is no equivalent fast tokenizer. The existing 4-chars-per-token heuristic is sufficient for compaction triggers (we only need "roughly over budget", not exact counts). If users need precise counting, they can inject a custom tokenizer via the `InputFilter` protocol.

**Key design from Microsoft's Semantic Kernel compaction framework (verified 2026-03-18):**
- Group messages into atomic units (user turn + assistant response + tool calls = 1 group)
- System messages are ALWAYS preserved
- Tool call + tool result = atomic group (never split)
- Summarization uses a separate cheap LLM call (e.g., haiku/gpt-4o-mini)
- Pipeline: gentle (tool collapse) -> moderate (summarize) -> aggressive (truncate)

**Confidence:** HIGH -- pattern is well-established, no new dependencies needed, `LlmSummaryGenerator` is the foundation.

### New Dependencies: NONE

Reuse `LlmSummaryGenerator.asummarize()` for the summarization step. The compaction pipeline is pure application logic.

---

## 2. Project Instructions Loading

**Goal:** Auto-discover and load CLAUDE.md / AGENTS.md / GEMINI.md / RULES.md files.

### Recommended Approach: Filesystem Discovery (no new dependencies)

| Component | Implementation | Why |
|-----------|---------------|-----|
| File discovery | `pathlib.Path` traversal: cwd -> parent -> home | stdlib, no deps |
| File merging | Concatenation with section headers and priority ordering | Simple, predictable |
| Injection point | New `InputFilter` subclass (`ProjectInstructionsFilter`) that prepends to system_prompt | Fits existing architecture |
| File watching (optional) | `pathlib.Path.stat().st_mtime` check on each call | Avoids inotify/watchdog dependency |

**Discovery order (priority high to low):**
1. `{project_root}/CLAUDE.md` (or AGENTS.md, GEMINI.md, RULES.md)
2. `{project_root}/.claude/instructions.md`
3. `~/.claude/CLAUDE.md` (global user instructions)
4. `~/.claude/projects/{project-path}/CLAUDE.md` (project-specific user overrides)

**Merging strategy:** Concatenate all found files with `---` separator, project-level instructions first (higher priority), global last. Total budget: configurable, default ~2000 tokens from `ContextBudget`.

### New Dependencies: NONE

Everything is stdlib (`pathlib`, `os`).

**Confidence:** HIGH -- straightforward filesystem operations.

---

## 3. Session Resume

**Goal:** Persist conversation history between `run()` calls for session continuity.

### What Exists Already

- `MessageStore` protocol: `save_message()`, `get_messages()`, `count_messages()`, `delete_messages_before()` -- already ISP-compliant, already implemented in InMemory/SQLite/PostgreSQL.
- `SessionState.runtime_messages` in `session/types.py` -- in-memory message list.
- `InMemorySessionManager` with `SessionSnapshotStore` -- serializes/deserializes session state with backend persistence.
- `SessionBackend` in `session/backends.py` -- pluggable persistence (InMemory, File, SQLite).

### Recommended Approach: Bridge MessageStore into ThinRuntime

| Component | Implementation | Why |
|-----------|---------------|-----|
| Message persistence | Use existing `MessageStore` protocol | Already has InMemory/SQLite/Postgres implementations |
| Session ID tracking | Add `session_id: str | None = None` to `RuntimeConfig` | Optional, backward-compatible |
| Resume on `run()` | If `session_id` set, load messages from MessageStore before LLM call | Transparent to callers |
| Auto-save | After each `run()`, persist new_messages from final event | Append-only, simple |

**Key insight:** ThinRuntime currently receives `messages` as a parameter to `run()`. For session resume, the caller (Agent facade or SessionManager) loads history from MessageStore and passes it. ThinRuntime itself does NOT need to know about persistence -- separation of concerns. The Agent facade or a new `SessionResumeFilter` (InputFilter) handles load/save.

### New Dependencies: NONE

Existing `MessageStore` implementations cover all backends. The `aiosqlite` and `asyncpg` optional deps already exist.

**Confidence:** HIGH -- uses existing infrastructure.

---

## 4. Web Tools (Built-in)

**Goal:** Expose WebSearch and WebFetch as ThinRuntime built-in tools.

### What Exists Already

- `WebProvider` protocol (2 methods: `fetch`, `search`) in `tools/web_protocols.py`
- `WebSearchProvider` protocol (1 method: `search`)
- `WebFetchProvider` protocol (1 method: `fetch`)
- `HttpxWebProvider` -- full implementation with SSRF protection, trafilatura fallback
- 6 search providers: DuckDuckGo, Tavily, Brave, SearXNG, Jina, Crawl4AI
- All already have optional deps in `pyproject.toml`

### Recommended Approach: Register as Built-in Tools

| Component | Implementation | Why |
|-----------|---------------|-----|
| Tool specs | Add `web_search` and `web_fetch` ToolSpecs to `builtin_tools.py` | Same pattern as existing 9 builtins |
| Tool executors | Wrap `HttpxWebProvider.search()` and `.fetch()` as async executors | Standard tool executor pattern |
| Provider injection | Accept `WebProvider` in ThinRuntime constructor (optional) | DIP -- runtime doesn't pick the provider |
| Default provider | If no WebProvider given but `httpx` available, use `HttpxWebProvider()` with no search | Lazy, graceful degradation |

**Tool schemas:**

```python
WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query"},
        "max_results": {"type": "integer", "default": 5},
    },
    "required": ["query"],
}

WEB_FETCH_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "URL to fetch"},
        "prompt": {"type": "string", "description": "What to extract from the page"},
    },
    "required": ["url"],
}
```

### New Dependencies: NONE

Everything already exists. Just wiring.

**Confidence:** HIGH -- pure integration work.

---

## 5. Multimodal Input

**Goal:** Support images, PDFs, and Jupyter notebooks as input content blocks.

### Content Block Formats by Provider

**Anthropic (verified from official docs, 2026):**
```python
# Base64 image
{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "<base64>"}}
# URL image
{"type": "image", "source": {"type": "url", "url": "https://..."}}
# Supported: JPEG, PNG, GIF, WebP. Max 8000x8000px. ~1600 tokens per 1.15MP image.
```

**OpenAI (verified from official docs):**
```python
# content is a list of blocks
{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<base64>"}}
# or URL
{"type": "image_url", "image_url": {"url": "https://..."}}
```

**Google Gemini (verified from official docs):**
```python
# inline_data Part
{"inline_data": {"mime_type": "image/jpeg", "data": "<base64>"}}
# Supported for files < 20MB inline.
```

### Domain Types Changes

The current `Message.content` is `str`. For multimodal, it needs to support `str | list[ContentBlock]`:

```python
@dataclass(frozen=True)
class ContentBlock:
    """A content block within a message (text, image, file)."""
    type: str  # "text" | "image" | "file"
    text: str | None = None
    media_type: str | None = None  # "image/jpeg", "application/pdf"
    data: str | None = None  # base64-encoded
    source_url: str | None = None
    metadata: dict[str, Any] | None = None
```

**Key design:** ContentBlock is a DOMAIN type (frozen dataclass, no external deps). Each LLM adapter converts ContentBlock to its provider-specific format. This is Clean Architecture -- adapters handle translation.

### PDF Parsing

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| pymupdf4llm | >=0.0.17 | PDF to markdown text extraction | Best quality-to-speed ratio for LLM consumption (0.12s, excellent markdown). Built on PyMuPDF. Specifically designed for LLM input. |

**Alternative considered:** `pdfplumber` -- excellent for tables but slower, larger dependency. `pypdf` -- fast but lower quality output.

**pymupdf4llm** is the recommended choice because:
1. Output is LLM-optimized markdown (headers, tables, lists preserved)
2. Fast (0.12s typical)
3. Single dependency (`PyMuPDF`)
4. MIT licensed

### Jupyter Notebook Parsing

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| nbformat | >=5.10 | Parse .ipynb files, extract cells and outputs | Official Jupyter library. stdlib-like stability. Already widely used. |

**nbformat** reads the JSON structure and provides typed access to cells, outputs, and metadata. No need for nbconvert -- just iterate cells and format as markdown.

### New Optional Dependencies

```toml
[project.optional-dependencies]
# Multimodal input: PDF parsing
pdf = ["pymupdf4llm>=0.0.17"]
# Multimodal input: Jupyter notebook parsing
notebook = ["nbformat>=5.10"]
```

**Image handling requires NO new dependencies** -- base64 encoding is stdlib, and the LLM SDKs (anthropic, openai, google-genai) already handle image content blocks.

**Confidence:** HIGH for images (well-documented APIs), MEDIUM for PDF/notebook (need integration testing with large files).

---

## 6. MCP Resource Reading

**Goal:** Support `resources/list` and `resources/read` MCP protocol methods in addition to existing `tools/list` and `tools/call`.

### MCP Resources Protocol (verified from spec 2025-03-26)

**JSON-RPC Methods:**

```python
# List available resources
{"jsonrpc": "2.0", "id": "1", "method": "resources/list", "params": {}}
# Response: {"result": {"resources": [{"uri": "file:///...", "name": "...", "mimeType": "text/plain"}]}}

# Read a resource
{"jsonrpc": "2.0", "id": "2", "method": "resources/read", "params": {"uri": "file:///path"}}
# Response: {"result": {"contents": [{"uri": "...", "text": "..."}]}}  # or blob with base64
```

**Resource content types:**
- Text resources: `{"uri": "...", "text": "content string"}`
- Binary resources: `{"uri": "...", "blob": "base64-encoded"}`

**Capabilities declaration:** Server declares `{"capabilities": {"resources": {}}}` or `{"capabilities": {"resources": {"subscribe": true}}}`.

### Recommended Approach: Extend McpClient

| Component | Implementation | Why |
|-----------|---------------|-----|
| `list_resources()` | New method on `McpClient`, same HTTP pattern as `list_tools()` | Consistent with existing MCP client |
| `read_resource()` | New method on `McpClient`, returns text or bytes | Same JSON-RPC pattern |
| Caching | Same TTL cache as tools (300s default) | Consistency |
| Integration | Resources loaded into context via `SystemPromptInjector` or dedicated filter | Plugs into existing InputFilter pipeline |

### New Dependencies: NONE

`McpClient` already uses `httpx` for JSON-RPC. Same transport, new methods.

**Confidence:** HIGH -- straightforward extension of existing MCP client. The protocol is well-specified.

---

## 7. System Reminders

**Goal:** Inject dynamic context (current date, git status, environment info, custom reminders) into conversations at strategic points.

### Recommended Approach: Conditional InputFilter

| Component | Implementation | Why |
|-----------|---------------|-----|
| `SystemReminderFilter` | New `InputFilter` that injects reminders into system_prompt | Fits existing architecture |
| Reminder registry | List of `Reminder` objects with condition + content callables | Extensible, testable |
| Token budget | Dedicated slice from ContextBudget (~500 tokens) | Prevents budget bloat |
| Injection frequency | Every N turns, or on condition (e.g., "if git repo detected") | Configurable |

**Reminder types:**
```python
@dataclass(frozen=True)
class SystemReminder:
    """A conditional system reminder."""
    name: str
    content: Callable[[], str] | str  # static or dynamic
    condition: Callable[[], bool] | None = None  # None = always inject
    priority: int = 5  # lower = higher priority
    max_tokens: int = 200
```

**Built-in reminders:**
- Current date/time (`datetime.now().isoformat()`)
- Working directory (`os.getcwd()`)
- Git branch (if `.git` exists, `subprocess` call)
- Project instructions digest (hash of loaded CLAUDE.md)

### New Dependencies: NONE

stdlib: `datetime`, `os`, `subprocess`, `pathlib`.

**Confidence:** HIGH -- simple pattern, well-understood.

---

## 8. Git Worktree Isolation

**Goal:** Subagents work in isolated git worktrees to avoid file conflicts.

### Recommended Approach: asyncio.subprocess + tempfile

| Component | Implementation | Why |
|-----------|---------------|-----|
| Worktree creation | `git worktree add <path> --detach` via `asyncio.create_subprocess_exec` | Non-blocking, clean isolation |
| Temp directory | `tempfile.mkdtemp(prefix="swarmline-worktree-")` | OS-managed cleanup |
| Worktree cleanup | `git worktree remove <path>` + `shutil.rmtree` as fallback | Graceful + forced cleanup |
| Subagent integration | Pass worktree path as sandbox `cwd` to `ThinSubagentOrchestrator` | Subagent sees isolated filesystem |
| Lifecycle | Create on subagent spawn, remove on subagent completion | Tied to subagent lifecycle |

**Git worktree commands (all via asyncio.create_subprocess_exec):**
```bash
git worktree add /tmp/swarmline-worktree-xxx --detach  # create
git worktree list --porcelain                            # list
git worktree remove /tmp/swarmline-worktree-xxx          # cleanup
```

**Key safety considerations:**
- Always use `--detach` to avoid creating branches
- Set `GIT_WORK_TREE` and `GIT_DIR` env vars for subprocess isolation
- Cleanup in `finally` block to prevent leaked worktrees
- Max worktrees limit (default 5) to prevent disk exhaustion

### New Dependencies: NONE

stdlib: `asyncio.create_subprocess_exec`, `tempfile`, `shutil`, `os`.

**Confidence:** MEDIUM -- git worktree management has edge cases (locked worktrees, concurrent access). Needs careful error handling.

---

## 9. Thinking Events

**Goal:** Support Anthropic extended thinking as a separate reasoning stream in RuntimeEvent.

### Anthropic Extended Thinking API (verified from official docs, 2026)

**Request parameter:**
```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=16000,
    thinking={"type": "enabled", "budget_tokens": 10000},
    # Or adaptive: thinking={"type": "adaptive"}
    # Display options: "summarized" (default Claude 4) or "omitted"
    messages=[...]
)
```

**Response content blocks:**
```python
# response.content = [
#   ThinkingBlock(type="thinking", thinking="...", signature="..."),
#   TextBlock(type="text", text="...")
# ]
```

**Streaming events:**
- `content_block_start` -- marks beginning of thinking/text block
- `content_block_delta` with `thinking_delta` -- streamed thinking content
- `content_block_delta` with `text_delta` -- streamed text content
- `signature_delta` -- encrypted thinking signature for multi-turn
- `content_block_stop` -- marks end of block

**Constraints:**
- `budget_tokens` must be < `max_tokens` (except with interleaved thinking)
- Only `tool_choice: {"type": "auto"}` or `{"type": "none"}` with extended thinking
- Thinking blocks MUST be preserved for multi-turn (signature is required)
- `display: "omitted"` -- no thinking_delta events, only signature_delta

### Recommended Approach: New RuntimeEvent Type + Adapter Extension

| Component | Implementation | Why |
|-----------|---------------|-----|
| New event type | Add `"thinking_delta"` to `RUNTIME_EVENT_TYPES` | Parallel to `assistant_delta` |
| `RuntimeEvent.thinking_delta(text)` | Factory method returning `RuntimeEvent(type="thinking_delta", data={"text": "..."})` | Consistent API |
| AnthropicAdapter changes | Parse `ThinkingBlock` from response, emit thinking events before text | Adapter responsibility |
| Config | Add `thinking: dict | None = None` to `RuntimeConfig.extra` | Optional, no breaking changes |
| Multi-turn | Preserve thinking blocks + signatures in message history | Required by Anthropic API |
| Provider fallback | Non-Anthropic providers ignore thinking config silently | Graceful degradation |

**OpenAI/Google:** Neither currently supports extended thinking in the same way. OpenAI has "reasoning" tokens but no exposed thinking content. Google has no equivalent. This is Anthropic-only for now.

### New Dependencies: NONE

`anthropic` SDK (already a dependency) handles the API. We parse the response blocks.

**Confidence:** HIGH -- well-documented API, straightforward adapter extension.

---

## 10. Background Agents

**Goal:** Run subagents in background, provide notification mechanism and monitor tool.

### Recommended Approach: asyncio.Task + EventBus

| Component | Implementation | Why |
|-----------|---------------|-----|
| Background execution | `asyncio.create_task()` wrapping subagent `run()` | Native async, no threads |
| Task registry | `dict[str, BackgroundTask]` on ThinRuntime or SubagentOrchestrator | Track running tasks |
| Notifications | Existing `EventBus.emit("background_agent_complete", ...)` | Reuse existing pub-sub |
| Monitor tool | New tool spec `monitor` -- returns status of background tasks | LLM can check progress |
| Result collection | `asyncio.gather()` or per-task `await` | Standard patterns |
| Cancellation | Existing `CancellationToken` per background task | Consistent with current design |

**Background task lifecycle:**
```python
@dataclass
class BackgroundTask:
    task_id: str
    agent_name: str
    task: asyncio.Task[list[RuntimeEvent]]
    started_at: float
    status: str = "running"  # "running" | "completed" | "failed" | "cancelled"
    result_summary: str = ""
```

**Monitor tool schema:**
```python
MONITOR_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "Background task ID to check (omit for all)"},
    },
}
```

### New Dependencies: NONE

stdlib: `asyncio.Task`, `asyncio.create_task`, `asyncio.gather`.

**Confidence:** MEDIUM -- asyncio.Task management is straightforward, but error propagation and cleanup in background tasks needs careful design. Unhandled exceptions in background tasks can be silent.

---

## Summary: Dependency Changes

### New Optional Dependencies (pyproject.toml additions)

```toml
# Multimodal input: PDF parsing
pdf = ["pymupdf4llm>=0.0.17"]
# Multimodal input: Jupyter notebook parsing
notebook = ["nbformat>=5.10"]
```

### NO New Core Dependencies

All 10 features build on existing infrastructure:
- `anthropic`, `openai`, `google-genai` -- existing, already handle multimodal + thinking
- `httpx` -- existing, used by McpClient and web tools
- `structlog` -- existing, for logging
- `pydantic` -- existing, for validation
- stdlib (`asyncio`, `pathlib`, `tempfile`, `subprocess`, `base64`, `json`, `datetime`) -- always available

### What NOT to Add

| Library | Why NOT |
|---------|---------|
| `tiktoken` | Multi-provider framework -- tiktoken is OpenAI-only. Char-based estimation is sufficient for compaction triggers. |
| `watchdog` | File watching for project instructions. `stat().st_mtime` is simpler, no daemon process needed. |
| `gitpython` | Git worktree management. `asyncio.create_subprocess_exec` is lighter, avoids a heavy dependency. |
| `aiofiles` | Async file I/O. `pathlib` is sufficient -- file reads are fast enough to not block the event loop for small config files. |
| `tokenizers` (HuggingFace) | Same problem as tiktoken -- model-specific. Adds Rust compilation dependency. |

---

## Integration Points Summary

| Feature | Primary Integration Point | Existing Abstraction |
|---------|--------------------------|---------------------|
| Compaction | `InputFilter` protocol in `input_filters.py` | `MaxTokensFilter`, `LlmSummaryGenerator` |
| Project Instructions | `InputFilter` protocol (new `ProjectInstructionsFilter`) | `SystemPromptInjector` |
| Session Resume | `MessageStore` protocol in `protocols/memory.py` | InMemory/SQLite/Postgres providers |
| Web Tools | `builtin_tools.py` tool registration | `HttpxWebProvider`, 6 search providers |
| Multimodal | `Message.content` type union, LLM adapter `call()` | `AnthropicAdapter`, `OpenAICompatAdapter`, `GoogleAdapter` |
| MCP Resources | `McpClient` in `runtime/thin/mcp_client.py` | Existing JSON-RPC transport |
| System Reminders | `InputFilter` protocol (new `SystemReminderFilter`) | `SystemPromptInjector`, `ContextBudget` |
| Git Worktree | `ThinSubagentOrchestrator` spawn logic | `asyncio.create_subprocess_exec` |
| Thinking Events | `RuntimeEvent` + `AnthropicAdapter` | `RUNTIME_EVENT_TYPES`, streaming pipeline |
| Background Agents | `ThinSubagentOrchestrator` + `EventBus` | `asyncio.Task`, `CancellationToken` |

---

## Sources

- [Anthropic Extended Thinking Docs](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking) -- HIGH confidence
- [Anthropic Vision Docs](https://docs.anthropic.com/en/docs/build-with-claude/vision) -- HIGH confidence
- [MCP Resources Spec 2025-03-26](https://spec.modelcontextprotocol.io/specification/2025-03-26/server/resources/) -- HIGH confidence
- [MCP Resources Spec 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/server/resources) -- HIGH confidence
- [Microsoft Semantic Kernel Compaction](https://learn.microsoft.com/en-us/agent-framework/agents/conversations/compaction) -- HIGH confidence, verified 2026-03
- [OpenAI Vision API](https://developers.openai.com/api/docs/guides/images-vision) -- HIGH confidence
- [Google Gemini Multimodal](https://ai.google.dev/gemini-api/docs/image-understanding) -- HIGH confidence
- [pymupdf4llm PyPI](https://pypi.org/project/PyMuPDF/) -- HIGH confidence
- [nbformat docs](https://nbformat.readthedocs.io/en/latest/format_description.html) -- HIGH confidence
- [tiktoken PyPI](https://pypi.org/project/tiktoken/) -- evaluated and rejected
