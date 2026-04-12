# Phase 10: Coding Subagent Inheritance and Validation - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning
**Source:** PRD-derived from `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md`

<domain>
## Phase Boundary

Эта фаза закрывает coding-agent tranche: inheritance на thin subagents и tranche-level validation/no-regression closure.

Фаза покрывает:
- parent-to-child inheritance of coding profile, tools, policy, task context;
- fail-fast handling для incompatible inheritance state;
- no-regression outside coding profile;
- targeted + broader regression closure;
- final quality gates (`ruff`, `mypy`, tranche-level acceptance verification).

Фаза не покрывает:
- foundation contracts/tool pack creation;
- new persistence path creation;
- new coding context semantics вне уже созданного contract.

</domain>

<decisions>
## Implementation Decisions

### Locked decisions
- child thin subagent должен наследовать тот же coding semantic surface, что и parent.
- incompatible inheritance state не должен silently downgrade в generic thin mode.
- non-coding thin behavior и security posture обязаны остаться неизменными.
- final tranche acceptance требует targeted packs, broader regression, `ruff`, `mypy`, и pass verdict по verification gate.
- никаких новых внешних зависимостей и никаких interface expansions сверх project limits.

### the agent's Discretion
- точное место inheritance sync logic между thin subagent orchestration и runtime wiring;
- как splitнуть фазу между inheritance implementation и final validation closure, если это улучшит executable plan quality;
- какой minimal critical-path integration suite лучше всего доказывает tranche acceptance.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Feature specification
- `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md` — subagent sync contract, tranche-level verification strategy, final DoD.

### Research and planning basis
- `.memory-bank/reports/2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md` — coding engine recommendations and subagent implications.
- `.memory-bank/plans/2026-04-12_feature_thin-coding-agent-profile.md` — stabilization and release-gate style constraints.

### Project constraints
- `AGENTS.md`
- `RULES.md`
- `.planning/ROADMAP.md` — Phase 10 goal and requirements.
- `.planning/REQUIREMENTS.md` — `CSUB-*`, `CVAL-*` requirements.

### Existing source-of-truth implementation files
- `src/swarmline/orchestration/thin_subagent.py` — current thin subagent orchestration seam.
- `src/swarmline/runtime/thin/subagent_tool.py` — existing subagent tool path that must inherit coding semantics correctly.
- `src/swarmline/runtime/thin/runtime.py` — runtime-level inheritance and validation surface.
- `src/swarmline/context/` — resulting coding-context source that child must inherit.
- `src/swarmline/policy/` — resulting coding policy surface that child must inherit.

</canonical_refs>

<specifics>
## Specific Ideas

- План обязан включить explicit non-coding no-regression verification, а не только coding happy path.
- Parent/child parity нужно доказывать и по visible tools, и по executable behavior, и по policy, и по task context.
- Финальная verification часть должна ссылаться на tranche acceptance gate из feature spec, а не придумывать новую.
- Если понадобятся targeted production fixes из regression closure, они должны оставаться в уже-owned zones, без расширения scope.

</specifics>

<deferred>
## Deferred Ideas

- Additional coding-agent features beyond current spec (PathService hardening, file mutation queue, richer tracing) — отдельный future tranche.

</deferred>

---

*Phase: 10-coding-subagent-inheritance-and-validation*
*Context gathered: 2026-04-12 via PRD-derived phase context*
