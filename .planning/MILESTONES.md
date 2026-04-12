# Milestones

## Completed

### v1.4.1 — Stabilization & Rename (2026-04-11)

- Security hardening (namespace validation, auth defaults, CLI env redaction)
- cognitia → swarmline rename, PyPI published
- Full validation gate: offline pytest, integration, Postgres, live suite, ruff, mypy

### v1.5.0-alpha — ThinRuntime Claude Code Parity v1 (2026-04-13)

10 phases completed (not yet released):
- Phase 1: Hook Dispatch (PreToolUse/PostToolUse/Stop/UserPromptSubmit)
- Phase 2: Tool Policy Enforcement (default-deny in ToolExecutor)
- Phase 3: LLM-Initiated Subagents (spawn_agent tool, depth/concurrency/timeout)
- Phase 4: Command Routing (/commands before LLM)
- Phase 5: Native Tool Calling (Anthropic/OpenAI/Google, Strangler Fig)
- Phase 6: Integration Validation (cross-feature tests, quality gates)
- Phase 7: Coding Profile Foundation (10 canonical tools, CodingToolPack)
- Phase 8: Coding Task Runtime (GraphTaskBoard facade, persistent snapshots)
- Phase 9: Coding Context & Compatibility (budget-aware 6 slices, alias map)
- Phase 10: Coding Subagent Inheritance (policy/hooks/config propagation)

Judge scores: 4.25 — 4.40 / 5.0

## Current

### v1.5.0 — ThinRuntime Parity v2 (2026-04-13 — in progress)

Goal: Close remaining Claude Code capability gaps. Extends Parity v1 with compaction, project instructions, session resume, web tools, multimodal, MCP resources, system reminders, worktree isolation, thinking events, background agents.

Target features (IDEA-044 — IDEA-053):
- Conversation Compaction (LLM-summarization)
- Project Instructions Loading (CLAUDE.md / AGENTS.md / RULES.md)
- Session Resume (conversation history persistence)
- Web Tools (WebSearch/WebFetch built-in)
- Multimodal Input (images, PDF, notebooks)
- MCP Resource Reading
- System Reminders (dynamic context)
- Git Worktree Isolation for subagents
- Thinking Events (separate reasoning stream)
- Background Agents + Monitor Tool
