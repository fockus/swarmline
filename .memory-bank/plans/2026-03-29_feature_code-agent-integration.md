# Phase 16: Code Agent Integration — Детальный план

> **Мастер-план:** `plans/2026-03-29_masterplan_v4.md`
> **Приоритет:** ★ HIGH — game-changer для adoption
> **Оценка:** 10-14 дней на всю фазу

## Концепция

Swarmline становится **универсальным инструментом** для код-агентов:

```
Code Agent (мозги + подписка LLM)
    └── MCP/CLI → Swarmline (инфраструктура агентов)
                     ├── Headless: memory, tools, plans, state (0 LLM)
                     └── Full: + собственные агенты (API key пользователя)
```

**Юридическая безопасность:** Swarmline = tool, как GitHub MCP или Figma MCP. Код-агент остаётся продуктом. Не нарушает ToS Anthropic/OpenAI.

---

## 16.1 — Swarmline MCP Server

### Файлы

| Файл | Действие | Строк |
|------|----------|-------|
| `src/swarmline/mcp/__init__.py` | NEW | 20 |
| `src/swarmline/mcp/server.py` | NEW — FastMCP server | 350 |
| `src/swarmline/mcp/session.py` | NEW — StatefulSession | 200 |
| `src/swarmline/mcp/sandbox_exec.py` | NEW — safe code execution | 150 |
| `src/swarmline/mcp/__main__.py` | NEW — entry point | 30 |
| `pyproject.toml` | MODIFY — entry point + dep | 5 |
| `tests/unit/test_mcp_server.py` | NEW | 300 |
| `tests/unit/test_mcp_session.py` | NEW | 200 |
| `tests/integration/test_mcp_integration.py` | NEW | 150 |
| `docs/mcp-server.md` | NEW | 200 |

### Tools (15 typed + 1 code)

**Agent lifecycle:**
1. `swarmline_create_agent(name, system_prompt, model?, runtime?, memory?, tools[])` → agent_id
2. `swarmline_query(agent_id, prompt)` → response text
3. `swarmline_conversation(agent_id, message, session_id?)` → response text
4. `swarmline_list_agents()` → JSON array
5. `swarmline_destroy_agent(agent_id)` → confirmation

**Memory:**
6. `swarmline_memory_store(agent_id, key, value, tags[]?)` → confirmation
7. `swarmline_memory_recall(agent_id, query, top_k?)` → JSON array of facts
8. `swarmline_memory_list(agent_id, tag?)` → JSON array

**Multi-agent:**
9. `swarmline_create_team(name, lead_config, worker_configs[])` → team_id
10. `swarmline_team_task(team_id, task_description)` → result

**Planning:**
11. `swarmline_create_plan(goal, steps[])` → plan_id
12. `swarmline_execute_plan(plan_id)` → execution result

**Tools:**
13. `swarmline_execute_tool(tool_name, args{})` → tool output

**System:**
14. `swarmline_status()` → system health JSON
15. `swarmline_configure(settings{})` → confirmation

**Code REPL:**
16. `swarmline_execute(code)` → eval result (stateful Python session)

### StatefulSession

```python
class StatefulSession:
    """Manages state across MCP tool calls."""
    _agents: dict[str, Agent]           # agent_id → Agent
    _conversations: dict[str, Conversation]  # session_id → Conversation
    _teams: dict[str, TeamOrchestrator]
    _plans: dict[str, Plan]
    _memory_providers: dict[str, MemoryProvider]
    _code_globals: dict[str, Any]       # persistent Python REPL state

    async def create_agent(self, ...) -> str: ...
    async def query(self, agent_id, prompt) -> str: ...
    async def cleanup(self) -> None: ...
```

### DoD
- [ ] `swarmline-mcp` запускается как STDIO MCP server
- [ ] `python -m swarmline.mcp` — альтернативный запуск
- [ ] 15 typed tools + 1 code REPL — все возвращают JSON
- [ ] StatefulSession: agents/memory/plans persist между вызовами
- [ ] swarmline_execute: sandboxed Python REPL (restricted builtins)
- [ ] Headless mode (default): только memory/tools/plans (0 LLM)
- [ ] Full mode (--mode full): + agent create/query (API key required)
- [ ] Error handling: invalid agent_id, missing API key, timeout → structured JSON errors
- [ ] Structured logging через structlog (НИКОГДА не stdout — corrupts JSON-RPC!)
- [ ] Graceful shutdown: cleanup agents/sessions при SIGTERM
- [ ] Unit-тесты: каждый tool, session lifecycle, error paths, headless vs full mode
- [ ] Integration-тест: MCP client → server → full roundtrip

---

## 16.2 — Swarmline CLI Client

### Файлы

| Файл | Действие | Строк |
|------|----------|-------|
| `src/swarmline/cli/__init__.py` | NEW | 10 |
| `src/swarmline/cli/main.py` | NEW — Click app | 80 |
| `src/swarmline/cli/agent_cmd.py` | NEW | 180 |
| `src/swarmline/cli/memory_cmd.py` | NEW | 120 |
| `src/swarmline/cli/team_cmd.py` | NEW | 100 |
| `src/swarmline/cli/run_cmd.py` | NEW | 80 |
| `src/swarmline/cli/setup_cmd.py` | NEW — auto-config code agents | 150 |
| `src/swarmline/cli/state.py` | NEW — SQLite state persistence | 100 |
| `pyproject.toml` | MODIFY — entry point `swarmline` | 3 |
| `tests/unit/test_cli_agent.py` | NEW | 200 |
| `tests/unit/test_cli_memory.py` | NEW | 120 |
| `tests/unit/test_cli_setup.py` | NEW | 100 |
| `tests/integration/test_cli_integration.py` | NEW | 150 |
| `docs/cli.md` | NEW | 250 |

### Commands

```
swarmline agent create --name X --prompt "..."     → agent-id (JSON)
swarmline agent query <id> "prompt"                → response (text|JSON)
swarmline agent chat <id>                          → interactive REPL
swarmline agent list                               → table/JSON
swarmline agent destroy <id>                       → confirmation

swarmline memory store <id> --key K --value V      → confirmation
swarmline memory recall <id> "query"               → facts (JSON)
swarmline memory list <id>                         → facts (JSON)

swarmline team create --config team.yaml           → team-id
swarmline team task <id> "description"             → result
swarmline team status <id>                         → status (JSON)

swarmline run <script.py>                          → script output
swarmline run --code 'await agent.query("hi")'     → result

swarmline mcp-serve                                → start MCP server
swarmline setup claude-code|codex|opencode         → auto-configure
```

### State persistence

```
~/.swarmline/
├── state.db          ← SQLite: agents, memory, sessions
├── config.yaml       ← user preferences
└── logs/             ← structured logs
```

### DoD
- [ ] `pip install swarmline[cli]` → `swarmline --help` работает
- [ ] agent create/query/list/destroy — полный lifecycle
- [ ] memory store/recall/list — persistent между вызовами
- [ ] team create/task/status — multi-agent из CLI
- [ ] `swarmline run <script.py>` — Python с Swarmline pre-imported
- [ ] `swarmline mcp-serve` — запуск MCP server
- [ ] JSON output при pipe (`| jq`), text при TTY
- [ ] State в `~/.swarmline/state.db` (SQLite)
- [ ] Exit codes: 0=ok, 1=error, 2=agent-error
- [ ] Unit-тесты: каждый subcommand + format switching

---

## 16.3 — Claude Code Skill

### Файлы

| Файл | Действие |
|------|----------|
| `skills/swarmline-agents/SKILL.md` | NEW — skill definition |
| `skills/swarmline-agents/references/examples.md` | NEW — 10 patterns |
| `skills/swarmline-agents/references/patterns.md` | NEW — 7 architectures |
| `skills/swarmline-agents/references/troubleshooting.md` | NEW |
| `docs/claude-code-integration.md` | NEW |
| `docs/codex-integration.md` | NEW |

### SKILL.md frontmatter

```yaml
---
name: swarmline-agents
description: >
  Create and orchestrate AI agents with Swarmline framework.
  Use when asked to create agents, multi-agent teams, agent
  pipelines, or persistent agent memory. Agents use YOUR LLM — no extra keys.
allowed-tools: Bash(swarmline *), Bash(pip install swarmline*), Read, Write, Glob, Grep
---
```

### Skill logic (instruction body)

1. Check: `swarmline --version` → install if missing
2. Detect: MCP available? → use MCP tools (faster, stateful)
3. Fallback: CLI via Bash (`swarmline agent create ...`)
4. Patterns: reference examples.md для конкретного use case
5. Multi-agent: YAML config → `swarmline team create`

### DoD
- [ ] SKILL.md: auto-invokes при "create agent", "agent team", "swarmline"
- [ ] Bash fallback: works without MCP config
- [ ] MCP mode: uses swarmline_* tools when available
- [ ] examples.md: 10 copy-paste patterns
- [ ] patterns.md: 7 architecture patterns
- [ ] troubleshooting.md: top-10 issues
- [ ] Claude Code setup guide: 3-step (install, config, verify)
- [ ] Codex setup guide: 3-step

---

## 16.4 — Headless Mode

### Файлы

| Файл | Действие |
|------|----------|
| `src/swarmline/runtime/headless.py` | NEW — HeadlessRuntime |
| `src/swarmline/mcp/server.py` | MODIFY — mode flag |
| `tests/unit/test_headless_runtime.py` | NEW |
| `docs/headless-mode.md` | NEW |

### Headless capabilities (0 LLM calls)

| Capability | Headless | Full |
|-----------|----------|------|
| Memory CRUD | ✅ | ✅ |
| Tool execution | ✅ | ✅ |
| Plan CRUD | ✅ | ✅ |
| Team state | ✅ | ✅ |
| Session state | ✅ | ✅ |
| Event bus | ✅ | ✅ |
| Agent.query() | ❌ | ✅ (needs API key) |
| Agent.stream() | ❌ | ✅ (needs API key) |
| LLM summarization | ❌ | ✅ (needs API key) |

### DoD
- [ ] HeadlessRuntime: implements AgentRuntime, NotImplementedError on run()
- [ ] MCP default = headless (0 LLM), `--mode full` enables agents
- [ ] Full mode: validates API key presence, clear error if missing
- [ ] Unit-тесты: headless all ops, full mode with mock LLM

---

## 16.5 — Auto-Setup Configs

### Файлы

| Файл | Действие |
|------|----------|
| `src/swarmline/cli/setup_cmd.py` | NEW (in 16.2) |
| `integrations/claude-code/settings.json.example` | NEW |
| `integrations/claude-code/README.md` | NEW |
| `integrations/codex/config.toml.example` | NEW |
| `integrations/codex/README.md` | NEW |
| `integrations/opencode/config.example` | NEW |
| `integrations/opencode/README.md` | NEW |

### One-liner setup

```bash
swarmline setup claude-code   # patches ~/.claude/settings.json
swarmline setup codex         # patches ~/.codex/config.toml
swarmline setup opencode      # patches opencode config
```

### DoD
- [ ] `swarmline setup claude-code` — non-destructive JSON merge
- [ ] `swarmline setup codex` — non-destructive TOML merge
- [ ] Backup existing config before patching
- [ ] Confirmation prompt before write
- [ ] Example configs в `integrations/`
- [ ] Unit-тесты: config patching с mock filesystem

---

## 16.6 — Use Cases & E2E Tests

### Описание

7 реальных сценариев использования Swarmline код-агентами. Каждый сценарий = отдельный E2E тест, проверяющий полный workflow через CLI/MCP.

### Файлы

| Файл | Действие |
|------|----------|
| `tests/e2e/test_use_case_research_swarm.py` | NEW — UC1: Research Swarm |
| `tests/e2e/test_use_case_persistent_memory.py` | NEW — UC2: Persistent Memory |
| `tests/e2e/test_use_case_review_pipeline.py` | NEW — UC3: Review Pipeline |
| `tests/e2e/test_use_case_resumable_plans.py` | NEW — UC4: Resumable Plans |
| `tests/e2e/test_use_case_meta_agent.py` | NEW — UC5: Meta Agent |
| `tests/e2e/test_use_case_cross_tool.py` | NEW — UC6: Cross-Tool Orchestration |
| `tests/e2e/test_use_case_learning_agent.py` | NEW — UC7: Learning Agent |
| `docs/use-cases.md` | NEW — документация всех 7 кейсов |

---

### UC1: "Исследователь-на-лету" (Research Swarm)

**Суть:** Код-агент создаёт 3 специализированных агента (security, perf, compat), запускает параллельно, собирает результаты.

**E2E тест (headless, через team + memory):**
```
1. team_register_agent × 3 (security, perf, compat)
2. team_create_task × 3 (по задаче на каждого)
3. team_claim_task × 3 (каждый берёт свою)
4. memory_save_message × 3 (каждый "агент" сохраняет результат)
5. memory_get_messages → verify 3 results present
6. team_list_tasks → all DONE
```

**DoD:**
- [ ] 3 агента зарегистрированы, 3 задачи созданы/claimed/completed
- [ ] Результаты каждого агента сохранены в memory
- [ ] Все результаты retrievable по topic_id

---

### UC2: "Код-агент с долговременной памятью" (Persistent Brain)

**Суть:** Facts/decisions persist между вызовами. `memory store` → `memory recall` roundtrip.

**E2E тест (headless):**
```
1. memory_upsert_fact("user1", "arch-db", "PostgreSQL for ACID")
2. memory_upsert_fact("user1", "arch-pattern", "Clean Architecture")
3. memory_upsert_fact("user1", "team-pref", "TDD, pytest, async-first")
4. memory_get_facts("user1") → verify all 3 facts present
5. memory_upsert_fact("user1", "arch-db", "PostgreSQL + Redis cache") → overwrite
6. memory_get_facts("user1") → verify updated value
```

**DoD:**
- [ ] Facts persist across multiple tool calls in single session
- [ ] Overwrite works correctly (upsert semantics)
- [ ] Facts isolated by user_id

---

### UC3: "Фабрика code review" (Review Pipeline)

**Суть:** Мульти-агентный review pipeline: register agents → create tasks → claim → complete → aggregate results.

**E2E тест (headless, team + memory):**
```
1. team_register_agent × 3 (architect, security, style)
2. team_create_task("pr-123-arch", priority=HIGH)
3. team_create_task("pr-123-sec", priority=HIGH)
4. team_create_task("pr-123-style", priority=MEDIUM)
5. team_claim_task(assignee="architect") → gets pr-123-arch (HIGH first)
6. team_claim_task(assignee="security") → gets pr-123-sec
7. team_claim_task(assignee="style") → gets pr-123-style
8. memory_upsert_fact("pr-123", "arch-review", "LGTM")
9. memory_upsert_fact("pr-123", "sec-review", "WARN: SQL injection line 42")
10. memory_upsert_fact("pr-123", "style-review", "FIX: missing docstrings")
11. memory_get_facts("pr-123") → all 3 reviews present
12. team_list_tasks() → verify all claimed
```

**DoD:**
- [ ] Priority-based task claiming works (HIGH before MEDIUM)
- [ ] Each agent gets unique task (no double-claiming)
- [ ] Review results aggregatable via memory

---

### UC4: "Планирование со стейт-машиной" (Resumable Plans)

**Суть:** Plan lifecycle: create → approve → execute steps → resume after "interruption".

**E2E тест (headless):**
```
1. plan_create("Migrate REST to GraphQL", steps=["Analyze", "Design", "Implement", "Test"])
2. plan_get(plan_id) → status=draft, 4 steps pending
3. plan_approve(plan_id) → status=approved
4. plan_update_step(step-1, status=completed, result="47 endpoints found")
5. plan_update_step(step-2, status=in_progress)
6. plan_get(plan_id) → step-1 ✅, step-2 🔄, step-3/4 ⬜
   # ^^^ Simulate "interruption" — all state preserved
7. plan_update_step(step-2, status=completed, result="Schema designed")
8. plan_update_step(step-3, status=completed, result="Resolvers done")
9. plan_update_step(step-4, status=completed, result="Tests pass")
10. plan_get(plan_id) → all steps completed
```

**DoD:**
- [ ] Full plan lifecycle: draft → approved → steps executing → completed
- [ ] State preserved after partial execution (simulate resume)
- [ ] Each step has result text

---

### UC5: "Мета-агент" (Agent Factory) — Full mode only

**Суть:** Код-агент через `exec_code` создаёт и тестирует нового агента.

**E2E тест (code execution):**
```
1. exec_code("print(2 + 2)") → stdout="4"
2. exec_code("import json; print(json.dumps({'ok': True}))") → stdout='{"ok": true}'
3. exec_code с timeout (бесконечный цикл) → timeout error
4. exec_code с syntax error → stderr contains SyntaxError
```

**DoD:**
- [ ] Python code executes and returns stdout
- [ ] Timeout kills long-running code
- [ ] Syntax errors return in stderr
- [ ] Import stdlib works

---

### UC6: "Cross-tool оркестрация" (Multi-Agent Workspace)

**Суть:** Shared plan + shared memory + shared task queue — два "агента" координируются.

**E2E тест (headless, plan + team + memory):**
```
1. plan_create("Build dashboard", steps=["API schema", "Backend", "Frontend", "E2E"])
2. plan_approve(plan_id)
3. team_register_agent("backend", "Backend Dev", "backend")
4. team_register_agent("frontend", "Frontend Dev", "frontend")
5. team_create_task("api-schema", assignee="backend")
6. team_claim_task(assignee="backend") → gets api-schema
7. memory_upsert_fact("dashboard", "api-schema", '{"endpoints": ["/users", "/stats"]}')
8. plan_update_step(step-1, completed, "API schema defined")
9. # Frontend reads what backend produced:
10. memory_get_facts("dashboard") → contains api-schema
11. team_create_task("react-components", assignee="frontend")
12. team_claim_task(assignee="frontend") → gets react-components
13. plan_update_step(step-3, completed, "Components built using API schema")
14. plan_get(plan_id) → steps 1,3 completed, 2,4 pending
```

**DoD:**
- [ ] Two agents share plan, memory, and task queue
- [ ] Agent B reads facts stored by Agent A
- [ ] Plan reflects cross-agent progress

---

### UC7: "Обучающийся ассистент" (Learning Agent)

**Суть:** Агент сохраняет паттерны/уроки, потом recall для применения.

**E2E тест (headless, memory):**
```
1. memory_upsert_fact("patterns", "error-handling", "Always use Result type")
2. memory_upsert_fact("patterns", "naming", "Private: _prefix, Protocols: no prefix")
3. memory_upsert_fact("patterns", "testing", "Contract tests for all backends")
4. memory_upsert_fact("patterns", "arch", "Domain = 0 external deps")
5. memory_get_facts("patterns") → 4 patterns present
6. # Simulate "new session" — facts still available:
7. memory_get_facts("patterns") → same 4 patterns
8. # Update a pattern:
9. memory_upsert_fact("patterns", "error-handling", "Result type + structured error codes")
10. memory_get_facts("patterns") → updated value for error-handling
```

**DoD:**
- [ ] Patterns persist and are retrievable
- [ ] Overwrite/update works correctly
- [ ] Multiple patterns coexist in same namespace

---

### Общие DoD для UC E2E тесто��

- [ ] Все 7 E2E тестов проходят с `pytest tests/e2e/test_use_case_*.py -v`
- [ ] Все тесты работают в headless mode (0 LLM, 0 API keys)
- [ ] UC5 тестирует code execution (subprocess, timeout)
- [ ] Тесты не зависят друг от друга (isolated sessions)
- [ ] docs/use-cases.md документирует все 7 сценариев с примерами вызовов
- [ ] Каждый UC может быть воспроизведён через CLI: `swarmline agent/memory/plan/team ...`

---

## Порядок реализации

```
Week 1:
  16.1 MCP Server (core)     ← 4-5 дней
  16.2 CLI Client (parallel)  ← 3-4 дня (можно начать параллельно)
  16.4 Headless Mode          ← 1 день (flag в MCP server)

Week 2:
  16.3 Skill + docs           ← 2-3 дня
  16.5 Auto-setup configs     ← 1 день
  16.6 E2E Use Case tests     ← 1-2 дня
  docs/use-cases.md           ← 0.5 дня
  Testing + polish            ← 1 день
```

## Зависимости

- 16.1 → standalone (core)
- 16.2 → standalone (parallel с 16.1)
- 16.3 → после 16.1 или 16.2 (использует один из них)
- 16.4 → часть 16.1 (mode flag)
- 16.5 → после 16.1 (настройки для MCP server)

## Новые зависимости в pyproject.toml

```toml
[project.optional-dependencies]
mcp = ["fastmcp>=2.0"]
cli = ["click>=8.1"]

[project.scripts]
swarmline = "swarmline.cli.main:app"
swarmline-mcp = "swarmline.mcp.server:main"
```
