---
kind: note
tags: [audit, bugfix, correctness, security, concurrency]
importance: high
created: 2026-03-30
---

# P1/P2 Audit Gaps — Plan Summary

15 issues from full v1.2.0 audit. 6 этапов, ~16 файлов, ~23 тестов.

**P1 (blocking):**
- False-green completion: pipeline/orchestrator не различает success/failure, task board state inconsistent
- ThinRuntime per-call config игнорируется для LLM path (closure captures constructor config)

**P2 (important):**
- WorkflowGraph.resume() shared mutable state в concurrent executions
- SessionManager blocks event loop (sync-over-async)
- Scheduler ignores max_concurrent_tasks
- SQLite episodic memory shared connection across threads
- Workspace path injection через agent_id/task_id
- SqliteTaskQueue O(N) full-scan on get()
- SSRF bypass via DNS/redirect, Docker no hardening, A2A no auth, MCP host exec

Plan: `plans/2026-03-30_bugfix_p1-p2-audit-gaps.md`
