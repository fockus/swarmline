# Feature Landscape: ThinRuntime Parity v2

**Domain:** AI agent runtime capabilities (coding agent, Claude Code parity)
**Researched:** 2026-04-13
**Confidence:** HIGH (official docs + API specs verified)

---

## 1. Conversation Compaction

### How It Works in Claude Code

Claude Code triggers compaction automatically when context reaches ~83.5% of the window (~167K tokens on 200K). The process:

1. Clears older tool outputs first (cheapest compression).
2. If still over threshold, sends entire conversation to a separate LLM call with a summarization prompt.
3. Replaces all pre-summary messages with a single `compaction` content block.
4. Re-injects project-root CLAUDE.md from disk after compaction (nested CLAUDE.md files reload lazily).

**Anthropic API contract** (beta `compact-2026-01-12`):
- `context_management.edits[].type: "compact_20260112"` in request.
- `trigger.type: "input_tokens"`, `trigger.value: 150000` (min 50000).
- Response contains `compaction` content block with summary text.
- Client MUST pass compaction block back on subsequent requests.
- `pause_after_compaction: true` pauses after summary, allowing client to inject preserved messages before continuing.
- Custom `instructions` field completely replaces default summarization prompt.
- Token usage breakdown includes separate `iterations` entries for compaction vs. message.
- Streaming: compaction blocks arrive as `compaction_delta` events.

**What is preserved:**
- Recent messages (last N turns before compaction point).
- Semantic summary of conversation history.
- System prompt and CLAUDE.md (re-read from disk).
- Tool use patterns and outcomes (summarized).

**What is lost:**
- Original message boundaries (consolidated into one summary).
- Detailed instructions from early conversation (unless in CLAUDE.md/system prompt).
- Exact code snippets from early turns (only semantically summarized).
- Nested CLAUDE.md instructions (until subdirectory files are re-accessed).

**Key difference from truncation:** Truncation discards old messages entirely. Compaction generates a semantic summary preserving continuity. The summary is an LLM-generated artifact, not a mechanical operation.

### Classification

| Aspect | Category | Rationale |
|--------|----------|-----------|
| Auto-trigger at token threshold | **Table Stakes** | Without this, long sessions crash or silently lose context |
| LLM-based summarization (not truncation) | **Table Stakes** | Simple truncation loses too much; users expect smart compression |
| Manual `/compact` command | **Table Stakes** | Users need escape hatch for proactive context management |
| Custom summarization instructions | **Differentiator** | Power users tune what survives compaction |
| `pause_after_compaction` (client-side message preservation) | **Differentiator** | Enables preserving last N messages verbatim alongside summary |
| Re-inject project instructions post-compaction | **Table Stakes** | Critical: compaction that loses project rules is a regression |
| Implementing Anthropic's `compact_20260112` API natively | **Anti-Feature** | Provider-specific API detail. Swarmline should use its own protocol that works across providers |

### Complexity: MEDIUM-HIGH

- LLM summarization call adds latency + cost.
- Token counting must be accurate across providers.
- Must integrate with existing `ContextBudget` and `CodingContextAssembler`.
- Edge case: compaction thrashing when single tool output fills context.

### Dependencies on Existing Features

- `ContextBudget` (context/budget.py) -- token counting infrastructure.
- `CodingContextAssembler` -- must re-assemble coding slices post-compaction.
- `RuntimeConfig.cost_budget` -- compaction LLM calls count toward budget.
- `ThinRuntime._llm_call` -- reuse for summarization call.
- Session/message history management.

---

## 2. Project Instructions (CLAUDE.md/AGENTS.md)

### How It Works in Claude Code

**Discovery algorithm (walk-up):**
1. Start at current working directory.
2. Walk up directory tree to filesystem root.
3. At each level, check for `CLAUDE.md`, `.claude/CLAUDE.md`, and `CLAUDE.local.md`.
4. All discovered files are concatenated (not overriding).
5. Within each directory, `CLAUDE.local.md` appended after `CLAUDE.md`.
6. Subdirectory CLAUDE.md files loaded lazily (on first file access in that subdirectory).

**Additional sources (merge priority, highest first):**
1. Managed policy (`/Library/Application Support/ClaudeCode/CLAUDE.md` on macOS).
2. Project (`./CLAUDE.md` or `./.claude/CLAUDE.md`).
3. User (`~/.claude/CLAUDE.md`).
4. Local (`./CLAUDE.local.md`).
5. Path-scoped rules (`.claude/rules/*.md` with `paths:` frontmatter).

**Key behaviors:**
- `@path/to/import` syntax for importing additional files (max depth 5).
- HTML comments stripped before injection.
- Injected as user message content, not system prompt.
- `AGENTS.md` support via `@AGENTS.md` import in CLAUDE.md.
- `claudeMdExcludes` setting to skip irrelevant files in monorepos.
- Path-scoped rules: `.claude/rules/testing.md` with `paths: ["**/*.test.ts"]` loads only when matching files are accessed.

**Hot reload behavior:**
- Project-root CLAUDE.md is re-read from disk after compaction.
- Nested CLAUDE.md files reload when Claude accesses files in their subdirectories.
- No file-watcher-based hot reload during a session (read at start + on-demand).

### Classification

| Aspect | Category | Rationale |
|--------|----------|-----------|
| Walk-up directory discovery | **Table Stakes** | Users expect monorepo/nested project support |
| File concatenation (not override) | **Table Stakes** | Layers must compose, not replace |
| `@import` syntax | **Table Stakes** | Prevents CLAUDE.md bloat, enables modular instructions |
| Path-scoped rules | **Differentiator** | Smart context management -- only inject rules for relevant files |
| AGENTS.md import compatibility | **Differentiator** | Multi-agent-tool interop |
| User-level instructions (~/.config) | **Table Stakes** | Personal preferences across projects |
| Managed policy (org-level) | **Anti-Feature** | Out of scope for a library -- org policy is deployment concern |
| HTML comment stripping | **Differentiator** | Nice for maintaining human-readable files with lower token cost |
| Hot reload via file watcher | **Anti-Feature** | Adds complexity with minimal benefit; on-demand reload sufficient |

### Complexity: MEDIUM

- Directory walking is straightforward.
- Import parsing requires cycle detection.
- Path-scoped rules need glob matching.
- Token budgeting for injected instructions.
- Must integrate with CodingContextAssembler priority system.

### Dependencies on Existing Features

- `CodingContextAssembler` (context/coding_context_builder.py) -- new slice type.
- `ContextBudget` -- instructions consume budget.
- `RuntimeConfig` -- new `project_instructions_paths` config.
- Compaction -- must survive and re-inject after compaction.

---

## 3. Session Resume

### How It Works in Claude Code

**Persistence:**
- Every message, tool use, and result written to plaintext JSONL under `~/.claude/projects/<project>/`.
- Sessions identified by unique ID.
- Named sessions via `--name` flag.

**Resume modes:**
- `claude --continue` (or `-c`): resume last session in current directory.
- `claude --resume` (or `-r`): browse all recent sessions.
- `claude --resume <id>`: resume specific session by ID.
- `claude --continue --fork-session`: branch off with new ID, preserving history.

**What is saved:**
- Full conversation history (messages, tool calls, tool results).
- Session metadata (directory, branch, timestamps, name).
- File snapshots before edits (for revert capability).

**What is NOT restored:**
- Session-scoped permissions (must re-approve).
- Active MCP server connections (reconnected on demand).
- Intermediate runtime state (only conversation history).

**Token impact:**
- Full history restored into context window.
- If history exceeds context, compaction triggers immediately.
- Sessions are independent -- no cross-session context leakage.

### Classification

| Aspect | Category | Rationale |
|--------|----------|-----------|
| Save conversation to JSONL | **Table Stakes** | Users expect to resume work after interruption |
| Resume last session | **Table Stakes** | Most common use case |
| Browse/select from session list | **Differentiator** | Multi-session management |
| Named sessions | **Differentiator** | Organizational convenience for parallel work |
| Fork session | **Differentiator** | Branch-and-explore without losing original |
| File snapshots for revert | **Anti-Feature** | Git exists; library shouldn't duplicate VCS |
| Auto-compact on resume if over budget | **Table Stakes** | Resume that crashes on context overflow is broken |

### Complexity: MEDIUM

- JSONL serialization of Message + ToolSpec is straightforward.
- Must handle Message types including tool_calls metadata.
- Session index/listing needs lightweight storage.
- Interplay with compaction on resume needs careful design.

### Dependencies on Existing Features

- `domain_types.Message` -- serialization/deserialization.
- `session/` module -- existing SessionState, SessionManager infrastructure.
- `task_session_store.py` -- existing task session persistence.
- Compaction -- auto-compact on resume when history exceeds budget.
- `RuntimeConfig` -- session_id, session persistence config.

---

## 4. Web Tools (WebSearch + WebFetch)

### How It Works in Claude Code / Anthropic API

**WebSearch** (`web_search_20250305` server tool):
- Anthropic-executed server-side tool.
- Parameters: `max_uses`, `allowed_domains`, `blocked_domains`, `user_location`.
- Returns: `web_search_tool_result` with search results (title, URL, snippet, encrypted page content).
- Citations always enabled for search.
- Pricing: $10 per 1,000 searches + standard token costs.
- Claude Code: 8 searches per call hardcoded; only extracts title + URL.

**WebFetch** (`web_fetch_20250910` / `web_fetch_20260209` server tool):
- Retrieves full page content from URLs.
- Parameters: `max_uses`, `allowed_domains`, `blocked_domains`, `max_content_tokens`, `citations`.
- Dynamic filtering (v2): Claude writes code to filter content before loading into context.
- URL validation: can only fetch URLs that appeared in conversation context (security).
- Supports text and PDF content types; no JavaScript rendering.
- Built-in caching (server-managed).
- No additional cost beyond token usage.

**For swarmline (non-Anthropic-hosted):**
- Cannot use Anthropic's server tools directly -- these are Anthropic API features.
- Must implement as local tools wrapping existing `WebProvider`/`WebSearchProvider` protocols.
- Existing infrastructure: `web_protocols.py` (WebSearchProvider, WebFetchProvider, WebProvider), `web_httpx.py` (HttpxWebProvider).

### Classification

| Aspect | Category | Rationale |
|--------|----------|-----------|
| WebFetch tool (URL -> text) | **Table Stakes** | Agents need to read web content |
| WebSearch tool (query -> results) | **Table Stakes** | Agents need to discover information |
| Domain allow/block lists | **Table Stakes** | Security control for web access |
| `max_uses` rate limiting | **Table Stakes** | Prevent runaway web calls consuming budget |
| URL validation (only fetch conversation URLs) | **Differentiator** | Defense against prompt injection exfiltration |
| `max_content_tokens` truncation | **Table Stakes** | Large pages can blow context budget |
| Dynamic filtering (code execution on fetch) | **Anti-Feature** | Requires code execution sandbox; over-engineering for library |
| Citations from fetched content | **Differentiator** | Nice for transparency but not core |
| Using Anthropic server tools API directly | **Anti-Feature** | Provider lock-in; swarmline must be provider-agnostic |

### Complexity: LOW-MEDIUM

- Protocols already exist (`WebSearchProvider`, `WebFetchProvider`).
- Need to wrap as ThinRuntime builtin tools (ToolSpec + executor).
- Security: SSRF protection already in `web_httpx.py`.
- Integration: register as builtin tools alongside sandbox/thinking.

### Dependencies on Existing Features

- `tools/web_protocols.py` -- existing protocol contracts.
- `tools/web_httpx.py` -- existing implementation.
- `tools/web_providers/` -- existing search provider implementations.
- `runtime/thin/builtin_tools.py` -- registration point for builtin tools.
- Tool policy -- web tools subject to allow/deny policy.
- `ContextBudget` -- fetched content consumes budget.

---

## 5. Multimodal Input

### How It Works in Claude Code / Anthropic API

**Supported image formats:** JPEG, PNG, GIF, WebP.

**Image limits (API):**
- Up to 100 images per request.
- Total 32MB across all images.
- >20 images: max 2000x2000 pixels each.
- Recommended: 1000x1000+ pixels for analysis.

**PDF support:**
- Under 100 pages.
- 1,500-3,000 tokens per page.
- Sent as base64-encoded `application/pdf` content.
- Both text and visual element analysis.

**API content block format:**
```json
{
  "type": "image",
  "source": {
    "type": "base64",
    "media_type": "image/png",
    "data": "<base64>"
  }
}
```

**Claude Code specifics:**
- Read tool handles images (PNG, JPG) -- presents visually.
- Read tool handles PDFs -- with `pages` parameter for large PDFs.
- Read tool handles Jupyter notebooks (.ipynb).
- Binary content passed as base64 in content blocks.

**For swarmline:**
- `Message.content` is currently `str` -- needs to support multi-part content (list of text/image/document blocks).
- Multi-provider: Anthropic, OpenAI, and Google all support vision, but with different content block formats.
- Provider adapters must translate between internal format and provider-specific format.

### Classification

| Aspect | Category | Rationale |
|--------|----------|-----------|
| Image input (JPEG, PNG, GIF, WebP) | **Table Stakes** | All major LLM providers support vision |
| PDF document input | **Differentiator** | Not all agent frameworks handle this well |
| Multi-part message content (text + images) | **Table Stakes** | Required for any multimodal support |
| Jupyter notebook rendering | **Differentiator** | Useful for data science agents |
| Auto-resize large images | **Differentiator** | Prevents context overflow from high-res images |
| Video input | **Anti-Feature** | Not broadly supported, high complexity |
| Audio input | **Anti-Feature** | Different modality, out of scope |

### Complexity: MEDIUM-HIGH

- `Message.content: str` needs expansion. Use `content_blocks: list[ContentBlock] | None = None` to maintain backward compat.
- Provider adapters (Anthropic, OpenAI, Google) need format translation.
- File reading tools need binary content handling.
- Token estimation for images is provider-specific.

### Dependencies on Existing Features

- `domain_types.Message` -- content type expansion (CRITICAL).
- `runtime/thin/llm_client.py` -- message serialization for API calls.
- `runtime/thin/native_tools.py` -- native tool API format.
- `runtime/thin/llm_providers.py` -- provider-specific content block formatting.
- `tools/builtin.py` -- Read tool needs image/PDF handling.
- `context/budget.py` -- token estimation for non-text content.

---

## 6. MCP Resources

### How It Works (MCP Specification 2025-06-18)

**Protocol messages:**
- `resources/list` -- paginated list of available resources.
- `resources/read` -- retrieve resource content by URI.
- `resources/templates/list` -- list URI templates for dynamic resources.
- `resources/subscribe` -- subscribe to resource changes.
- `notifications/resources/updated` -- server notifies client of changes.
- `notifications/resources/list_changed` -- server notifies of list changes.

**Resource data model:**
- `uri`: unique identifier (RFC 3986 compliant).
- `name`: resource name.
- `title`: optional display name.
- `description`: optional description.
- `mimeType`: optional MIME type.
- `size`: optional size in bytes.

**Content types:**
- Text: `{ "text": "...", "mimeType": "..." }`
- Binary: `{ "blob": "<base64>", "mimeType": "..." }`

**URI schemes:**
- `file://` -- filesystem-like resources.
- `https://` -- web resources (client can fetch directly).
- `git://` -- version control resources.
- Custom schemes (e.g., `note://`, `config://`).

**Annotations:**
- `audience`: `["user"]`, `["assistant"]`, `["user", "assistant"]`.
- `priority`: 0.0-1.0 (importance for context inclusion).
- `lastModified`: ISO 8601 timestamp.

**Caching:**
- Subscription-based invalidation (not HTTP-style caching).
- Client reads resource, subscribes to changes, re-reads on notification.

**Error handling:**
- Resource not found: JSON-RPC error `-32002`.
- Internal errors: `-32603`.

**Capability declaration:**
```json
{ "capabilities": { "resources": { "subscribe": true, "listChanged": true } } }
```

### Classification

| Aspect | Category | Rationale |
|--------|----------|-----------|
| `resources/list` + `resources/read` | **Table Stakes** | Core MCP resource protocol |
| URI-based addressing | **Table Stakes** | MCP spec requirement |
| Text + binary content | **Table Stakes** | Resources are multimodal |
| Resource templates | **Differentiator** | Dynamic resource discovery |
| Subscriptions | **Differentiator** | Real-time resource updates |
| `listChanged` notifications | **Differentiator** | Dynamic resource discovery |
| Annotations (audience, priority) | **Differentiator** | Smart context inclusion |
| Implementing own resource server | **Anti-Feature** | Swarmline is a client, not a server |

### Complexity: MEDIUM

- MCP client already exists (`mcp_client.py`) for tools.
- Resources use same transport (HTTP/JSON-RPC).
- Need to extend MCP client with resource methods.
- Integration with context assembly (resources as context packs).
- Binary content handling ties into multimodal support.

### Dependencies on Existing Features

- `runtime/thin/mcp_client.py` -- extend with resource methods.
- `ContextPack` / `CodingContextAssembler` -- resources as context inputs.
- Multimodal (feature 5) -- binary resources need content block support.
- `RuntimeConfig.mcp_servers` -- resource-capable server discovery.

---

## 7. System Reminders

### How It Works in Claude Code

**Mechanism:** `<system-reminder>` XML tags injected into conversation messages (not system prompt). Treated as high-priority context that "OVERRIDE any default behavior."

**Placement:** Injected as user message content, not system prompt. This keeps the system prompt frozen for prompt caching.

**Trigger conditions:**
- CLAUDE.md: injected once at conversation start.
- Path-scoped rules: re-injected as system-reminders when Claude accesses files matching their `paths:` pattern.
- MCP server instructions: injected when server tools are first used.
- Security warnings: injected when suspicious file patterns detected.
- Hook results: injected based on tool use events.
- Conditional context: injected based on conversation state.

**Key design decisions:**
- Messages array, not system prompt (preserves prompt cache).
- Reactive, not periodic -- fires when conditions met.
- ~40 distinct system reminders in Claude Code v2.1.104.

**Budget allocation:** System reminders consume message tokens, not system prompt budget. They are subject to compaction (can be lost), except for rules that are re-triggered on file access.

### Classification

| Aspect | Category | Rationale |
|--------|----------|-----------|
| Conditional context injection based on events | **Table Stakes** | Agents need dynamic context without bloating system prompt |
| Injection into messages (not system prompt) | **Table Stakes** | Prompt cache preservation is critical for cost |
| Event-driven triggers (file access, tool use) | **Table Stakes** | Core mechanism for reactive context |
| Re-injection after compaction | **Table Stakes** | Reminders must survive context management |
| Integration with hooks (PreToolUse/PostToolUse) | **Table Stakes** | Hooks are natural trigger source |
| XML tag format for priority signaling | **Differentiator** | Claude-specific; other providers may not respect XML tags |
| 40+ hardcoded reminder types | **Anti-Feature** | Library should provide mechanism, not content |

### Complexity: LOW-MEDIUM

- Message injection is simple (prepend/append to user message).
- Trigger system maps to existing HookRegistry events.
- Budget tracking via ContextBudget.
- The mechanism is simple; the value is in the trigger logic.

### Dependencies on Existing Features

- `HookRegistry` / `HookDispatcher` -- trigger events.
- `domain_types.Message` -- injection point.
- `CodingContextAssembler` -- budget-aware injection.
- Project Instructions (feature 2) -- path-scoped rules trigger system reminders.
- Compaction (feature 1) -- reminders re-injected post-compaction.

---

## 8. Git Worktree Isolation

### How It Works in Claude Code

**Lifecycle:**
1. **Create:** `git worktree add .claude/worktrees/<name> -b <branch>` -- creates isolated checkout.
2. **Use:** Subagent's working directory set to worktree path. All file operations scoped there.
3. **Merge-back:** Human review of changes; standard git merge/cherry-pick.
4. **Cleanup:** Worktrees with no changes automatically cleaned up. Changed worktrees persist for review.

**Configuration:** Set `isolation: worktree` in subagent frontmatter YAML.

**Benefits:**
- True parallel execution -- subagents cannot see each other's in-progress edits.
- No file lock conflicts.
- Each subagent gets its own branch.
- Standard git merge for integration.

**Conflict handling:**
- Conflicts handled at merge time, not during execution.
- Each worktree is an independent checkout -- no mid-execution conflicts.
- If both main and subagent modify same file, conflict surfaces on merge.

**Claude Code specific:**
- `claude -w` flag for CLI worktree sessions.
- `/team-build` dispatches agents with automatic worktree isolation.
- Worktrees stored in `.claude/worktrees/` inside the repo.

### Classification

| Aspect | Category | Rationale |
|--------|----------|-----------|
| Create worktree for subagent | **Table Stakes** | Core isolation mechanism for parallel agents |
| Auto-cleanup on no changes | **Table Stakes** | Prevent worktree pollution |
| Branch per worktree | **Table Stakes** | Git best practice for worktrees |
| `isolation: worktree` config flag | **Table Stakes** | Simple opt-in mechanism |
| Automatic merge-back | **Anti-Feature** | Too risky for automated merge; human review required |
| Conflict detection before merge | **Differentiator** | Warn user about potential merge conflicts |
| Worktree lifecycle events (hooks) | **Differentiator** | Allow custom setup/teardown per worktree |

### Complexity: MEDIUM

- `git worktree add/remove` commands are straightforward.
- Must handle edge cases: dirty worktree cleanup, branch naming conflicts.
- Subagent CWD override is simple (already supported).
- No concurrent git operations on same repo (git handles this with locks).

### Dependencies on Existing Features

- `ThinSubagentOrchestrator` -- spawn subagents in worktree CWD.
- `SubagentConfig` -- new `isolation` field.
- Coding tools -- `bash`, `read`, `write` must use worktree paths.
- Process management -- cleanup on subagent termination.

---

## 9. Thinking Events

### How It Works (Anthropic Extended Thinking API)

**Enabling:**
```json
{ "thinking": { "type": "enabled", "budget_tokens": 10000 } }
```
Or adaptive (Opus 4.6+):
```json
{ "thinking": { "type": "adaptive" }, "effort": "medium" }
```

**Content block structure:**
```json
{
  "type": "thinking",
  "thinking": "Let me analyze this step by step...",
  "signature": "WaUjzkypQ2mUEVM36O2T..."
}
```

**Streaming events:**
- `content_block_start` with `content_block.type: "thinking"`.
- `content_block_delta` with `delta.type: "thinking_delta"` (thinking text).
- `content_block_delta` with `delta.type: "signature_delta"` (signature).
- `content_block_stop`.
- Then text blocks follow.

**Interleaved thinking (Opus 4.6+ / Claude 4 with beta header):**
- Thinking blocks appear between tool calls.
- `[thinking] -> [tool_use] -> [thinking] -> [tool_use] -> [thinking] -> [text]`.
- `budget_tokens` can exceed `max_tokens` in interleaved mode.

**Multi-turn rules:**
- Thinking blocks MUST be passed back unmodified in multi-turn conversations.
- Cannot toggle thinking mode mid-turn (within tool use loop).
- Only `tool_choice: "auto"` or `"none"` supported with thinking.

**Display options:**
- `"summarized"` (default) -- thinking text is a summary of reasoning.
- `"omitted"` -- thinking text is empty, but signature preserved for round-trip.

**Clearing thinking blocks (beta `context-management-2025-06-27`):**
- `clear_thinking_20251015` -- removes thinking from context to save tokens.

**Provider landscape:**
- Anthropic: native extended thinking API.
- OpenAI: "reasoning" in o1/o3 models (different API).
- Google: thinking in Gemini 2.5 (different API).
- Each provider has its own thinking block format.

### Classification

| Aspect | Category | Rationale |
|--------|----------|-----------|
| Separate thinking event type in RuntimeEvent | **Table Stakes** | UI needs to distinguish thinking from response |
| Stream thinking_delta events | **Table Stakes** | Users want to see reasoning as it happens |
| Preserve thinking blocks in multi-turn | **Table Stakes** | API requirement for correct behavior |
| Budget tokens configuration | **Table Stakes** | Cost control for thinking |
| Interleaved thinking | **Differentiator** | Advanced feature for complex multi-step reasoning |
| Thinking block clearing | **Differentiator** | Token optimization for long conversations |
| Provider-agnostic thinking abstraction | **Table Stakes** | Swarmline must work across providers |
| Display modes (summarized/omitted) | **Differentiator** | Flexibility for different use cases |

### Complexity: MEDIUM-HIGH

- New `RuntimeEvent` type: `"thinking_delta"` alongside `"assistant_delta"`.
- Provider adapters must translate thinking blocks to/from internal format.
- Multi-turn: thinking blocks in message history need preservation logic.
- Streaming: `stream_parser.py` needs thinking event handling.
- Interleaved mode changes tool call loop flow.
- Three different providers, three different thinking APIs.

### Dependencies on Existing Features

- `domain_types.RuntimeEvent` -- new event type `"thinking_delta"`.
- `domain_types.Message` -- thinking blocks in content (ties into multimodal).
- `runtime/thin/llm_providers.py` -- provider-specific thinking API.
- `runtime/thin/native_tools.py` -- thinking + tool_use interaction.
- `runtime/thin/stream_parser.py` -- parse thinking SSE events.
- `runtime/thin/llm_client.py` -- pass thinking config to API.
- `RuntimeConfig` -- new thinking configuration fields.

---

## 10. Background Agents

### How It Works in Claude Code

**Spawn pattern:**
- Background agents run asynchronously in their own context.
- Continue working even after main agent completes.
- Each gets optional worktree isolation.
- Configured via `background: true` in subagent frontmatter.

**Monitor Tool** (v2.1.98, April 2026):
- Built-in tool that runs background shell commands.
- Each line of stdout becomes a notification event.
- Main agent is "woken up" when output arrives.
- Event-driven (no polling): zero token cost during idle.
- Use cases: log tailing, dev server monitoring, PR status polling, file watching.

**Notification flow:**
1. Main agent spawns background agent/monitor.
2. Background process runs independently.
3. On stdout event (or task completion), notification pushed to main agent.
4. Main agent receives notification as a new message in its context.
5. Main agent can react, ignore, or stop the background process.

**Error handling:**
- Background agent errors captured and forwarded as notifications.
- Crashes are non-fatal to main agent.
- Timeout-based cleanup for hung background processes.

**Cancellation:**
- Main agent can stop background agents explicitly.
- Background agents can be stopped via `/agents` Running tab.
- Process termination on session end.

### Classification

| Aspect | Category | Rationale |
|--------|----------|-----------|
| Spawn background subagent | **Table Stakes** | Long-running tasks shouldn't block main conversation |
| Notification on completion | **Table Stakes** | Agent needs to know when background work finishes |
| Error forwarding from background | **Table Stakes** | Failures must be visible |
| Background process cancellation | **Table Stakes** | Control mechanism for runaway processes |
| Monitor tool (stdout streaming) | **Differentiator** | Event-driven architecture eliminates polling |
| Background color coding in UI | **Anti-Feature** | UI concern, not library responsibility |
| Continue after main agent exits | **Differentiator** | Useful for long-running builds/tests |
| Multiple concurrent background agents | **Differentiator** | Parallel monitoring of different streams |

### Complexity: HIGH

- Async process management (asyncio tasks/subprocess).
- Event notification system (callback or queue).
- Resource cleanup on cancellation/error/timeout.
- Interaction with existing `ThinSubagentOrchestrator`.
- Monitor tool: subprocess stdout streaming + event injection.
- Must not leak resources (processes, file handles, worktrees).

### Dependencies on Existing Features

- `ThinSubagentOrchestrator` -- extend with background mode.
- `SubagentConfig` -- new `background: bool` field.
- `RuntimeEvent` -- notification event type.
- Git Worktree (feature 8) -- isolation for background agents.
- `CancellationToken` -- extend for background cancellation.
- `EventBus` -- notification delivery mechanism.

---

## Feature Dependencies Graph

```
Multimodal Input (5)
     |
     v
MCP Resources (6) -----> needs binary content support from (5)
     |
Thinking Events (9) ---> needs multi-part Message.content from (5)

Conversation Compaction (1)
     |
     +---> Project Instructions (2) re-inject after compaction
     |
     +---> System Reminders (7) re-inject after compaction
     |
     +---> Session Resume (3) auto-compact on resume

Session Resume (3) -----> needs compaction (1) for over-budget history

Git Worktree (8) -------> needs subagent (existing) infrastructure
     |
     v
Background Agents (10) -> needs worktree (8) for isolation

Web Tools (4) ----------> independent, uses existing protocols

System Reminders (7) ---> needs Project Instructions (2) for path triggers
                    |---> needs Hook dispatch (existing)
```

## Consolidated Table Stakes / Differentiators / Anti-Features

### Table Stakes (Must Build)

| Feature | Aspect | Complexity |
|---------|--------|------------|
| Compaction | Auto-trigger + LLM summarization + re-inject instructions | MEDIUM-HIGH |
| Project Instructions | Walk-up discovery + concatenation + imports | MEDIUM |
| Session Resume | JSONL persistence + resume last + auto-compact | MEDIUM |
| Web Tools | WebSearch + WebFetch as builtin tools | LOW-MEDIUM |
| Multimodal | Multi-part Message content + image/PDF support | MEDIUM-HIGH |
| MCP Resources | list + read protocol | MEDIUM |
| System Reminders | Event-driven context injection into messages | LOW-MEDIUM |
| Worktree Isolation | Create/use/cleanup lifecycle | MEDIUM |
| Thinking Events | Separate event type + multi-turn preservation | MEDIUM-HIGH |
| Background Agents | Spawn + notify + cancel pattern | HIGH |

### Differentiators (Nice to Have)

| Feature | Aspect |
|---------|--------|
| Compaction | Custom summarization instructions, pause_after_compaction |
| Project Instructions | Path-scoped rules, AGENTS.md import, HTML comment stripping |
| Session Resume | Named sessions, fork session, session browsing |
| Web Tools | URL validation, citations |
| Multimodal | PDF input, Jupyter notebooks, auto-resize |
| MCP Resources | Subscriptions, templates, annotations |
| System Reminders | Provider-optimized XML tags |
| Worktree | Conflict detection, lifecycle hooks |
| Thinking | Interleaved thinking, block clearing, display modes |
| Background | Monitor tool, continue-after-exit, concurrent monitors |

### Anti-Features (Do NOT Build)

| What | Why |
|------|-----|
| Anthropic `compact_20260112` passthrough | Provider lock-in |
| Managed org-level instructions | Deployment concern, not library scope |
| File watcher hot reload | Over-engineering |
| Dynamic filtering for web fetch | Requires code execution sandbox |
| Anthropic server tools API usage | Provider lock-in |
| Video/audio multimodal | Out of scope |
| Automatic merge-back from worktrees | Too risky without human review |
| UI-specific features (colors, tabs) | Library, not application |
| 40 hardcoded reminder types | Library provides mechanism, not content |
| File snapshots for revert | Git exists |

## MVP Recommendation

### Phase 1 -- Foundation (low risk, high value):
1. **Project Instructions Loading** -- immediate DX improvement, medium complexity
2. **System Reminders** -- environmental awareness, low complexity
3. **Web Tools** -- pure wiring of existing infrastructure, low complexity
4. **MCP Resource Reading** -- extend existing MCP client, medium complexity

### Phase 2 -- Context Management:
5. **Conversation Compaction** -- critical for production use, medium-high complexity
6. **Session Resume** -- enables conversation continuity, medium complexity

### Phase 3 -- Multimodal + Thinking:
7. **Multimodal Input** -- foundational type change, medium-high complexity
8. **Thinking Events** -- provider-specific integration, medium-high complexity

### Phase 4 -- Advanced Orchestration:
9. **Git Worktree Isolation** -- subagent enhancement, medium complexity
10. **Background Agents + Monitor** -- most complex feature, high complexity

### Defer to v1.6.0:
- PDF parsing (pymupdf4llm optional dependency)
- Jupyter notebook parsing (nbformat optional dependency)
- MCP resource subscriptions (no user demand yet)
- Interleaved thinking (beta API, still evolving)
- Monitor tool (requires background agents to be stable first)

---

## Sources

### Official Documentation (HIGH confidence)
- [Compaction API](https://platform.claude.com/docs/en/build-with-claude/compaction)
- [Extended Thinking API](https://platform.claude.com/docs/en/docs/build-with-claude/extended-thinking)
- [Web Fetch Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool)
- [Web Search Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
- [MCP Resources Spec](https://modelcontextprotocol.io/specification/2025-06-18/server/resources)
- [Claude Code Memory](https://code.claude.com/docs/en/memory)
- [Claude Code Subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code How It Works](https://code.claude.com/docs/en/how-claude-code-works)
- [Claude Vision](https://platform.claude.com/docs/en/build-with-claude/vision)
- [Claude PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)

### Community / Analysis (MEDIUM confidence)
- [Claude Code System Prompts Repository](https://github.com/Piebald-AI/claude-code-system-prompts)
- [How Claude Code Builds a System Prompt](https://www.dbreunig.com/2026/04/04/how-claude-code-builds-a-system-prompt.html)
- [System Reminders Steering Pattern](https://michaellivs.com/blog/system-reminders-steering-agents/)
- [Claude Code Compaction Explained](https://okhlopkov.com/claude-code-compaction-explained/)
- [Claude Code Worktree Guide](https://claudefa.st/blog/guide/development/worktree-guide/)
- [Claude Code Monitor Tool](https://claudefa.st/blog/guide/mechanics/monitor)
