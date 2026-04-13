# Plan

## Текущий приоритет

**ThinRuntime Claude Code Parity v1** — COMPLETE (10 фаз). Следующий: v1.5.0 release + **Parity v2** (расширенные возможности).

Завершённый план: `plans/2026-04-12_feature_thin-runtime-claude-code-parity.md`
GSD Roadmap: `.planning/ROADMAP.md`

## Следующий шаг

1. **v1.5.0 release** — version bump + CHANGELOG + sync to public repo
2. **ThinRuntime Parity v2** — 10 новых идей в бэклоге (IDEA-044 — IDEA-053)

## Релизный контекст

**v1.4.1** опубликован на PyPI (swarmline). Следующий release: **v1.5.0** после завершения ThinRuntime parity.

## Активный план

| Phase | Название | Приоритет | Статус |
|-------|----------|-----------|--------|
| 1 | Hook Dispatch в ThinRuntime | P0 | ✅ |
| 2 | Tool Policy Enforcement | P0 | ✅ |
| 3 | LLM-Initiated Subagents | P1 | ✅ |
| 4 | Command Routing | P2 | ✅ |
| 5 | Native Tool Calling | P2 | ✅ |
| 6 | Integration Validation | P3 | ✅ |
| 7 | Coding Profile Foundation | P2 | ✅ |
| 8 | Coding Task Runtime and Persistence | P2 | ✅ |
| 9 | Coding Context and Compatibility | P2 | ✅ |
| 10 | Coding Subagent Inheritance and Validation | P3 | ✅ |

### ThinRuntime Parity v2 — Claude Code Gap Closure (IDEA-044 — IDEA-053)

**Tier 1 — Critical (закрывают самые заметные gaps):**
| # | IDEA | Название | Сложность |
|---|------|----------|-----------|
| 1 | 044 | Conversation Compaction (LLM-суммаризация) | Medium |
| 2 | 045 | Project Instructions Loading (CLAUDE.md) | Low |
| 3 | 046 | Session Resume (conversation history) | Medium |
| 4 | 047 | Web Tools (WebSearch/WebFetch built-in) | Low |

**Tier 2 — Important (полноценный coding agent):**
| # | IDEA | Название | Сложность |
|---|------|----------|-----------|
| 5 | 048 | Multimodal Input (images, PDF, notebooks) | High |
| 6 | 049 | MCP Resource Reading | Low |
| 7 | 050 | System Reminders (dynamic context) | Medium |
| 8 | 051 | Git Worktree Isolation для субагентов | Medium |

**Tier 3 — Nice-to-have:**
| # | IDEA | Название | Сложность |
|---|------|----------|-----------|
| 9 | 052 | Thinking Events (отдельный reasoning поток) | Low |
| 10 | 053 | Background Agents и Monitor Tool | Medium |

### Ecosystem Iterations (из masterplan v3):

#### Iteration 1 (highest ROI):
1. QW-1/2/3: py.typed, badges, deprecation cleanup
2. **11.1** OTel Exporter
3. **11.2** Structured Output (Pydantic-level)
4. **12.1** `swarmline init` CLI
5. **12.3** API Docs + Community infra

#### Iteration 2 (differentiation):
6. **13.1** Eval Framework Core
7. **12.2** Production Templates (5 шт)
8. **15.1** `swarmline serve` HTTP API

#### Iteration 3 (advanced):
9. **11.3** A2A Protocol
10. **15.2** HITL Patterns
11. **14.1** Episodic Memory
12. **14.2** Procedural Memory

#### Iteration 4 (polish):
13. **13.2** Eval Compare
14. **14.3** Memory Consolidation
15. **15.3** Plugin Registry
16. **15.4** Benchmarks

## Направление
swarmline = **простая библиотека** (не фреймворк) для AI агентов.
- Core (Phases 6-8): ✅ DONE → v1.0.0-core
- Enterprise extras (Phase 9): tasks, hierarchy, delegation, scheduler
- Platform (Phase 10): CLI, MCP, plugins
- Ecosystem (Phase 11): OpenTelemetry, Structured Output, A2A
- Evaluation (Phase 13): Agent eval framework
- Advanced Memory (Phase 14): Episodic, Procedural, Consolidation
- Deployment (Phase 15): serve, HITL, plugins, benchmarks

## Ключевые изменения v3 vs v2
- Core/Enterprise разделение (optional extras)
- 9B/9C/9E: MVP + Full уровни
- Ложные зависимости убраны (9E⊬10A, 9C⊬9B, 9A⊬7A)
- 10A/10B стартуют на 8 недель раньше
- RuntimeConfig → composition (typed groups)
- Migration plan для legacy (RuntimePort, SessionManager)
- Error handling strategy для multi-agent
- API Stability plan → semver после v1.0-core

## Завершено
- ✅ Phase 0-4: upstream middleware + multi-provider ThinRuntime (v0.5.0)
- ✅ Phase 6: DX Foundation (structured output, @tool, registry, cancel, typed events)
- ✅ Phase 7: Production Safety (cost budget, guardrails, input filters, retry/fallback)
- ✅ Phase 8: Persistence & UI (sessions, event bus, tracing, UI projection, RAG)
