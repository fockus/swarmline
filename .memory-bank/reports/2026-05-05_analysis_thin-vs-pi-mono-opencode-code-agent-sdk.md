# Analysis: Thin Runtime vs pi-mono / opencode — Path to a Minimal Code Agent SDK

**Date**: 2026-05-05
**Type**: Competitive analysis + gap audit
**Scope**: ThinRuntime (`src/swarmline/runtime/thin/`) vs `badlogic/pi-mono` (44.6K stars) and `anomalyco/opencode` (fork of `sst/opencode`, ~155K stars)
**Goal**: identify what must be added to thin so a developer can use it as an SDK to build a minimal code agent.

> **Note**: User originally listed two more references ("а также с этим и с этим") but did not provide the URLs. This report covers only pi-mono and opencode. To extend, add referenced repos and re-run the audit.

---

## 1. ThinRuntime — current state

`src/swarmline/runtime/thin/` — ~5447 LOC, 25 files.

| Concern | File(s) | Status |
|---------|---------|--------|
| Loop / strategies | `runtime.py`, `react_strategy.py`, `planner_strategy.py`, `conversational.py`, `strategies.py` | Mature |
| LLM transport | `llm_client.py`, `llm_providers.py`, `native_tools.py`, `stream_parser.py` | Multi-provider (Anthropic / OpenAI-compat / Gemini / DeepSeek) |
| Tool execution | `executor.py`, `builtin_tools.py`, `coding_toolpack.py`, `mcp_client.py` | Has sandbox / web / thinking + coding toolpack + MCP |
| Sub-agents | `subagent_tool.py` | spawn_agent / monitor_agent |
| Configuration | `runtime.py::ThinRuntime.__init__` | **12 collaborators** — large surface |
| Hooks | external `swarmline.hooks.*` (PreToolUse / PostToolUse / Stop) | Wired via `HookRegistry` |
| Policy | external `swarmline.policy.*` (`DefaultToolPolicy`) | Default-deny |
| Workspace / commands / skills | external (`ExecutionWorkspace`, `CommandRegistry`, MCP skills) | Wired but mandatory in default flow |

**SDK ergonomics today**: requires user to know about `RuntimeConfig`, `HookRegistry`, `DefaultToolPolicy`, `ExecutionWorkspace`, `CommandRegistry`, `SwarmlineStack` bootstrap. No public single-line `CodeAgent(model, cwd).run(prompt)` facade.

---

## 2. pi-agent-core (badlogic/pi-mono) — TypeScript

Clean 3-tier monorepo:

| Layer | Package | Files |
|-------|---------|-------|
| Transport | `@mariozechner/pi-ai` | unified multi-provider LLM, `streamSimple`, `Message`, `EventStream` |
| Loop | `@mariozechner/pi-agent-core` | **5 files**: `agent.ts`, `agent-loop.ts`, `types.ts`, `proxy.ts`, `index.ts` |
| App | `pi-coding-agent` | session, skills, slash-commands, registry, system prompt, compaction, telemetry, output guard, bash-executor, edit/find/grep/ls/read/write + `file-mutation-queue` |

### Architectural decisions worth stealing

1. **`AgentMessage` ≠ LLM `Message`**. Loop holds enriched domain messages (incl. UI/notification roles). `convertToLlm: (AgentMessage[]) => Message[]` is the single seam to LLM. Lets SDK consumers add custom roles for UI without polluting the LLM contract.
2. **Mid-run control as callbacks** (all in `AgentLoopConfig`):
   - `shouldStopAfterTurn(ctx)` — graceful stop after a turn
   - `getSteeringMessages()` — inject inter-turn instructions
   - `getFollowUpMessages()` — queue follow-ups after `agent_end`
   - `transformContext(messages)` — pruning / compaction before `convertToLlm`
   - `getApiKey(provider)` — dynamic OAuth token per LLM call
3. **`beforeToolCall` / `afterToolCall` semantics**:
   - Before: `{block: true, reason}` to deny, otherwise pass-through
   - After: per-field overrides (`content` / `details` / `isError` / `terminate`)
   - Both receive `AbortSignal`
4. **`toolExecution: "sequential" | "parallel"`** — first-class config field
5. **`EventStream<AgentEvent, AgentMessage[]>`** — typed stream with explicit end token
6. **`file-mutation-queue.ts`** — atomic batched file mutations (anti-partial-write)
7. **`tool-definition-wrapper.ts`** — uniform per-tool schema + render + truncate plumbing

---

## 3. opencode (sst/opencode → anomalyco fork) — TypeScript

Server-first monorepo. SDK = OpenAPI-generated client. Runtime is an HTTP daemon.

### Notable modules in `packages/opencode/src/`

- `session/` — `compaction`, `processor`, `projectors`, `retry`, `revert`, `summary`, `todo`, `overflow`, prompt subdir
- `permission/` — runtime approval (`arity`, `evaluate`, `schema`)
- `lsp/` — full LSP client (`client`, `diagnostic`, `language`, `launch`)
- `snapshot/` — session-state snapshots for revert/undo
- `worktree/` — git-worktree-aware execution
- `skill/` — discovery
- `share/` + `sync/` — shared sessions
- `tool/`: `apply_patch`, `edit`, `glob`, `grep`, `lsp`, `mcp-exa`, `plan`, `question`, `read`, `shell`, `skill`, `task` (sub-agent), `todo`, `webfetch`, `websearch`, `write` — each with `.txt` prompt sidecar
- `plugin/`, `mcp/`, `bus/`, `acp/` (Agent Client Protocol)

### Capabilities thin lacks today

- `apply_patch` tool (structured diffs vs line-level edit)
- `todo` tool as first-class (Claude-Code pattern)
- Snapshot + revert
- LSP-as-tool (diagnostics / definitions)
- Approval flow separate from policy (async user prompt)
- HTTP-server + OpenAPI SDK (language-agnostic)
- Plugin entry-points
- Skills discovery directory
- Per-tool prompt sidecar
- Compaction as an explicit pipeline stage

---

## 4. Gap matrix — what thin needs for a Minimal Code Agent SDK

Target DX:

```python
from swarmline import CodeAgent

agent = CodeAgent(model="sonnet", cwd="/repo")
async for ev in agent.run("fix typo in README"):
    print(ev)
```

— this should work without instantiating `RuntimeConfig` / `HookRegistry` / `ExecutionWorkspace` manually.

### P0 — required for minimal SDK

| ID | Gap | Action |
|----|-----|--------|
| **A** | No public `CodeAgent` facade | New module `swarmline.code_agent` with `CodeAgent(model, cwd, tools=..., on_permission=...)`, `.run(prompt) -> AsyncIterator[Event]`, `.stream(...)`, `.close()` |
| **B** | `ThinRuntime.__init__` exposes 12 collaborators | Builder / `from_config()` factory; auto-construct sane defaults for `hook_registry`, `tool_policy`, `workspace`, `command_registry`, `subagent_config` when omitted |
| **C** | Coding-tool set incomplete | Audit `coding_toolpack.py` against canonical set: `read`, `write`, `edit`, `glob`, **`apply_patch`** (missing), **`todo`** (missing), `bash`, `grep` |
| **D** | No AgentMessage / convertToLlm seam | Introduce `AgentMessage` (user / assistant / tool_result + UI: notification / status), `convert_to_llm` callback. Strangler-Fig migration; old `Message` paths keep working |
| **E** | No async permission callback | `on_permission_request: (tool, args) -> Allow \| Deny(reason) \| AskUser(prompt)`. Separate from `DefaultToolPolicy` (declarative deny) |
| **F** | Mid-run control surface missing | Add to `RuntimeConfig`: `should_stop_after_turn`, `get_steering_messages`, `get_followup_messages`, `transform_context` |
| **G** | Tool execution mode implicit | `tool_execution: Literal["sequential","parallel"]` in `RuntimeConfig` |
| **H** | No CLI runner | `python -m swarmline.code_agent "<prompt>"` over the facade — needed for adoption + e2e smoke |

### P1 — strong differentiators

| ID | Item | Rationale |
|----|------|-----------|
| I | Atomic file-mutation queue | pi `file-mutation-queue.ts`: protect against partial writes between batched edits |
| J | Snapshot + revert | `agent.snapshot()` → rollback files + history. opencode `session/revert.ts` |
| K | Session persistence / resume | `agent.save(path)` / `CodeAgent.resume(path)` exposed from thin |
| L | Pluggable compaction strategy | `compaction_strategy: CompactionStrategy` in config |
| M | Per-tool prompt sidecar | Pattern from opencode (`read.txt` next to `read.ts`); customize prompts without forking |
| N | `AGENTS.md` loader | Auto-merge `cwd/AGENTS.md` into system prompt |
| O | Cost / budget guard as event | `BudgetExceededEvent` in stream; soft/hard limits in config (some pieces already in `cost.py`) |

### P2 — advanced parity (beyond "minimal")

| ID | Item |
|----|------|
| P | LSP-as-tool (diagnostics, definitions) |
| Q | Worktree-aware execution (`git worktree add` per task) |
| R | HTTP-server mode (`swarmline serve`) + OpenAPI spec → multi-language SDK |
| S | Plugin entry-points (`swarmline.tools` group) |
| T | Skills discovery directory (`~/.swarmline/skills/*.yaml`) |

---

## 5. Suggested first-pass plan (1–2 weeks)

If the goal is a v1.6.0 side-deliverable shipping the SDK:

1. **Spike** (1 day): prototype `CodeAgent` facade in `swarmline/code_agent.py`, wrap current `ThinRuntime` + `bootstrap.SwarmlineStack`. Find the Optional-defaults choke-points.
2. **P0-A,B,H** (2–3 days): facade + default stack assembly + CLI runner. Integration tests with fake-LLM, real read/write/edit on tmpdir.
3. **P0-C** (2 days): finish `apply_patch` + `todo` tools. Unit-test diff parser, integration on batched edits.
4. **P0-E** (1 day): `on_permission_request` API.
5. **P0-D, F, G** (3–4 days): AgentMessage + convertToLlm + mid-run hooks. Most invasive — message-model change. Strangler Fig: new type alongside, old code keeps working.
6. **Docs** + `examples/code_agent_quickstart.py`.

P1 / P2 — separate milestones once the facade lands.

---

## 6. References

- pi-mono: https://github.com/badlogic/pi-mono
  - `packages/agent` (5 files, agent-core)
  - `packages/coding-agent/src/core` (full coding-agent app)
- opencode: https://github.com/anomalyco/opencode (fork of `sst/opencode`)
  - `packages/opencode/src/{session,permission,lsp,snapshot,worktree,skill,tool,plugin}`
  - `packages/sdk/js` + `openapi.json` — server-first SDK pattern
- Related prior reports:
  - `reports/2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md`
  - `reports/2026-04-12_audit_thin-runtime-gaps.md`
