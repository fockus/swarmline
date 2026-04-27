---
type: roadmap-overview
tags: [post-v1.5.0, phase-9-full, phase-10-rest, phase-11, planning-pointer]
related_features: [enterprise-multi-agent, platform-extras, openai-agents-sdk]
sprint: null
importance: medium
created: 2026-04-27
---

# post-v1.5.0-roadmap-overview
Date: 2026-04-27 01:28

Краткий entry-point для будущей сессии "что делать после v1.5.0 на PyPI". Подробности — в `plans/2026-03-18_masterplan_v3.md` (lines 462-815) и `BACKLOG.md` (IDEA-001…040). Эта заметка — навигатор + ranking, не дубликат.

## Phase 9 Full — Enterprise Multi-Agent & Tasks (~20-28 дн)

**Что осталось** (Phase 9 MVP + Knowledge Bank + Task Enhancements уже done):

- **9B-Full** `swarmline[tasks]` (~5-7 дн) — `CheckoutEngine` (atomic claim, stale adoption), `TaskSession` (context per task, не per agent), `parent_id` дерево, audit log, fulltext search.
- **9C-Full** `swarmline[multi-agent]` (~3-4 дн) — `AgentPermissions` (`can_create_agents`, `max_sub_agents`), agent creates agent с budget inheritance, cycle detection, `get_org_chart()`, config versioning.
- **9D** `swarmline[multi-agent]` (~8-12 дн) — `AgentOrchestrator` (несколько runtime'ов одновременно), `DelegationTool`, error policies (`fail_fast`/`continue_on_error`/`retry`/`fallback`), `ConcurrencyGroup`, `AggregatedResult(completed, failed, partial)`. **Самая тяжёлая часть — настоящий multi-runtime fan-out.**
- **9E-Full** `swarmline[scheduler]` (~3-4 дн) — `WakeupQueue` + `CoalescingEngine` (merge concurrent wakeups), `JitterPolicy`, orphan detection при restart, `ContextSinceLastRun`.

## Phase 10 rest — Platform extras (~12-19 дн)

**10A (CLI runtime) ✅ done.** Каждый sub-phase ниже независим, можно вытащить поодиночке.

| ID | Что | Объём | Источник |
|----|-----|-------|----------|
| 10B | MCP Multi-Transport (Stdio + StreamableHttp + tool list caching) | 3-4 дн | IDEA-014 |
| 10C | MCP Approval Policies (per-call approve/reject) — после 10B | 1-2 дн | IDEA-012 |
| 10D | Credential Proxy (multi-tenant placeholder → real key isolation) | 2-3 дн | IDEA-020 |
| 10E | OAuth Subscription Auth (Claude Pro/Max, OpenAI Plus как Codex) | 3-4 дн | IDEA-001 |
| 10F | RTK Token Optimizer (toggleable wrapper, graceful fallback) | 1-2 дн | IDEA-017 |
| **10G** | **`swarmline init` CLI (project scaffolding)** | **1-2 дн** | **IDEA-029 — TOP PICK** |
| 10H | LiteLLM Adapter (100+ providers как fallback) | 1-2 дн | IDEA-030 |

**10E ограничения:** OAuth = нет prompt caching, нет 1M context, нет `service_tier=fast` на Claude. Не замена API-ключам, дополнение для подписчиков.

## Phase 11 — OpenAI Agents SDK Integration (~11-15 дн, ⏸️ gated)

**Условие старта:** SDK ≥ v1.0 **И** Phase 6-8 done. Phase 6-8 ✅. Блокирует только версия SDK. На 2026-03-17 (ADR-001) — v0.12.3, 13+ релизов за 3 недели.

**Решение ADR-001 = опция C "Ждать v1.0".** Переоценить когда (а) SDK v1.0 выходит, ИЛИ (б) deepagents окажется недостаточным.

**Sub-phases:** 11A OpenAI Agents Runtime (4-5 дн) → 11B Session Backends Bridge (Redis/Dapr/PG, 2-3 дн) → 11C Pydantic Output + Guardrails Bridge (2-3 дн) → 11D MCP + Handoffs Bridge (3-4 дн).

**Что даёт:** native MCP с approval policies, 9 session backends, griffe schema gen.
**Что НЕ даёт:** граф-оркестрация (handoffs flat → не заменит deepagents/LangGraph), tracing lock-in в OpenAI Traces, дублирует наши абстракции.

**Pre-flight перед запуском:** 1-2 ч research-spike — проверить актуальную версию openai-agents и changelog с 2026-03-17.

## Recommendation: первый шаг после v1.5.0 на PyPI

**10G `swarmline init`** — 1-2 дня, огромный DX-эффект. Аналог `npx create-mastra@latest` / `crewai create` — у swarmline сейчас этого нет, и это заметная DX-дыра для onboarding'а. Самая дешёвая видимая win, не требует enterprise-extras пакетов и не блокирована внешними версиями.

Дальше — выбор между **9D delegation** (если приходят клиенты с multi-agent use cases) и **Production v2.0 Sprints 2-6** (если приоритет — стабильность платформы).
