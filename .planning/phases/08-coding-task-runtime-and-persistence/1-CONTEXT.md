# Phase 8: Coding Task Runtime and Persistence - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning
**Source:** PRD-derived from `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md`

<domain>
## Phase Boundary

Эта фаза создаёт persistent task/todo/session runtime для coding runs.

Фаза покрывает:
- один explicit task runtime owner;
- reuse `GraphTaskBoard` как backend task lifecycle;
- provider-backed todo path;
- session-to-task binding и typed snapshot roundtrip;
- fail-fast semantics при missing provider/binding.

Фаза не покрывает:
- canonical coding tool surface foundation и policy foundation, если они ещё не смёржены;
- coding context assembly;
- legacy alias compatibility layer;
- subagent inheritance and tranche-wide closure.

</domain>

<decisions>
## Implementation Decisions

### Locked decisions
- task runtime строится поверх `GraphTaskBoard + TaskSessionStore`, а не как новый engine.
- `todo_read/todo_write` в coding mode должны использовать provider-backed implementation.
- markdown shim не является допустимым production persistence path.
- task statuses: `pending`, `ready`, `in_progress`, `blocked`, `completed`, `failed`, `cancelled`.
- typed snapshots должны поддерживать resume-friendly roundtrip.
- missing provider, missing binding и unsupported resume path обязаны fail-fast.

### the agent's Discretion
- точная форма `CodingTaskRuntime` facade и snapshot dataclasses;
- где разместить adapter layer между task runtime, todo provider и session binding;
- можно ли разнести phase work на persistence facade и restart/resume closure в разные plans внутри одной фазы.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Feature specification
- `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md` — task lifecycle contract, persistence requirements, verification expectations.

### Research and planning basis
- `.memory-bank/reports/2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md` — direct reuse recommendations for `todo/tools.py`, `TaskSessionStore`, `GraphTaskBoard`.
- `.memory-bank/plans/2026-04-12_feature_thin-coding-agent-profile.md` — persistence-focused tranche decomposition and DoD.

### Project constraints
- `AGENTS.md`
- `RULES.md`
- `.planning/ROADMAP.md` — Phase 8 goal and requirements.
- `.planning/REQUIREMENTS.md` — `CTSK-*` requirements.

### Existing source-of-truth implementation files
- `src/swarmline/multi_agent/graph_task_board.py` — current lifecycle backend.
- `src/swarmline/session/task_session_store.py` — session-task binding persistence.
- `src/swarmline/todo/tools.py` — provider-backed todo tools.
- `src/swarmline/runtime/thin/builtin_tools.py` — current thin task/todo shims to be replaced or bypassed in coding path.
- `src/swarmline/session/` — current session semantics that resume path must respect.

</canonical_refs>

<specifics>
## Specific Ideas

- План должен исключать lifecycle duplication: один owner task state, один backend semantics source.
- Нужны explicit negative tests на invalid transitions и missing persistence seams.
- Если phase предполагает new typed snapshot files, acceptance criteria должны быть observable через roundtrip tests.
- В `read_first` для executor должны обязательно попасть existing graph task board and session binding files.

</specifics>

<deferred>
## Deferred Ideas

- Coding context slices based on persisted task/session state — Phase 9.
- Subagent inheritance of task context — Phase 10.
- Wider tranche hardening and non-coding regression closure — Phase 10.

</deferred>

---

*Phase: 08-coding-task-runtime-and-persistence*
*Context gathered: 2026-04-12 via PRD-derived phase context*
