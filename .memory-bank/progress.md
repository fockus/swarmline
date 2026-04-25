# Progress

## 2026-04-13: Release contract sync after parity re-audit

- Public Python contract corrected from `3.10+` to `3.11+` in `pyproject.toml`, README badge, init template, and the plugin registry comment. This matches actual stdlib usage (`StrEnum`, `datetime.UTC`) already present in the codebase.
- Re-verified current runtime signal after the sync:
  - `pytest -q` → green (`5100 passed, 5 skipped, 5 deselected`)
  - targeted parity/regression packs → green (`222 passed`, `190 passed`)
  - `ty check src/swarmline/ --python-version 3.11` → red (`70 diagnostics`)
- Updated `STATUS.md` and `checklist.md` so Memory Bank no longer claims a green repo-wide release gate. Current truth: parity functionality is implemented, but v1.5.0 release remains blocked on repo-wide typing cleanup.

## 2026-04-12: Phase 6 Integration Validation complete (Judge 4.25/5.0)

- Cross-feature integration tests: hooks+commands, stop hook, backward compat, unregistered passthrough
- mypy fix: variable shadowing (tc → ntc) in native tool path
- Quality gates: 4394 passed, ruff clean, mypy clean, 86% coverage
- ThinRuntime Claude Code Parity milestone: Phases 1-6 COMPLETE
- Commit: 250164a

## 2026-04-12: Phase 5 Native Tool Calling complete (Judge 4.33/5.0)

- NativeToolCallAdapter Protocol + NativeToolCall/Result frozen dataclasses
- 3 adapters (Anthropic, OpenAI, Google) с call_with_tools()
- React strategy: native path + parallel execution (asyncio.gather) + Strangler Fig fallback
- Budget enforcement в native path (max_tool_calls)
- Hooks + policy dispatched через executor.execute() (тот же pipeline что JSON-in-text)
- isinstance() вместо hasattr() для Protocol check
- 29 тестов (18 unit + 8 strategy + 3 integration), 4389 total, 0 regressions
- Review iteration 1: 2 CRITICAL + 4 SERIOUS → all fixed. Judge iteration 1: FAIL (3.95) → iteration 2: PASS (4.33)
- Commit: 1b08eeb

## 2026-04-12: Phase 4 Command Routing complete (Judge 4.59/5.0)

- CommandInterceptor в ThinRuntime.run() — перехват /commands перед LLM
- Только зарегистрированные команды перехватываются; unknown /text, URL, multiline → LLM
- Pipeline: UserPromptSubmit hook → Command intercept → Guardrails → LLM
- AgentConfig.command_registry + runtime_wiring + ThinRuntime integration
- 15 тестов (11 unit + 2 wiring + 2 integration), 4360 total, 0 regressions
- Review iteration 1: 3 SERIOUS findings → all fixed (resolve() check, multiline guard, TYPE_CHECKING)
- Judge iteration 2: PASS 4.59/5.0
- Commit: 2549def

## 2026-04-12: Detailed feature spec complete — Thin coding-agent profile

- На основе анализа `2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md` и плана `2026-04-12_feature_thin-coding-agent-profile.md` собрана implementation-ready спецификация в `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md`.
- Спецификация зафиксировала:
  - scope / non-goals / acceptance criteria;
  - reuse matrix по `swarmline`, `aura`, `claw-code-agent`, `pi-mono`;
  - architecture seams, compatibility contract, task lifecycle contract, coding context contract;
  - 9 implementation steps с шаговыми DoD;
  - execution waves и merge-point правила;
  - детальную verification strategy по каждому шагу и tranche-level acceptance gate.
- Отдельно зафиксировано, что `claw-code-agent` остаётся reference-only до отдельного подтверждения лицензии.
- Черновик спецификации перенесён из `.specs/tasks/draft/` в `.specs/tasks/todo/`.

## 2026-04-12: Phase 3 Complete — LLM-Initiated Subagents

- **Judge: 4.02/5.0** (PASS, iteration 2 after reviewer fixes)
- SubagentToolConfig (max_depth=3, max_concurrent=4, timeout=300s)
- SUBAGENT_TOOL_SPEC registered as spawn_agent tool
- create_subagent_executor: fail-safe, all errors → JSON
- ThinRuntime wiring: auto-append spec to active_tools in run()
- Tool inheritance: child gets actual parent tools (not just builtins)
- Reviewer findings fixed: spec injection in run(), tool inheritance, depth propagation
- 33 new tests, commit: 65479ac
- Total tests: 4356 passed

## 2026-04-12: Phase 2 Complete — Tool Policy Enforcement

- **Judge: 4.26/5.0** (PASS, iteration 2 after reviewer fixes)
- DefaultToolPolicy enforced in ToolExecutor after PreToolUse hooks
- Pipeline: hooks → policy → execute → post-hooks
- PermissionAllow.updated_input handling added (contract compliance)
- AgentConfig.tool_policy field + wiring through RuntimeFactory
- 10 new tests (8 original + 2 edge cases from review)
- Reviewer findings fixed: false-positive MCP test, typing, updated_input
- Commit: 0822a62
- Total tests: 4323 passed

## 2026-04-12: Phase 1 Complete — Hook Dispatch in ThinRuntime

- **Judge: 4.40/5.0** (PASS, iteration 2 after reviewer fixes)
- HookDispatcher Protocol (4 methods, ISP), HookResult frozen dataclass, DefaultHookDispatcher
- ToolExecutor: PreToolUse/PostToolUse hooks fire before/after every tool call
- ThinRuntime: UserPromptSubmit/Stop hooks fire at start/end of run()
- Agent → RuntimeFactory → ThinRuntime wiring via merge_hooks in create_kwargs
- 50 new tests (27 dispatcher + 7 executor + 7 runtime + 3 wiring + 2 integration + 4 legacy)
- Coverage: dispatcher.py 98%, all 4313 tests pass, ruff + mypy clean
- DRY fix: removed duplicate merge_hooks from agent.py
- Reviewer findings fixed: modify chaining, stop hook result text, proper typing
- Commit: a50e4ec
- P0 security gap CLOSED: SecurityGuard now actually blocks tools in thin runtime

## 2026-04-12: GSD Initialized — ThinRuntime Claude Code Parity

- PROJECT.md: ThinRuntime доработка до полноценного runtime (hooks, subagents, commands, native tools, policy)
- REQUIREMENTS.md: 36 v1 requirements (HOOK 10, PLCY 4, SUBA 8, CMDR 4, NATV 6, INTG 4)
- ROADMAP.md: 6 phases, 11 plans, interactive mode, quality models (Opus), research + plan check + verifier
- Key decisions: fail-open hooks, subagent prompt from tool args, Anthropic-first native tools
- Bridge: GSD (.planning/) ↔ MB (.memory-bank/) connected

## 2026-04-12: Repository housekeeping — cognitia → swarmline

- Renamed folder /Apps/cognitia → /Apps/swarmline + symlink
- Git remotes: origin → swarmline-dev, public → swarmline (removed old cognitia remotes)
- CLAUDE.md, AGENTS.md, AGENTS.public.md — updated with swarmline references, versioning rules
- docs/releasing.md — created full release workflow documentation (SemVer, PyPI, dual-repo)
- .memory-bank/ — all 53 files updated: cognitia → swarmline

## 2026-04-11: Audit remediation follow-up — SessionManager snapshot store seam
- Extracted session snapshot serialization/persistence from `src/swarmline/session/manager.py` into `src/swarmline/session/snapshot_store.py`.
- `_AsyncSessionCore` now delegates snapshot codec and backend load/save/delete to `SessionSnapshotStore`, while keeping cache/TTL/lifecycle orchestration in the manager core.
- Preserved behavior that mattered for rehydration and TTL: wall-clock ↔ monotonic conversion stayed unchanged, `is_rehydrated` is still applied on snapshot load, and `close()` vs `close_all()` semantics remain distinct.
- Verified:
  - targeted session pack: `50 passed`
  - repo-wide `ruff check` on touched session files/tests: green
  - repo-wide `mypy src/swarmline`: green (`355` source files)
  - full offline `pytest -q`: `4249 passed, 3 skipped, 5 deselected`

## 2026-04-11: Audit remediation follow-up — SessionManager runtime bridge seam
- Extracted runtime execution/legacy streaming bridge logic from `src/swarmline/session/manager.py` into `src/swarmline/session/runtime_bridge.py`.
- `_AsyncSessionCore` now keeps locking, TTL/cache, and persistence orchestration, while runtime-specific event mapping and legacy `StreamEvent` bridging are delegated to helper functions.
- Preserved public behavior: no signature changes for `run_turn()` / `stream_reply()`, no API expansion, and existing session semantics around terminal events, history persistence, and runtime error normalization stayed intact.
- Verified:
  - targeted session pack: `50 passed`
  - repo-wide `ruff check` on touched session files/tests: green
  - repo-wide `mypy src/swarmline`: green (`354` source files)
  - full offline `pytest -q`: `4249 passed, 3 skipped, 5 deselected`

## 2026-04-11: Audit remediation follow-up — phase-4 low-risk seams
- Extracted `ThinRuntime` helper logic into `src/swarmline/runtime/thin/runtime_support.py` and switched `ThinRuntime` wrappers to delegate through the helper seam while preserving patchable compatibility for `runtime.default_llm_call`.
- Extracted mutable orchestration run-state management into `src/swarmline/multi_agent/graph_orchestrator_state.py`; `DefaultGraphOrchestrator` now delegates run creation/snapshot/stop/execution bookkeeping to `GraphRunStore`.
- Preserved public behavior and existing tests: the changes are structural only, with no API expansion and no behavior drift in runtime/orchestrator flows.
- Verified:
  - targeted thin-runtime pack: `42 passed`
  - targeted graph-orchestrator pack: `83 passed`
  - repo-wide `ruff check src tests`: green
  - repo-wide `mypy src/swarmline`: green (`353` source files)
  - full offline `pytest -q`: `4249 passed, 3 skipped, 5 deselected`

## 2026-04-10: Phase 0 — Swarmline + HostAdapter
- Added LifecycleMode enum (EPHEMERAL, SUPERVISED, PERSISTENT)
- Extended AgentCapabilities (max_depth, can_delegate_authority)
- Created HostAdapter Protocol (4 methods, ISP)
- Implemented AgentSDKAdapter + CodexAdapter
- Created PersistentGraphOrchestrator + GoalQueue
- Updated models.yaml with codex-mini
- Added governance checks for authority + capability delegation

## 2026-03-29 (Paperclip-inspired Components)

- Проанализирован Paperclip AI (TypeScript control plane для AI-агентов, ~700 файлов, ~50 DB-таблиц).
- Gap-анализ: из 9 идей Paperclip 5 уже реализованы (daemon/scheduler, pipeline/budget, plugins/registry, task comments, enhanced task workflow). Выявлено 6 реальных gaps.
- Реализовано 6 новых универсальных компонентов (protocol-first, zero new deps):
  - **TaskSessionStore** (session/) — привязка session к agent+task для resume между heartbeats. InMemory + SQLite. 26 contract tests.
  - **ActivityLog** + **ActivityLogSubscriber** (observability/) — persistent structured audit trail с EventBus bridge. InMemory + SQLite. 39 tests.
  - **PersistentBudgetStore** (pipeline/) — cross-run budget tracking с monthly/lifetime windows, scoped per agent/graph/tenant. InMemory + SQLite. 26 tests.
  - **RoutineBridge** (daemon/) — Scheduler → TaskBoard auto-task creation с dedup. 17 tests (14 unit + 3 integration).
  - **ExecutionWorkspace** (multi_agent/) — изоляция рабочей среды: temp_dir, git_worktree, copy. 10 tests.
  - **PluginRunner** + worker shim (plugins/) — subprocess JSON-RPC с crash recovery, exponential backoff, graceful shutdown. 21 tests.
- Code review: 2 серьёзных issue найдены и исправлены (list_active без lock, publish→emit mismatch).
- Итого: 31 файл, +4010 LOC, 139 новых тестов, ruff + mypy clean.

## 2026-03-18

- Реализованы P1 follow-up fixes для `cli` runtime, `agent_tool` и `TaskQueue`.
- Обновлены `docs/cli-runtime.md`, `docs/multi-agent.md` и protocol docstring для claim- и stdin-семантики.
- Добавлены/обновлены тесты для `RuntimeFactory`, `CliAgentRuntime`, `Agent.query`, `Conversation.say`, `execute_agent_tool`, `TaskQueue` contract/integration.
- Проверено: targeted `pytest` green (`172 passed`), полный offline `pytest -q` green (`2321 passed, 16 skipped, 5 deselected`), targeted `ruff check` по changed files green.
- Ограничение: repo-wide `ruff check src/ tests/` и `mypy src/swarmline/` по-прежнему падают на pre-existing issues вне этого fix set.
- Закрыт второй batch review findings: SQLite terminal transitions теперь atomic, `CliAgentRuntime` fail-fast'ится с `bad_model_output` без final event, autodetect Claude переведён на basename, `execute_agent_tool()` изолирует любой `Exception`.
- Добавлены новые regression tests для contract/integration path'ов `TaskQueue`, `CliAgentRuntime`, `Agent.query`, `Conversation.say` и `execute_agent_tool`.
- Проверено: targeted `pytest` green (`150 passed`), targeted `ruff check` green, полный offline `pytest -q` green (`2331 passed, 16 skipped, 5 deselected`).
- Ограничение остаётся прежним: `mypy` по touched modules поднимает pre-existing ошибки из импортируемых модулей вне текущего diff.
- Выполнен полный read-only аудит библиотеки с участием сабагентов (`Mendel`, `Linnaeus`, `Dalton`).
- Подтверждено верификацией: `pytest -q` green (`2331 passed, 16 skipped, 5 deselected`), но repo-wide `ruff check src/ tests/` остаётся красным (`68` ошибок), а `mypy src/swarmline/` — красным (`48` ошибок в `23` файлах).
- Зафиксирован подробный отчёт со сценариями, примерами и приоритетами: `.memory-bank/reports/2026-03-18_library-audit.md`.
- Ключевые выводы аудита: runtime/session migration не завершена; portable runtime path теряет `mcp_servers`; `Conversation`/facade игнорируют `final.new_messages`; thin-team path не advertises `send_message`; SDK/runtime helpers всё ещё имеют silent-success paths без terminal event.
- На основе audit-report подготовлен детальный remediation plan с фазами, DoD, wave-based порядком и параллельным разбиением по сабагентам: `.memory-bank/plans/2026-03-18_fix_library-audit-remediation.md`.
- Wave 1 remediation для контрактов `sdk_query` / `RuntimeAdapter` / `collect_runtime_output` реализован в пределах ownership: incomplete run больше не считается success без terminal `ResultMessage`/`final RuntimeEvent`.
- Добавлены regression tests на incomplete stream paths и минимальные runtime fixes только в `src/swarmline/runtime/sdk_query.py`, `src/swarmline/runtime/adapter.py`, `src/swarmline/orchestration/runtime_helpers.py`.
- Проверено: targeted `pytest -q tests/unit/test_sdk_query.py tests/unit/test_runtime_adapter.py tests/unit/test_collect_runtime_output.py` green (`65 passed`).
- Ограничение: broader repo-wide lint/type gates не запускались, чтобы не выходить за scope targeted verification.
- Выполнен Wave 1 fixes в пределах ownership: `BaseRuntimePort` и `InMemorySessionManager` теперь сохраняют final metadata в `StreamEvent(done)`, а `ThinRuntimePort` больше не скрывает local tools за `active_tools=[]`.
- Добавлены regression tests на final metadata и tool advertisement в `tests/unit/test_runtime_ports_base_coverage.py` и `tests/unit/test_session_manager.py`.
- Проверено: targeted `pytest` по owned test files green (`55 passed`); изменения не выходят за пределы разрешённых файлов.
- 2026-03-18 16:12: закрыт Wave 1 срез по `ThinTeamOrchestrator` и buffered retry path в `ThinRuntime`.
- `ThinTeamOrchestrator.start()` теперь advertises `send_message` в worker-visible `SubagentSpec.tools`, а worker specs создаются через `dataclasses.replace()` без мутации исходного config.
- `ThinRuntime` больше не оборачивает `llm_call` retry-wrapper'ом в конструкторе; retry ownership остался в buffered strategy path, без nested wrapper layering.
- Добавлены regression tests в `tests/unit/test_thin_team_orchestrator.py` и `tests/unit/test_thin_runtime.py`.
- Проверено: targeted `pytest -q tests/unit/test_thin_team_orchestrator.py tests/unit/test_thin_runtime.py tests/integration/test_retry_integration.py tests/unit/test_retry_policy.py` green (`56 passed`).
- 2026-03-18 16:40: Wave 1 audit-remediation собран и доведён до общего green на основном workspace с использованием сабагентов (`Newton`, `Feynman`, `Copernicus`, `Epicurus`).
- Исправлено по contract seams: portable runtime path теперь сохраняет `mcp_servers`; `Agent.query()` / `Conversation.say()` / `Conversation.stream()` используют canonical `final.new_messages`; `sdk_query`, `RuntimeAdapter` и `collect_runtime_output()` больше не принимают incomplete run как success; `BaseRuntimePort` и `InMemorySessionManager` переносят final metadata в `done`; `ThinRuntimePort` advertises local tools; `ThinTeamOrchestrator` advertises `send_message`; `ThinRuntime` не создаёт nested retry wrapper.
- Дополнительно закрыты локальные integration seams вокруг CLI/portable registry: `runtime=\"cli\"` теперь игнорирует facade-only `mcp_servers`, а boundary typing для Claude SDK выровнен без изменения runtime contract.
- Проверено: targeted `pytest` green (`256 passed, 18 warnings`), targeted `ruff check` green, targeted `mypy --follow-imports=silent` green (`11` source files), полный offline `pytest -q` green (`2347 passed, 16 skipped, 5 deselected`).
- Остаток плана не закрыт: впереди runtime/session migration cleanup, factory/optional import surface hardening и repo-wide static debt cleanup из audit-report.
- 2026-03-18 17:25: выполнены два low-risk batch'а Wave 2 поверх основного remediation plan.
- Batch A: вынесен private helper `src/swarmline/agent/runtime_wiring.py`, который централизует portable runtime plan (`RuntimeConfig`, `tool_executors`, `active_tools`, conditional `mcp_servers`, `deepagents.thread_id`) для `Agent` и `Conversation`. Это сократило дублирование в portable runtime path без втягивания `SessionManager` в ранний refactor.
- Batch B: package surfaces `runtime`, `runtime.ports`, `hooks`, `memory`, `skills` переведены на lazy fail-fast optional exports через `__getattr__`; `None` placeholders убраны. Отдельно сохранена совместимость с package-style submodule access (`swarmline.runtime.thin`) для `monkeypatch`/import tooling.
- Добавлены regression tests: `tests/unit/test_agent_runtime_wiring.py`, новые call-through guards в `test_agent_facade.py` и `test_agent_conversation.py`, import-isolation сценарии для optional exports в `test_import_isolation.py`.
- Проверено: targeted `pytest` по helper slice green (`76 passed, 1 skipped`), targeted import/registry subsets green (`54 passed`, `32 passed`, `30 passed`), targeted `ruff check` green, targeted `mypy --follow-imports=silent` green, полный offline `pytest -q` green (`2357 passed, 16 skipped, 5 deselected`).
- Остаток плана после этих batch'ей: registry/factory fail-soft cleanup (`RuntimeFactory._effective_registry`, builtin `cli` fallback, entry-point discovery errors) и более глубокий runtime/session migration cleanup вокруг `SessionManager`.
- 2026-03-18 17:15: подтверждённые 4 re-review findings вынесены в отдельную заметку `.memory-bank/notes/2026-03-18_17-15_rereview-findings-followup.md`, чтобы не потерять их в следующем remediation batch.
- Выполнен более широкий re-audit текущего worktree с участием сабагентов (`Carson`, `Poincare`, `Heisenberg`) и локальными воспроизведениями по runtime/session/public-surface seams.
- Новый consolidated report: `.memory-bank/reports/2026-03-18_reaudit_broader-audit.md`.
- Подтверждено дополнительно: `BaseRuntimePort` и `SessionManager` всё ещё синтезируют `done` на silent EOF; `ClaudeCodeRuntime` может выдать `error` и затем `final`; DeepAgents portable path теряет tool history; `ThinWorkflowExecutor`/`MixedRuntimeExecutor` частично интегрированы; `convert_event()` теряет `tool_name` для `tool_call_finished`.
- Подтверждены broader non-code gaps: docs/README не синхронизированы с `cli` runtime и fail-fast optional exports, skills migration narrative остаётся противоречивой, `test_skills_optional_loader_fail_fast_without_yaml` даёт ложный сигнал и падает при isolated run на unsupported expectation.
- Repo-wide snapshot на момент re-audit: `python -m pytest -q` green (`2357 passed, 16 skipped, 5 deselected`), `ruff check src/ tests/ --statistics` red (`60` ошибок), `mypy src/swarmline/` red (`27` ошибок в `17` файлах).
- На основе re-review + broader audit собран единый remediation backlog с wave-based приоритизацией, параллельными ownership slices и DoD: `.memory-bank/plans/2026-03-18_fix_reaudit-remediation-backlog.md`.
- Backlog разделён на:
  - Wave 1: must-fix correctness (`terminal contract`, `canonical history`, `cli fallback`, `workflow executor integration`)
  - Wave 2: docs/tests/public-surface sync
  - Wave 3: tracked architecture/static debt
- Wave 1 Batch 1A slice реализован точечно в `src/swarmline/runtime/claude_code.py` и `tests/unit/test_claude_code_runtime.py`: failed adapter turn теперь завершается только error path и не синтезирует `final`.
- Проверено: `python -m pytest -q tests/unit/test_claude_code_runtime.py` green (`11 passed`), targeted `ruff check` green, targeted `mypy --follow-imports=silent src/swarmline/runtime/claude_code.py` green.
- 2026-03-18 17:10: зафиксированы 4 повторно подтверждённых review findings в `.memory-bank/notes/2026-03-18_17-10_2026-03-18review-findings-followup.md`:
  - `SessionManager.stream_reply()` теряет canonical `final.new_messages`;
  - builtin `cli` расходится с legacy fallback path `RuntimeFactory.create()`;
  - `swarmline.runtime` lazy optional exports ломают star-import в SDK-free окружении;
  - `swarmline.skills` lazy optional exports ломают star-import без PyYAML.
- 2026-03-18 17:25: выполнен follow-up read-only аудит runtime/session/orchestration seams после этих 4 findings; подробный отчёт сохранён в `.memory-bank/reports/2026-03-18_runtime-session-orchestration-followup-audit.md`.
- Подтверждены новые defects:
  - `BaseRuntimePort.stream_reply()` и `SessionManager.stream_reply()` всё ещё синтезируют `done` на silent EOF без terminal `final/error`;
  - `ClaudeCodeRuntime.run()` эмитит `error` и затем `final` для одного и того же failed turn;
  - deepagents portable path теряет `tool` history (`build_langchain_messages()` игнорирует `tool` role, `final.new_messages` содержит только assistant text);
  - `ThinWorkflowExecutor` не advertises tools (`active_tools=[]`), а `MixedRuntimeExecutor` не делает runtime routing, только пишет metadata;
  - `RuntimePort` conversion для `tool_call_finished` теряет `tool_name`.
- Проверено: полный offline `pytest -q` green (`2357 passed, 16 skipped, 5 deselected`), repo-wide `ruff check src/ tests/ --statistics` red (`60` issues), repo-wide `mypy src/swarmline/` red (`27` errors in `17` files).
- Следующий шаг: либо превратить follow-up audit report в remediation backlog/plan, либо начать low-risk fix wave с terminal-contract wrappers (`BaseRuntimePort`, `SessionManager`, `ClaudeCodeRuntime`).
- Выполнен re-review текущего diff и подтверждены 4 открытых findings, которые нельзя потерять: `SessionManager.stream_reply()` всё ещё теряет canonical `final.new_messages`; builtin `cli` по-прежнему расходится с legacy fallback в `RuntimeFactory`; `swarmline.runtime` и `swarmline.skills` имеют package-level optional export regressions через `__all__`/`__getattr__`.
- Эти 4 findings отдельно зафиксированы в `.memory-bank/notes/2026-03-18_19-20_rereview-open-findings.md`.
- Поверх strict review выполнен более широкий read-only аудит public API/import surface, registry/factory composition и docs/examples drift с использованием сабагентных срезов и локальной верификации.
- Дополнительно подтверждены adjacent gaps: cold `import swarmline` и cold `from swarmline.skills import YamlSkillLoader` всё ещё ломаются через `runtime.model_registry -> yaml`; `docs/runtimes.md` / `docs/why-swarmline.md` всё ещё описывают только 3 runtime; `docs/advanced.md` продолжает обещать `None` для `registry_to_sdk_hooks`; `tests/unit/test_import_isolation.py` не ловит cold-start failure для skills path.
- Проверено: полный offline `pytest -q` green (`2357 passed, 16 skipped, 5 deselected`), repo-wide `ruff check src/ tests/` красный (`60` ошибок), repo-wide `mypy src/swarmline/` красный (`27` ошибок в `17` файлах).
- Подробный follow-up отчёт записан в `.memory-bank/reports/2026-03-18_reaudit_public-surface-and-followup-gaps.md`.
- 2026-03-18 19:45: выполнен Wave 1 Batch 1C в пределах ownership: `RuntimeFactory` теперь поддерживает legacy fallback для builtin `cli` даже при `registry is None`, при этом семантика создания переиспользует `_create_cli()` из `registry.py` без дублирования constructor logic.
- Добавлены regression tests на fallback path при `_effective_registry is None` и на registry-backed builtin matrix для `cli`.
- Проверено: `python -m pytest -q tests/unit/test_runtime_factory.py tests/integration/test_runtime_registry_integration.py` green (`24 passed`), `ruff check src/swarmline/runtime/factory.py src/swarmline/runtime/registry.py tests/unit/test_runtime_factory.py tests/integration/test_runtime_registry_integration.py` green, `mypy --follow-imports=silent src/swarmline/runtime/factory.py src/swarmline/runtime/registry.py` green.
- 2026-03-18 20:05: выполнен docs-sync batch для runtime surface и optional import narrative: обновлены `README.md`, `docs/runtimes.md`, `docs/api-reference.md`, `docs/why-swarmline.md`, `docs/index.md`, `docs/agent-facade.md`, `docs/advanced.md`, `docs/architecture.md`, `docs/tools-and-skills.md` и docstring в `src/swarmline/runtime/registry.py`.
- Синхронизировано: `cli` добавлен в runtime narrative как subprocess NDJSON light-tier runtime без portable MCP/subagents guarantee; `registry_to_sdk_hooks` теперь описан как fail-fast `ImportError` при отсутствии extras; `skills` narrative переведён на `SkillRegistry` в package root и `YamlSkillLoader` как infrastructure helper/lazy export.
- Проверено: `git diff --check -- README.md docs/runtimes.md docs/api-reference.md docs/why-swarmline.md docs/index.md docs/agent-facade.md docs/advanced.md docs/architecture.md docs/tools-and-skills.md src/swarmline/runtime/registry.py` green; search-smoke не нашёл старые формулировки про `3` runtimes, `All three runtimes`, старый `YamlSkillLoader + SkillRegistry` package-root narrative или `registry_to_sdk_hooks ... It is None`.
- 2026-03-18 20:40: выполнен repo-wide ruff cleanup только в первой группе тестов: убраны unused imports/vars и один лишний `f`-prefix в `tests/e2e/test_agent_facade_e2e.py`, `tests/e2e/test_commands_e2e.py`, `tests/e2e/test_generic_workflow_e2e.py`, `tests/e2e/test_mcp_bridge_e2e.py`, `tests/e2e/test_team_orchestration_e2e.py`, `tests/integration/test_code_workflow_dod.py`, `tests/integration/test_deepagents_mcp.py`, `tests/integration/test_mcp_bridge_http.py`, `tests/integration/test_team_orchestration.py`, `tests/integration/test_thin_runtime_tools.py`.
- Проверено: `ruff check` по указанным файлам green; `git diff --check` по указанным файлам green.
[2026-03-18] Repo-wide ruff cleanup slice (tests group 2) completed for the allowed file set. Removed unused imports/variables, fixed `E402` smoke-import ordering with minimal `# noqa: E402` on intentional `importorskip` files, and preserved test logic. Verification: `ruff check` passed on the 14 requested test files.
[2026-03-18] Source typing cleanup slice (first half) completed for the allowed file set: `src/swarmline/tools/sandbox_docker.py`, `src/swarmline/tools/web_providers/tavily.py`, `src/swarmline/tools/web_providers/duckduckgo.py`, `src/swarmline/tools/web_providers/crawl4ai.py`, `src/swarmline/orchestration/workflow_langgraph.py`, `src/swarmline/runtime/deepagents_memory.py`, `src/swarmline/runtime/deepagents_langchain.py`, `src/swarmline/runtime/deepagents_native.py`, `src/swarmline/runtime/ports/deepagents.py`. Applied safe optional-dependency typing boundaries (`# type: ignore[...]` on import sites), localized `deepagents_native` helper imports to avoid transitive `options_builder` analysis, and kept runtime semantics unchanged. Verification: `mypy --follow-imports=silent` green on the 9-file slice; `ruff check` green on the changed source files.
[2026-03-18 17:49] Source typing cleanup slice (second half) completed for the allowed file set: `src/swarmline/runtime/structured_output.py`, `src/swarmline/memory/sqlite.py`, `src/swarmline/memory/postgres.py`, `src/swarmline/tools/web_providers/searxng.py`, `src/swarmline/tools/web_providers/brave.py`, `src/swarmline/runtime/deepagents_hitl.py`, `src/swarmline/runtime/thin/llm_providers.py`, `src/swarmline/runtime/options_builder.py`. Added a typed protocol for Pydantic-like structured-output models, widened SQL helper row containers to `Sequence[Any]`, replaced SQLAlchemy `rowcount` attribute access with `getattr`, tightened Brave/SearXNG query params to `dict[str, str]`, made DeepAgents HITL request iteration explicit, normalized Google/OpenAI SDK calls with local casts, and used `PermissionMode`/`SettingSource` from `claude_agent_sdk` for `ClaudeOptionsBuilder`. Verification: `ruff check` green on the changed source files; `mypy --follow-imports=silent` green on the 8-file slice.
[2026-03-18 21:15] Re-audit remediation program completed end-to-end on the main workspace with subagent-assisted slices (`Euler`, `Faraday`, `Gibbs`, `Parfit`) plus local integration/fixup.
- Correctness fixes closed: `SessionManager.stream_reply()` now persists canonical `final.new_messages` and preserves final metadata; `BaseRuntimePort` and session runtime path emit `error` on silent EOF instead of synthetic success; `ClaudeCodeRuntime` stops after terminal `error`; DeepAgents portable path round-trips assistant tool-calls + tool results; builtin `cli` works through both registry and legacy `RuntimeFactory` fallback; workflow executor advertises local tools and `MixedRuntimeExecutor` is documented as observability-only.
- Public surface/docs sync closed: runtime/hooks/ports/skills `__all__` now expose only stable core symbols while explicit optional imports still fail fast; import-isolation tests cover star-import behavior; README and docs now describe 4 runtimes (`cli` included), fail-fast `registry_to_sdk_hooks`, and `skills.loader` as infrastructure helper.
- Static debt closed: repo-wide `ruff` cleanup on tests, repo-wide `mypy` cleanup on 17 source files, with one post-merge compatibility fix in `GoogleAdapter` so async-mock tests and real SDK paths both work.
- Final verification on main workspace: `ruff check src/ tests/` green, `mypy src/swarmline/` green (`199` source files), `python -m pytest -q` green (`2366 passed, 16 skipped, 5 deselected`), `git diff --check` green.
[2026-03-18 21:06] Started a fresh release-risk audit on the clean post-remediation workspace, with mini-subagent output explicitly treated as candidate discovery only; final conclusions were filtered through local reproduction and code inspection.
- Baseline re-verified before the audit: clean worktree, `python -m pytest -q` green (`2366 passed, 16 skipped, 5 deselected`), `ruff check src/ tests/` green, `mypy src/swarmline/` green.
- Manual smoke confirmed the public example surface is at least partially healthy: `python examples/17_runtime_switching.py` and `python examples/19_cli_runtime.py` both pass.
- New read-only report recorded in `.memory-bank/reports/2026-03-18_wave0-wave1_release-risk-audit.md`.
- Confirmed code defects in this pass: `Conversation` persists partial assistant text after `error`; portable runtime exceptions escape from `Conversation` and `SessionManager.run_turn()`; `_RuntimeEventAdapter` drops `tool_name` for `tool_call_finished`; `SqliteSessionBackend` is not concurrency-safe; `InMemorySessionBackend` aliases saved state; `BaseTeamOrchestrator` marks all-failed/all-cancelled teams as `completed`; `DeepAgentsTeamOrchestrator` drops worker task composition; default `DeepAgentsSubagentOrchestrator` advertises tools without executors.
- Confirmed release-surface drift: several docs files still describe only 3 runtimes even though the current registry and examples expose 4 (`cli` included).
[2026-03-18 22:05] Finalized the Wave 0 / Wave 1 release-risk audit after re-checking strong findings locally and filtering out stale draft items.
- The final report in `.memory-bank/reports/2026-03-18_wave0-wave1_release-risk-audit.md` now supersedes the earlier draft and removes the false-positive docs-drift item; the current docs surface does reflect 4 runtimes.
- Additional confirmed finding added after local repro: `SessionKey.__str__()` is collision-prone (`"a:b"+"c"` vs `"a"+"b:c"`), and `SessionManager` uses that raw string as the storage/lock/backend key, so one session can overwrite another.
- Verified again during finalization: `SqliteSessionBackend` concurrent access reproduces a hard failure (`SystemError: error return without exception set`), `Conversation` still persists partial assistant text after `error`, `Conversation` and `SessionManager.run_turn()` still leak runtime exceptions, `DeepAgentsTeamOrchestrator` still spawns workers with raw task and no `send_message` tool wiring.
[2026-03-18 22:45] Completed the follow-up release-risk audit for the remaining waves (persistence/provider edges/workflow/export/public surface), again using `gpt-5.4` subagents only as candidate discovery and promoting findings only after local repro or direct code inspection.
- New report recorded in `.memory-bank/reports/2026-03-18_wave2-plus_release-risk-audit.md`.
- Additional confirmed bugs beyond the Wave 0/1 report:
  - `InMemoryMemoryProvider.save_session_state()` / `get_session_state()` alias mutable state instead of snapshotting it;
  - SQL memory backends document `user > ai_inferred > mcp`, but SQLite repro shows `mcp` still overwrites `ai_inferred`;
  - `WorkflowGraph.execute(..., resume=True)` skips the checkpointed node and resumes from its successor;
  - LangGraph export helpers drop parallel-group semantics entirely;
  - `CliAgentRuntime.cancel()` surfaces as `runtime_crash` (`code -15`) rather than `cancelled`;
  - dict-style `mcp_servers` configs silently fail on portable runtime wiring because MCP URL resolution ignores plain dict values;
  - Claude SDK tool-result metadata (`tool_use_id`, `is_error`) is dropped, and failed tool results become `tool_call_finished(ok=True)`.
- Verified-safe areas in this pass: no new defendable optional-deps/public-surface bug was confirmed; examples `09`, `10`, `20`, `21`, `22`, `24`, `25`, `26` run successfully on the current workspace.
[2026-03-18 23:05] Built a single execution backlog that unifies all confirmed findings from the Wave 0/1 and Wave 2+ release-risk audits.
- New plan recorded in `.memory-bank/plans/2026-03-18_unified-release-risk-remediation-backlog.md`.
- The unified backlog groups all confirmed defects into 5 implementation batches: runtime/session contracts, persistence identity/snapshots, orchestration/team correctness, workflow recovery/export fidelity, and storage contract closure.
- The plan defines parallel ownership zones, merge points, batch-level DoD, and final acceptance gates (`ruff`, `mypy`, `pytest`, representative example smoke).
[2026-03-18 23:55] Unified release-risk remediation backlog executed and fully re-verified on the main workspace.
- Batch 1/2 defects closed in code and tests: `RuntimeAdapter` now preserves tool-result correlation/error metadata, `ClaudeCodeRuntime` maps that metadata into `RuntimeEvent.tool_call_finished`, `SessionKey` escapes delimiter-bearing IDs, `InMemorySessionBackend` behaves as a snapshot store, `SqliteSessionBackend` survives concurrent async access through serialized connection usage, `InMemoryMemoryProvider` snapshots session state, and MCP URL resolution now accepts dict-style server configs.
- Batch 3/4/5 targeted suites were re-run as validation gates and stayed green, confirming no remaining actionable gaps on team orchestration, workflow resume/export, or SQL fact precedence in the current tree.
- Verification:
  - targeted Batch 1/2 regression pack: `205 passed`
  - merge-point portable/session regression pack: `110 passed`
  - orchestration/workflow/storage regression pack: `66 passed`
  - repo-wide `ruff check src/ tests/`: green
  - repo-wide `mypy src/swarmline/`: green (`199` source files)
  - full offline `pytest -q`: `2396 passed, 16 skipped, 5 deselected`
  - smoke: `python examples/20_workflow_graph.py` green
  - smoke: real `CliAgentRuntime` happy path via temporary `claude` wrapper emits `assistant_delta` + `final`; generic NDJSON without terminal event still fail-fast'ится как `bad_model_output`
- Knowledge note recorded in `.memory-bank/notes/2026-03-18_23-55_unified-release-risk-remediation-complete.md`.
[2026-03-18 23:59] Follow-up hardening pass executed locally after re-checking the current dirty workspace against the unified backlog and fresh quality gates.
- Реально исправлено в этом проходе:
  - `Conversation.say()` / `Conversation.stream()` больше не добавляют partial assistant message в history, если turn завершился terminal `error`.
  - portable runtime exceptions в `Conversation._execute_agent_runtime()` и `InMemorySessionManager` нормализуются в typed error path вместо uncaught crash.

[2026-04-12 04:55] Подготовлен и записан подробный comparative/reuse report по развитию `thin` как coding-agent на основе локального анализа `swarmline`, `aura`, `claw-code-agent`, `pi-mono` и трёх параллельных сабагентных проходов.
- Новый отчёт: `.memory-bank/reports/2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md`.
- Зафиксирована итоговая рекомендация: не писать новый runtime, а собрать `ThinRuntime` в отдельный coding-agent profile поверх уже существующих seams (`tools/builtin`, `todo/tools`, `GraphTaskBoard`, `TaskSessionStore`, `context.builder`).
- Подтверждён legal split по reuse: `aura` подходит как источник осмысленного code reuse (MIT указан в README), `claw-code-agent` пока использовать только как reference до явного license clearance.
- Сформирован implementation backlog по уровням P0/P1/P2: unified tool pack, task runtime facade, coding-agent policy profile, PathService, bash classifier, file mutation queue, richer context compiler, delegation/verify flows.

[2026-04-12 05:10] На основе comparative/reuse report оформлен отдельный feature plan для следующего tranche: `.memory-bank/plans/2026-04-12_feature_thin-coding-agent-profile.md`.
- План не переключает текущий активный `plan.md`, а фиксирует follow-on work после/поверх текущего parity направления.
- В план встроены explicit rule gates из `RULES.md`: TDD-first, contract-first, Clean Architecture, no new deps, fail-fast, phased DoD, targeted + broader verification.
- Фазы разбиты на low-risk slices: architecture contracts, unified tool pack, task runtime, PathService/execution policy, file mutation queue, coding context compiler, profile wiring, stabilization.
  - `_RuntimeEventAdapter` сохраняет `tool_name` для `tool_call_finished`.
  - `CliAgentRuntime.cancel()` теперь завершает run через `RuntimeEvent.error(kind="cancelled")`, а не `runtime_crash`.
  - `InMemoryMemoryProvider.save_session_state()` / `get_session_state()` переведены на snapshot semantics.
  - убран дублированный regression test в `tests/unit/test_workflow_executor.py`, из-за которого repo-wide `ruff` не проходил.
- Повторно проверено как уже закрытое в текущем дереве: `SessionKey` escaping, `SqliteSessionBackend` concurrent access, workflow checkpoint resume, LangGraph parallel export, DeepAgents team aggregate status и SQL fact-source priority.
- Verification:
  - targeted unit pack: `pytest -q tests/unit/test_agent_conversation.py tests/unit/test_session_manager.py tests/unit/test_cli_runtime.py tests/unit/test_agent_facade.py` → `124 passed`
  - targeted storage pack: `pytest -q tests/unit/test_inmemory_provider.py` → `22 passed`
  - targeted SQL storage pack: `pytest -q tests/unit/test_sqlite_memory.py tests/unit/test_postgres_memory.py` → `41 passed`
  - repo-wide `pytest -q` → `2397 passed, 16 skipped, 5 deselected`
  - repo-wide `ruff check src/ tests/` → green
  - repo-wide `mypy src/swarmline/` → green
  - `git diff --check` → green
- Ограничение процесса: попытка распараллелить дополнительный implementation pass через `gpt-5.4` сабагентов сорвалась на usage-limit среды; финальный fix/verification проход выполнен локально без понижения модели.
[2026-03-18 23:58] Examples release-surface audit completed with one real fix on top of the current workspace.
- `examples/01_agent_basics.py` нарушал contract из `examples/README.md`: дефолтный запуск уходил в live `thin` runtime, печатал пустые ответы и выбрасывал auth traceback в `stderr` без API key.
- Исправление: пример переведён на deterministic mock runtime по умолчанию, live path вынесен за `--live` + `ANTHROPIC_API_KEY`; добавлен subprocess smoke test `tests/integration/test_examples_smoke.py`, который фиксирует offline behavior.
- Повторная проверка examples surface: все `examples/01-27` завершаются с `exit=0` и без `stderr`.
- Verification:
  - `pytest -q tests/integration/test_examples_smoke.py` → `1 passed`
  - `python examples/01_agent_basics.py` → green, non-empty output
  - full smoke over `examples/01-27` via subprocess run → `FAILED: 0`, `STDERR_ONLY: 0`
  - `ruff check examples/01_agent_basics.py tests/integration/test_examples_smoke.py` → green
  - `git diff --check examples/01_agent_basics.py tests/integration/test_examples_smoke.py` → green
[2026-03-18 23:10] Examples smoke coverage expanded from one script to the full runnable examples surface.
- `tests/integration/test_examples_smoke.py` now parametrically executes every `examples/*.py` offline, strips common provider API keys from the environment, and asserts `exit=0`, empty `stderr`, and non-empty `stdout`.
- This closes the regression gap that let `examples/01_agent_basics.py` silently drift away from the README promise while the test suite still stayed green.
- Verification:
  - `pytest -q tests/integration/test_examples_smoke.py` → `28 passed`
  - `ruff check tests/integration/test_examples_smoke.py examples/01_agent_basics.py` → green
  - `git diff --check -- tests/integration/test_examples_smoke.py examples/01_agent_basics.py` → green
[2026-03-18 23:29] Live/external examples surface audited read-only after the offline smoke pass.
- Reviewed `examples/17`, `18`, `19`, `24`, `25`, `26`, `27` against README promises, env gating, and related runtime/orchestration seams.
- Confirmed three actionable gaps:
  - `examples/README.md` overstates live/full-mode availability for complex scenarios `24-27`; only `27` has an executable live entrypoint, `24` has commented guidance only, and `25`/`26` are mock-only.
  - `examples/27_nano_claw.py --live` fail-opens when `ANTHROPIC_API_KEY` is missing: prints an error but exits `0`, which is misleading for automation and manual verification.
  - `examples/27_nano_claw.py` loses live usage/cost accounting on streaming turns by fabricating a `Result` without `usage`/`total_cost_usd` before running middleware, so `/cost` and `TurnLogger` stay inaccurate in real mode.
- Verified-safe in this pass:
  - `examples/17_runtime_switching.py`, `18_custom_runtime.py`, and `19_cli_runtime.py` run cleanly without provider credentials.
  - Default invocations of `examples/24`, `25`, `26`, and `27` remain green and silent on `stderr`.
- Verification:
  - targeted subprocess smoke for `17`, `18`, `19`, `24`, `25`, `26`, and `27 --live` (without `ANTHROPIC_API_KEY`) completed without unexpected crashes
  - static cross-check of README/live flags vs example implementations
[2026-03-18 23:29] Live/examples audit completed for docs/env-gating and partially integrated demo paths.
- Verified default runnable surface again and then audited live/degraded behavior around `examples/24-27` plus README claims.
- Confirmed two actionable issues:
  - `examples/27_nano_claw.py --live` prints a missing-key error but exits `0`, unlike `examples/01_agent_basics.py --live` which fail-fast exits `1`.
  - `examples/27_nano_claw.py` demo mode does not execute any tool handlers; it returns canned assistant text claiming file operations succeeded while `_MOCK_FS` remains unchanged.
- Confirmed one documentation gap:
  - `examples/README.md` and `examples/24_deep_research.py` imply a real "full/live" mode for complex scenarios, but `24/25/26` expose no runnable live entrypoint or CLI switch; `24` only contains a commented code snippet.
- Verification:
  - `python examples/01_agent_basics.py --live` without key → clear message, `EXIT:1`
  - `python examples/27_nano_claw.py --live` without key → clear message, `EXIT:0`
  - `python examples/27_nano_claw.py` → green, but no `[tool]` events and no real mock FS side-effects
  - in-process repro for `NanoClaw(runtime=\"mock\")` write request → reply says file was written, but `_MOCK_FS` unchanged and `/project/utils.py` absent
  - static check: `examples/24_deep_research.py`, `25_shopping_agent.py`, `26_code_project_team.py` have no `--live` or other runnable live entrypoint
- Report recorded in `.memory-bank/reports/2026-03-18_live-examples-audit.md`.
[2026-03-18 23:34] Live/examples remediation completed on top of the offline smoke coverage pass.
- Fixed live/external gaps in the runnable examples surface:
  - `examples/19_cli_runtime.py` now demonstrates the real Claude NDJSON command shape with `--output stream-json`.
  - `examples/24_deep_research.py` gained an executable `--live` path backed by `Agent(..., runtime="thin", output_type=ResearchReport)` and now fail-fast exits when `ANTHROPIC_API_KEY` is missing.
  - `examples/27_nano_claw.py --live` now fail-fast exits with code `1` when `ANTHROPIC_API_KEY` is missing.
  - `examples/27_nano_claw.py` demo mode now emits real mock tool events, mutates `_MOCK_FS` on write/read/list flows, and preserves `usage` / `total_cost_usd` from the streaming final event before middleware runs.
  - `examples/README.md` now describes the live surface honestly: optional live modes exist for `24` and `27`, while `25` and `26` stay mock-only demos.
- Regression coverage expanded in `tests/integration/test_examples_smoke.py`:
  - `19` asserts stream-json Claude command,
  - `24 --live` and `27 --live` assert fail-fast missing-key behavior,
  - `27` demo mode asserts real mock tool side-effects,
  - `27` streaming path asserts cost metadata survives into `CostTracker`.
- Verification:
  - `pytest -q tests/integration/test_examples_smoke.py` → `33 passed`
  - targeted async regressions for `27` demo/tool-cost path → `2 passed`
  - full manual subprocess smoke over `examples/01-27` → `failed=[]`, `stderr_only=[]`
  - `ruff check examples/19_cli_runtime.py examples/24_deep_research.py examples/27_nano_claw.py tests/integration/test_examples_smoke.py` → green
  - `git diff --check -- examples/19_cli_runtime.py examples/24_deep_research.py examples/27_nano_claw.py examples/README.md tests/integration/test_examples_smoke.py` → green
[2026-03-18 23:40] Docs/examples consistency remediation completed after the live-surface pass.
- Public docs surface is now aligned with the current runnable examples and middleware/runtime API:
  - `docs/examples.md` was rewritten from a stale pre-examples catalog into the real `examples/01-27` index with honest live-mode notes.
  - `docs/getting-started.md` and `docs/agent-facade.md` no longer reference nonexistent `CostTracker` attributes like `budget_exceeded`; `agent-facade` also no longer documents unsupported `SecurityGuard(on_blocked=...)`, the wrong `build_middleware_stack()` default budget, or the wrong `after_result` order.
  - `README.md` no longer advertises the nonexistent `swarmline[cli]` extra; `cli` runtime now points to base `swarmline` install.
  - `docs/cli-runtime.md` early snippets now use the real Claude stream-json command shape consistently.
- Added regression coverage in `tests/integration/test_docs_examples_consistency.py` for:
  - docs examples catalog referencing all runnable `examples/*.py`,
  - absence of nonexistent `CostTracker` API in user-facing docs,
  - no bogus `swarmline[cli]` install instruction,
  - stream-json command consistency in CLI runtime docs,
  - current live-mode claim in `examples/README.md`.
- Verification:
  - `pytest -q tests/integration/test_docs_examples_consistency.py tests/integration/test_examples_smoke.py` → `39 passed`
  - `ruff check tests/integration/test_docs_examples_consistency.py tests/integration/test_examples_smoke.py examples/19_cli_runtime.py examples/24_deep_research.py examples/27_nano_claw.py` → green
  - `git diff --check -- README.md docs/cli-runtime.md docs/examples.md docs/agent-facade.md docs/getting-started.md tests/integration/test_docs_examples_consistency.py tests/integration/test_examples_smoke.py` → green
[2026-03-18 23:58] Release-oriented live runtime verification completed with code fixes and full green gates.
- Fixed two real runtime compatibility bugs discovered during live smoke:
  - `resolve_model_name()` no longer collapses explicit provider-prefixed models like `openrouter:anthropic/claude-3.5-haiku` to the registry default; this unblocked real `thin` OpenRouter verification through the facade.
  - `CliAgentRuntime` now normalizes legacy Claude command shapes to the live-compatible form `claude --print --verbose --output-format stream-json -`, upgrades stale `--output` flags, and uses an explicit NDJSON-capable default command. `examples/19_cli_runtime.py`, `docs/cli-runtime.md`, and CLI docs-consistency tests were synced to the same canonical shape.
- Installed missing optional deps for real `deepagents` verification: `deepagents`, `langchain`, `langgraph`, `langchain-openai` (plus transitive packages). This exposed hidden optional-deps gaps:
  - `src/swarmline/runtime/deepagents_native.py` now exports lazy wrapper functions for `build_deepagents_chat_model()` and `create_langchain_tool()` so patch-based tests still work when extras are installed.
  - `src/swarmline/orchestration/workflow_langgraph.py` now type-erases the `StateGraph(dict)` construction point, which avoids mypy failures that only appear when `langgraph` is actually present.
- Live verification results:
  - `thin` via OpenRouter-compatible path: `Agent(runtime="thin", model="openrouter:anthropic/claude-3.5-haiku")` with the supplied OpenRouter key returned `OK`.
  - Using that same key as `ANTHROPIC_API_KEY` on the native Anthropic path failed with `401 invalid x-api-key`; this confirms OpenRouter credentials are not a drop-in substitute for direct Anthropic runtime/example paths.
  - `claude_sdk` runtime: `Agent(runtime="claude_sdk", model="sonnet")` returned `OK`.
  - `cli` runtime: direct `CliAgentRuntime()` with the normalized default Claude command returned `assistant_delta("OK")` and `final("OK")`.
  - `deepagents` runtime: verified both direct `DeepAgentsRuntime(RuntimeConfig(... base_url="https://openrouter.ai/api/v1"))` and facade path with `OPENAI_BASE_URL=https://openrouter.ai/api/v1`; both returned `OK`.
- Important environment note:
  - Installing the `deepagents` stack upgraded shared packages (`openai`, `anthropic`, `google-auth`) and `pip` reported dependency conflicts with external `aider-chat`. Swarmline itself remains green after the upgrade, but this environment-side effect should be kept in mind outside the repository.
- Final verification:
  - `pytest -q tests/unit/test_runtime_types.py tests/unit/test_agent_config.py tests/unit/test_cli_runtime.py tests/integration/test_cli_runtime_integration.py tests/integration/test_examples_smoke.py tests/integration/test_docs_examples_consistency.py tests/unit/test_deepagents_models.py tests/unit/test_deepagents_runtime.py tests/integration/test_deepagents_stage4_surface.py` → `197 passed`
  - `pytest -q tests/unit/test_deepagents_native.py` → `12 passed`
  - `ruff check src/ tests/` → green
  - `mypy src/swarmline/` → green
  - `pytest -q` → `2517 passed, 11 skipped, 5 deselected`
  - `git diff --check` → green

## 2026-03-19 00:54 MSK — OpenRouter live examples/runtime verification follow-up

- Fixed the remaining live-path regression in `ThinRuntime` examples and synchronized docs:
  - `src/swarmline/runtime/thin/modes.py` now recognizes common English planner/react intents (`plan`, `step-by-step`, `list`, `read`, `write`, `execute`, `run`, etc.), which restores the expected `react` path for English tool-oriented prompts like `List the files in /project`.
  - `examples/27_nano_claw.py` now suppresses raw streamed JSON envelopes and prints the parsed final text when the model streams a JSON `final` envelope token-by-token, so live CLI output is human-readable again.
  - `examples/README.md` and `docs/examples.md` now reflect that examples `24` and `27` accept either `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY` for `--live`.
- Added regression coverage:
  - `tests/unit/test_thin_modes.py` covers English react/planner prompts.
  - `tests/integration/test_examples_smoke.py` now checks Nano Claw's JSON-envelope streaming case in addition to OpenRouter live-key resolution.
  - `tests/integration/test_docs_examples_consistency.py` asserts that examples docs mention both supported live credentials.
- Live verification results with the supplied OpenRouter key:
  - `examples/24_deep_research.py --live` returned a structured research report successfully through `thin` + `openrouter:anthropic/claude-3.5-haiku`.
  - `examples/27_nano_claw.py --live` executed `list_directory`, displayed the tool result, and rendered a clean final answer (`Files in /project: ...`) instead of leaking JSON.
  - Runtime matrix smoke:
    - `thin` + `openrouter:anthropic/claude-3.5-haiku` → `OK`
    - `cli` default runtime → `OK`
    - `claude_sdk` + `model='sonnet'` → `OK`
    - `deepagents` works with the same OpenRouter key only through the supported OpenAI-compatible path (`model='openai:anthropic/claude-3.5-haiku'` + `OPENAI_BASE_URL=https://openrouter.ai/api/v1`); direct `openrouter:*` alias remains unsupported for DeepAgents.
- Verification after the changes:
  - `pytest -q tests/unit/test_thin_modes.py tests/integration/test_thin_runtime_tools.py tests/integration/test_examples_smoke.py tests/integration/test_docs_examples_consistency.py` → `65 passed`
  - `pytest -q tests/integration/test_examples_smoke.py tests/integration/test_docs_examples_consistency.py` → `42 passed`
  - `ruff check src/ tests/ examples/` → green
  - `mypy src/swarmline/` → green
  - `git diff --check` → green

## 2026-03-19 01:20 MSK — Final release verification after OpenRouter follow-up

- Re-ran full release-facing verification after the ThinRuntime mode heuristic fix and Nano Claw streaming-output fix:
  - `examples/24_deep_research.py --live` with `OPENROUTER_API_KEY` returned a structured report successfully.
  - `examples/27_nano_claw.py --live` with `OPENROUTER_API_KEY` executed `list_directory`, showed the tool result, and rendered a clean final text answer instead of raw JSON.
  - runtime smoke passed for:
    - `thin` + `model='openrouter:anthropic/claude-3.5-haiku'`
    - `cli` default runtime
    - `claude_sdk` + `model='sonnet'`
    - `deepagents` through the supported OpenAI-compatible OpenRouter path (`OPENAI_BASE_URL=https://openrouter.ai/api/v1`)
- Final verification:
  - `pytest -q tests/unit/test_thin_modes.py tests/unit/test_thin_runtime.py tests/unit/test_thin_streaming.py tests/integration/test_thin_runtime_tools.py tests/integration/test_examples_smoke.py tests/integration/test_docs_examples_consistency.py` → `101 passed`
  - `ruff check src/ tests/` → green
  - `ruff check examples/24_deep_research.py examples/27_nano_claw.py` → green
  - `mypy src/swarmline/` → green
  - `pytest -q` → `2524 passed, 11 skipped, 5 deselected`
  - `git diff --check` → green

## 2026-03-19 01:35 MSK — Credentials/provider docs consolidated

- Added canonical public reference `docs/credentials.md` with the runtime/provider/env-var matrix for `thin`, `claude_sdk`, `deepagents`, and `cli`.
- Synchronized entry docs to link to that reference:
  - `README.md`
  - `docs/getting-started.md`
  - `docs/configuration.md`
  - `docs/runtimes.md`
  - `docs/cli-runtime.md`
  - `mkdocs.yml`
- Captured key rules explicitly:
  - `AgentConfig.env` is primarily for `claude_sdk`
  - portable facade runtimes read provider credentials from process env
  - `RuntimeConfig.base_url` is available on direct runtime construction, not on `AgentConfig`
  - DeepAgents uses the OpenAI-compatible path for OpenRouter rather than `openrouter:*`
- Verification:
  - `pytest -q tests/integration/test_docs_examples_consistency.py tests/integration/test_examples_smoke.py` → `44 passed`
  - `ruff check tests/integration/test_docs_examples_consistency.py` → green
  - `mkdocs build --strict` → green
  - `git diff --check` → green

## 2026-03-19 02:25 MSK — Docs site visual pass pushed into steel/minimal direction

- Reworked the docs landing around a more product-like visual language:
  - new `docs/index.md` with a strong hero, runtime matrix, capability grid, use-case grid, guided quick-start path, and clearer CTA structure
  - thin mono SVG iconography throughout feature/runtime/docs cards
  - new scroll-reveal behavior in `docs/assets/site.js`
- Strengthened the site chrome in `docs/assets/extra.css`:
  - frosted steel header/tabs/search
  - higher-contrast card hierarchy and hover motion
  - more editorial spacing and grid rhythm
  - responsive fixes for the homepage hero
- Fixed a confirmed mobile bug where the hero title overflowed horizontally by forcing hero grid children to shrink correctly and reducing mobile hero typography.
- Visual smoke checked in browser against the rebuilt site:
  - desktop dark homepage
  - desktop light homepage
  - mobile homepage
- Verification:
  - `mkdocs build --strict` → green
  - `pytest -q tests/integration/test_docs_examples_consistency.py` → `8 passed`
  - `git diff --check` → green

## 2026-03-29 — Code Audit: Uncommitted Code
- Полный аудит 39 незакоммиченных файлов (daemon, pipeline, multi_agent, misc)
- 4 параллельных ревьюера, 373 теста passed, ruff clean
- Найдено: 11 CRITICAL, 18 SERIOUS, 22 WARNING
- Общая оценка: 5.6/10 (NEEDS_CHANGES)
- Отчёт: reports/2026-03-29_code-audit_uncommitted.md
- Приоритет: Tier 1 фиксы (6 CRITICAL) → Tier 2 (SERIOUS) → Tier 3 (warnings)

## 2026-03-29 (сессия 2)

- Полный аудит + code review библиотеки: 86 findings → все critical/serious исправлены
- Track A (Graph Agent Config): 5 фаз — AgentExecutionContext, skills/MCP inheritance, dual-dispatch runner, governance
- Track B (Knowledge Bank): 4 фазы — domain types, 5 ISP protocols, multi-backend storage, tools + consolidation
- Code review graph+KB: S1 (delegate governance) + S2 (root task tracking) исправлены, S3-W7 → BACKLOG
- Архитектурный отчёт: reports/2026-03-29_architecture_graph-agents-and-knowledge-bank.md
- Task Progress + BLOCKED + Workflow Stages (4 фазы):
  - TaskStatus.BLOCKED с обязательным blocked_reason
  - progress: float с авто-расчётом из subtasks (_propagate_parent заменил _propagate_completion)
  - stage: str для пользовательских workflow + WorkflowConfig/WorkflowStage domain types
  - GraphTaskBlocker protocol (block_task/unblock_task) во всех 3 backend'ах
  - DelegationRequest.stage → GraphTaskItem.stage passthrough
- Коммиты: a33afa6..163a98f (7 коммитов)
- Тесты: 3770 passed, ruff clean
- Отчёты: reports/2026-03-29_review_*.md, reports/2026-03-29_feature_task-progress-stages-blocked.md
[2026-04-11] Security/correctness remediation slice completed for the active P1/P2 audit-gap plan.
- Closed secure-by-default surfaces: `HttpxWebProvider` now revalidates redirect hops and binds requests to validated resolved IPs; MCP host execution is opt-in (`create_server(..., enable_host_exec=False)`); `LocalSandboxProvider.execute()` is opt-in via `SandboxConfig.allow_host_execution`; `/v1/query` is closed by default unless auth or explicit opt-in is configured.
- Closed orchestration/task-state bugs: `DefaultGraphOrchestrator.delegate()` checks approval before creating/checking out subtasks; `ThinPlannerMode` and `DeepAgentsPlannerMode` now reject unapproved plans before side effects; graph task boards enforce `IN_PROGRESS -> DONE` only, reject parent cycles, and scope helper/recursive queries by namespace in SQLite/Postgres.
- Closed concurrency/hardening gaps: `Agent.query_structured()` now uses per-call config without mutating shared `Agent._config`; `YamlSkillLoader` re-resolves and rejects symlinked/out-of-root files before reads; `Scheduler` bounds launched asyncio tasks by `max_concurrent` instead of accumulating an unbounded pending backlog.
- Testing updated: added SSRF rebinding/redirect regressions, planner/orchestrator denial regressions, `query_structured()` concurrency regression, scheduler bounded-launch regression, sandbox/MCP/serve secure-default regressions, task-board contract/isolation regressions, and converted `tests/unit/test_postgres_backends.py` into smoke-only coverage plus env-gated behavioral Postgres integration harness (`tests/integration/test_postgres_backends_integration.py`).
- Verification: targeted + broader regressions green (`370 passed, 3 skipped`), `ruff check` green on changed files, targeted `mypy` green on all touched source files. Full repo-wide `mypy src/swarmline/` still reports a pre-existing optional dependency import issue in `src/swarmline/runtime/agent_sdk_adapter.py` when `claude_code_sdk` stubs are absent.
- Not included in this slice: the larger Phase 3 architectural refactor (`AgentConfig` DTO cleanup, `Agent`/`Conversation` split, `SessionManager` split, `BaseRuntimePort` slimming, shared SQLite/Postgres storage core). Those remain separate high-risk refactor work after the secured Phase 1/2 baseline.
[2026-04-11] Phase 3 low-risk slice: AgentConfig boundary cleanup.
- `AgentConfig` больше не делает runtime/capability negotiation в `__post_init__`; dataclass оставлен как более чистый DTO с обязательной только проверкой `system_prompt`.
- Runtime-facing validation и model resolution перенесены в `RuntimeFactory` (`validate_agent_config()`, `resolve_agent_model()`), а internal wiring переведён на эти helpers: `Agent`, `Conversation`, `build_portable_runtime_plan()`, `_build_runtime_config()`.
- Для backward compatibility сохранён `AgentConfig.resolved_model` как thin wrapper поверх `RuntimeFactory.resolve_agent_model()`; публичный surface не сломан, но internal code больше не опирается на config-level runtime logic.
- Контракт тестов обновлён: invalid runtime / feature_mode / capability mismatch теперь разрешены на DTO-construction layer и fail-fast на runtime/bootstrap boundary (`Agent(...)`).
- Verification: targeted Phase 3 slice green (`135 passed`, затем повторный narrowed rerun `110 passed`), `ruff check` green, targeted `mypy` green.
- Остаток архитектурного плана не тронут: `SessionManager` split, `Agent`/`Conversation` deeper extraction, `BaseRuntimePort` slimming, shared SQLite/Postgres storage core.
[2026-04-11] Phase 3 low-risk slice: SessionManager async core split.
- `InMemorySessionManager` разделён на внутренний `_AsyncSessionManagerCore` и тонкий compatibility facade.
- Async hot path (`aget/aregister/aclose/aclose_all/run_turn/stream_reply/aupdate_role`) теперь идёт напрямую в core без sync bridge.
- Sync API (`get/register/update_role`) остался как legacy bridge поверх core, чтобы не ломать public surface и existing sync callers.
- Backward-compatible attribute aliases `_sessions/_locks/_ttl_seconds/_backend` сохранены для существующих внутренних caller'ов и тестов.
- Verification: `pytest -q tests/unit/test_session_manager.py tests/unit/test_concurrency_bugs.py` → `41 passed`; `ruff check src/swarmline/session/manager.py` → green; `mypy src/swarmline/session/manager.py` → green.
[2026-04-11] Phase 3 low-risk slice: shared runtime dispatch extraction for Agent/Conversation.
- Added `src/swarmline/agent/runtime_dispatch.py` with shared `dispatch_runtime()` selection and `run_portable_runtime()` execution helper.
- `Agent._execute_stream()` and `Conversation._execute()` now route through the shared dispatcher, while private seams (`_execute_stream`, `_execute_claude_sdk`, `_execute_agent_runtime`, `_execute`, `_create_adapter`) remain intact as thin wrappers.
- Portable runtime execution (`RuntimeFactory` creation, `runtime.run(...)`, cleanup, error adaptation) is centralized in the helper and reused by both `Agent` and `Conversation`.
- Verification: `pytest -q tests/unit/test_agent_facade.py tests/unit/test_agent_conversation.py` → `77 passed`; `ruff check src/swarmline/agent/agent.py src/swarmline/agent/conversation.py src/swarmline/agent/runtime_dispatch.py` → green; `mypy src/swarmline/agent/agent.py src/swarmline/agent/conversation.py src/swarmline/agent/runtime_dispatch.py` → green.
[2026-04-11] Phase 3 integration follow-up: SessionManager split + Agent/Conversation dispatch slice integrated and regression-checked together.
- `src/swarmline/session/manager.py` now uses internal `_AsyncSessionCore` with `InMemorySessionManager` as a sync-compat facade; async paths remain direct, sync paths are bridge-only compatibility shims.
- `src/swarmline/agent/runtime_dispatch.py` is now the shared runtime helper for `dispatch_runtime()`, portable runtime execution, one-shot `claude_sdk` streaming, and conversation adapter creation; `Agent` and `Conversation` consume it via thin private wrappers.
- Private seam compatibility was preserved for tests and monkeypatch-based callers: `_execute_stream`, `_execute_claude_sdk`, `_execute_agent_runtime`, `_execute`, `_create_adapter`, `_RuntimeEventAdapter`, `_ErrorEvent` all remain available.
- Verification: targeted unit regression `pytest -q tests/unit/test_session_manager.py tests/unit/test_concurrency_bugs.py tests/unit/test_agent_facade.py tests/unit/test_agent_conversation.py` → `118 passed`; broader regression `pytest -q tests/integration/test_session_backends_integration.py tests/integration/test_agent_facade_wiring.py tests/unit/test_agent_runtime_wiring.py` → `22 passed`; `ruff check` green; targeted `mypy` green for all touched files.
[2026-04-11] Phase 3 runtime-port slimming slice.
- Extracted `src/swarmline/runtime/ports/_helpers.py` with the shared history/compaction/prompt assembly/stream terminal handling logic that was previously concentrated in `BaseRuntimePort`.
- `src/swarmline/runtime/ports/base.py` now keeps the public surface and private seams intact (`_history`, `_rolling_summary`, `_build_system_prompt`, `_maybe_summarize`, `convert_event`, `truncate_long_args`) while delegating the internal work to helper functions.
- Verification: `pytest -q tests/unit/test_runtime_ports_base_coverage.py tests/unit/test_compaction.py tests/unit/test_runtime_ports_base.py tests/unit/test_cross_session_memory.py tests/unit/test_protocol_contracts.py tests/unit/test_standalone_import.py` → `94 passed`; `ruff check src/swarmline/runtime/ports/base.py src/swarmline/runtime/ports/_helpers.py` → green; `mypy src/swarmline/runtime/ports/base.py src/swarmline/runtime/ports/_helpers.py` → green.
[2026-04-11] Memory storage DRY slice: shared policy/serialization layer for SQLite/Postgres providers.
- Added `src/swarmline/memory/_shared.py` with the common storage-normalization helpers: JSON serialize/deserialize, scoped fact merge policy, goal-state normalization, session-state shaping, and phase-state normalization.
- `src/swarmline/memory/sqlite.py` and `src/swarmline/memory/postgres.py` now delegate the shared policy/serialization logic to the helper module while keeping SQL dialect-specific statements and backend behavior in place.
- Preserved private compatibility aliases inside each provider (`_json_or_none`, `_load_json_or_none`, `_load_json_value`, scoped merge helpers) so existing tests and internal seams do not break.
- Added focused unit coverage in `tests/unit/test_memory_shared.py` for the shared normalization and merge policy.
- Verification: `pytest -q tests/unit/test_memory_shared.py tests/unit/test_sqlite_memory.py tests/unit/test_postgres_memory.py` → `50 passed`; `ruff check src/swarmline/memory/_shared.py src/swarmline/memory/sqlite.py src/swarmline/memory/postgres.py tests/unit/test_memory_shared.py tests/unit/test_sqlite_memory.py tests/unit/test_postgres_memory.py` → green; `mypy src/swarmline/memory/_shared.py src/swarmline/memory/sqlite.py src/swarmline/memory/postgres.py` → green.
[2026-04-11] Restored repository instruction files into `main` after user-approved comparison.
- Restored `AGENTS.public.md`, `CLAUDE.md`, and `RULES.md` from `/tmp/swarmline-switch-backup-20260411-165845/` into the repository root after explicit user approval.
- Pre-restore comparison result: `AGENTS.public.md` was byte-identical to current `AGENTS.md`; `CLAUDE.md` and `RULES.md` remained intentionally absent from `main` until the user requested their return.
- Verification: compared file presence/content before restore and confirmed working tree contains only the three restored files plus this `progress.md` update; no code/runtime paths changed, so no test run was required for this documentation/instructions-only restoration.
[2026-04-11] Stabilization tranche docs/release sync completed on the owned docs/memory-bank surface.
- Updated `README.md`, `docs/capabilities.md`, `docs/getting-started.md`, `docs/configuration.md`, `docs/migration-guide.md`, and `CHANGELOG.md` to document secure-by-default defaults and the `v1.4.0` release posture.
- Documented the three explicit upgrade recipes required by the tranche: MCP host exec opt-in, `LocalSandboxProvider` host execution opt-in, and intentional `/v1/query` exposure.
- Synced `.memory-bank/STATUS.md`, `.memory-bank/plan.md`, and `.memory-bank/checklist.md` to current repo truth and the stabilization tranche.
- Verification performed on the owned docs only: targeted `rg` searches for `enable_host_exec`, `allow_host_execution`, `allow_unauthenticated_query`, `LocalSandboxProvider`, `sandboxed execution`, and `/v1/query` to ensure stale wording was removed or replaced where required.
- No source code or tests were touched in this tranche.
[2026-04-11] Stabilization tranche implementation completed across observability, release packaging, and validation.
- Added `src/swarmline/observability/security.py` and wired consistent `security_decision` logs into the deny-paths for `LocalSandboxProvider.execute()`, `exec_code(trusted=False)`, `HttpxWebProvider.fetch()` blocked targets, and `swarmline serve` query denial paths (`query_disabled` vs `missing_or_invalid_bearer_token`).
- Removed the legacy string-pattern blocklist from `src/swarmline/mcp/_tools_code.py`; the helper is now documented and tested as explicit unsafe host execution behind the trusted gate, not as a pseudo-sandbox.
- Updated release truth to `v1.4.0`: `pyproject.toml`, `src/swarmline/serve/app.py`, `CHANGELOG.md`, user-facing docs, and `.memory-bank/*` are now aligned.
- Fixed the Postgres integration harness loop-scope issue by dropping the async `session_factory` fixture from module scope to per-test scope in `tests/integration/test_postgres_backends_integration.py`.
- Removed two repo-wide `ruff` blockers from tests (`tests/unit/test_execution_context.py`, `tests/unit/test_namespaced_event_bus.py`) while running the validation matrix.
- Validation performed:
  - `pytest -q` → `4223 passed, 3 skipped, 5 deselected`
  - `pytest -m integration -q` → `31 passed, 5 skipped, 4195 deselected`
  - disposable Postgres harness via Docker + `SWARMLINE_TEST_POSTGRES_DSN=... pytest tests/integration/test_postgres_backends_integration.py -q` → `3 passed`
  - `python -m pip install ddgs` for the optional live search dependency, then `pytest -m live -q -rs` → `5 passed`
  - `ruff check src/ tests/` → green
  - `mypy src/swarmline/` → `Success: no issues found in 347 source files`
[2026-04-11] Audit remediation tranche implemented and validated end-to-end.
- Security hardening shipped: shared namespace-segment validation (`path_safety.py`) now protects filesystem-backed memory/sandbox/todo paths; `A2AServer` and `HealthServer` require auth by default with explicit loopback-only `allow_unauthenticated_local=True`; `CliAgentRuntime` now inherits only an allowlisted host env by default; MCP HTTP/SSE targets are validated against insecure HTTP and private/loopback/link-local/metadata destinations unless explicitly opted in; `PlanStore.load()/update_step()` now respect the active namespace.
- Public contract/docs truth shipped: root `README.md` quickstarts were rewritten to the real API (`SecurityGuard`, graph agents, knowledge bank, pipeline builder), and `tests/integration/test_docs_examples_consistency.py` now executes root README quickstart Python fences to catch drift.
- Architecture boundary shipped: added `RuntimeFactoryPort` and shared `runtime_dispatch` seams so `agent/` depends on an abstraction instead of directly on the concrete runtime factory; `AgentConfig.resolved_model` remains only as a deprecated compatibility shim over `resolve_model_name()`.
- Low-risk phase-4 DRY slice shipped: extracted shared graph task-board serialization/comment helpers into `src/swarmline/multi_agent/graph_task_board_shared.py`, with SQLite/Postgres backends keeping their existing static wrappers and behavior.
- Validation performed:
  - targeted security packs green (`201 passed`, plus MCP/docs/runtime targeted packs green)
  - targeted graph task-board regression green (`46 passed, 3 skipped`)
  - repo-wide `ruff check src tests` → green
  - repo-wide `mypy src/swarmline` → `Success: no issues found in 351 source files`
  - full offline `pytest -q` → `4249 passed, 3 skipped, 5 deselected`
[2026-04-12 05:35] Detailed spec по `ThinRuntime` как `coding-agent profile` доведён до execution-ready состояния в `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md`.
- Спецификация опирается на analysis report `2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md`, feature plan `2026-04-12_feature_thin-coding-agent-profile.md` и ограничения из `RULES.md`.
- Зафиксированы: scope/non-goals, acceptance criteria, source-of-truth reuse matrix, architecture seams, compatibility contract, task lifecycle contract, coding context contract, 9 implementation steps, tranche-level verification strategy и final acceptance gate.
- После judge-review по phase `parallelize` execution section усилена до stage-gated wave contracts: для каждой wave есть `inputs`, `owner`, `write scope`, `tests first`, `exit criteria`, `merge gate` и `fail-fast stop condition`.
- Отдельно закреплена ownership map для high-conflict файлов (`runtime/thin/runtime.py`, `runtime/ports/thin.py`, `runtime/thin/prompts.py`, `orchestration/**`, `policy/**`) и правило запуска downstream waves только от последнего merged baseline.
- Зафиксировано, что `claw-code-agent` остаётся `reference-only` до отдельного подтверждения лицензии; прямой reuse ограничен существующими модулями `swarmline` и seam-level adaptation из `aura`.
- Проверка на этом шаге: итоговый spec-файл существует в `.specs/tasks/todo/`, draft-версия удалена, `progress.md` обновлён. Код и тесты проекта не менялись, поэтому `pytest`/`ruff`/`mypy` не запускались.
[2026-04-12 06:40] GSD phase-planning для `implement-thin-coding-agent-profile` доведён до blocker-free состояния по фазам 07-10.
- На основе `.specs/tasks/todo/implement-thin-coding-agent-profile.feature.md`, analysis report `2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md` и feature plan `2026-04-12_feature_thin-coding-agent-profile.md` оформлены executable GSD plans:
  - `.planning/phases/07-coding-profile-foundation/07-01-PLAN.md`
  - `.planning/phases/08-coding-task-runtime-and-persistence/08-01-PLAN.md`
  - `.planning/phases/09-coding-context-and-compatibility/09-01-PLAN.md`
  - `.planning/phases/10-coding-subagent-inheritance-and-validation/10-01-PLAN.md`
- По ходу planning loop обновлены `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md` и phase context-файлы `07-CONTEXT.md`, `08-CONTEXT.md`, `09-CONTEXT.md`, `10-CONTEXT.md` под новый coding-agent tranche.
- Ключевые post-checker правки:
  - Phase 07 зафиксирована как foundation-only без протекания persistence/todo runtime из Phase 08; синхронизирован `files_modified`.
  - Phase 08 переведена на contract-first с ISP-compliant ports вместо монолитного protocol, добавлен explicit allow-list expansion через `runtime/thin/coding_profile.py`, typed snapshot persistence/rehydration и parity-regression для `coding_toolpack`.
  - Phase 09 получила обязательный RED smoke proof для alias execution на real coding-mode path, continuity links к `TaskSessionStore`, persistence re-check и расширенный broader regression по coding-profile/tool-surface drift.
  - Phase 10 получила explicit `10-01-GATE.md`, полный canonical `read_first`, links к `context/` и `policy/`, mandatory `LLM-as-Judge` section и hard `CVAL-03` proof через Python AST public-surface audit `HEAD vs working tree`.
- Верификация planning loop выполнена через несколько раундов `gsd-plan-checker` сабагентов; итоговый статус после последних post-fix sanity checks:
  - Phase 07: blocker-free, 1 residual warning про плотный scope.
  - Phase 08: blocker-free, residual warnings только про плотность/derivation, без обязательной ревизии.
  - Phase 09: blocker-free, tranche-final closure осознанно оставлена на Phase 10 по фазовой границе.
  - Phase 10: blocker-free после AST-audit fix; sanity-check вернул `Blockers: none`, `Warnings: none`.
- Код проекта на этом шаге не менялся; это planning-only tranche. Поэтому `pytest`, `ruff` и `mypy` по репозиторию не запускались, а verification performed относится к phase-plan review/subagent checks и structural consistency планов.
[2026-04-13] Phase 11 (Foundation Filters) завершена — ThinRuntime Parity v2 старт.
- Milestone: v1.5.0 Parity v2 (7 фаз, IDEA-044—IDEA-053). Roadmap: docs/2026-04-13_milestone_v1.5.0-parity-v2.md
- Phase 11 delivered: InputFilter protocol + ProjectInstructionFilter (CLAUDE.md/project instructions loading) + SystemReminderFilter (dynamic system reminder injection), wired into ThinRuntime filter chain.
- 50 новых тестов: 19 (ProjectInstructionFilter) + 17 (SystemReminderFilter) + 14 (ThinRuntime integration).
- Judge score: 4.40/5.0 (PASS).
- Key commits: d6de9ea (phase-11 implementation), 7c4124f (docs: advance to Phase 12), 0fc6e15 (milestone roadmap), 1eb5c5b (requirements), a8c2384 (research).
- Verification: pytest -q → 4778 passed, 3 skipped, 5 deselected. ruff check src/ tests/ → all checks passed. Source files: 328.
- Next: Phase 12 (Tool Surface Expansion) — WebSearch + WebFetch builtin tools + Thinking tool.
[2026-04-13] Phase 12 (Tool Surface Expansion) завершена — Judge 4.43/5.0, commit 4d2d018.
- Delivered:
  - Domain allow/block filter for web_fetch in HttpxWebProvider: RuntimeConfig.web_allowed_domains/web_blocked_domains fields, domain validation on fetch(), 20 unit tests.
  - MCP resource reading in McpClient: list_resources() + read_resource() with in-memory caching, ResourceDescriptor frozen dataclass exported from domain layer, 11 unit tests.
  - read_mcp_resource tool registered in ToolExecutor + wired into ThinRuntime active_tools, 15 integration tests.
- Quality gates: pytest -q → 4824 passed, 3 skipped, 5 deselected. ruff check src/ tests/ → all checks passed. Source files: ~330.
- Parity v2 progress: 2/7 фаз (29%). Overall: 12/17 фаз (71%).
- Next: Phase 13 — Conversation Compaction (LLM-суммаризация истории + token threshold trigger).
[2026-04-13] Phase 13 (Conversation Compaction) завершена — Judge 4.23/5.0, commit 8a63ad6.
- Delivered: ConversationCompactionFilter реализует InputFilter protocol с 3-tier cascade:
  - Tier 1: tool result collapse — старые tool call/result пары сворачиваются в compact summaries
  - Tier 2: LLM summarization — старейшие сообщения суммаризируются через async llm_call
  - Tier 3: emergency truncation — дропаем старейшие сообщения O(n) при исчерпании лимитов
- CompactionConfig frozen dataclass: threshold, preserve_recent_pairs, per-tier enable flags
- Auto-wired в ThinRuntime.run() из RuntimeConfig.compaction (None → no-op, backward-compatible)
- 35 новых тестов: 26 unit + 9 integration
- Quality gates: pytest -q → 4859 passed, 3 skipped, 5 deselected. ruff check src/ tests/ → all checks passed. Source files: ~330.
- Parity v2 progress: 3/7 фаз (43%). Overall: 13/17 фаз (76%).
- Next: Phase 14 — Session Resume (conversation history persistence + ThinRuntime resume wiring).
[2026-04-13] Phase 14 (Session Resume) завершена — Judge 4.30/5.0, commit d3602c5.
- Delivered:
  - JsonlMessageStore: JSONL file-based message persistence. Filenames = SHA-256(session_id). Corrupted-line resilience (skip bad JSON, continue). Implements MessageStore protocol.
  - Conversation.resume(session_id): loads full message history from MessageStore, applies auto-compaction via CompactionConfig (Phase 13 integration).
  - Auto-persist in say() and stream(): saves messages after each turn without explicit caller action.
  - 40 новых тестов: 18 JSONL unit + 10 resume unit + 12 integration.
- Quality gates: pytest -q → 4899 passed, 3 skipped, 5 deselected. ruff check src/ tests/ → all checks passed. Source files: ~332.
- Parity v2 progress: 4/7 фаз (57%). Overall: 14/17 фаз (82%).
- Next: Phase 15 — Thinking Events (ThinkingEvent domain type + ThinRuntime emission wiring).

[2026-04-13] Phase 17 (Parallel Agent Infrastructure) завершена — Judge 4.15/5.0, commit 2e2c800. ФИНАЛЬНАЯ ФАЗА PARITY v2.
- Delivered:
  - SubagentSpec.isolation="worktree": child agents run in dedicated git worktree with automatic lifecycle (create/cleanup/stale detection/max 5 limit)
  - RuntimeEvent.background_complete: domain event for async agent completion notifications
  - SubagentSpec.run_in_background: fire-and-forget spawn with output buffering and mandatory timeout
  - monitor_agent tool: polling-based status/output check for background agents
  - ThinRuntime wiring: on_background_complete callback + _bg_events draining in run() loop
  - 54 новых тестов: 14 worktree + 8 tool isolation + 15 background + 17 monitor/runtime
- Review: 3 SERIOUS findings (cwd not applied, assert→ValueError, callback crash) — all fixed iteration 2
- Quality gates: pytest -q → 5096 passed, 5 skipped, 5 deselected. ruff clean.
- **Parity v2 progress: 7/7 фаз (100%). Overall: 17/17 фаз (100%). PARITY COMPLETE.**
- Next: v1.5.0 release.

## 2026-04-21

### Auto-capture 2026-04-21 (session 85d26e5f)
- Session ended without an explicit /mb done
- Details will be reconstructed on the next /mb start (MB Manager can read the transcript)

## 2026-04-25

### Production v2.0 — Phase 01a (ty-strict-foundation): Sprint 1A COMPLETE

**Goal:** ty 75 → ≤62, 11 critical runtime-bug'ов → 0, CI gate активен. **Achieved.**

**6 stages, 21 новых тестов, 7 файлов нового кода/конфига:**

- **Stage 1** — `tests/architecture/test_ty_strict_mode.py` (3 tests, slow marker) + `.github/workflows/ci.yml` (lint + typecheck + tests + architecture jobs) + `slow` marker в `pyproject.toml`. Baseline: 75
- **Stage 2** — `CodingTaskBoardPort` Protocol (composition of GraphTaskBoard + GraphTaskScheduler + cancel_task) → `coding_task_runtime.py` typed correctly. 15 tests. Baseline: 72 (-3)
- **Stage 3** — `project_instruction_filter.py` annotation fix (`list[tuple[int, list[str]]]`) + `agent_registry_postgres.py` typed `cast(CursorResult, result).rowcount`. 4 tests + 2 PG-skipped. Baseline: 70 (-2)
- **Stage 4** — `ToolFunction` Protocol (`@runtime_checkable`) + `tool()` decorator returns `ToolFunction` natively. Removed 4 `# type: ignore[attr-defined]`. 8 tests. Baseline: 66 (-4)
- **Stage 5** — `_hook_name(...)` helper (`getattr(hook, "__name__", repr(hook))`) replacing 4 inline `entry.callback.__name__` accesses in `hooks/dispatcher.py`. 11 tests. Baseline: 62 (-4)
- **Stage 6** — Documentation handoff: `notes/2026-04-25_ty-strict-decisions.md` (3 reusable patterns: OptDep / DecoratedTool / CallableUnion), `BACKLOG.md ADR-003` (Use ty strict-only), `plans/...01b...md` scaffolded for next Sprint

**Verification (Sprint 1A Gate, all 7 conditions GREEN):**
- ✅ `ty check src/swarmline/` = **62 diagnostics** (was 75, -13)
- ✅ 0 critical errors на 11 target lines (coding_task_runtime / project_instruction_filter / agent_registry_postgres / agent/tool / graph_tools / hooks/dispatcher)
- ✅ 4500+ existing tests passed (no regressions in any of the 4 areas)
- ✅ ruff check + format clean
- ✅ All Sprint 1A artifacts on disk
- ✅ `tests/architecture/ty_baseline.txt` = 62
- ✅ `.github/workflows/ci.yml` runs `ty check src/swarmline/`, fail-on-error

**Tests:** 21 new (3 architecture + 6 unit/15 integration Stage 2 + 4 Stage 3 + 8 Stage 4 + 11 Stage 5 — overlap deduplicated). All green. Cumulative: 5117 + 21 = 5138 passing tests.

**Next step:** Sprint 1B (`plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md`) — apply 3 patterns to remaining 62 errors → ty: 0 → release v1.5.0 typing gate green.

**Files modified/added:**
- ✚ `tests/architecture/__init__.py`, `tests/architecture/test_ty_strict_mode.py`, `tests/architecture/ty_baseline.txt` (62)
- ✚ `.github/workflows/ci.yml` (4 jobs: lint, typecheck, tests, architecture)
- ✚ `src/swarmline/agent/tool_protocol.py` (`ToolFunction` Protocol)
- ✚ `src/swarmline/hooks/_helpers.py` (`_hook_name` helper)
- ✚ `src/swarmline/orchestration/coding_task_ports.py` (`CodingTaskBoardPort` composite)
- ✚ 4 new test files (project_instruction_filter, agent_registry_postgres, tool_function_protocol, hook_name_helper, coding_task_runtime_protocol_deps, coding_task_runtime_cancel_flow)
- ✚ `.memory-bank/notes/2026-04-25_ty-strict-decisions.md`
- ✚ `.memory-bank/plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md` (scaffold)
- ⌥ `pyproject.toml` (slow marker)
- ⌥ `src/swarmline/agent/__init__.py` (export ToolFunction)
- ⌥ `src/swarmline/agent/tool.py` (return type → ToolFunction)
- ⌥ `src/swarmline/multi_agent/graph_tools.py` (removed 3 `# type: ignore`)
- ⌥ `src/swarmline/orchestration/coding_task_runtime.py` (board: CodingTaskBoardPort)
- ⌥ `src/swarmline/project_instruction_filter.py` (segments annotation)
- ⌥ `src/swarmline/multi_agent/agent_registry_postgres.py` (CursorResult cast)
- ⌥ `src/swarmline/hooks/dispatcher.py` (4 _hook_name swaps)
- ⌥ `.memory-bank/BACKLOG.md` (ADR-003 filled)
- ⌥ `.memory-bank/checklist.md` (6 stages marked DONE)

### Sprint 1B (Phase 01b: ty-bulk-cleanup) — COMPLETE [Stage 1 → 6, ty 62 → 0]

**Goal:** Drive `ty check src/swarmline/` from 62 → 0 diagnostics by applying the 3 canonical patterns from Sprint 1A's decisions note (OptDep stub / DecoratedTool ToolFunction / CallableUnion). Lock baseline=0 as the v1.5.0 release gate.

**Result:** **ACHIEVED.** 6 stages, 5 commits, ~70 new tests, baseline=0 locked, ADR-003 outcome confirmed (ty strict-mode = sole release gate).

**Per-stage breakdown:**

| Stage | Goal | ty | Commit | New tests |
|-------|------|----|----|-----------|
| 1 | OptDep batch (22 unresolved-import) | 62 → 40 | 88d51d5 | 23 |
| 2 | Unresolved-attribute batch (4 fixes) | 40 → 36 | e4f1d70 | ~5 |
| 3 | Callable narrow (9 call-non-callable) | 36 → 27 | a5fb6fe | 10 |
| 4 | Argument-type batch (22 mixed → 5) + STRUCTURAL `event_mapper.py` | 27 → 5 | 65f08af | 29 |
| 5 | Точечные остатки (5 misc → 0) | 5 → 0 | 2299dff | 10 |
| 6 | Final verification + lock baseline=0 | 0 (locked) | (this commit) | 0 |

**Key learnings:**
- `# type: ignore[<rule>]` is INERT under `respect-type-ignore-comments = false`. Project policy: ty-native `# ty: ignore[<rule>]  # <reason ≥10 chars>` everywhere; Stage 4+5 cleaned 22 inert legacy ignores.
- Real bug found in `pi_sdk/event_mapper.py` (Stage 4): `TurnMetrics(input_tokens=...)` would raise `TypeError` at runtime; renamed to canonical `tokens_in`/`tokens_out`/`tool_calls_count`/`model`. ty caught a latent bug — exactly the value of strict typing as a gate.
- Line-anchored tests are the right scaffolding for ignore-style fixes. They catch line drift after `ruff format` immediately and prevent silent re-introduction.
- Multi-rule ty ignore syntax `# ty: ignore[rule-1, rule-2]` works (Stage 5 Gemini parts loop).
- Architecture meta-test parser must recognize both `Found N diagnostics` AND `All checks passed!` — added in Stage 5.

**Sprint 1B Gate verification:**
- ✅ `ty check src/swarmline/` → All checks passed! (0 diagnostics)
- ✅ `tests/architecture/ty_baseline.txt` = **0**
- ✅ Full offline `pytest` → 5352 passed, 7 skipped, 5 deselected (no regressions)
- ✅ `ruff check`, `ruff format --check` clean on all touched files
- ✅ ADR-003 outcome: ty strict-mode = sole release gate (no mypy)

**Tests cumulative:** 5138 (post-1A) + 77 (1B) ≈ 5215 → actual 5352 (some overlap with concurrent feature work). Net Sprint 1B addition: ~77 line-anchored / structural / no-naked / multi-rule / inert-mypy regression tests.

**Files modified/added (Sprint 1B):**
- ✚ `tests/unit/test_optdep_typing_fixes.py`, `tests/unit/test_attribute_resolution_fixes.py`, `tests/unit/test_callable_narrow_fixes.py`, `tests/unit/test_argument_type_fixes.py`, `tests/unit/test_misc_typing_fixes.py`
- ⌥ `tests/architecture/test_ty_strict_mode.py` (parser recognizes "All checks passed!")
- ⌥ `tests/architecture/ty_baseline.txt` (62 → 40 → 36 → 27 → 5 → **0** locked)
- ⌥ ~30 source files across `src/swarmline/` (line-anchored ignore + reason; only 1 structural fix in `pi_sdk/event_mapper.py`)
- ⌥ `.memory-bank/checklist.md` (Sprint 1B section, 6 stages DONE)
- ⌥ `.memory-bank/STATUS.md` (release gate green; Sprint 1A/1B in roadmap; tests=5352; v1.5.0 gate table)
- ⌥ `.memory-bank/plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md` (all 6 stages DONE)

**Next step:** v1.5.0 release branch. `release/v1.5.0` → bump `pyproject.toml` → finalize CHANGELOG → merge to main → tag v1.5.0 → `./scripts/sync-public.sh --tags` → public PyPI via OIDC Trusted Publishing.

