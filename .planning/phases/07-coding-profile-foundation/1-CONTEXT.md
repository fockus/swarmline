# Phase 7: Coding Profile Foundation - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning
**Source:** PRD-derived from `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md`

<domain>
## Phase Boundary

Эта фаза создаёт foundation для `coding-agent profile` поверх существующего `ThinRuntime` без создания нового runtime hierarchy.

Фаза покрывает:
- public/internal contract spine для coding-profile;
- canonical coding tool pack;
- profile-scoped policy wiring;
- единую semantic surface между visible tools и executable tools;
- сохранение secure-by-default поведения вне coding profile.

Фаза не покрывает:
- persistent task/todo/session adapters;
- coding context assembly;
- subagent inheritance;
- tranche-wide hardening beyond targeted foundation verification.

</domain>

<decisions>
## Implementation Decisions

### Locked decisions
- `ThinRuntime` расширяется через opt-in profile, а не через новый runtime.
- canonical source of truth для coding tools: `src/swarmline/tools/builtin.py`.
- canonical source of truth для todo tools: `src/swarmline/todo/tools.py`.
- visible tool surface и executable tool surface должны собираться из одного canonical builder.
- `claw-code-agent` остаётся reference-only до отдельного подтверждения лицензии.
- default-deny outside coding profile не меняется.
- coding profile разрешает только явно объявленный allow-list инструментов.
- новые seams должны быть contract-first и не шире 5 методов.
- fail-fast обязателен для unknown profile, tool leakage и wiring drift.

### the agent's Discretion
- точная форма `CodingProfileConfig` и связанных dataclass/protocol seams;
- разбиение foundation на 1 или несколько executable plans внутри фазы;
- naming внутренних helper modules при сохранении публичного contract;
- точное место policy profile registration при условии соблюдения existing architecture.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Feature specification
- `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md` — source-of-truth по scope, acceptance criteria, contracts, implementation steps, verification strategy.

### Research and planning basis
- `.memory-bank/reports/2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md` — reuse matrix, direct-reuse boundaries, legal constraints for `claw-code-agent`.
- `.memory-bank/plans/2026-04-12_feature_thin-coding-agent-profile.md` — tranche decomposition, rule gates, phase-level DoD and risks.

### Project constraints
- `AGENTS.md` — repository workflow and coding rules.
- `RULES.md` — TDD-first, contract-first, clean architecture, fail-fast constraints.
- `.planning/ROADMAP.md` — phase goal and requirement IDs for Phase 7.
- `.planning/REQUIREMENTS.md` — `CADG-*` requirements.

### Existing source-of-truth implementation files
- `src/swarmline/tools/builtin.py` — canonical builtin coding tools.
- `src/swarmline/todo/tools.py` — provider-backed todo tool implementations.
- `src/swarmline/runtime/thin/runtime.py` — current ThinRuntime integration point.
- `src/swarmline/runtime/thin/builtin_tools.py` — existing thin builtin tool surface.
- `src/swarmline/runtime/ports/thin.py` — current active tool exposure path.
- `src/swarmline/policy/tool_policy.py` — default-deny baseline that must remain intact outside coding profile.

</canonical_refs>

<specifics>
## Specific Ideas

- Закрепить `CodingProfileConfig`, `CodingTaskRuntime`, `CodingContextAssembler`, `PathService` seams в typed form, но не реализовывать task/context phases здесь целиком.
- В этой фазе желательно закрыть requirement coverage для `CADG-01..05` одним coherent plan set.
- Tool surface должен явно включать `read`, `write`, `edit`, `multi_edit`, `bash`, `ls`, `glob`, `grep`; todo/task persistence paths допускаются только как contract hooks, не как завершённая persistence implementation.
- `write_todos` / `task` stub behavior не должен оставаться в active coding path foundation outcome.

</specifics>

<deferred>
## Deferred Ideas

- Full persistent task/todo/session semantics — Phase 8.
- Coding context slices and compaction — Phase 9.
- Legacy compatibility wiring and subagent inheritance closure beyond foundation minimum — Phases 9-10.

</deferred>

---

*Phase: 07-coding-profile-foundation*
*Context gathered: 2026-04-12 via PRD-derived phase context*
