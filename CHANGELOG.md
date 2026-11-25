# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-11-25

### Changed (BREAKING)
- **`create_subagent_executor` default-denies instead of inheriting the parent toolset.**
  An absent `toolset_policy` used to mean "child inherits the parent's ENTIRE toolset" — a
  backward-compat carve-out that made the security property opt-IN: a host that forgot to wire a
  policy handed every LLM-spawned child everything the parent could do, which is the exact failure
  `ToolsetPolicy` exists to prevent. An absent policy is now an EMPTY allowlist. Both resolution
  branches (explicit `tools=[...]` and no `tools=` at all) resolve against the same set, so naming
  tools cannot buy what the policy does not grant — otherwise the default would be bypassable by
  typing names. The trusted programmatic path (`SubagentSpec.tools` set by host code passed to
  `orchestrator.spawn`) never routed through this executor and is unaffected.
  **Migration:** hosts relying on the old default must wire an explicit `ToolsetPolicy` naming the
  tools a spawned child may use.
- **`spawn_agent` rejects host-controlled arguments.** `timeout`, `timeout_seconds`, `routing`,
  `depth`, `current_depth` and `max_depth` in the tool call are now an explicit error. None is in
  `SUBAGENT_TOOL_SPEC` today, so a well-behaved model never sends one, but a schema that grows later
  must not let a model widen its own timeout or reset its own recursion budget. Rejecting loudly
  beats dropping silently: a silently ignored `timeout` looks to the model like a limit it raised.

### Security
- **Checkpoint state is redacted before it reaches durable storage** (`resilience/checkpoint.py`).
  `CheckpointWriter.after_tool_call` now runs `observability.redaction.redact_secrets` over every
  string leaf of the persisted payload. Tool output reaches a checkpoint through several state keys
  — offload projections, write-failure fallbacks that hold the WHOLE body, compression summaries,
  and small results still inline in `lm_messages` — so an API key a tool happened to echo used to
  outlive the run inside the host's database. The walk covers leaves rather than a list of known
  keys, so every state key added later is covered by construction. Only the persisted COPY is
  redacted: the live in-memory state keeps the real bytes, so the running agent still sees what its
  tool returned. Applies to every host store, since all four checkpoint write sites in the react
  loop funnel through this one method.

### Added
- **`CodeAgent` facade** with workspace tools, permission callbacks, resilience settings and persistent multi-turn sessions; the dedicated CLI remains planned.
- **Artifact storage and workspace tools**, native graph channel/command types, and provider-hosted tool contracts (provider execution support remains partial).
- **Image input in the current user turn** (taskloom Sprint 7i S1). `Agent.query()` and
  `Agent.stream()` accept `prompt_blocks: list[ContentBlock] | None = None`: with blocks, the
  CURRENT user message becomes `content_blocks=[TextBlock(prompt), *prompt_blocks]` (its `content`
  stays the plain prompt), so an `ImageBlock` reaches the provider as an image part (OpenAI
  `image_url` data URI, Anthropic `image`, Gemini `inline_data`) on every model round of that turn.
  History messages never carry blocks. Without the argument the runtime gets exactly the messages
  it got before. The `claude_sdk` runtime takes a text prompt only and drops blocks with a warning.
- **`ModelProfile.vision: bool = False`** and `vision: true` in `models.yaml` for models whose
  OpenRouter catalog entry lists `image` in `architecture.input_modalities` (Claude, `gpt-4o`,
  `gpt-4o-mini`, `o3`, Gemini 2.5, `deepseek/deepseek-v4.1-flash`, `moonshotai/kimi-k2.5`).
  A profile without the key is text-only; a non-bool value fails the registry load.
- **Image token estimate** (`context.budget.IMAGE_TOKEN_ESTIMATE = 1600`,
  `estimate_image_tokens`, `estimate_message_tokens`): compaction, per-round budgeting and the
  estimated usage fallback count an image part as 1600 tokens instead of ignoring it.
- **Point edits of a todo list: `apply_todo_ops`, `TodoEditProvider`, `todo_edit`** (`todo/ops.py`,
  `todo/protocols.py`, `todo/tools.py`). `apply_todo_ops(items, ops, *, now, new_id, max_todos)` applies
  an atomic batch of `add` (server-generated id, optional `after_id`) / `update` (status and/or text by
  id; `created_at` kept) / `remove` operations: the first invalid operation raises
  `TodoEditError(op_index, reason)` and nothing is applied. Several `in_progress` items are allowed
  (parallel work delegated to sub-agents is legitimate — taskloom AGR-086); pending work with nothing started returns
  `hint="mark the item you start next as in_progress"`. `TodoEditProvider` is a separate one-method
  protocol (`apply_edit(ops)`, ISP — `TodoProvider` is unchanged); `InMemoryTodoProvider` implements
  both. `create_todo_tools(provider, *, include_read=True, full_list_response=False)` registers
  `todo_edit` for an edit-capable provider; `full_list_response=True` answers `todo_write`/`todo_edit`
  with the whole list `[{id, content, status}]` plus `hint`. Tool descriptions and error messages are
  English now and say that several items may be `in_progress` when work runs in parallel. A store failure other than a validation error (`ValueError`, incl. `TodoEditError`) reaches the model as a generic "the todo list is unavailable right now; try again" and is logged in full — no SQL text or table names in the model's context.
- **`recitation_mode="replace_tail"`** (`runtime/thin/round_recitation.py`,
  `native_config["recitation_mode"]`). The live plan is recited before EVERY model round, round 1
  included (the cadence is ignored); the previous recitation turn is removed from the projection by
  object identity (no marker keys in the provider payload), so the projection holds exactly one, and
  it is the last message; the prefix before it is byte-identical between rounds. A blank plan removes
  the stale turn; a failed read keeps the last one. After a round compaction the fresh turn is the
  tail. The default `append` mode is byte-identical to before. Recitation logic moved out of
  `round_context.py` into `RecitationTail`; child runtimes drop `recitation_mode` with the other
  parent-run recitation keys.
- **Deterministic stop signals and a run time budget for the ReAct loop** (`runtime/thin/loop_guards.py`).
  Opt-in via `native_config["loop_guards_enabled"] = True`; absent (or any other value) keeps every
  request byte-identical (golden hash test). No progress: every tool call is fingerprinted as
  (tool, args, result) with volatile parts scrubbed (ISO timestamps, UUIDs, `duration`/`elapsed`/`pid`
  JSON fields); `StuckDetector`'s exact repeat of the latest call, or a post-compaction re-run of the
  calls made just before a per-round compaction, warns the model once with a tail user message
  (status `loop_guard.warned: <tool>`); the same kind of signal again soft-lands the run with
  `native_metadata["exit_reason"] == "no_progress"` (the two kinds count apart, so re-reading lost
  context after an earlier repeat warning only warns). The loop-limit soft landing is never cut by
  an exhausted time budget. An empty model reply is retried once with a
  nudge; a second in a row ends the run with a `bad_model_output` error `empty_model_response`
  instead of an empty completion. `native_config["run_budget_seconds"]` (> 0) counts from the start
  of this execution: a wrap-up notice is appended at the tail at 80% (the cached prefix is never
  rewritten), the run soft-lands with `exit_reason == "time_budget"` at 100%, and every model call
  (streamed chunks included) is capped by the remaining budget — never extended past its own timeout.
  Polling (the same call with a changing result) is progress. `_soft_landing_call` takes the exit
  reason and instruction (defaults unchanged). `ToolCallRecord` gains an optional `result_hash`
  (+ `repeat_key`, `compute_result_hash`) and `StuckDetector` a `detect_latest_repeat`; records
  without a hash behave exactly as before.
- **Tool results can reach the model as labelled data** (CE-24, new module
  `runtime/thin/tool_result_render.py`). `native_config["data_provenance_enabled"] = True` renders
  every tool result the ReAct loop hands back to the model — native path, text-ReAct path, and a
  `role="tool"` message in the initial projection or the per-round rebuild after compaction —
  through one `ToolResultRendering` (`render_tool_result(...)` underneath) as a
  `wrap_data(..., source="tool:<name>")` envelope, so a planted instruction reads as quoted data.
  Harness text stays OUTSIDE the envelope: the tool-result offload restore marker moves into the
  envelope `note` (the omitted middle shows as `[...]`), located by POSITION via the new
  `tool_result_offload.split_offload_projection`, so a look-alike marker inside the tool's own
  output stays quoted; results of tools listed in `native_config["data_provenance_harness_tools"]`
  (e.g. a host's yield-model `spawn_agent` receipt) render unlabelled. An offloaded transcript
  message carries `metadata["offload_key"]` so a rebuild renders it the same way. The envelope is
  applied after offload and after error detection (`tool_call_finished.ok`, the stuck detector
  and the event summary still read the raw result) and is deterministic, so the prompt-cache
  prefix stays append-only. Without the key the rendered bytes and the transcript are unchanged;
  an empty result keeps the plain label. `_messages_to_lm(messages, *, rendering=None)` is the
  additive keyword.
- **`wrap_data` escapes spaced and look-alike tags** (`context/data_envelope.py`): any `<`, `＜`
  (U+FF1C) or `﹤` (U+FE64), optional whitespace, optional `/`, optional whitespace, then `data`
  in any case gets its opener escaped to `&lt;` (was: only `<data` / `</data` exactly). `data`
  spelled in fullwidth letters is deliberately left as is — not a tag to a model or a parser.
- **Compaction and plan recitation before every model round of a ReAct run** (CE-9, new module
  `swarmline.runtime.thin.round_context`). `ThinRuntime.run()` used to compact and recite once,
  before the loop, so a long tool-calling run outgrew the window mid-way. `RoundContextRefresher`
  now runs before rounds 2..N: when the request budget exceeds the compaction threshold it
  compacts the STRUCTURED view of the run (`messages` + `new_messages`, tool call/result units kept
  atomic) with the SAME `ConversationCompactionFilter` the startup step used (shared anti-thrashing
  history, persisted through the existing checkpoint key) down to
  `threshold - round_hysteresis_tokens` (never below half the threshold), and rebuilds the LM
  projection from it. Between compactions the projection is append-only, so the provider's
  prompt-cache prefix holds; the host transcript (`new_messages`) is never modified. Every
  `recitation_round_cadence` rounds a LIVE plan provider (`native_config["recitation_plan_provider"]`,
  `async () -> str`, 2 s timeout; errors and timeouts skip the round with a warning) is appended as
  a `<plan-recitation>` meta turn and re-appended after a rebuild; a static `recitation_plan_text` is
  never recited mid-run. Round compaction is disabled for the run, with a status event, when the
  projection cannot be rebuilt losslessly: a run resumed from an lm-only checkpoint, or
  `get_steering_messages` / `get_followup_messages` / `transform_context` / `recovery_cascade` /
  an auto-verify loop configured. Each round compaction logs `compaction.round` with `round`,
  `tokens_before`, `tokens_after` and `tier`. Opt-in: `CompactionConfig.per_round` (default
  `False`) and `round_hysteresis_tokens` (default 8 000), read by `build_portable_runtime_plan`
  from `native_config["compaction_per_round"]` / `["compaction_round_hysteresis_tokens"]`;
  `KernelContext.round_refresher` (default `None`) reaches `run_react(round_refresher=...)` only
  when set. Without the keys the requests are byte-identical (golden-pinned).
  `ConversationCompactionFilter.filter` takes an optional `target_tokens` and exposes `last_tier`.
- **`native_config["max_tool_calls"]` sets the run's tool-call budget** (`build_portable_runtime_plan`;
  positive int, floats truncated, anything else keeps the default of 8). Hosts size it to their
  turn budget: the fixed default ended long runs on their 9th tool call.
- **Usage of every native tool call, budget anchored on it** (ref: hermes). `NativeToolCallResult`
  gains `usage` (input/output/total, `cache_read_tokens`/`cache_write_tokens` when reported, and
  `prompt_tokens` — the full request as the provider counted it, tool schemas included; Anthropic's
  prompt is input + cache read + cache write), filled by the Anthropic, OpenAI-compatible and Gemini
  adapters. The per-round budget is that `prompt_tokens` plus an estimate of what was appended
  since, falling back to the plain estimate when no usage is known or after a rebuild.
- **Compaction summary acceptance gate + verbatim user request** (`swarmline.compaction_gate` and
  `swarmline.compaction_turns`, new modules). A Tier-2 summary is embedded only when
  `SummaryAcceptanceGate.check` passes: all seven fixed sections present — a label counts only at a
  line start (optional markdown `**`/`#`/`-` decoration), first occurrence, so `Errors:` in the
  middle of a `Next Steps:` line is content — with `Next Steps:` last and non-empty (the truncation proxy — `llm_call`
  returns bare text, no `finish_reason`), the LLM part at most 16 000 chars, the rendered summary
  shorter than the region it replaces, and a savings ratio of at least `MIN_SAVINGS_RATIO` (0.10).
  The summary now opens with `User Request (verbatim):` — the latest human turn of the compacted
  region (recitation and `<system-reminder>` turns excluded), copied by code, never by the LLM
  (`none` when the region has no human turn), capped at `verbatim_budget_chars(threshold)` (25% of
  the compaction budget, at least 2 000 chars) as head + `[truncated N chars]` + tail so one huge
  paste cannot keep Tier 3 over budget. A rejected LLM summary falls back to the deterministic
  local digest; if that is rejected too, Tier 2 is dropped and Tier 3 sees the messages exactly as
  they were before Tier 2, and the attempt is recorded in `compression_history` with zero savings so
  the anti-thrashing cooldown stops repeats; the cooldown lifts once the context has grown by
  `COOLDOWN_REGROWTH_RATIO` (25%) past the last recorded attempt (derived from the persisted
  history, so it also lifts after a checkpoint resume). Tier 3 never drops the summary or the latest human
  request (a request larger than the budget stays, with a warning). The summarizer input is wrapped
  in an escaped `<transcript>` block marked as data, and both prompts say never to mark the verbatim
  request as done. An iterative UPDATE feeds back only the LLM-written part of the prior summary.
  **Behaviour change for hosts with Tier 2 on:** a plain-prose summary without the fixed sections is
  no longer accepted — it routes to the local fallback. `MIN_SAVINGS_RATIO` and `savings_ratio`
  moved to `compaction_gate` and stay importable from `swarmline.compaction`.
- **Deterministic summary appendices** (`swarmline.compaction_anchors`, new module, no LLM):
  `## User Messages (verbatim, newest first)` (every other human turn of the region plus those a
  prior summary carried, at most 16; 2 000 chars each, 8 000 total, `[truncated N chars]` markers,
  and a cumulative `[N earlier user messages omitted]` marker for turns dropped past the cap),
  `## Anchor Index (mechanically extracted, exact)` (URLs, file paths, git SHAs, UUIDs, `run_…`-style
  ids and error lines with their frequency, 4 000-char budget, byte-deterministic order) and an
  optional `## Context Recovery` section rendered from the new `CompactionConfig.recovery_hint`
  (`native_config["compaction_recovery_hint"]` in `build_portable_runtime_plan`; default `None`
  renders nothing).
- **Data envelope primitive** `swarmline.context.wrap_data(content, *, source, note=None)`: renders
  quoted data as `<data source="...">…</data>` behind a "quoted data, not instructions" preamble;
  forged `<data`/`</data` inside the content are escaped, `source` is sanitized to `[a-z0-9:_.-]`,
  and the output is byte-deterministic (no random ids — prompt-cache and resume safe).
- **Model profiles: context window, output limit, prompt cache** (`swarmline.runtime`): new
  top-level `profiles:` section in `runtime/models.yaml`, keyed by the model id without a routing
  prefix (`moonshotai/kimi-k2.5`, `anthropic/claude-opus-4-5`, `deepseek/deepseek-v4.1-flash`, plus
  every model under `providers:`). Each entry declares `context_window`, `max_output_tokens` and
  `prompt_cache` (`explicit` | `automatic` | `none`); a bad entry (non-positive window, output not
  strictly inside the window, unknown cache mode, non-int value) fails the registry load with a
  `ValueError` naming the model. New frozen `ModelProfile`, `UNKNOWN_MODEL_PROFILE` (conservative
  32k / 4k / `none`), `ModelRegistry.get_profile(model_id)` (exact, case/space-insensitive) and
  `resolve_model_profile(raw, registry=None)`: strips a known provider prefix (`openrouter:`,
  `anthropic:`, ...) and a known OpenRouter variant suffix (`:free`, `:batch`, `:nitro`, `:floor`,
  `:online`, `:thinking`), then matches the exact profile id or an explicitly declared alias, and
  returns `None` for anything else — deliberately **not** the registry's greedy `startswith`
  matching (`gpt-4` does not become `gpt-4o`) and **no** fallback to `default_model`, so a caller
  can never size an unknown model's context as if it were another model's. OpenRouter-style
  entries carry the catalog's `top_provider` limits (e.g. `deepseek/deepseek-v4.1-flash`
  1040000 / 384000, `moonshotai/kimi-k2.5` 262144 / 235929); `anthropic/claude-opus-4.5` and
  `anthropic/claude-opus-4-5` share one profile via a YAML anchor. The section lives apart from
  `providers:`, so `get_provider`, `resolve_provider`, `get_model_extras`, `list_providers` and
  `valid_models` are unchanged. `provider_resolver._parse_prefix` is now public as
  `parse_provider_prefix` (same behaviour; reused instead of copied).
- **Kanban CAS-safe dispatch + notes journal** (`swarmline.kanban`): new `KanbanDispatch` protocol (`try_claim`/`release_claim`/`list_claimable`, ISP: 3
  methods) closes the deferral left by `KanbanAssignment.claim_task`, which unconditionally
  overwrites a claim. `try_claim(task_id, assignee, *, lease_id, stale_before)` claims a card only
  if it currently has no lease, or its `last_heartbeat_at` is older than `stale_before`, stamping
  `assignee`/`claimed_at`/`last_heartbeat_at`/`metadata["lease_id"]`/`metadata["dispatched"]=True`
  on success and returning `None` on a held, live card. `release_claim(task_id, *, lease_id)`
  clears `metadata["lease_id"]` only when it matches the caller's `lease_id` — a foreign or absent
  lease is a no-op returning the card unchanged; `assignee`/`claimed_at`/`dispatched` are left as
  history. `list_claimable(*, statuses, stale_before, limit, include_fresh_claims=False)` returns
  only leaf cards (no child links) in the requested statuses that are free or stale, ordered by
  creation time; passing `include_fresh_claims=True` additionally returns leaf cards held under a
  live (non-stale) lease, for callers that need to reconcile against a lease-holder's liveness —
  this read grants no ownership and mutates nothing. A new
  `KanbanNotes` protocol (`append_note`, ISP: 1 method) appends a typed `KanbanNote`
  (`kind`/`text`/`at`/`run_id`/`outcome`) to `metadata["notes"]` under a FIFO cap that keeps the
  newest entries — no schema migration, since the `metadata` column already exists on both
  reference adapters. Both `InMemoryKanbanStore` and `SqliteKanbanStore` implement both protocols;
  the SQLite adapter's `try_claim` is CAS-safe via a single `UPDATE ... WHERE` (re-checking the
  free-or-stale condition against the current row's JSON `metadata` at write time) plus
  `cursor.rowcount`, with the dispatch/notes SQL split into a new sibling module
  (`kanban/sqlite_dispatch.py`) to keep `sqlite.py` from growing past the SRP line-count
  guideline. `KanbanAssignment.claim_task` is unchanged (still unconditional, back-compat).
- **Worker briefing renderer + `kanban_note` tool** (`swarmline.kanban.briefing`):
  `render_worker_context(card, *, parents, done_children_results, notes,
  artifact_refs, caps=BriefingCaps())` is a pure, stdlib-only function (no I/O, no wall clock) that
  renders one deterministic markdown document for a worker picking up a card — a kanban dispatcher
  run, a spawn child, or an in-run subagent — instead of it having to re-read a transcript to get
  oriented. Sections render in a fixed order: title+id, body, parent goal, prior attempts (the most
  recent `caps.max_full_attempts` shown in full, older ones collapsed to one line each), results of
  done child cards, progress notes, artifact/file references, and a completion instruction pointing
  at `kanban_complete`/`kanban_note`. Any section with no content is omitted rather than rendered as
  an empty heading. `BriefingCaps` holds every size cap in one dataclass (`body_bytes=8192`,
  `field_bytes=2048`, `max_notes=10`, `max_full_attempts=3`, `total_bytes=16384` by default) so a
  pathological card (huge title/body, many notes/attempts/parents/children/artifacts) still
  produces a bounded document: the header's byte cost (only `card.title` is ever truncated,
  hard to `""` if needed — `card.id` itself is not) and the completion instruction are reserved
  first and survive whenever `total_bytes` holds both (about 215 bytes for a short id; smaller is
  a degenerate config, not specially guarded beyond not crashing), the remaining sections fill
  whatever budget is left in canonical order, and the first one that no longer fits is truncated
  instead of the whole document being blindly cut from the front. Truncation always lands on a UTF-8 character
  boundary — never splitting a multi-byte character — and appends a `…[truncated N chars]` marker
  where N is the number of characters (not bytes) dropped. A new opt-in `kanban_note(task_id, text)` tool
  (`create_kanban_note_tools`, `kanban/tools.py`) appends a `"progress"`-kind `KanbanNote` through
  `KanbanNotes.append_note`, sharing `BriefingCaps.max_notes` as its FIFO cap; the factory withholds
  the tool entirely (returns two empty dicts) when the injected store does not implement
  `KanbanNotes`, so an agent's toolset never advertises a tool call that would fail.
- **Loop-limit soft landing** (`runtime/thin/react_strategy.py`, open-beta-hermes-saas Sprint 1a
  Stage 2): opt-in via `RuntimeConfig.native_config["loop_limit_soft_landing"]` (default absent/
  `False` — byte-identical to before). When the iteration budget is exhausted with the flag on, the
  loop makes exactly ONE additional LLM call with no tool schemas (raw `system_prompt`, never the
  react-built prompt or the native tool-calling adapter), asking the model to summarize what it
  accomplished, what remains, and the next concrete step. The reply becomes a normal `final` event
  carrying `native_metadata={"exit_reason": "loop_limit"}` instead of the `loop_limit` error, with
  usage/metrics accounted for through the same `_build_usage`/`_build_metrics` path every other turn
  uses. Any failure or cancellation of that one extra call falls back to the pre-existing
  `RuntimeEvent.error(kind="loop_limit")` — no summary is ever fabricated from a partial/failed call.
- **Kanban assignment + liveness** (`swarmline.kanban`): `KanbanTask` gained optional `assignee` /
  `claimed_at` / `last_heartbeat_at` fields (default `None`, backward compatible) and a new
  `KanbanAssignment` protocol (`claim_task`/`heartbeat`, ISP: 2 methods) implemented by both
  `InMemoryKanbanStore` and `SqliteKanbanStore`. A new, SEPARATE `create_kanban_liveness_tools`
  factory exposes `kanban_claim`/`kanban_heartbeat` as opt-in model tools — deliberately not merged
  into `create_kanban_tools` (which stays frozen at exactly six tools; a downstream dispatch-only
  toolset derives its own frozen tool-count contract from that factory's output). Mirrors hermes'
  `kanban_claim`/`kanban_heartbeat` semantics: claiming/heartbeating a card is orthogonal to its
  lifecycle `status`. The `_task_to_dict` tool-response serializer OMITS `assignee`/`claimed_at`/
  `last_heartbeat_at` entirely (not `null`) for a never-claimed task, so the six pre-existing tools'
  JSON response shape stays byte-identical to before this fields existed.
- **Kanban retitle** (`swarmline.kanban`): new `KanbanRetitle` protocol (`update_title`, ISP: 1
  method) implemented by both reference adapters — replaces a card's `title` without touching
  `status`, for hosts that mirror external state (e.g. a todo item's changed text) onto a card.
- **Compaction cascade "cheap -> expensive" (`swarmline.compaction`, context-engineering-manus-parity
  Stage 6)**: Tier 0 (Ступень A, no-LLM) hash-dedup of tool results >= 200 chars
  (`DUPLICATE_TOOL_OUTPUT_MARKER`) + templated one-liners for tools declared
  `CompactionConfig.compactable_tool_names` (reproducible/re-callable — Claude Code
  `COMPACTABLE_TOOLS` pattern), always attempted first inside `ConversationCompactionFilter.filter()`
  before the existing Tier 1/2/3 cascade. Tier 2 (LLM summarization) now produces a structured
  fixed-section digest (Ступень C: Goal / Constraints / Progress / Key Decisions+why / Errors
  verbatim / Files / Next Steps) with an iterative UPDATE prompt (`<previous-summary>`,
  PRESERVE/ADD/UPDATE) when an earlier summary ages back into the compaction region. Safe-fail:
  `SummarizerAbortError` (+ stdlib `TimeoutError`/`ConnectionError`/`OSError`) ABORTS the whole
  compaction pass (history left untouched, exception propagates) instead of falling back; any
  other summarizer failure gets a deterministic, non-LLM local fallback summary (same fixed
  sections) instead of jumping straight to Tier 3. Anti-thrashing cooldown (`ANTI_THRASHING_WINDOW=2`,
  `MIN_SAVINGS_RATIO=0.10`) — an in-run analog of taskloom's `conversation_distiller.py`
  `compression_history` algorithm (ported, not imported — zero taskloom coupling; different layer,
  ephemeral in-run messages vs. persisted cross-run conversation history) — skips the LLM call (not
  the cheap tiers or the Tier 3 safety net) when the last 2 Tier-2 attempts each saved under 10%;
  tracked via a caller-owned `compression_history` constructor param + read-only property for
  checkpoint persistence. `CompactionConfig.effective_threshold_tokens` (`effective = window -
  max_output_reserve`, floored at `MIN_EFFECTIVE_THRESHOLD_TOKENS`) is opt-in via
  `context_window_tokens` (`None` default preserves every existing caller's behaviour
  byte-identically) — regression-tested against the "16k-model perpetual emergency-compaction"
  pitfall. Cut-point integrity (tool_use/tool_result pairs are ATOMIC across every tier, including
  under partial/inconsistent `non_compactable` tagging and tier-boundary slicing) is covered by a
  seeded-`random` property test over synthetic histories (no new `hypothesis` dependency). Wired
  into `agent/runtime_wiring.py` (Ступень B) via `native_config["compaction_enabled"]` +
  `compaction_threshold_tokens`/`compaction_context_window_tokens`/
  `compaction_max_output_reserve_tokens`/`compaction_preserve_recent_pairs`/
  `compaction_compactable_tool_names` — absent/falsy is a hard no-op (`RuntimeConfig.compaction`
  stays `None`), closing the same composition-root wiring-gap shape flagged as BL-77 for Stage 4's
  tool-result offload.
- **Prompt caching (`swarmline.context.prompt_caching`)**: Anthropic `cache_control`
  breakpoint placement — Hermes `system_and_3` recipe. `build_cached_system()` splits a flat
  system prompt on a literal boundary marker (when present) into a CACHED static block +
  an UNCACHED dynamic block — a host with no static/dynamic split gets the whole prompt
  cached as one block (fallback). `mark_last_message_breakpoints()` marks the last up-to-3
  ELIGIBLE (non-system, cacheable-last-block) messages, stripping any pre-existing
  `cache_control` first so the total never exceeds Anthropic's 4-breakpoint ceiling; every
  block is deep-copied (no aliasing with caller-owned nested structures, e.g. image
  `source`). TTL is configurable per call (`"5m"` default — no `ttl` key, Anthropic's own
  default; `"1h"` — explicit `ttl` key). Wired into `AnthropicAdapter.call()`/`.stream()`
  (`runtime/thin/llm_providers.py`) behind `_prompt_caching_enabled`/`_prompt_caching_ttl`
  kwargs — absent/`False` keeps the request payload byte-identical to before; any error
  building the decoration fails OPEN (falls back to the uncached request, never breaks the
  underlying LLM call). `default_llm_call` (`runtime/thin/llm_client.py`) threads both from
  `RuntimeConfig.native_config["prompt_caching_enabled"/"prompt_caching_ttl"]`,
  Anthropic-only (hard no-op for every other provider). Every completed Anthropic call
  (`call()`/`.stream()`/`.call_with_tools()`) logs `cache_read_input_tokens`/
  `cache_creation_input_tokens` (normalized to 0 when absent) from the real provider usage
  block (KV cache hit-rate is Manus's context-engineering metric #1).
- **`FileScratchpadProvider`** (`swarmline.scratchpad`): durable, dependency-free scratchpad backed
  by one JSON file per `base_dir`. Entries survive process restarts, so an agent resuming after a
  redeploy still sees its own working notes. Model-supplied keys never touch the filesystem (single
  store file), so path traversal is structurally impossible; a corrupt store — or an individual
  unreadable entry — is quarantined aside rather than silently overwritten by the next write.
- **`NamespacedScratchpadProvider`** (`swarmline.scratchpad`): decorator that scopes a SHARED
  scratchpad provider to an opaque namespace — prefixes entry keys, and filters
  `read(None)`/`search`/`delete` back to that prefix. For hosts that build one provider per process
  but serve multiple tenants/sessions: without it, model-supplied keys collide across callers.
  Knows nothing about any particular identity model.
- **`OpenVikingScratchpadProvider.with_namespace(uri)`**: returns a provider over a different
  namespace, reusing the same client. Rebinding (rather than only prefixing keys) also scopes
  `search`, which passes the namespace as `target_uri`.

- **Temporal durable runtime (experimental)** (`swarmline[temporal]`, `runtime="temporal"`): the agent
  loop runs as a deterministic Temporal workflow; every LLM/tool call is an activity on a worker
  fleet with per-activity timeouts and retry policies. A run survives worker crashes/deploys and
  resumes from the last completed step. Buffered mode needs no extra infra; streaming mode relays
  RuntimeEvents live through a shared EventBus (Redis/NATS) with deterministic-id dedup. Tools,
  MCP servers, and LLM credentials live on workers (`swarmline.runtime.temporal.worker`); the
  client facade implements the standard `AgentRuntime` protocol. Implements phases 1–2 of
  `docs/proposals/temporal-runtime.md`.
- **Temporal runtime phase 3 — durable HITL, reattach, worker CLI**:
  - *Durable approvals*: workers can run with an `ApprovalPolicy` — a gated tool call does not
    execute; the workflow parks on a Temporal signal (surviving deploys/restarts) with a durable
    expiry timer (`approval_timeout_seconds`, default 24h, auto-deny). `TemporalApprovalClient`
    resolves requests from any process (`approve`/`deny`/`pending` by `run_id` + `correlation_id`);
    approvals can modify tool args; denials/expiries become failed tool results the model reacts
    to — never run failures. New `approval_requested`/`approval_resolved` events; pending requests
    are inspectable via a workflow query. `supports_hitl=True`.
  - *Reattach*: `TemporalAgentRuntime.attach(run_id)` re-joins a running (or finished) run from
    any process and yields events like `run()`. `supports_resume=True`.
  - *Worker CLI*: `swarmline temporal-worker` bootstraps a worker (`--task-queue`,
    `--tools module:attr`, `--event-bus redis://…|nats://…`, `--require-approval <tool>`
    repeatable, `--api-key-env` for Temporal Cloud).
- **Temporal runtime phase 4 — scale hardening**:
  - *Reference-based history* (`use_reference_history=True`): the conversation lives in a
    worker-side `HistoryStore` (`MessageStoreHistoryAdapter` bridges Postgres/SQLite
    `MessageStore`s; `InMemoryHistoryStore` for tests); workflow payloads carry revision
    numbers instead of the growing message list; per-turn deltas append through an idempotent
    activity (retry-safe via expected-revision guard).
  - *Continue-as-new* (`continue_as_new_after_iterations`): long runs roll workflow history
    over per N-iteration segments — same run id, reattach/signals/queries keep working,
    `max_iterations`/`max_tool_calls` stay global across segments.
  - *Compaction at materialization*: worker-side `CompactionConfig` collapses old tool pairs
    and drops oldest messages when referenced history crosses the token threshold; the store
    is never rewritten. CLI: `--history-store module:attr`, `--compaction-threshold N`.
  - *Redaction PayloadCodec* (`redact_payloads`, **on by default**): secret patterns
    (Bearer/sk-*/userinfo/KEY=value) are scrubbed from every JSON payload before it reaches
    server-side Temporal history; decode is passthrough so mixed deployments degrade safely.
  - *OpenTelemetry interceptor* (`otel_interceptor=True`): temporalio `TracingInterceptor` on
    the connection — client → workflow → activity spans join one trace.
  - *Eval trace export* (`runtime.temporal.eval_export`): fetch completed run results from
    Temporal and score them with `eval` module scorers offline (`run_to_eval_result`,
    `score_run_results`) — production runs, no re-execution.
- **Langfuse integration** (`swarmline[langfuse]`): `LangfuseExporter` bridges EventBus events to
  Langfuse — LLM calls as generations (model, token usage, latency, errors), tool calls as spans,
  optional session grouping. Duck-typed client injection for tests / client sharing.
- **LangSmith integration** (`swarmline[langsmith]`): `LangSmithExporter` bridges EventBus events to
  LangSmith runs (`llm` / `tool` run types) with inputs/outputs, timing, error status, and project
  targeting.
- **Enriched LLM call events**: `llm_call_start`/`llm_call_end` now carry a per-call
  `correlation_id` (concurrent calls pair correctly in every exporter — previously OTelExporter
  fell back to guessing), `duration_ms`, and `error_message` (redacted) on failure.
- **Opt-in LLM content capture**: `RuntimeConfig(extra={"capture_llm_content": True})` adds
  redacted, truncated prompts (`messages`) and completions (`response`) to LLM call events for
  observability platforms. Off by default (default-secure).

### Changed

- **BREAKING — scratchpad writes must be confirmed.** `OpenVikingAgfsClient.write` (the Protocol
  `OpenVikingScratchpadProvider` delegates to) changed from `-> None` to `-> bool`, and
  `OpenVikingScratchpadProvider.write` now raises the new `ScratchpadWriteError` unless the client
  returns `True`.

  *Why:* the provider previously constructed and returned a `ScratchpadEntry` unconditionally, so a
  rejected AGFS write still looked like a stored note. The `scratch_write` tool reported
  `status: ok` to the model for data that did not exist, and the next `scratch_read` came back
  empty — an agent planning around memory it was told it had is worse off than one with no
  scratchpad at all. `create_scratchpad_tools`' write executor now returns
  `{"status": "error", "key": ..., "stored": false, "error": ...}` instead of a false success.

  *Migration for third-party `OpenVikingAgfsClient` implementations:* return `True` at the end of
  `write` when the entry was stored, and `False` (or raise) when it was not. Anything other than
  `True` — including the `None` that the old `-> None` annotation implied — is now treated as an
  unconfirmed write and fails closed, deliberately: silently accepting `None` would reinstate the
  bug for exactly the implementations most likely to still have it.

  *No migration needed* for `InMemoryScratchpadProvider` or `FileScratchpadProvider` — neither goes
  through this Protocol.

- **New export:** `ScratchpadWriteError` from `swarmline.scratchpad`.

- **`orchestration/plan_tools.py` descriptions translated to English.** `plan_create`/`plan_status`
  `ToolSpec.description`, their JSON-schema property descriptions, and the `plan_create` "goal is
  required" error message were Russian; translated to English (non-breaking — behavior, field
  names, and schema shape are unchanged). `plan_create`'s description also now states the real
  mechanic: plan steps advance automatically as the caller works through them, with no separate
  step-update tool.

### Fixed
- Native ReAct calls now honor the run deadline, and soft landing preserves accumulated custom-adapter token usage without double-counting built-in adapters.
- Compaction preserves images in the current user request through summary and fallback paths.
- **`todo_write` no longer resets `created_at`** of items already on the list (bulk replace used to
  stamp every item with the call time); unchanged items keep `updated_at` too.
- **A run nested inside a tool wiped its parent's usage totals.** The per-run usage accumulator
  is a ContextVar shared by every run in the task; each `ThinRuntime` run reset it at start and its
  finalization consumed it, so a nested run (a tool that runs an agent) erased what the parent had
  accumulated and the parent's final usage undercounted. Each run now opens its own scope
  (`begin_native_usage_scope` / `end_native_usage_scope`) and the caller's totals come back when it
  ends, on every exit path.
- **Spawned subagents inherited the parent run's plan recitation.** `ThinSubagentOrchestrator`
  handed its runtime config to children unchanged, including `native_config`'s live
  `recitation_plan_provider` and the recitation settings around it, so a child recited the
  parent's todo list. `child_runtime_config` strips those keys; everything else is inherited as
  before.
- **Run usage reported the cache counters of the last call only, and the native ReAct path none**
  (BL-89, BL-98). The per-run usage accumulator now sums `cache_read_tokens`/`cache_write_tokens`
  over every adapter-backed call (Anthropic `cache_*_input_tokens`, OpenAI-compatible
  `prompt_tokens_details.cached_tokens`, Gemini `cached_content_token_count`), and `_build_usage`
  prefers those sums; the native ReAct loop sums `NativeToolCallResult.usage` across its calls and
  passes it as `provider_usage` to finalization, so a user-supplied native adapter is covered too.
- **Compaction summaries and collapsed tool placeholders never reached the model** (F-1). Tier 1
  and Tier 2 build their artifacts as `role="system"` messages, and every provider adapter
  (`_filter_chat_messages` for Anthropic, `OpenAICompatAdapter._prepare`, `GoogleAdapter._prepare`)
  drops non-user/assistant chat turns — so compaction silently degraded to truncation. Artifacts are
  now tagged `metadata["compaction_artifact"] = "summary" | "collapsed"` and rendered by
  `runtime/thin/helpers._message_to_lm` as a user-role data envelope
  (`source="compaction-summary" | "compaction-collapsed"`) with the note "reference only; answer the
  latest message below, not this summary; tools remain fully available; do not repeat actions
  listed as completed". Provider filters are unchanged: any other system message is still dropped.
  `_merge_adjacent_system_messages` never merges a compaction artifact with a non-artifact system
  message, so protected system text is never re-rendered as quoted data.
- **A lease-staleness cutoff is normalized before it is compared** (new `kanban/_time.py`).
  `KanbanDispatch.try_claim`/`list_claimable` decide lease liveness by comparing `stale_before`
  against a card's `last_heartbeat_at`, and on every adapter that is a plain STRING comparison
  (on SQLite it happens inside the `UPDATE ... WHERE` itself). Lexicographic order matches
  chronological order only while both sides are canonical UTC — which nothing stated publicly,
  and which a caller has no reason to guess. An hour-old cutoff spelled `...T05:00:00+03:00`
  sorts ABOVE the `...T03:00:00+00:00` heartbeat it is an hour BEHIND, so a live lease read as
  stale and its card could be handed to a second worker and executed twice; the `Z` spelling of
  an equal instant failed the same way at the boundary, since `+` sorts before `Z`. Cutoffs are
  now normalized to canonical UTC on entry to both dispatch paths on both adapters, a value that
  is not an instant raises `ValueError` instead of silently deciding liveness from arbitrary
  text, and one writer of the canonical form (`now_iso`) replaces four copies of
  `datetime.now(UTC).isoformat()`. The format contract is stated on the `KanbanDispatch`
  protocol itself, so the next adapter inherits it.

## [1.7.0] - 2026-06-23

### Added
- **Coding-agent stack merged from the April prototype line into the v1.6.x release line.** All new modules are opt-in and backward-compatible — the new `RuntimeConfig` fields default to `None`/`False`, so existing callers are unaffected.
  - `code_runtime_types` — `CodeRuntimePort` unified coding-runtime contract (events, sessions, capabilities).
  - `workspace/` — git ops, mutation policy, conflict detection, verification.
  - `code_intel/` — repo map, impact analysis, language seams, edit planning, coverage checks.
  - `governance/` — permissions, approval gates, audit trail, secrets.
  - `evolution/` — self-evolution engine (stuck detection + recovery cascade), wired into the thin react loop via `RuntimeConfig.evolution_enabled` / `stuck_detector` / `recovery_cascade`.
  - `eval/` coding extensions — golden tasks, coding scorer, provider comparison, regression gate.
  - `scratchpad/` — in-memory + OpenViking scratchpad providers and tools.
  - Orchestration: SGR `NextStep` schema, `ContextBridge`, `spawn_research`; semantic skill discovery (BM25 + hybrid retriever) with `search()` / health / tier management on `SkillRegistry`.
- **Empty-aware structured retry (universal, provider-agnostic, opt-in).** `finalize_with_validation`
  previously retried only when structured output failed to parse/validate; a response that was
  **schema-valid but semantically empty** (e.g. a selection schema whose `picks` list parses to `[]`)
  was passed through as a successful final result, so consumers shipped "nothing found". A structured
  output may now opt into emptiness detection by implementing `is_empty_result(self) -> bool`. When it
  reports itself empty, the engine treats it as the **same retryable miss as a parse failure** —
  re-asked within the existing `max_model_retries` budget (with a distinct retry instruction), then
  surfaced as a `bad_model_output` error instead of a silently-empty success. Schemas that do **not**
  implement the method behave byte-for-byte as before, and a buggy predicate that raises is fail-safe
  (treated as "not empty"). No provider/model knowledge and no new config knob — it reuses
  `max_model_retries`. This lets every consumer drop its bespoke empty-retry wrapper.

### Fixed
- **MCP server now works with FastMCP 3.x.** `create_server()` passed the removed `FastMCP(description=...)` kwarg, which raises `TypeError` on `fastmcp>=3.0`. Switched to the canonical `instructions=` field (present in both FastMCP 2.x and 3.x), so the STDIO MCP server starts on either major line. `@mcp.tool()` and `server.run(transport="stdio")` were already 3.x-compatible.

### Internal
- Merge resolved 5 additive conflicts (subagent types, thin subagent orchestrator, thin react strategy, runtime config, skill registry) as unions — no behavior dropped. Two line-pinned `ty:ignore` guard tests re-aligned after line shifts. Offline unit suite gains +720 passing tests with no new failures versus the 1.6.10 baseline.

## [1.6.10] - 2026-06-22

### Security
- **`swarmline[deepagents]` now requires `langchain>=1.3.9`** (was `>=1.2.11`), clearing
  **GHSA-gr75-jv2w-4656** — a path-traversal class in LangChain filesystem-search middleware and
  config loaders where resolved paths/symlinks could escape the configured root. Only affected
  callers exposing a deepagents filesystem agent over untrusted input. Pulls `langgraph>=1.2.5,<1.3.0`
  and `langchain-core>=1.3` to satisfy the upgrade (verified: deepagents runtime tests green).

### Internal
- **`ty` is now pinned exactly (`ty==0.0.29`) in the `dev` extra.** The unpinned floor let CI pull a
  newer pre-1.0 `ty` whose changed diagnostics broke the type-check gate (and the version-coupled
  suppression meta-tests). No source/runtime change; the pin only makes the CI type-check
  deterministic. Bump `ty` deliberately in future, fixing new diagnostics + meta-tests together.

### Changed
- **`json_object` structured mode now injects the JSON schema into the prompt.** Providers that
  support `response_format={"type": "json_object"}` but not full `json_schema` were returning empty
  nested structures because the schema was never communicated to the model. The engine now appends
  the schema to the prompt in `json_object` mode so nested fields populate reliably. This is the
  fix that lets the polza deepseek/qwen families use native `json_object` (see 1.6.7/1.6.8).

### Fixed
- **`/v1/info` now reports the real package version.** `serve/app.py` hardcoded the version string
  and had silently drifted (stuck at `1.5.0` through the entire 1.6.x line); it now derives from
  `importlib.metadata.version("swarmline")`, so the served version can never drift from the
  package again.

## [1.6.8] - 2026-06-14

### Fixed
- **Reverted the polza→`json_object` structured flip introduced in 1.6.7.** Plain `json_object`
  mode was emptying nested schema structures on the polza deepseek/qwen families, so structured
  output temporarily returned to the portable prompt-mode path. Superseded by the schema-injection
  fix in 1.6.9.

## [1.6.7] - 2026-06-13

### Changed
- **polza structured output is now model-aware.** The polza proxy serves heterogeneous upstream
  models, so structured-output capability is keyed on the upstream model id, not the proxy:
  `polza:deepseek/*` and `polza:qwen/*` now use native `json_object` response_format (verified
  live: nested schemas populate correctly), while `polza:google/gemini-*` keeps portable
  prompt-mode (json_object reliably returned empty nested structures there). Fixes the
  intermittent EMPTY structured payloads (and the resulting 18-26s retry spikes) that
  prompt-mode produced on the deepseek/qwen families.
  `get_provider_structured_capabilities()` gained an optional `model_id` parameter
  (back-compat default `""`).

## [1.6.6] - 2026-06-12

### Fixed
- **Prompt-mode structured calls now accept a bare schema JSON object** (not only a
  `{"schema": ...}` wrapper) returned by OpenAI-compatible proxies.

## [1.6.5] - 2026-06-12

### Fixed
- **The `reasoning` option now reaches OpenAI-compatible proxies** via `extra_body`, paired with
  `max_retries=0` so a proxy that rejects the field fails fast instead of silently retrying.

## [1.6.4] - 2026-06-09

### Changed
- **`resolve_model_name` is now fail-loud (behavior change).** A non-empty model that is neither
  a known alias/id nor a recognized `provider:model` slug now raises `UnknownModelError` instead
  of silently coercing to the default model. This is the bug class that turned
  `polza:google/gemini-3.5-flash` into `claude-sonnet-4` in production with zero signal when the
  provider was missing from the allowlist. Set `SWARMLINE_ALLOW_MODEL_FALLBACK=1` to restore the
  old silent-fallback behavior (now emits a warning). `None`/empty/whitespace still resolves to
  the default (the caller's explicit "use default" signal).
- The accepted-provider allowlist in `resolve_model_name` is now **derived** from
  `provider_resolver._OPENAI_COMPAT_PROVIDERS` (plus native `anthropic`/`google`) instead of a
  duplicated hardcoded set — the drift between the two lists was the root cause of the polza bug.

## [1.6.3] - 2026-06-08

### Fixed
- **polza uses PROMPT-mode structured output, not `json_object`.** Initial portability fix for the
  polza proxy. Later refined into model-aware handling (1.6.7) and schema-injection (1.6.9).

## [1.6.2] - 2026-06-08

### Fixed
- **polza registered in the `resolve_model_name` allowlist** with its structured-output
  capabilities, fixing the silent fallback-to-default for `polza:*` models.

## [1.6.1] - 2026-06-08

### Added
- **`polza.ai` provider** (OpenAI-compatible proxy) and **per-config `api_key` threading** so each
  `AgentConfig` can carry its own provider API key instead of relying solely on environment.

## [1.6.0] - 2026-06-07

### Added — typed data-flow pipeline (registry-dispatch engine)

- **A declarative, registry-dispatch typed data-flow pipeline** under `swarmline.pipeline`. Stages
  are frozen dataclasses dispatched by their *type* (no `isinstance` chain — open/closed);
  `run_pipeline(stages, value, *, event_sink=None, fallback="none")` executes them. Register custom
  stage kinds with `register_stage_runner` or the `@stage_runner` decorator — extend the engine
  without modifying it.
- **Six stage primitives:** `TypedStage` (validator + retries + fallback), `ConditionalStage`
  (route to one of N sub-chains by a selector), `GuardStage` (short-circuit with a fixed payload
  when a predicate trips), `FanOutStage` (dynamic, concurrency-capped fan-out with dedup +
  fail-soft), `ParallelStage` (static named fork/join, `require_all` / `allow_partial`), `LoopStage`
  (bounded reviewer loop).
- **Declarative YAML loader:** `load_pipeline_from_yaml(path, *, registries=...)`,
  `build_pipeline(spec, *, registries=...)`, `PipelineRegistries`. Structure is validated by a
  pydantic spec; handler / validator / selector / predicate / payload / dedup **names** resolve
  against the injected registries and fail fast on an unknown name at load time (callables never
  live in the YAML).
- **Public surface:** `StageOutcome`, the `PipelineError` hierarchy (`StageConfigError`,
  `StageValidationError`, `StageExecutionError`), `StageDependency`, `EventSink`, `resolve_path`.
  Everything is additive — no existing export changed.
- **Docs:** new "Typed Data-Flow Pipeline (registry-dispatch)" section in `docs/pipeline.md`.
  **Example:** `examples/31_typed_dataflow_pipeline.py` (offline, runnable).

### Changed — `TypedPipeline` (alias `WorkflowChain`) now runs on the unified registry engine

- `TypedPipeline` is now a **thin facade** over the registry-dispatch engine — one engine, one set
  of stage primitives, no `isinstance` dispatch. Existing behaviour, the legacy `event_bus` event
  names, and the result shape are preserved (the published contract test suite passes unchanged in
  behaviour).
- Observable hardening (more correct than before, backward-compatible): a **failed stage now records
  its attempt count** in `result.attempts`; with `fallback="last_valid"` and **no prior successful
  stage**, a failure is reported as `failed` (nothing to fall back to) rather than `fallback`. These
  are intentional, non-byte-identical refinements of the previous wording/accounting.
- `PipelineResult.terminated_early: bool` added (additive, default `False`).
- `PipelineContext` is now a single shared class across the typed pipeline and the data-flow engine.

### Deprecated — verbose `*PipelineStage` aliases

- `TypedPipelineStage`, `ParallelPipelineStage` and `LoopPipelineStage` are **deprecated** in favour
  of the canonical short names `TypedStage`, `ParallelStage` and `LoopStage`. Importing a long name
  (from `swarmline.pipeline` or `swarmline.pipeline.typed`) emits a `DeprecationWarning`; the alias
  still resolves to the *identical* canonical class (so registry dispatch is unaffected) and will be
  **removed in 2.0.0**.
- `TypedPipelineResult` is **retained** (not deprecated): it is the only public name for the
  data-flow result type — the top-level `PipelineResult` is the distinct phase-based result.
- The deprecated long aliases are no longer listed in `__all__`, so `from swarmline.pipeline import *`
  no longer pulls them (import them explicitly by name if needed). Both `import swarmline.pipeline`
  and the star-import stay warning-free even under `-W error::DeprecationWarning`; each alias warns
  only on explicit access (once per process).

### Added / Changed — native tool-calling in the thin react path (universal, two-phase)

- **`structured_mode` is now the single knob for native vs portable tool-calling + structured
  output in the thin runtime.** When `structured_mode` is `"native"` or `"auto"` and the
  resolved adapter supports native tool-calling, the react loop now:
  1. runs a **clean** native tool loop (`call_with_tools`) — the model calls tools natively,
     with no text-ReAct JSON envelope and no `final_message` nesting; then
  2. produces the final structured output via a **separate** structured call that carries
     provider-native `response_format` (`json_schema`/`json_object`) when supported, validated
     via the existing `finalize_with_validation` (**two-phase**). The tool loop never carries
     `response_format`, so models that reject "tools + response_format together" work.
  `"prompt"` (the global default) is unchanged — existing consumers see no behavior change.
- **`AgentConfig.use_native_tools: bool | None = None`** — advanced override. `None` derives
  native tools from `structured_mode` (`native`/`auto` → on); set `True`/`False` to force it
  independently of structured output.
- **`AgentConfig.max_turns` now maps to the react `max_iterations` budget** (previously
  unmapped; the loop was always capped at 6). The global default (6) is unchanged when
  `max_turns` is unset.
- **Safety:** native tool-calling is capability-checked (adapter must implement
  `NativeToolCallAdapter`) and any native failure falls back to the text-ReAct path
  automatically. Note: with `structured_mode="auto"` AND tools present, consumers now also get
  native tool-calling (previously `auto` affected only structured output) — auto-fallback keeps
  this safe.
- See `examples/native_tools_openrouter.py` for the recommended usage.

### Hardening (adversarial review of the two-phase path)

- **Phase-2 finalization no longer falls back to text-ReAct on a finalization error.** The
  structured finalize now runs *outside* the native try/except, so a structured-output error
  surfaces cleanly to the caller instead of being mistaken for a native-adapter failure (which
  would silently switch to text-ReAct and risk a conflicting second final event).
- **Empty-stop is handled cleanly.** When the native loop ends with empty text and a schema is
  configured, the structured retry no longer seeds a confusing empty `assistant` message — it
  simply asks for the schema-valid answer given the tool context.
- **The native path now emits an `assistant_delta`** with the model's final text before
  finalization (when not buffering), matching the text-ReAct / clarify paths (no more UX-silent
  native finalization).
- Tests: added Phase-2 malformed-output retry coverage and a fail-loud native-adapter fixture.

## [1.5.1] - 2026-06-07

### Added
- **`Agent.query_structured_result(...)`** — like `query_structured`, but returns the full
  `Result` (the parsed structured value plus run metadata/usage) instead of just the parsed value.

## [1.5.0] - 2026-04-25

This is a substantial release that brings ThinRuntime to feature parity with Claude Code's
agent loop and adds two new runtime adapters, multimodal input, parallel agents, session
resume, conversation compaction, and a typed thinking-events surface.

> **Pre-public-release security audit (added 2026-04-27).** Before the public sync to PyPI, a security review surfaced 6 findings (2× P1, 4× P2) which have been folded into v1.5.0. The full pytest gate is now **5532 passed** (was 5452 at initial tag), `ty check` 0 diagnostics, `ruff check` clean. See **Security audit closure** below for details.

### Security audit closure (added 2026-04-27, pre-public-release)

- **P1 — `path_safety` rejects `"."` and `".."` namespace segments.** Previously `SandboxConfig(user_id=".", topic_id="alice")` and `("alice", ".")` resolved to the same workspace path, breaking tenant isolation. Now both raise `ValueError`. Affects `tools/types.SandboxConfig`, `todo/fs_provider`, `memory_bank/fs_provider`.
- **P1 — `pi_sdk` runtime applies an env allowlist (parity with CLI runtime).** The Node bridge previously inherited the full host environment (`OPENAI_API_KEY`, `AWS_*`, CI tokens). It now uses `DEFAULT_PI_SDK_ENV_ALLOWLIST` (`PATH`/`HOME`/Node + provider keys). Legacy behavior available via `PiSdkOptions(inherit_host_env=True)`. New `PiSdkOptions` fields: `inherit_host_env`, `env_allowlist`, `env`. Shared `runtime/_subprocess_env.build_subprocess_env()` helper used by both CLI and pi_sdk runtimes (DRY).
- **P2 — `web_fetch` rejects non-HTTP schemes.** `file://`, `ftp://`, `data:`, `javascript:`, `gopher://`, `ssh://`, `smb://`, `ws[s]://` URLs previously passed `HttpxWebProvider._validate_url` and could reach delegated browser-capable fetch providers (Crawl4AI, Jina). Now blocked at validator entry; only `http`/`https` (case-insensitive) proceed.
- **P2 — E2B sandbox resolves shell-wrapper denylist bypass.** `sh -c 'rm -rf /workspace'` previously bypassed `denied_commands={"rm"}` because the `rm` token sat inside a quoted argument. The provider now detects shell wrappers (`sh`/`bash`/`zsh`/`dash`/`ksh`/`fish`) and recursively re-parses the `-c` payload through the same denylist. Brings E2B to parity with Local/Docker/OpenShell. No behavioral change without an explicit denylist.
- **P2 — Secret redaction for runtime/CLI/serve error messages.** Provider exceptions, CLI subprocess stderr, and HTTP 500 responses could include `Bearer` tokens, `sk-*` API keys (OpenAI, Anthropic), GitHub tokens (`ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_`), URL userinfo, and `KEY=value` env strings. New `observability/redaction.py` exposes `redact_secrets(text)` and `DEFAULT_SECRET_PATTERNS`; applied at `provider_runtime_crash`, CLI runtime stderr decode, and `/v1/query` 500 path. `JsonlTelemetrySink` now sources the same pattern set (DRY — single source of truth instead of two near-duplicate regex tuples).
- **P2 — `serve.create_app(allow_unauthenticated_query=True)` now requires an explicit `host=` argument.** The earlier v1.5.0 path (logged a deprecation warning when `host=None` and silently accepted the call) could combine with `uvicorn --host 0.0.0.0` to expose unauthenticated `/v1/query` publicly. The host argument is now mandatory; passing `host=None` or `host=""` raises `ValueError`. **Migration:** `create_app(agent, allow_unauthenticated_query=True, host="127.0.0.1")` for local-only mode, or pass `auth_token=` for production.
- **Test additions:** 80 new tests across 6 atomic stages (path_safety 14, pi_sdk env 8, web schemes 19, E2B wrappers 11, redaction 27, serve loopback +2/-1 net). Plan: [`.memory-bank/plans/2026-04-27_fix_security-audit.md`](.memory-bank/plans/2026-04-27_fix_security-audit.md).

### Added

#### ThinRuntime Claude Code parity (Phases 1–10)

- **Hook dispatch** — full `PreToolUse` / `PostToolUse` / `Stop` / `UserPromptSubmit` lifecycle in ThinRuntime via `HookRegistry`.
- **Tool policy enforcement** — `DefaultToolPolicy` is now wired through `ToolExecutor`; default-deny applies to ThinRuntime (parity with `claude_sdk` adapter).
- **LLM-initiated subagents** — `spawn_agent` builtin tool lets the model delegate work to a child Agent. Configurable via `AgentConfig.subagent_config: SubagentToolConfig`.
- **Command routing** — slash-command registry recognized inside ThinRuntime conversations. Configurable via `AgentConfig.command_registry`.
- **Native tool calling** — parallel tool execution path using provider-native function-call APIs (Anthropic `tool_use`, OpenAI `tools`, Google `functionDeclarations`).
- **Coding profile** — opt-in `CodingProfileConfig` enables a curated coding-agent tool surface (sandbox, web, thinking) with hardened policy. Set `AgentConfig.coding_profile`.

#### ThinRuntime Parity v2 (Phases 11–17)

- **Phase 11 — Foundation filters**: `ProjectInstructionFilter` walks up from cwd loading `CLAUDE.md` / `AGENTS.md` / `RULES.md` / `GEMINI.md` into the system prompt; `SystemReminderFilter` injects dynamic context blocks.
- **Phase 12 — Tool surface expansion**: `web_fetch` honours `web_allowed_domains` / `web_blocked_domains` filters; new MCP resource tools (`list_resources`, `read_resource`, builtin `read_mcp_resource`) with TTL caching; `ResourceDescriptor` exported.
- **Phase 13 — Conversation compaction**: 3-tier cascade (tool-result collapse → LLM summarization → emergency truncation) via `ConversationCompactionFilter` + `CompactionConfig`.
- **Phase 14 — Session resume**: `JsonlMessageStore` (SHA-256 filenames, corrupted-line resilience) + `Conversation.resume(session_id)` with auto-persist and auto-compaction.
- **Phase 15 — Thinking events**: typed `ThinkingConfig` union (`ThinkingConfigEnabled` / `ThinkingConfigAdaptive` / `ThinkingConfigDisabled`); `RuntimeEvent.thinking_delta` factory; `LlmCallResult` envelope; AnthropicAdapter extracts thinking blocks.
- **Phase 16 — Multimodal input**: `ContentBlock` / `TextBlock` / `ImageBlock` types; `Message.content_blocks` additive field; multimodal converters for Anthropic / OpenAI / Google adapters; `BinaryReadProvider`; PDF and Jupyter notebook extractors.
- **Phase 17 — Parallel agents**: `SubagentSpec.isolation` (`shared` / `worktree`); per-agent git worktree lifecycle for `spawn_agent`; `RuntimeEvent.background_complete`; new `monitor_agent` builtin tool.

#### New runtime adapters

- **`runtime="pi_sdk"`** — Pi SDK adapter via Node.js bridge. Fourth runtime in the matrix.
- **`runtime="openai_agents"`** — OpenAI Agents SDK adapter (Codex + OpenAI models). Fifth runtime in the matrix.

#### Other additions

- **Agent packs** — `AgentPackResolver`, `AgentPackResource`, `ResolvedAgentPack` for declarative agent-bundle loading. See `docs/agent-pack.md`.
- **Typed pipeline primitives** — structured workflow building blocks (`pipeline/typed.py`, `pipeline/bridge.py`, chain extensions).
- **JSONL telemetry sink** — `JsonlTelemetrySink` subscribes to `EventBus`, writes append-only JSONL events to disk with non-blocking I/O and serialized concurrent writes. Built-in key-name redaction for secrets.
- **Subagent worktree isolation** — `SubagentToolConfig` exposes worktree-isolation knobs to LLM-initiated subagents.

### Changed

- **Default runtime** — `AgentConfig.runtime` default flipped from `"claude_sdk"` → `"thin"`. Existing code that passes `runtime="claude_sdk"` explicitly is unaffected; only callers that relied on the implicit default see new behaviour. Recommendation: pin `runtime=...` explicitly. (See `docs/migration/v1.4-to-v1.5.md`.)
- **Python 3.10 dropped** — minimum supported interpreter is now `>=3.11`. CI matrix updated in `.github/workflows/publish.yml`.
- **`ty` strict-mode baseline = 0** — Sprints 1A/1B drove diagnostics from 75 → 0 (locked in `tests/architecture/ty_baseline.txt`).
- LLM error messages standardised on English in `runtime/thin/errors.py` and `runtime/thin/llm_client.py` (was Russian).
- `docs/agent-facade.md` corrected — `system_prompt` (not `runtime`) is the only required `AgentConfig` parameter.

### Deprecated

- **`AgentConfig.max_thinking_tokens`** — use `AgentConfig.thinking={"type":"enabled","budget_tokens":N}` (or one of the typed `ThinkingConfigEnabled` / `ThinkingConfigAdaptive` / `ThinkingConfigDisabled` dataclasses) instead. Backwards-compatible mapping is preserved in `runtime/options_builder.py`; the field will be removed in a future release.

### Fixed

- **C-1 / C-3** — test isolation: `observability/logger.py` no longer calls `logging.basicConfig(force=True)` on every reconfigure and now routes stdlib logging to `stderr`. This eliminates cross-test contamination and preserves the CLI JSON contract on `stdout`.
- **C-2** — `JsonlTelemetrySink.record()` no longer blocks the event loop: file I/O wrapped in `asyncio.to_thread()` and concurrent writes serialized via a lazy `asyncio.Lock`.
- **C-9** — Russian error string in `runtime/thin/errors.py` translated to English ("LLM API error" replaces "Ошибка LLM API").
- **C-10** — `docs/agent-facade.md` accuracy: `system_prompt` is the only required field; `runtime` defaults to `"thin"`.
- E402 `noqa` placement on multi-line imports in `tests/unit/test_otel_exporter.py`.

### Documentation

- New: `docs/migration/v1.4-to-v1.5.md` — migration guide for the 1.4 → 1.5 transition.
- New / extended: `docs/agent-pack.md`, `docs/observability.md`, `docs/structured-output.md`, `docs/pipeline.md` — parity v2 surface and JSONL telemetry coverage.
- `CLAUDE.md` and `AGENTS.md` aligned to Python 3.11+.

### Internal

- Sprint 1A — `ty` strict-mode foundation (75 → 62 diagnostics).
- Sprint 1B — six staged batches (62 → 0): OptDep, unresolved-attribute, callable narrow, argument-type, miscellaneous, baseline lock.

## [1.4.1] - 2026-04-11

### Changed

- **Branding**: package renamed `cognitia` → `swarmline`. PyPI distribution is `swarmline==1.4.1`. All 4263 tests pass post-rename.
- CI: GitHub Actions workflows updated to Node.js 24-compatible action versions.

### Fixed

- `docs` extra: missing `mkdocstrings` dependency added so `mkdocs build` works in a clean install.

### Tests

- Added contract tests for `Agent.query()` `messages` parameter behaviour.

## [1.4.0] - 2026-04-11

### Changed

- Documented the secure-by-default release posture for the `v1.4.0` stabilization tranche:
  - `enable_host_exec=False` for MCP host execution
  - `allow_host_execution=False` for `LocalSandboxProvider`
  - `allow_unauthenticated_query=False` for `/v1/query`
- Added explicit migration recipes for enabling MCP host exec, enabling sandbox host execution, and intentionally opening `/v1/query`
- Aligned README, capabilities, getting-started, configuration, and memory-bank notes with the current release truth

### Release readiness

- `v1.4.0` is release-doc ready: the remaining work is packaging/version publication, not further product design

## [1.3.0] - 2026-03-30

### Changed

- **Branding**: Swarmline renamed to Swarmline across README and documentation

### Fixed

- **P1 — False-green completion**: Pipeline now detects failed/timed-out root agent (wait_for_task None → phase FAILED)
- **P1 — Task state consistency**: Orchestrator calls checkout_task() on start/delegate, cancel_task() on failure/cancel
- **P1 — ThinRuntime per-call config**: Per-call RuntimeConfig now applies to actual LLM path via partial binding (not just guardrails/cost)
- **P2 — Concurrency**: WorkflowGraph.resume() per-execution interrupt isolation; SessionManager async backend methods; Scheduler honors max_concurrent_tasks via Semaphore
- **P2 — SQLite thread safety**: EpisodicMemory uses threading.Lock + check_same_thread=False; TaskQueue.get() uses SQL-level filtering instead of O(N) Python scan
- **P2 — Security hardening**: SSRF DNS resolution + localhost block + no-redirect; workspace slug validation; A2A server auth_token + request size limit; Docker cap_drop=ALL + network=none + mem_limit; MCP exec_code trusted=True required; daemon auth wired through config
- **P3 — Observability bounds**: ActivityLog max_entries eviction; ConsoleTracer ended span pruning
- **Critical**: FTS5 BEFORE DELETE/UPDATE triggers (prevents stale search duplicates)
- **Critical**: Exponential retry backoff in orchestrator (prevents retry storm / livelock)
- **Critical**: Task board read methods under async lock (prevents dict iteration crash)
- **Critical**: run_turn/stream_reply use async aget() (prevents event loop blocking)
- Workspace lock safety + plugin/session publish→emit method rename
- 30+ additional security, correctness, and concurrency fixes across all modules

## [1.2.0] - 2026-03-30

### Added

- **Agent Graph System** — hierarchical multi-agent with org charts, governance, delegation
  - AgentNode with capabilities, skills, MCP servers, runtime config
  - AgentExecutionContext — structured runner context replacing 4 positional strings
  - GraphBuilder DSL with YAML/dict support
  - Governance: AgentCapabilities (can_hire, can_delegate, max_children) + GraphGovernanceConfig
  - Graph tools: hire_agent, delegate_task, escalate
  - InMemory + SQLite + PostgreSQL backends
  - GraphCommunication: inter-agent messaging (InMemory/SQLite/Postgres/Redis/NATS)
  - GraphTaskBoard: hierarchical tasks with DAG dependencies, atomic checkout
  - Task progress auto-calculation from subtasks
  - TaskStatus.BLOCKED with mandatory reason
  - Extensible workflow stages (WorkflowConfig, WorkflowStage)
- **Knowledge Bank** — universal domain-agnostic structured knowledge storage
  - 5 ISP protocols: KnowledgeStore, KnowledgeSearcher, ProgressLog, ChecklistManager, VerificationStrategy
  - DocumentMeta YAML frontmatter with kind, tags, importance
  - Multi-backend: filesystem, SQLite, PostgreSQL, custom providers
  - Knowledge tools: search, save_note, get_context
  - Episode-to-Knowledge consolidation
- **Pipeline Engine** — multi-phase execution with budget gates
- **Daemon** — universal long-running process manager
- **Evaluation Framework** — agent eval with compare/history (Phases 13.1-13.2)
- **Memory Enhancements**
  - Episodic Memory with InMemory + SQLite (Phase 14.1)
  - Procedural Memory — learned tool sequences (Phase 14.2)
  - Consolidation Pipeline — episodes to knowledge (Phase 14.3)
- **HTTP API** (`swarmline serve`) — Phase 15.1
- **Human-in-the-Loop** approval patterns — Phase 15.2
- **Plugin Registry** + Benchmarks — Phases 15.3-15.4
- **Paperclip-inspired Components**
  - TaskSessionStore: session-per-task persistence
  - ActivityLog + ActivityLogSubscriber: structured audit trail
  - PersistentBudgetStore: durable cost tracking
  - RoutineBridge: scheduler to task board integration
  - ExecutionWorkspace: temp_dir/git_worktree/copy isolation
  - PluginRunner: subprocess JSON-RPC plugin host
- **API Docs** — auto-generated + community infra (Phase 12.3)

### Changed

- GraphTaskBoard: `_propagate_completion()` renamed to `_propagate_parent()` (always recurses for progress)
- Redis/NATS EventBus: URL now required parameter (no localhost default)
- A2A adapter: URL now required parameter
- Provider resolver: ollama/local marked as dev-only defaults
- Clean Architecture: domain types extracted to `domain_types.py`

### Fixed

- 30+ security fixes across all modules (exec_code blocklist, SSRF protection, path traversal, FTS5 sanitization, timing-safe auth)
- 19 mypy type errors resolved (orchestrator, tools, postgres backends, SDK adapters)
- delegate_task governance enforcement (check_delegate_allowed)
- Root task execution tracking in orchestrator
- localhost defaults removed from production constructors

## [1.1.0] - 2026-03-29

### Added

- **Code Agent Integration** (`swarmline.mcp`, `swarmline.cli`) — Phase 16
  - MCP Server (`swarmline-mcp`): 20 typed tools via FastMCP STDIO — memory (6), plans (5), team (5), agent (3), code (1)
  - Headless Runtime: 0 LLM mode for external code agents (Claude Code, Codex CLI, OpenCode)
  - Stateful Session: auto-detect mode from env vars, holds all InMemory providers
  - CLI Client (`swarmline`): Click-based CLI with 6 command groups — memory, plan, team, agent, run, mcp-serve
  - Claude Code Skill: `SKILL.md` + 10 reference patterns for seamless integration
  - Integration configs: claude-code, codex, opencode ready-made configurations
  - 7 E2E use case tests: research swarm, persistent memory, review pipeline, resumable plans, meta-agent, cross-tool, learning agent
- **OpenTelemetry Exporter** (`swarmline.observability.otel`) — Phase 11.1
  - `OTelExporter`: bridges Swarmline EventBus to OpenTelemetry spans
  - Auto-creates spans for LLM calls, tool executions, agent queries
  - Configurable via `OTelConfig(service_name, endpoint, headers, insecure)`
  - Lazy import — only requires `opentelemetry-api` + `opentelemetry-sdk` when used
  - New optional: `swarmline[otel]`
- **Structured Output at Agent Level** (`swarmline.agent`) — Phase 11.2
  - `Agent.query_structured(prompt, output_type: type[T]) -> T` — type-safe Pydantic output
  - Auto-generates JSON Schema from Pydantic model, runs through runtime retry loop
  - `StructuredOutputError` raised when parsing fails after all retries
  - Zero changes to ThinRuntime (already supported `output_type`)
- **A2A Protocol Support** (`swarmline.a2a`) — Phase 11.3
  - Full Agent-to-Agent protocol: JSON-RPC 2.0 over HTTP + SSE streaming
  - `SwarmlineA2AAdapter`: pure adapter pattern, wraps any Agent as A2A service (0 core changes)
  - `A2AServer`: Starlette ASGI server with `/.well-known/agent.json` discovery
  - `A2AClient`: httpx-based client with `discover()`, `send_task()`, `stream_task()`
  - Domain types: `Task`, `AgentCard`, `AgentSkill`, `TaskStatus`, `Message`, `Artifact`
  - New optional: `swarmline[a2a]` (starlette + httpx)
- **`swarmline init` CLI Scaffolding** — Phase 12.1
  - `swarmline init my-agent` scaffolds a production-ready agent project in seconds
  - Flags: `--runtime` (thin/claude/deepagents), `--memory` (inmemory/sqlite), `--full`, `--output`, `--force`
  - Generates: `agent.py`, `config.yaml`, `tests/`, `.env.example`, `pyproject.toml`, `README.md`
  - Full mode adds: `Dockerfile`, `docker-compose.yml`, `skills/`
  - Pure stdlib templates (string.Template), no Jinja2 dependency

### Changed

- `docs/getting-started.md` updated with `swarmline init` quick start as primary onboarding path
- `docs/examples.md` expanded with examples 29 (structured output) and 30 (A2A agent)
- `pyproject.toml` extras: added `otel`, `a2a`, `mcp`, `cli`, `code-agent` bundles

## [1.0.0-core] - 2026-03-18

### Added

- **Structured Output** (`swarmline.runtime`) — Phase 6A
  - `output_type` in `RuntimeConfig` — auto-extracts JSON Schema from Pydantic models
  - `validate_structured_output`, `try_resolve_structured_output`, `extract_structured_output` helpers
  - Retry on validation failure with configurable `max_model_retries`
- **Tool Decorator Enhancements** (`swarmline.agent.tool`) — Phase 6B
  - `@tool` decorator: auto JSON Schema inference from type hints
  - Docstring parsing for parameter descriptions
  - `ToolDefinition.to_tool_spec()` bridge for runtime compatibility
- **Runtime Registry** (`swarmline.runtime.registry`) — Phase 6C
  - `RuntimeRegistry`: thread-safe extensible registry with plugin discovery via entry points
- **Cancellation** (`swarmline.runtime`) — Phase 6D
  - `CancellationToken`: cooperative cancellation with callbacks
- **Runtime Events** (`swarmline.runtime.types`) — Phase 6D
  - Typed `RuntimeEvent` accessors: `.text`, `.tool_name`, `.structured_output`, `.is_final`, `.is_error`
  - Static factory methods: `RuntimeEvent.assistant_delta()`, `.final()`, `.error()`, etc.
- **Runtime Context Manager** — `AgentRuntime` context manager (`async with runtime as r:`) — Phase 6D
- **Protocols ISP Split** — `protocols.py` split into `protocols/memory.py`, `session.py`, `routing.py`, `tools.py`, `runtime.py` — Phase 6D
- **Cost Budget Tracking** (`swarmline.runtime.cost`) — Phase 7A
  - `CostBudget` and `CostTracker` for per-session budget enforcement
  - Bundled `pricing.json` with pricing data for major models
  - Budget enforcement in ThinRuntime with `action_on_exceed` ("error"/"warn")
- **Guardrails** (`swarmline.guardrails`) — Phase 7B
  - `Guardrail` Protocol, `InputGuardrail`/`OutputGuardrail` marker protocols
  - Built-in guardrails: `ContentLengthGuardrail`, `RegexGuardrail`, `CallerAllowlistGuardrail`
  - Parallel guardrail execution via `asyncio.gather`
- **Input Filters** (`swarmline.filters`) — Phase 7C
  - `InputFilter` Protocol for pre-processing user input
  - `MaxTokensFilter` for token budget enforcement
  - `SystemPromptInjector` for dynamic system prompt augmentation
- **Retry and Fallback** (`swarmline.resilience`) — Phase 7D
  - `RetryPolicy` Protocol, `ExponentialBackoff` with jitter
  - `ModelFallbackChain` and `ProviderFallback` data objects for multi-model resilience
- **Session Backends** (`swarmline.session.backends`) — Phase 8A
  - `SessionBackend` Protocol for pluggable session persistence
  - `InMemorySessionBackend` for development and testing
  - `SqliteSessionBackend` with `asyncio.to_thread()` for non-blocking I/O
- **Memory Scopes** (`swarmline.memory.scopes`) — Phase 8A
  - `MemoryScope` enum (`GLOBAL`/`AGENT`/`SHARED`) with `scoped_key()` namespace isolation
- **Event Bus** (`swarmline.observability.event_bus`) — Phase 8B
  - `EventBus` Protocol with fire-and-forget pub-sub
  - `InMemoryEventBus` implementation with topic-based subscription
- **Tracing** (`swarmline.observability.tracing`) — Phase 8B
  - `Tracer` Protocol, `NoopTracer`, `ConsoleTracer` (structlog-based)
  - `TracingSubscriber` bridge connecting EventBus to Tracer
  - ThinRuntime emits `llm_call_start/end`, `tool_call_start/end` events via EventBus
- **UI Projection** (`swarmline.ui.projection`) — Phase 8C
  - `EventProjection` Protocol, `ChatProjection` implementation
  - `project_stream` async generator for real-time UI updates
  - UI blocks: `TextBlock`, `ToolCallBlock`, `ToolResultBlock`, `ErrorBlock`
  - `UIState.to_dict()`/`from_dict()` serialization for frontend transport
- **RAG** (`swarmline.rag`) — Phase 8D
  - `Retriever` Protocol, `Document` frozen dataclass
  - `SimpleRetriever` (word-overlap scoring for development and testing)
  - `RagInputFilter` implementing `InputFilter` — auto-wraps via `RuntimeConfig.retriever`
- **Multi-Agent Coordination** (`swarmline.multi_agent`) — Phase 9 MVP
  - `AgentTool` Protocol — expose any runtime as a callable tool for other agents
  - `create_agent_tool_spec()` / `execute_agent_tool()` — agent-as-tool utility functions
  - `AgentToolResult` frozen dataclass with success/output/error/metrics
  - `TaskQueue` Protocol (5 methods, ISP-compliant) with `InMemoryTaskQueue` and `SqliteTaskQueue`
  - `TaskItem`, `TaskStatus`, `TaskPriority`, `TaskFilter` domain types
  - `AgentRegistry` Protocol (5 methods, ISP-compliant) with `InMemoryAgentRegistry`
  - `AgentRecord`, `AgentStatus`, `AgentFilter` domain types
- **CLI Agent Runtime** (`swarmline.runtime.cli`) — Phase 10A
  - `CliAgentRuntime` — subprocess-based runtime for external CLI agents (Claude Code, custom)
  - `NdjsonParser` Protocol with `ClaudeNdjsonParser` and `GenericNdjsonParser`
  - `CliConfig` frozen dataclass (command, timeout, max_output_bytes, env)
  - Registered in `RuntimeRegistry` as `"cli"` with light tier capabilities
- **27 Runnable Examples** (`examples/`)
  - End-to-end examples covering all major features: agent basics, tool decorator, structured output, middleware, hooks, input filters, guardrails, RAG, memory providers, sessions, cost budget, retry/fallback, cancellation, thinking tool, event bus/tracing, UI projection, runtime switching, custom runtime, CLI runtime, workflow graph, agent-as-tool, task queue, agent registry, deep research, shopping agent, code project team, nano-claw

### Changed

- Audit remediation Wave 1: portable `mcp_servers`, canonical `final.new_messages`, terminal contract hardening, port/session final metadata, thin-team `send_message`, single-layer retry
- Audit remediation Wave 2: shared portable runtime wiring helper for `Agent`/`Conversation`, lazy fail-fast optional exports for `runtime`/`hooks`/`memory`/`skills`
- Re-audit remediation: `SessionManager` keeps canonical `final.new_messages`, `BaseRuntimePort`/session runtime paths fail on silent EOF and preserve final metadata, `ClaudeCodeRuntime` stops after terminal error, DeepAgents portable path round-trips tool history, builtin `cli` works through registry and legacy fallback, workflow executor advertises tools, docs/runtime narrative synced
- Review-fix batch 1: narrowed exceptions, `isinstance` test, `None` score fix
- Review-fix batch 2: `assert` replaced with guard clauses, process leak fix, unused imports removed
- P1 follow-up fixes: `runtime="cli"` ignores facade-only kwargs, CLI stdin includes `system_prompt`, `execute_agent_tool()` fails on `RuntimeEvent.error`/missing final, `TaskQueue.get()` atomically claims TODO tasks as `IN_PROGRESS`
- P1 follow-up batch 2: SQLite `complete()`/`cancel()` use atomic CAS transition, CLI runtime emits `bad_model_output` when subprocess exits without final event, Claude autodetect uses basename, `execute_agent_tool()` catches arbitrary `Exception`

### Fixed

- Repo-wide `ruff check` clean (60 errors in src/ and tests/ resolved)
- Repo-wide `mypy` clean (27 errors in 17 files resolved)
- Session/runtime migration cleanup (Wave 2 Phase 5)
- Factory/registry hardening (Wave 2 Phase 6)

### Deprecated
- `RuntimePort` protocol — use `AgentRuntime` from `swarmline.runtime.base`

## [0.5.0] - 2026-03-16

### Added
- **ThinRuntime Built-in Tools** (`swarmline.runtime.thin.builtin_tools`)
  - 9 tools: `read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`, `execute`, `write_todos`, `task`
  - `feature_mode` filtering (portable/hybrid/native_first)
  - DeepAgents-compatible aliases (Read→read_file, Bash→execute, etc.)
  - `merge_tools_with_builtins()` — user tools override built-ins by name
- **Token-Level Streaming** (`swarmline.runtime.thin.stream_parser`)
  - `IncrementalEnvelopeParser` — stateful incremental JSON brace-tracking parser
  - `StreamParser` — high-level streaming parser with ActionEnvelope extraction
  - React + Conversational + Planner modes all stream per-token via `_try_stream_llm_call()`
  - Fallback to non-streaming on parse error
- **ThinTeamOrchestrator** (`swarmline.orchestration.thin_team`)
  - Full `TeamOrchestrator` + `ResumableTeamOrchestrator` protocol implementation
  - Lead delegation: `_compose_worker_task()` personalizes task per worker
  - MessageBus per-team with auto-registered `send_message` tool
  - pause/resume via cancel + re-spawn
- **ThinSubagent Full Implementation** (`swarmline.orchestration.thin_subagent`)
  - `_create_runtime()` creates per-worker `_ThinWorkerRuntime` with ThinRuntime
  - `register_tool()` public method for tool injection (replaces private access)
  - Supports `llm_call`, `local_tools`, `mcp_servers`, `runtime_config` via constructor
- **MessageBus Tools** (`swarmline.orchestration.message_tools`)
  - `SEND_MESSAGE_TOOL_SPEC` — ToolSpec with JSON Schema (to_agent, content)
  - `create_send_message_tool()` — factory for send/broadcast executor
  - `send_message_tool_spec()` — accessor function
- **McpBridge** (`swarmline.runtime.mcp_bridge`)
  - Library-level MCP facade (runtime-agnostic, works with thin + deepagents)
  - `discover_tools()` / `discover_all_tools()` — tool names prefixed as `mcp__{server}__{tool}`
  - `create_tool_executor()` — async callable factory for LangChain integration
  - Caching delegated to McpClient TTL (300s)
- **DeepAgents MCP Integration** (`swarmline.runtime.deepagents`)
  - `mcp_servers` parameter in `__init__()` — creates `McpBridge` automatically
  - MCP tools injected into `selected_tools` with executor wiring
  - Graceful degradation with `logging.warning` on discovery failure
- **WorkflowGraph** (`swarmline.orchestration.workflow_graph`)
  - Declarative graph execution: linear, conditional branching, loop with max, parallel, subgraph, interrupt/resume
  - `InMemoryCheckpoint` for state persistence
  - `to_mermaid()` — graph visualization export
- **Workflow Executors** (`swarmline.orchestration.workflow_executor`)
  - `ThinWorkflowExecutor` — LLM per-node via ThinRuntime
  - `MixedRuntimeExecutor` — route nodes to different runtimes via `node_interceptor`
  - `compile_to_langgraph()` — LangGraph StateGraph compiler for deepagents
- **GenericWorkflowEngine** (`swarmline.orchestration.generic_workflow_engine`)
  - Pluggable `ExecutorPort` + `VerifierPort` protocols
  - Retry/verify loop with configurable `max_retries`
- **CommandRegistry v2** (`swarmline.commands`)
  - `CommandDef` with typed `parameters` (JSON Schema), `description`, `category`
  - `to_tool_definitions()` — commands available as LLM tools
  - `execute_validated()` — JSON Schema parameter validation before execute
  - YAML auto-discovery via `loader.py` (`load_commands_from_yaml`, `auto_discover_commands`)
  - Backward compatible with string-based API
- **JSON Utilities** (`swarmline.runtime.thin.json_utils`)
  - `find_json_object_boundaries()` — shared brace-tracking parser (DRY extraction)

### Changed
- `CodeWorkflowEngine` now delegates to `GenericWorkflowEngine` (thin wrapper with `_PlannerExecutor` + `_DoDVerifierAdapter`)
- `MixedRuntimeExecutor` uses `node_interceptor` parameter instead of monkey-patching `_execute_node`
- Runtime Feature Matrix added to README.md

### Tests
- 298 new tests (1085 → 1383 passed): builtin_tools (20), streaming (20), thin_subagent (9), thin_team (12), message_tools (7), mcp_bridge (4), deepagents_mcp (5), workflow_graph (8), workflow_executor (10), generic_workflow (6), commands_v2 (12), json_utils (18), code_workflow_delegation (3), and more

## [0.4.0] - 2026-03-15

### Added
- **Code Verification Pipeline** (`swarmline.orchestration`)
  - `CodeVerifier` Protocol — ISP-compliant (5 methods: verify_contracts, verify_tests_substantive, verify_tests_before_code, verify_linters, verify_coverage)
  - `TddCodeVerifier` — implementation respecting `CodingStandardsConfig` (disabled checks auto-SKIP)
  - `CommandRunner` Protocol + `CommandResult` — sandbox-agnostic command execution
  - `DoDStateMachine` — criteria-driven verification state machine (PENDING → VERIFYING → PASSED/FAILED) with max loop counter
  - `CodeWorkflowEngine` — structured code pipeline: plan → execute → verify_dod → loop
  - `WorkflowPipeline` Protocol — generic research → plan → execute → review → verify
  - `WorkflowResult` — structured pipeline result
- **Verification Types** (`swarmline.orchestration.verification_types`)
  - `VerificationStatus` (PASS/FAIL/SKIP), `CheckDetail`, `VerificationResult` with `.passed` property
- **Coding Standards Configs** (`swarmline.orchestration.coding_standards`)
  - `CodingStandardsConfig` — TDD, SOLID, DRY, KISS, Clean Arch flags with factory methods: `strict()`, `minimal()`, `off()`
  - `WorkflowAutomationConfig` — `full()`, `light()`, `off()` factories
  - `AutonomousLoopConfig` — `strict()`, `light()` factories
  - `CodePipelineConfig` — aggregate with `production()`, `development()` presets
  - `TeamAgentsConfig` — team role configuration
- **ToolOutputCompressor Middleware** (`swarmline.agent.middleware`)
  - Content-type aware compression: JSON (truncate arrays), HTML (strip tags), Text (head+tail)
  - Integrates with `HookRegistry` via `on_post_tool_use` callback
  - Configurable `max_result_chars` (default 10000)
- **Middleware helpers**
  - `build_middleware_stack()` — factory for common middleware combinations (cost_tracker, tool_compressor, security_guard)
- **HookRegistry.merge()** — public API to combine hook registries from multiple middlewares
- **PlanStep DoD fields** — `dod_criteria`, `dod_verified`, `verification_log` for plan verification tracking

### Changed
- `PlanStep` transition methods use `dataclasses.replace()` (new DoD fields auto-propagate)

### Tests
- 51 new unit tests: tool_output_compressor (12), verification_types (9), coding_standards (12), code_verifier (10), dod_state_machine (8)

## [0.3.0b1] - 2026-03-13

### Added
- **Agent Facade API** (`swarmline.agent`) — high-level 3-line API for AI agents
  - `Agent` class with `query()`, `stream()`, `conversation()` methods
  - `@tool` decorator for defining tools with auto-inferred JSON Schema
  - `Middleware` protocol with built-in `CostTracker` and `SecurityGuard`
  - `Conversation` for explicit multi-turn dialog management
- **Import isolation** — `import swarmline` works without any optional dependencies
- **Test markers** — `requires_claude_sdk`, `requires_anthropic`, `requires_langchain`, `live`
- LICENSE (MIT), CHANGELOG, CONTRIBUTING, comprehensive documentation

### Fixed
- `@tool` handler contract mismatch with Claude Agent SDK MCP format
- `hooks/__init__.py` crash when `claude_agent_sdk` not installed
- Optional dependency boundaries fully verified with smoke tests

## [0.2.0] - 2026-02-11

### Added
- **Multi-runtime support** — 3 pluggable runtimes:
  - `claude_sdk` — Claude Agent SDK (subprocess, built-in MCP)
  - `thin` — lightweight built-in loop (react/planner/conversational modes)
  - `deepagents` — LangChain Deep Agents integration
- **RuntimeFactory** — create runtime by config/env/override
- **Runtime Ports** — `BaseRuntimePort`, `ThinRuntimePort`, `DeepAgentsRuntimePort`
- **Model Registry** — multi-provider (Anthropic, OpenAI, Google, DeepSeek) with aliases
- **SwarmlineStack** — bootstrap facade factory for quick setup
- **Memory providers** — InMemory, PostgreSQL, SQLite
- **Web tools** — pluggable search (DuckDuckGo, Tavily, SearXNG, Brave) and fetch providers
- **Orchestration** — plan manager, subagent spawning, team coordination
- **SDK 0.1.48 integration** — `one_shot_query`, `sdk_tools`, hooks bridge
- **LLM Summarizer** — automatic conversation summarization with history cap
- **Circuit Breaker** — resilience pattern for external calls
- 14 ISP-compliant protocols (each <=5 methods)

### Changed
- Domain-agnostic: removed all finance-specific defaults from library code
- `RoleSkillsLoader` moved to `swarmline.config.role_skills`
- `RoleRouterConfig` is now a typed dataclass (was dict)

## [0.1.0] - 2026-02-10

### Added
- **Core protocols** — `FactStore`, `GoalStore`, `MessageStore`, `SummaryStore`, `UserStore`, `SessionStateStore`, `PhaseStore`, `ToolEventStore`
- **Behavior protocols** — `RoleRouter`, `ModelSelector`, `ToolIdCodec`, `ContextBuilder`, `SessionRehydrator`, `RuntimePort`
- **Session management** — `InMemorySessionManager`, `DefaultSessionRehydrator`
- **Context builder** — `DefaultContextBuilder` with token budget and priority-based overflow
- **Tool policy** — `DefaultToolPolicy` with default-deny and always-denied tools list
- **Skills** — `YamlSkillLoader`, `SkillRegistry` for declarative MCP skill management
- **Routing** — `KeywordRoleRouter` for keyword-based role resolution
- **Observability** — `AgentLogger` with structured JSON logging
- **Memory** — `InMemoryMemoryProvider`, `PostgresMemoryProvider`
- **Commands** — `CommandRegistry` with aliases

[Unreleased]: https://github.com/fockus/swarmline/compare/v1.6.0...HEAD
[1.6.0]: https://github.com/fockus/swarmline/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/fockus/swarmline/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/fockus/swarmline/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/fockus/swarmline/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/fockus/swarmline/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/fockus/swarmline/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/fockus/swarmline/compare/v1.0.0...v1.1.0
[1.0.0-core]: https://github.com/fockus/swarmline/compare/v0.5.0...v1.0.0-core
[0.5.0]: https://github.com/fockus/swarmline/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/fockus/swarmline/compare/v0.3.0b1...v0.4.0
[0.3.0b1]: https://github.com/fockus/swarmline/compare/v0.2.0...v0.3.0b1
[0.2.0]: https://github.com/fockus/swarmline/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/fockus/swarmline/releases/tag/v0.1.0
