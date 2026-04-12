# Phase 9: Coding Context and Compatibility - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning
**Source:** PRD-derived from `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md`

<domain>
## Phase Boundary

Эта фаза добавляет coding-specific context assembly и compatibility/fail-fast wiring для legacy aliases.

Фаза покрывает:
- bounded coding context slices;
- deterministic budget discipline;
- continuity-preserving compaction behavior;
- legacy alias to canonical wiring;
- explicit failure modes вместо silent fallback.

Фаза не покрывает:
- initial coding profile foundation;
- persistent task runtime creation;
- subagent inheritance;
- tranche-wide regression closure beyond scope-local verification.

</domain>

<decisions>
## Implementation Decisions

### Locked decisions
- coding context включает только: active task, task board, workspace, recent search, session, skill/profile summaries.
- coding slices появляются только при активном coding profile.
- omission/truncation под budget pressure должна быть deterministic и testable.
- compaction должна сохранять continuity facts, нужные для resume.
- legacy aliases (`read_file`, `write_file`, `edit_file`, `execute`, `write_todos`, `task`) либо маппятся в canonical behavior, либо fail-fast.
- compatibility layer не должен становиться вторым implementation path.

### the agent's Discretion
- точная реализация `CodingContextAssembler` vs extension existing `DefaultContextBuilder`;
- нужен ли отдельный compatibility resolver module или thin runtime-local adapter;
- как разделить plans внутри фазы между context assembly и compatibility wiring без размытия semantic surface.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Feature specification
- `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md` — coding context contract, compatibility contract, verification matrix.

### Research and planning basis
- `.memory-bank/reports/2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md` — context engineering gaps, `aura` context compiler patterns, `pi-mono` tool UX patterns.
- `.memory-bank/plans/2026-04-12_feature_thin-coding-agent-profile.md` — coding context compiler tranche and fail-fast constraints.

### Project constraints
- `AGENTS.md`
- `RULES.md`
- `.planning/ROADMAP.md` — Phase 9 goal and requirements.
- `.planning/REQUIREMENTS.md` — `CCTX-*`, `COMP-*` requirements.

### Existing source-of-truth implementation files
- `src/swarmline/context/builder.py` — current budget-aware context builder.
- `src/swarmline/runtime/thin/runtime.py` — runtime wiring point for coding context and compatibility semantics.
- `src/swarmline/runtime/thin/prompts.py` — prompt/context surface that must stay coherent.
- `src/swarmline/runtime/ports/thin.py` — tool visibility layer relevant for alias exposure.
- `src/swarmline/runtime/thin/builtin_tools.py` — current legacy names/shims.

</canonical_refs>

<specifics>
## Specific Ideas

- Нужны explicit tests на presence/absence каждого slice по profile mode.
- Нужны budget stress tests с малыми лимитами и observable truncation behavior.
- Legacy alias parity нужно доказывать через policy path, result semantics и error shape, а не только через name mapping.
- Внутри плана нельзя допускать параллельные изменения schema/tool-description wiring и prompt/runtime semantic wiring без single-owner discipline.

</specifics>

<deferred>
## Deferred Ideas

- Parent-child subagent inheritance of coding context — Phase 10.
- Tranche-wide hardening and non-coding regression closure — Phase 10.

</deferred>

---

*Phase: 09-coding-context-and-compatibility*
*Context gathered: 2026-04-12 via PRD-derived phase context*
