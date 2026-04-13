# Project Research Summary

**Project:** Swarmline ThinRuntime Parity v2 (v1.5.0)
**Domain:** LLM Agent Framework -- Runtime Feature Expansion
**Researched:** 2026-04-13
**Confidence:** HIGH

## Executive Summary

8 of 10 features require zero new core dependencies -- the existing architecture (InputFilter protocol, RuntimeEvent pipeline, McpClient, SubagentOrchestrator) provides clean extension points. Only 2 new optional deps: `pymupdf4llm` (PDF) and `nbformat` (Jupyter). Recommended 7-phase build ordered by dependency chains and blast radius.

## Stack Additions (NEW Only)

**New optional:** `pymupdf4llm>=0.0.17` (PDF→markdown), `nbformat>=5.10` (Jupyter cells)
**Rejected:** tiktoken (OpenAI-only), watchdog (overkill), gitpython (heavy), aiofiles (unnecessary)

## Feature Classification

| Feature | Table Stakes | Differentiator |
|---------|-------------|----------------|
| Compaction | Auto-trigger + LLM summarization | 3-tier pipeline (collapse/summarize/truncate) |
| Project Instructions | Walk-up discovery + concatenation | Multi-format (CLAUDE/AGENTS/GEMINI/RULES.md) |
| Session Resume | JSONL persistence + resume-last | Auto-compact on resume |
| Web Tools | WebSearch/WebFetch builtins | Domain allow/block lists |
| Multimodal | Image support across 3 providers | PDF + Jupyter (optional extras) |
| MCP Resources | list + read protocol | Subscriptions + templates (v1.6.0+) |
| System Reminders | Conditional context injection | Priority ordering + budget cap |
| Worktree Isolation | Create/cleanup lifecycle | Stale detection + max limit |
| Thinking Events | thinking_delta event type | Multi-turn signature preservation |
| Background Agents | Spawn + notify + cancel | Monitor tool for stdout streaming |

## Recommended Build Order (7 Phases)

| Phase | Features | Rationale | Complexity |
|-------|----------|-----------|------------|
| 1 | Project Instructions + System Reminders | Zero modifications, pure InputFilter | LOW |
| 2 | Web Tools + MCP Resources | Wiring existing infrastructure | LOW-MEDIUM |
| 3 | Conversation Compaction | Must precede Session Resume | MEDIUM-HIGH |
| 4 | Session Resume | Depends on compaction + stable Message type | MEDIUM |
| 5 | Thinking Events | Additive RuntimeEvent, Anthropic-only | MEDIUM |
| 6 | Multimodal Input | Most invasive: Message type + all adapters | HIGH |
| 7 | Worktree Isolation + Background Agents | Highest complexity, schedule last | HIGH |

**Critical ordering:** Phase 3 MUST precede Phase 4 (resume without compaction = context overflow). Phase 6 MUST come after Phase 4 (multimodal changes Message serialization).

## Top 5 Pitfalls

1. **Message.content type breakage** — Add optional `content_blocks` field, keep `content: str` untouched
2. **Compaction losing tool context** — Atomic message grouping (user+assistant+tool_call+tool_result)
3. **Thinking signature loss** — Mark recent thinking blocks as non-compactable
4. **Git worktree leak** — try/finally cleanup, cleanup_stale() on startup, max 5 limit
5. **Background task exception silencing** — done_callbacks + mandatory timeout (5 min)

## Research Gaps

- Compaction summarization prompt quality (empirical testing needed)
- Provider-specific image token estimation (each provider different)
- Background agent event injection into parent run() loop
- Interleaved thinking mode (deferred to post-v1.5.0)

---
*Research completed: 2026-04-13*
*Ready for roadmap: yes*
