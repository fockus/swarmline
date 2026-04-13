# Domain Pitfalls: ThinRuntime Parity v2

**Domain:** AI Agent Framework -- 10 New Features
**Researched:** 2026-04-13

## Critical Pitfalls

Mistakes that cause rewrites or major issues.

### Pitfall 1: Breaking Message.content Type Signature
**What goes wrong:** Changing `Message.content` from `str` to `str | list[ContentBlock]` for multimodal support breaks every consumer that accesses `message.content` as a string -- including all 3 LLM adapters, InputFilter implementations, tool executors, session serialization, memory stores, and tests.
**Why it happens:** Multimodal naturally suggests making `content` a union type. It looks simple in the type definition but the blast radius is enormous.
**Consequences:** Hundreds of test failures. Every `message.content` access needs `isinstance` checks. Serialization/deserialization breaks.
**Prevention:**
1. Add a NEW optional field `content_blocks: list[ContentBlock] | None = None` (default None)
2. Keep `content: str` as the primary field
3. Add a `Message.text_content` property that extracts text from either field
4. LLM adapters check `content_blocks` first, fall back to `content`
5. All existing code continues using `content` unchanged
**Detection:** Any test that accesses `message.content` without type checking.

### Pitfall 2: Compaction Summarization Losing Tool Call Context
**What goes wrong:** LLM summarization of older messages drops tool call details that are needed by subsequent tool calls. For example, summarizing away a `read_file` result means the agent can't reference the file content later.
**Why it happens:** Naive summarization treats all messages equally. Tool call + result atomic groups need special handling.
**Consequences:** Agent asks to re-read files it already read. Circular tool calling. Context degradation.
**Prevention:**
1. Follow the Microsoft Semantic Kernel pattern: group messages into atomic units (user turn, assistant text, tool_call + tool_result)
2. Never split tool call from its result
3. Summarize TEXT messages; COLLAPSE tool results to `[Tool: name -> brief_summary]` instead of summarizing them
4. Preserve the most recent N messages verbatim (recency window)
5. Test with real coding conversations, not synthetic data
**Detection:** Agent re-requesting tools it already called in the same session.

### Pitfall 3: Thinking Block Signature Loss in Multi-turn
**What goes wrong:** Anthropic extended thinking requires that thinking blocks with their signatures be preserved and echoed back in multi-turn conversations. If the conversation compactor or session resume strips thinking blocks, the API returns errors.
**Why it happens:** Thinking blocks look like internal state that can be safely discarded. But Anthropic requires the complete thinking block sequence (including signatures) for the previous assistant turn to be present in multi-turn requests.
**Consequences:** `400 Bad Request` from Anthropic API on subsequent turns. Session breaks.
**Prevention:**
1. Mark thinking blocks as non-compactable
2. When persisting messages for session resume, include thinking blocks and signatures
3. The compaction pipeline must preserve the MOST RECENT assistant response's thinking blocks in full
4. Older thinking blocks can be safely removed
**Detection:** Anthropic API errors mentioning "thinking" or "signature" after compaction or session resume.

### Pitfall 4: Git Worktree Leak on Subagent Crash
**What goes wrong:** A subagent crashes (exception, timeout, OOM) and its git worktree is never cleaned up. After many failed runs, disk fills with leaked worktrees. `git worktree list` shows dozens of stale entries.
**Why it happens:** Cleanup logic is in the happy path but not in the error/exception path. `asyncio.Task` exceptions can be swallowed silently.
**Consequences:** Disk exhaustion. Git operations slow down (git iterates all worktrees). Stale branch references.
**Prevention:**
1. Always create worktrees in a `try/finally` block
2. Use `atexit` handler as a last resort
3. Implement a `WorktreeManager.cleanup_stale()` method that runs on startup, removing worktrees older than a threshold
4. Add max_worktrees limit (default 5)
5. Use `tempfile.mkdtemp()` so the OS can clean up temp dirs
6. Register worktrees in a cleanup manifest file on disk
**Detection:** `git worktree list --porcelain` showing entries with no running process.

### Pitfall 5: Background Agent Exception Silencing
**What goes wrong:** `asyncio.create_task()` creates a background task. If the task raises an exception, it is stored on the Task object but never retrieved. Python logs "Task exception was never retrieved" and the error is lost.
**Why it happens:** Standard asyncio behavior -- unhandled exceptions in tasks are only logged at garbage collection time.
**Consequences:** Background agents fail silently. Monitor tool shows "running" forever. No error notification to parent agent.
**Prevention:**
1. Always add a `done_callback` to background tasks that captures exceptions and emits error events
2. Use `task.add_done_callback(self._on_background_complete)` where the callback checks `task.exception()` and updates the BackgroundTask status
3. Set a timeout for background tasks (default 5 minutes)
4. Never share the same RuntimeEvent stream between parent and child -- background agents run with their own event accumulator
**Detection:** Monitor tool returning "running" for tasks that have actually crashed.

## Moderate Pitfalls

### Pitfall 6: Compaction LLM Call Blocking the Agent Loop
**What goes wrong:** Compaction uses an LLM call for summarization. If this call is slow (5-10s), it blocks the entire agent turn because InputFilter.filter() is awaited synchronously in the filter pipeline.
**Prevention:**
1. Use a cheap/fast model for summarization (haiku, gpt-4o-mini)
2. Set a short timeout (10s)
3. On timeout, fall back to truncation (MaxTokensFilter behavior)
4. Consider caching: only re-summarize if message list has changed since last compaction

### Pitfall 7: Project Instructions File Encoding Issues
**What goes wrong:** CLAUDE.md files with non-UTF8 encoding (Windows-1251, ISO-8859-1) cause UnicodeDecodeError.
**Prevention:** Read files with `errors="replace"` or `errors="ignore"`. Log a warning for non-UTF8 files. Most CLAUDE.md files are UTF-8 but edge cases exist (especially on Windows).

### Pitfall 8: Session Resume Message Ordering
**What goes wrong:** Messages loaded from MessageStore come in a different order than they were created. Conversation context is scrambled.
**Prevention:**
1. MessageStore.get_messages() must return messages in chronological order
2. Add an explicit `ORDER BY created_at ASC` in SQLite/Postgres implementations
3. In-memory store should use a list (already ordered)
4. Add a contract test: `test_get_messages_returns_chronological_order`

### Pitfall 9: MCP Resource URI Injection
**What goes wrong:** A malicious MCP server returns resource URIs containing path traversal (`../../etc/passwd`) or other injection vectors. The client blindly passes these to downstream consumers.
**Prevention:**
1. Validate URIs before use
2. Only allow `file://`, `https://`, and custom schemes
3. Reject URIs with `..` path segments
4. Log and skip invalid URIs
5. Route resource reads through ToolExecutor -- hooks + policy apply (same as tool calls)

### Pitfall 10: Multimodal Content Size Explosion
**What goes wrong:** A user passes a 10MB image as base64. This bloats the message to ~13MB (base64 overhead). Combined with conversation history, the request exceeds provider limits (32MB for Anthropic).
**Prevention:**
1. Validate image size before encoding
2. Resize images larger than 1568px on the long edge (Anthropic recommendation)
3. Set a max_image_size_bytes config (default 5MB)
4. For PDFs, extract text instead of sending full binary

### Pitfall 11: InputFilter Ordering Matters
**What goes wrong:** Filters are applied sequentially. Wrong order causes unexpected behavior (e.g., compaction runs after MaxTokensFilter already truncated, so compaction summary is incomplete).
**Prevention:**
1. Document filter ordering: ProjectInstructions -> SystemReminders -> Compaction -> MaxTokensFilter
2. Compaction MUST run before MaxTokensFilter
3. Add a docstring to RuntimeConfig.input_filters explaining order semantics
4. Consider a priority system for filters (like ContextPack priorities)

### Pitfall 12: Session Resume Without Compaction Causes Context Overflow
**What goes wrong:** Resuming a long session loads entire history, exceeds context window, and causes LLM API errors.
**Prevention:**
1. Session Resume must have a built-in max_messages limit as a safety valve (default: 100)
2. MaxTokensFilter already exists as a safety net -- ensure it's always in the filter pipeline
3. If compaction is available, it naturally handles resumed sessions
4. If compaction is NOT configured, truncation still works

## Minor Pitfalls

### Pitfall 13: System Reminder Token Budget Overflow
**What goes wrong:** Too many active system reminders eat into the LLM's context budget, leaving less room for actual conversation.
**Prevention:** Set a hard token budget for reminders (default 500 tokens). Prioritize reminders by priority field. Drop low-priority reminders when budget is exceeded.

### Pitfall 14: Web Tool Rate Limiting
**What goes wrong:** Agent makes rapid web search calls, triggering rate limits from search providers (DuckDuckGo, Brave, Tavily).
**Prevention:** Add a simple rate limiter to the web tool executor (max 1 request per second). Return a helpful error message when rate-limited.

### Pitfall 15: Monitor Tool Polling Loop
**What goes wrong:** The LLM calls `monitor` in a tight loop to check on background agents, wasting tokens and tool call budget.
**Prevention:** Add a `min_interval_seconds` check to the monitor tool. If called too frequently, return "no new updates, check again later" without counting as a tool call failure.

### Pitfall 16: Thinking Events With Non-Anthropic Providers
**What goes wrong:** User enables thinking config but uses OpenAI/Google provider. No thinking events are emitted, but no error either. User is confused.
**Prevention:** When thinking is configured and the resolved provider is not Anthropic, emit a `RuntimeEvent.status("Thinking events are only supported with Anthropic models")` once at the start.

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Project Instructions | File encoding (#7), File read on every turn | Read once at construction with `errors="replace"` |
| System Reminders | Token overflow (#13) | Hard token budget, priority ordering |
| Web Tools | Rate limiting (#14) | Per-second rate limiter |
| MCP Resources | URI injection (#9), No access control | Validate URIs, route through ToolExecutor |
| Session Resume | Message ordering (#8), Context overflow without compaction (#12) | ORDER BY created_at, max_messages safety valve |
| Compaction | Tool context loss (#2), LLM blocking (#6), Filter ordering (#11) | Atomic message groups, cheap model, document filter order |
| Thinking Events | Provider mismatch (#16), Signature loss (#3), Token counting | Status warning, preserve thinking blocks, separate thinking_tokens |
| Multimodal | Content size (#10), Message type break (#1) | Size validation, optional content_blocks field |
| Git Worktree | Worktree leak (#4) | try/finally, cleanup_stale(), max limit, cleanup manifest |
| Background Agents | Exception silencing (#5), Monitor polling (#15) | done_callback, timeout, min_interval check |

## Sources

- [Microsoft Semantic Kernel Compaction](https://learn.microsoft.com/en-us/agent-framework/agents/conversations/compaction) -- atomic message groups, compaction strategies
- [Anthropic Extended Thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking) -- thinking signature preservation requirements
- [Anthropic Vision](https://docs.anthropic.com/en/docs/build-with-claude/vision) -- image size limits and recommendations
- [Python asyncio docs](https://docs.python.org/3/library/asyncio-task.html) -- Task exception handling patterns
- [MCP Resources Spec](https://spec.modelcontextprotocol.io/specification/2025-03-26/server/resources/) -- resource URI format
- Codebase analysis of existing error handling patterns, message usage patterns, filter pipeline, event streams
