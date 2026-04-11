# Plan

## Текущий приоритет
**v1.4.0 Release Candidate** — validation gate completed on `main`; next step is external publish/tag workflow.

## Активный план

**Release publication** — tag/publish `v1.4.0` and announce the secure-by-default tranche.

## Следующий шаг

**Next engineering tranche** → performance/load hardening after `v1.4.0` publication.

### Iteration 1 (highest ROI):
1. QW-1/2/3: py.typed, badges, deprecation cleanup
2. **11.1** OTel Exporter
3. **11.2** Structured Output (Pydantic-level)
4. **12.1** `cognitia init` CLI
5. **12.3** API Docs + Community infra

### Iteration 2 (differentiation):
6. **13.1** Eval Framework Core
7. **12.2** Production Templates (5 шт)
8. **15.1** `cognitia serve` HTTP API

### Iteration 3 (advanced):
9. **11.3** A2A Protocol
10. **15.2** HITL Patterns
11. **14.1** Episodic Memory
12. **14.2** Procedural Memory

### Iteration 4 (polish):
13. **13.2** Eval Compare
14. **14.3** Memory Consolidation
15. **15.3** Plugin Registry
16. **15.4** Benchmarks

## Направление
cognitia = **простая библиотека** (не фреймворк) для AI агентов.
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
