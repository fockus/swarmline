# Plan: DOC-debt + Phase 9 MVP + Phase 10A CLI Runtime

**Date:** 2026-03-18
**Type:** feature
**Status:** Draft
**Complexity:** XL (22 stages, ~90-120 minutes developer time)

## Goal

Close documentation debt (6-DOC, 7-DOC, 8-DOC), implement Phase 9 MVP (agent-as-tool, task queue, agent registry), and add CLI Agent Runtime (10A). All with contract-first approach, TDD, and Clean Architecture.

## Scope

### Included:
- examples/ directory with runnable Python scripts for all Phase 6-8 features
- CHANGELOG.md entries for v0.6.0, v0.7.0, v1.0.0-core
- docs/getting-started.md update with Phase 6-8 features
- mkdocs.yml update with full nav for Phase 6-8 doc pages
- Phase 9A: AgentTool Protocol + implementation + tests
- Phase 9B-MVP: TaskQueue Protocol + InMemory/Sqlite implementations + tests
- Phase 9C-MVP: AgentRegistry Protocol + InMemory implementation + tests
- Phase 10A: CliAgentRuntime + NdjsonParser + tests + docs

### NOT included:
- Phase 9 Full (enterprise tasks, hierarchy, delegation, scheduler)
- Phase 10B-10H (MCP, OAuth, RTK, LiteLLM, cognitia init)
- Phase 11 (OpenAI Agents SDK)
- Actual mkdocs build / deployment
- Redis session backend
- Full API reference auto-generation

## Assumptions

- Existing docs pages (structured-output.md, production-safety.md, sessions.md, observability.md, ui-projection.md, rag.md, runtime-registry.md) are complete and just need nav wiring
- examples/ directory does not exist yet (confirmed by investigation)
- Phase 6-8 code is fully implemented and tested (2122 tests passing)
- AgentRuntime Protocol (runtime/base.py) is stable and will not change
- RuntimeRegistry (runtime/registry.py) supports register/get/list_available
- SessionBackend Protocol (session/backends.py) is the reference for 9B storage patterns
- @tool decorator (agent/tool.py) is the reference for 9A tool integration
- CLI NDJSON format for Claude Code: claude --print - --output-format stream-json

## Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Examples depend on API keys at runtime | Medium | Low | All examples use mock/stub LLM call or clear env var instructions |
| 9A agent-as-tool circular dependency (Agent imports Runtime imports Agent) | Medium | High | Use lazy imports + Protocol-based decoupling |
| 9B TaskQueue Protocol grows beyond ISP limit | Low | Medium | Strict 5-method limit, split if needed |
| 10A NDJSON format changes in future Claude CLI versions | Medium | Medium | Pluggable NdjsonParser, version detection |
| mkdocs nav breaks with missing pages | Low | Low | Verify all referenced .md files exist before committing |

---

## BLOCK 1: DOC Debt

---

## Stage 1: examples/ -- runnable Python scripts

**Complexity:** M
**Time:** ~5 min
**Dependencies:** --
**Agent:** developer
**Files:**
- CREATE: examples/01_structured_output.py
- CREATE: examples/02_tool_decorator.py
- CREATE: examples/03_guardrails.py
- CREATE: examples/04_cost_budget.py
- CREATE: examples/05_retry_fallback.py
- CREATE: examples/06_sessions.py
- CREATE: examples/07_event_bus_tracing.py
- CREATE: examples/08_ui_projection.py
- CREATE: examples/09_rag.py
- CREATE: examples/README.md

### Tasks:
1. Create examples/ directory
2. Write each example as a standalone async Python script:
   - Imports from cognitia public API only
   - Uses asyncio.run(main()) pattern
   - Has a comment header explaining what it demonstrates
   - Uses a mock llm_call callable where possible to run without API keys
   - Each file <= 60 lines
3. Create examples/README.md listing all examples with 1-line descriptions

### DoD:
- [ ] 9 example files created, each syntactically valid Python
- [ ] Each example imports only from cognitia public API (no internal modules)
- [ ] README.md lists all examples
- [ ] Lint clean: ruff check examples/

### Test Scenarios:
- Static analysis only (examples are documentation, not test targets)
- ruff check examples/ passes

### Commands:
```bash
ruff check examples/
python -c "import ast, pathlib; [ast.parse(f.read_text()) for f in pathlib.Path('examples').glob('*.py')]"
```

### Edge cases:
- Examples that need API keys should have clear os.environ.get("ANTHROPIC_API_KEY") with error message
- Mock llm_call should return plausible responses

---

## Stage 2: CHANGELOG.md -- v0.6.0, v0.7.0, v1.0.0-core

**Complexity:** S
**Time:** ~3 min
**Dependencies:** --
**Agent:** developer
**Files:**
- MODIFY: CHANGELOG.md

### Tasks:
1. Add [1.0.0-core] - 2026-03-18 section with Phase 8 features (session backends, event bus, tracing, UI projection, RAG)
2. Add [0.7.0] - 2026-03-18 section with Phase 7 features (cost budget, guardrails, input filters, retry/fallback)
3. Add [0.6.0] - 2026-03-18 section with Phase 6 features (structured output via output_type, @tool decorator, adapter registry, cancellation, context manager, typed events, protocols split)
4. Add link references at bottom
5. Entries follow Keep a Changelog format with Added/Changed/Tests subsections

### DoD:
- [ ] 3 new version sections in CHANGELOG.md
- [ ] Each section has Added subsection with bullet points
- [ ] Link references at bottom are correct
- [ ] No duplicate entries with existing 0.5.0 section

### Test Scenarios:
- Manual review: sections are in reverse chronological order
- Links are syntactically valid markdown

### Commands:
```bash
head -100 CHANGELOG.md
```

---

## Stage 3: docs/getting-started.md -- update with Phase 6-8 features

**Complexity:** M
**Time:** ~5 min
**Dependencies:** --
**Agent:** developer
**Files:**
- MODIFY: docs/getting-started.md

### Tasks:
1. Update "Structured Output" section (line ~130) to show output_type with Pydantic model (not just output_format dict)
2. Add new section "Cost Budget" after Middleware section showing CostBudget usage
3. Add new section "Guardrails" showing Guardrail Protocol usage
4. Add new section "Sessions" showing SqliteSessionBackend persistence
5. Add new section "Event Bus and Tracing" showing ConsoleTracer
6. Add new section "RAG" showing Retriever Protocol usage
7. Add new section "UI Projection" showing ChatProjection + project_stream
8. Update "Next Steps" links to include new doc pages
9. Fix event type names in streaming section (line ~106-112): should use assistant_delta, tool_call_started (not text_delta, tool_use_start)

### DoD:
- [ ] 6 new sections added to getting-started.md
- [ ] Structured Output section updated to show output_type
- [ ] Streaming section uses correct event type names
- [ ] All code snippets use actual cognitia public API
- [ ] File is valid Markdown

### Test Scenarios:
- Manual review: code snippets match actual API
- All import paths exist in source tree

### Commands:
```bash
python -c "
from cognitia.runtime.cost import CostBudget
from cognitia.session.backends import SqliteSessionBackend
from cognitia.observability.tracing import ConsoleTracer
from cognitia.ui.projection import ChatProjection, project_stream
print('All imports OK')
"
```

### Edge cases:
- Backward compatibility: keep old output_format example as alternative

---

## Stage 4: mkdocs.yml -- full nav update

**Complexity:** S
**Time:** ~2 min
**Dependencies:** --
**Agent:** developer
**Files:**
- MODIFY: mkdocs.yml

### Tasks:
1. Add Phase 6-8 doc pages to nav under appropriate sections:
   - Features section: add Structured Output, Runtime Registry, Production Safety, Sessions, Observability, UI Projection, RAG
2. Verify all referenced .md files exist in docs/
3. Keep existing nav items, extend with new

### DoD:
- [ ] All existing doc pages (structured-output.md, production-safety.md, sessions.md, observability.md, ui-projection.md, rag.md, runtime-registry.md) are in nav
- [ ] Nav structure is logical (Getting Started > Core Concepts > Features > Reference)
- [ ] No broken references (all .md files exist)

### Test Scenarios:
- Verify with yaml parse and file existence check

### Commands:
```bash
python -c "
import yaml, pathlib
y = yaml.safe_load(open('mkdocs.yml'))
def extract_mds(nav, acc=None):
    if acc is None: acc = []
    if isinstance(nav, list):
        for item in nav: extract_mds(item, acc)
    elif isinstance(nav, dict):
        for v in nav.values(): extract_mds(v, acc)
    elif isinstance(nav, str) and nav.endswith('.md'):
        acc.append(nav)
    return acc
mds = extract_mds(y['nav'])
missing = [m for m in mds if not (pathlib.Path('docs') / m).exists()]
print(f'Total pages: {len(mds)}, Missing: {missing}')
"
```

---

## BLOCK 2: Phase 9 MVP

---

## Stage 5: 9A Protocol + Domain Types -- AgentTool

**Complexity:** S
**Time:** ~3 min
**Dependencies:** --
**Agent:** developer
**Files:**
- CREATE: src/cognitia/protocols/multi_agent.py
- CREATE: src/cognitia/multi_agent/__init__.py
- CREATE: src/cognitia/multi_agent/types.py

### Tasks:
1. Create src/cognitia/multi_agent/types.py with domain types:
   - AgentToolResult frozen dataclass: success: bool, output: str, error: str | None, agent_id: str, tokens_used: int, cost_usd: float
2. Create src/cognitia/protocols/multi_agent.py with:
   - AgentTool Protocol (runtime_checkable): as_tool(name: str, description: str) -> ToolSpec (1 method, well under ISP limit)
3. Create src/cognitia/multi_agent/__init__.py with re-exports
4. Update src/cognitia/protocols/__init__.py to re-export AgentTool

### DoD:
- [ ] AgentToolResult is frozen dataclass with 6 fields
- [ ] AgentTool Protocol has exactly 1 method (ISP-compliant)
- [ ] Both are importable from cognitia.protocols and cognitia.multi_agent
- [ ] mypy src/cognitia/multi_agent/ src/cognitia/protocols/multi_agent.py clean
- [ ] No external dependencies (stdlib + cognitia.runtime.types only)

### Test Scenarios:
- test_agent_tool_result_is_frozen -- cannot mutate fields
- test_agent_tool_result_default_values -- error=None, tokens_used=0, cost_usd=0.0
- test_agent_tool_protocol_is_runtime_checkable -- isinstance check works

### Commands:
```bash
mypy src/cognitia/multi_agent/ src/cognitia/protocols/multi_agent.py
ruff check src/cognitia/multi_agent/ src/cognitia/protocols/multi_agent.py
```

---

## Stage 6: 9A Contract Tests

**Complexity:** S
**Time:** ~3 min
**Dependencies:** Stage 5
**Agent:** tester
**Files:**
- CREATE: tests/unit/test_agent_tool_types.py
- CREATE: tests/unit/test_agent_tool_contract.py

### Tasks:
1. tests/unit/test_agent_tool_types.py:
   - test_agent_tool_result_is_frozen -- FrozenInstanceError on mutation
   - test_agent_tool_result_defaults -- error=None, tokens_used=0, cost_usd=0.0
   - test_agent_tool_result_to_dict -- serialization round-trip
2. tests/unit/test_agent_tool_contract.py:
   - test_agent_tool_protocol_runtime_checkable -- class implementing as_tool passes isinstance
   - test_agent_tool_as_tool_returns_tool_spec -- returned ToolSpec has name, description, parameters
   - test_agent_tool_as_tool_marks_local -- ToolSpec.is_local == True
   - test_agent_tool_without_method_fails_isinstance -- class without as_tool fails isinstance check

### DoD:
- [ ] 7 unit tests in 2 files
- [ ] All tests are contract tests (test Protocol, not implementation)
- [ ] Tests pass with ANY correct implementation of AgentTool
- [ ] pytest tests/unit/test_agent_tool_types.py tests/unit/test_agent_tool_contract.py -v all green

### Commands:
```bash
pytest tests/unit/test_agent_tool_types.py tests/unit/test_agent_tool_contract.py -v
```

---

## Stage 7: 9A Implementation -- AgentTool on ThinRuntime

**Complexity:** M
**Time:** ~5 min
**Dependencies:** Stage 5, Stage 6
**Agent:** developer
**Files:**
- CREATE: src/cognitia/multi_agent/agent_tool.py
- MODIFY: src/cognitia/runtime/thin/runtime.py (add as_tool method, ~15 lines)
- MODIFY: src/cognitia/multi_agent/__init__.py (re-export)

### Tasks:
1. Create src/cognitia/multi_agent/agent_tool.py:
   - create_agent_tool_executor(runtime, config, timeout_seconds) -> Callable -- async function that:
     a. Creates messages from tool input args
     b. Calls runtime.run(messages=..., system_prompt=..., active_tools=[])
     c. Collects final event text
     d. Returns AgentToolResult
     e. Handles timeout via asyncio.wait_for
     f. Handles errors -> AgentToolResult(success=False, error=str(e))
   - create_agent_tool_spec(name, description) -> ToolSpec -- generates ToolSpec with input parameter schema
2. Add as_tool(self, name, description) -> ToolSpec method to ThinRuntime:
   - Returns create_agent_tool_spec(name, description)
   - Registers the executor in self._local_tools via create_agent_tool_executor
3. File agent_tool.py stays under 100 lines

### DoD:
- [ ] ThinRuntime.as_tool("helper", "A helper agent") returns valid ToolSpec
- [ ] Executor function handles success path (returns AgentToolResult with output)
- [ ] Executor function handles error path (returns AgentToolResult with success=False)
- [ ] Executor function handles timeout (asyncio.TimeoutError)
- [ ] agent_tool.py <= 100 lines
- [ ] Contract tests from Stage 6 pass
- [ ] ruff check src/cognitia/multi_agent/ clean
- [ ] mypy src/cognitia/multi_agent/ clean

### Test Scenarios:
- test_thin_runtime_as_tool_returns_valid_spec -- name, description, parameters correct
- test_agent_tool_executor_success -- mock runtime returns final event, executor returns AgentToolResult
- test_agent_tool_executor_error -- runtime raises, executor returns success=False
- test_agent_tool_executor_timeout -- runtime exceeds timeout, executor returns timeout error

### Commands:
```bash
pytest tests/unit/test_agent_tool_types.py tests/unit/test_agent_tool_contract.py -v
ruff check src/cognitia/multi_agent/
mypy src/cognitia/multi_agent/
```

---

## Stage 8: 9A Integration Tests

**Complexity:** S
**Time:** ~3 min
**Dependencies:** Stage 7
**Agent:** tester
**Files:**
- CREATE: tests/integration/test_agent_tool_integration.py

### Tasks:
1. Integration test with real ThinRuntime + mock llm_call:
   - test_agent_as_tool_full_flow -- create ThinRuntime with mock llm, call as_tool, execute via another ThinRuntime that calls the sub-agent tool
   - test_agent_as_tool_sub_agent_error_propagates -- sub-agent llm raises, parent gets tool error result
   - test_agent_as_tool_timeout_integration -- sub-agent takes too long
   - test_agent_as_tool_result_contains_metrics -- tokens_used > 0

### DoD:
- [ ] 4 integration tests
- [ ] Tests use real ThinRuntime with mock llm_call (no external API)
- [ ] pytest tests/integration/test_agent_tool_integration.py -v all green

### Commands:
```bash
pytest tests/integration/test_agent_tool_integration.py -v
```

---

## Stage 9: 9B-MVP Protocol + Domain Types -- TaskQueue

**Complexity:** S
**Time:** ~3 min
**Dependencies:** --
**Agent:** developer
**Files:**
- CREATE: src/cognitia/multi_agent/task_types.py
- MODIFY: src/cognitia/protocols/multi_agent.py (add TaskQueue Protocol)

### Tasks:
1. Create src/cognitia/multi_agent/task_types.py:
   - TaskStatus enum: TODO, IN_PROGRESS, DONE, CANCELLED (4 values)
   - TaskPriority enum: LOW, MEDIUM, HIGH, CRITICAL (4 values)
   - TaskItem frozen dataclass: id, title, description, status, priority, assignee_agent_id, metadata, created_at
   - TaskFilter frozen dataclass: status, priority, assignee_agent_id (all optional)
2. Add to src/cognitia/protocols/multi_agent.py:
   - TaskQueue Protocol (runtime_checkable): 5 methods exactly:
     - async put(item: TaskItem) -> None
     - async get(filters: TaskFilter | None = None) -> TaskItem | None (highest priority unassigned)
     - async complete(task_id: str) -> bool
     - async cancel(task_id: str) -> bool
     - async list_tasks(filters: TaskFilter | None = None) -> list[TaskItem]
3. Update __init__.py re-exports

### DoD:
- [ ] TaskStatus has exactly 4 values
- [ ] TaskPriority has exactly 4 values
- [ ] TaskItem is frozen dataclass with 8 fields
- [ ] TaskQueue Protocol has exactly 5 methods (ISP limit)
- [ ] All types are stdlib-only (no external deps)
- [ ] mypy src/cognitia/multi_agent/task_types.py clean

### Test Scenarios:
- test_task_item_is_frozen -- FrozenInstanceError on mutation
- test_task_status_values -- exactly 4 statuses
- test_task_priority_ordering -- CRITICAL > HIGH > MEDIUM > LOW

### Commands:
```bash
mypy src/cognitia/multi_agent/task_types.py src/cognitia/protocols/multi_agent.py
ruff check src/cognitia/multi_agent/
```

---

## Stage 10: 9B-MVP Contract Tests

**Complexity:** S
**Time:** ~3 min
**Dependencies:** Stage 9
**Agent:** tester
**Files:**
- CREATE: tests/unit/test_task_queue_contract.py
- CREATE: tests/unit/test_task_types.py

### Tasks:
1. tests/unit/test_task_types.py:
   - test_task_item_frozen -- cannot mutate
   - test_task_item_defaults -- metadata={}, assignee_agent_id=None
   - test_task_status_transitions -- valid values
   - test_task_filter_none_means_no_filter
2. tests/unit/test_task_queue_contract.py:
   - Parametrized contract tests that accept a queue_factory fixture:
   - test_put_and_list -- put 2 tasks, list returns both
   - test_get_returns_highest_priority -- put low + critical, get returns critical
   - test_get_with_assignee_filter -- put 2 tasks assigned to different agents, filter by assignee
   - test_complete_marks_done -- complete task, list shows DONE status
   - test_cancel_marks_cancelled -- cancel task, list shows CANCELLED
   - test_get_returns_none_when_empty -- empty queue returns None
   - test_complete_nonexistent_returns_false -- unknown id returns False

### DoD:
- [ ] 11 tests across 2 files
- [ ] Contract tests are parametrizable (can test any TaskQueue implementation)
- [ ] pytest tests/unit/test_task_types.py -v passes

### Commands:
```bash
pytest tests/unit/test_task_types.py -v
```

---

## Stage 11: 9B-MVP Implementation -- InMemory + Sqlite

**Complexity:** M
**Time:** ~5 min
**Dependencies:** Stage 9, Stage 10
**Agent:** developer
**Files:**
- CREATE: src/cognitia/multi_agent/task_queue.py

### Tasks:
1. InMemoryTaskQueue:
   - Dict-based storage: dict[str, TaskItem]
   - get() returns highest priority TODO task (sorted by TaskPriority enum value), optionally filtered
   - complete() transitions TODO/IN_PROGRESS -> DONE via dataclasses.replace()
   - cancel() transitions TODO/IN_PROGRESS -> CANCELLED
   - Thread-safe with asyncio.Lock
2. SqliteTaskQueue:
   - Same interface, SQLite storage
   - Uses asyncio.to_thread() like SqliteSessionBackend
   - Single table: tasks (id TEXT PK, title TEXT, description TEXT, status TEXT, priority TEXT, assignee TEXT, metadata TEXT, created_at REAL)
   - get() uses ORDER BY priority_order DESC LIMIT 1 (map priority to int for SQL ordering)
3. Both classes < 150 lines each
4. Update __init__.py

### DoD:
- [ ] InMemoryTaskQueue passes all contract tests from Stage 10
- [ ] SqliteTaskQueue passes all contract tests from Stage 10
- [ ] Both implementations < 150 lines
- [ ] ruff check src/cognitia/multi_agent/task_queue.py clean
- [ ] mypy src/cognitia/multi_agent/task_queue.py clean

### Test Scenarios:
- Contract tests parametrized with both implementations
- test_sqlite_task_queue_persistence -- data survives close/reopen

### Commands:
```bash
pytest tests/unit/test_task_queue_contract.py tests/unit/test_task_types.py -v
ruff check src/cognitia/multi_agent/task_queue.py
mypy src/cognitia/multi_agent/task_queue.py
```

---

## Stage 12: 9B-MVP Integration Tests

**Complexity:** S
**Time:** ~3 min
**Dependencies:** Stage 11
**Agent:** tester
**Files:**
- CREATE: tests/integration/test_task_queue_integration.py

### Tasks:
1. test_task_queue_priority_ordering_integration -- put 10 tasks with random priorities, verify get() always returns highest
2. test_task_queue_concurrent_get -- 3 concurrent get() calls do not return same task
3. test_sqlite_task_queue_file_persistence -- write tasks, create new SqliteTaskQueue on same file, tasks are there
4. test_task_lifecycle_full -- put -> get -> complete -> verify status

### DoD:
- [ ] 4 integration tests
- [ ] pytest tests/integration/test_task_queue_integration.py -v all green

### Commands:
```bash
pytest tests/integration/test_task_queue_integration.py -v
```

---

## Stage 13: 9C-MVP Protocol + Domain Types -- AgentRegistry

**Complexity:** S
**Time:** ~3 min
**Dependencies:** --
**Agent:** developer
**Files:**
- CREATE: src/cognitia/multi_agent/registry_types.py
- MODIFY: src/cognitia/protocols/multi_agent.py (add AgentRegistry Protocol)

### Tasks:
1. Create src/cognitia/multi_agent/registry_types.py:
   - AgentStatus enum: IDLE, RUNNING, STOPPED (3 values)
   - AgentRecord frozen dataclass: id, name, role, parent_id (str | None), runtime_name, runtime_config (dict), status (AgentStatus), budget_limit_usd (float | None), metadata (dict)
   - AgentFilter frozen dataclass: role (str | None), status (AgentStatus | None), parent_id (str | None)
2. Add to src/cognitia/protocols/multi_agent.py:
   - AgentRegistry Protocol (runtime_checkable): 5 methods:
     - async register(record: AgentRecord) -> None
     - async get(agent_id: str) -> AgentRecord | None
     - async list_agents(filters: AgentFilter | None = None) -> list[AgentRecord]
     - async update_status(agent_id: str, status: AgentStatus) -> bool
     - async remove(agent_id: str) -> bool
3. Update __init__.py

### DoD:
- [ ] AgentStatus has exactly 3 values
- [ ] AgentRecord is frozen dataclass with 9 fields
- [ ] AgentRegistry Protocol has exactly 5 methods (ISP limit)
- [ ] mypy clean

### Test Scenarios:
- test_agent_record_is_frozen
- test_agent_status_values -- exactly 3
- test_agent_registry_protocol_runtime_checkable

### Commands:
```bash
mypy src/cognitia/multi_agent/registry_types.py src/cognitia/protocols/multi_agent.py
ruff check src/cognitia/multi_agent/
```

---

## Stage 14: 9C-MVP Contract Tests

**Complexity:** S
**Time:** ~3 min
**Dependencies:** Stage 13
**Agent:** tester
**Files:**
- CREATE: tests/unit/test_agent_registry_contract.py
- CREATE: tests/unit/test_agent_registry_types.py

### Tasks:
1. tests/unit/test_agent_registry_types.py:
   - test_agent_record_frozen -- FrozenInstanceError
   - test_agent_record_defaults -- parent_id=None, budget_limit_usd=None
   - test_agent_status_values -- 3 statuses
2. tests/unit/test_agent_registry_contract.py (parametrized with registry factory):
   - test_register_and_get -- register, get by id returns record
   - test_get_nonexistent_returns_none
   - test_list_all -- register 3, list returns 3
   - test_list_with_role_filter -- filter by role
   - test_update_status -- IDLE -> RUNNING
   - test_update_nonexistent_returns_false
   - test_remove -- remove, get returns None
   - test_list_by_parent_id -- tree query: children of parent

### DoD:
- [ ] 11 tests across 2 files
- [ ] Contract tests are parametrizable
- [ ] pytest tests/unit/test_agent_registry_types.py -v passes

### Commands:
```bash
pytest tests/unit/test_agent_registry_types.py -v
```

---

## Stage 15: 9C-MVP Implementation -- InMemoryAgentRegistry

**Complexity:** S
**Time:** ~3 min
**Dependencies:** Stage 13, Stage 14
**Agent:** developer
**Files:**
- CREATE: src/cognitia/multi_agent/agent_registry.py

### Tasks:
1. InMemoryAgentRegistry:
   - Dict-based storage: dict[str, AgentRecord]
   - register() stores record (error if id already exists)
   - get() returns by id or None
   - list_agents() with optional role/status/parent_id filters
   - update_status() via dataclasses.replace(), returns False if not found
   - remove() deletes, returns False if not found
   - Thread-safe with asyncio.Lock
2. File < 80 lines
3. Update __init__.py

### DoD:
- [ ] InMemoryAgentRegistry passes all contract tests from Stage 14
- [ ] File < 80 lines
- [ ] ruff check + mypy clean

### Test Scenarios:
- All contract tests from Stage 14 parametrized with InMemoryAgentRegistry

### Commands:
```bash
pytest tests/unit/test_agent_registry_contract.py tests/unit/test_agent_registry_types.py -v
ruff check src/cognitia/multi_agent/agent_registry.py
mypy src/cognitia/multi_agent/agent_registry.py
```

---

## Stage 16: 9C-MVP Integration Tests

**Complexity:** S
**Time:** ~2 min
**Dependencies:** Stage 15
**Agent:** tester
**Files:**
- CREATE: tests/integration/test_agent_registry_integration.py

### Tasks:
1. test_agent_registry_tree_structure -- register parent + 2 children, query children by parent_id
2. test_agent_registry_status_lifecycle -- IDLE -> RUNNING -> STOPPED transitions
3. test_agent_registry_duplicate_id_error -- register same id twice raises ValueError

### DoD:
- [ ] 3 integration tests
- [ ] pytest tests/integration/test_agent_registry_integration.py -v all green

### Commands:
```bash
pytest tests/integration/test_agent_registry_integration.py -v
```

---

## BLOCK 3: Phase 10A CLI Runtime

---

## Stage 17: 10A Protocol + Domain Types -- CliAgentRuntime

**Complexity:** S
**Time:** ~3 min
**Dependencies:** --
**Agent:** developer
**Files:**
- CREATE: src/cognitia/runtime/cli/__init__.py
- CREATE: src/cognitia/runtime/cli/types.py
- CREATE: src/cognitia/runtime/cli/parser.py

### Tasks:
1. Create src/cognitia/runtime/cli/types.py:
   - CliConfig frozen dataclass: command (list[str], e.g. ["claude", "--print", "-"]), output_format (str, e.g. "stream-json"), timeout_seconds (float, default 300), max_output_bytes (int, default 4_000_000), env (dict[str, str], extra env vars)
2. Create src/cognitia/runtime/cli/parser.py:
   - NdjsonParser Protocol (runtime_checkable): def parse_line(self, line: str) -> RuntimeEvent | None (1 method)
   - ClaudeNdjsonParser implementation: maps Claude Code stream-json events to RuntimeEvent:
     - type=assistant, subtype=text -> RuntimeEvent.assistant_delta
     - type=assistant, subtype=tool_use -> RuntimeEvent.tool_call_started
     - type=result -> RuntimeEvent.final
     - Unknown types -> None (skip)
   - GenericNdjsonParser implementation: passes raw JSON as RuntimeEvent data with type mapping
3. Create __init__.py with re-exports

### DoD:
- [ ] CliConfig is frozen with 5 fields
- [ ] NdjsonParser Protocol has 1 method (ISP)
- [ ] ClaudeNdjsonParser handles at least 3 event types
- [ ] GenericNdjsonParser as fallback
- [ ] mypy src/cognitia/runtime/cli/ clean

### Test Scenarios:
- test_cli_config_frozen
- test_claude_parser_text_event -- maps assistant text to RuntimeEvent.assistant_delta
- test_claude_parser_result_event -- maps result to RuntimeEvent.final
- test_claude_parser_unknown_event_returns_none
- test_generic_parser_passthrough

### Commands:
```bash
mypy src/cognitia/runtime/cli/
ruff check src/cognitia/runtime/cli/
```

---

## Stage 18: 10A Contract Tests

**Complexity:** S
**Time:** ~3 min
**Dependencies:** Stage 17
**Agent:** tester
**Files:**
- CREATE: tests/unit/test_cli_parser.py
- CREATE: tests/unit/test_cli_types.py

### Tasks:
1. tests/unit/test_cli_types.py:
   - test_cli_config_frozen -- FrozenInstanceError
   - test_cli_config_defaults -- timeout=300, max_output=4MB
2. tests/unit/test_cli_parser.py:
   - test_claude_parser_assistant_text -- correct mapping
   - test_claude_parser_tool_use -- tool_call_started event
   - test_claude_parser_result -- final event with text
   - test_claude_parser_invalid_json_returns_none -- malformed line
   - test_claude_parser_unknown_type_returns_none
   - test_generic_parser_any_json -- passes through as event
   - test_ndjson_parser_protocol_check -- isinstance(ClaudeNdjsonParser(), NdjsonParser)

### DoD:
- [ ] 9 tests across 2 files
- [ ] pytest tests/unit/test_cli_parser.py tests/unit/test_cli_types.py -v all green

### Commands:
```bash
pytest tests/unit/test_cli_parser.py tests/unit/test_cli_types.py -v
```

---

## Stage 19: 10A Implementation -- CliAgentRuntime

**Complexity:** M
**Time:** ~5 min
**Dependencies:** Stage 17, Stage 18
**Agent:** developer
**Files:**
- CREATE: src/cognitia/runtime/cli/runtime.py
- MODIFY: src/cognitia/runtime/registry.py (add cli registration)
- MODIFY: src/cognitia/runtime/capabilities.py (add cli capabilities)

### Tasks:
1. Create src/cognitia/runtime/cli/runtime.py:
   - CliAgentRuntime implements AgentRuntime:
     - __init__(config: RuntimeConfig, cli_config: CliConfig, parser: NdjsonParser | None = None):
       - Default parser: ClaudeNdjsonParser() if command starts with "claude", else GenericNdjsonParser()
     - async def run(...) (async generator):
       a. Build command: cli_config.command + [prompt_from_messages]
       b. Start subprocess via asyncio.create_subprocess_exec(stdout=PIPE, stderr=PIPE, env=...)
       c. Read stdout line by line
       d. Parse each line via parser.parse_line(line) -> yield RuntimeEvent
       e. Handle process exit code (non-zero -> RuntimeEvent.error)
       f. Enforce max_output_bytes cap
       g. Enforce timeout_seconds via asyncio.wait_for
     - cancel(): send SIGTERM to subprocess, after 5s SIGKILL
     - cleanup(): ensure subprocess terminated
     - __aenter__/__aexit__: delegate to parent
   - File < 200 lines
2. Register in registry.py:
   - Add _create_cli lazy factory
   - Register in _register_builtins as "cli"
3. Add cli capabilities in capabilities.py

### DoD:
- [ ] CliAgentRuntime implements AgentRuntime Protocol
- [ ] Subprocess spawning, line-by-line NDJSON reading
- [ ] Timeout enforcement
- [ ] Max output bytes cap
- [ ] Cancel via SIGTERM -> SIGKILL
- [ ] Registered in RuntimeRegistry as "cli"
- [ ] RuntimeConfig(runtime_name="cli") is valid
- [ ] File < 200 lines
- [ ] ruff check src/cognitia/runtime/cli/ clean
- [ ] mypy src/cognitia/runtime/cli/ clean

### Test Scenarios:
- test_cli_runtime_implements_agent_runtime -- isinstance check
- test_cli_runtime_registered_in_registry -- "cli" in registry.list_available()
- test_cli_runtime_run_success -- mock subprocess outputs NDJSON, events yielded correctly
- test_cli_runtime_run_timeout -- subprocess exceeds timeout, error event
- test_cli_runtime_cancel_sigterm -- cancel sends SIGTERM
- test_cli_runtime_max_bytes_cap -- exceeding cap yields error

### Commands:
```bash
ruff check src/cognitia/runtime/cli/
mypy src/cognitia/runtime/cli/
```

---

## Stage 20: 10A Unit + Integration Tests

**Complexity:** M
**Time:** ~5 min
**Dependencies:** Stage 19
**Agent:** tester
**Files:**
- CREATE: tests/unit/test_cli_runtime.py
- CREATE: tests/integration/test_cli_runtime_integration.py

### Tasks:
1. tests/unit/test_cli_runtime.py:
   - test_cli_runtime_isinstance_agent_runtime -- Protocol check
   - test_cli_runtime_registered_in_registry -- get_default_registry().is_registered("cli")
   - test_cli_runtime_run_mock_subprocess -- mock asyncio.create_subprocess_exec, feed NDJSON lines, verify events
   - test_cli_runtime_error_on_nonzero_exit -- subprocess exits 1, yields error event
   - test_cli_runtime_cancel_sends_signal -- verify subprocess.terminate() called
   - test_cli_runtime_timeout -- verify timeout handling
   - test_cli_runtime_max_bytes_exceeded -- large output triggers error
   - test_cli_runtime_default_parser_claude -- command ["claude", ...] -> ClaudeNdjsonParser
   - test_cli_runtime_default_parser_custom -- command ["my-agent", ...] -> GenericNdjsonParser
2. tests/integration/test_cli_runtime_integration.py:
   - test_cli_runtime_echo_subprocess -- use echo as CLI command, verify final event
   - test_cli_runtime_multiline_ndjson -- subprocess outputs multiple NDJSON lines, all parsed
   - test_cli_runtime_config_valid -- RuntimeConfig(runtime_name="cli") does not raise

### DoD:
- [ ] 9 unit tests + 3 integration tests = 12 total
- [ ] Unit tests mock subprocess (no real process spawning)
- [ ] Integration tests use real subprocess (echo command)
- [ ] pytest tests/unit/test_cli_runtime.py tests/integration/test_cli_runtime_integration.py -v all green

### Commands:
```bash
pytest tests/unit/test_cli_runtime.py tests/integration/test_cli_runtime_integration.py -v
```

---

## Stage 21: 10A + 9 MVP Documentation

**Complexity:** S
**Time:** ~3 min
**Dependencies:** Stages 7, 11, 15, 19
**Agent:** developer
**Files:**
- CREATE: docs/cli-runtime.md
- CREATE: docs/multi-agent.md
- MODIFY: mkdocs.yml (add nav entries)
- MODIFY: CHANGELOG.md (add Phase 9 MVP + 10A entries)

### Tasks:
1. Create docs/cli-runtime.md:
   - Overview of CliAgentRuntime
   - Claude Code preset example
   - Custom CLI preset example
   - NdjsonParser Protocol for custom parsers
   - Configuration options (CliConfig)
2. Create docs/multi-agent.md:
   - AgentTool (agent-as-tool pattern)
   - TaskQueue (simple task management)
   - AgentRegistry (agent lifecycle)
   - Code examples for each
3. Add to mkdocs.yml nav under Features
4. Add CHANGELOG entries for Phase 9 MVP + 10A

### DoD:
- [ ] docs/cli-runtime.md created with 3+ code examples
- [ ] docs/multi-agent.md created with 3+ code examples
- [ ] mkdocs.yml nav updated
- [ ] CHANGELOG.md has Phase 9 MVP + 10A entries
- [ ] All code examples in docs use actual public API

### Commands:
```bash
python -c "
import yaml, pathlib
y = yaml.safe_load(open('mkdocs.yml'))
def extract_mds(nav, acc=None):
    if acc is None: acc = []
    if isinstance(nav, list):
        for item in nav: extract_mds(item, acc)
    elif isinstance(nav, dict):
        for v in nav.values(): extract_mds(v, acc)
    elif isinstance(nav, str) and nav.endswith('.md'):
        acc.append(nav)
    return acc
mds = extract_mds(y['nav'])
missing = [m for m in mds if not (pathlib.Path('docs') / m).exists()]
print(f'Missing: {missing}' if missing else 'All nav pages exist')
"
```

---

## BLOCK 4: Final Verification

---

## Stage 22: Full Test Suite + Coverage + Lint

**Complexity:** M
**Time:** ~5 min
**Dependencies:** All previous stages
**Agent:** developer
**Files:** none (verification only)

### Tasks:
1. Run full test suite
2. Run ruff check on all new code
3. Run mypy on all new code
4. Verify coverage threshold for new modules

### DoD:
- [ ] pytest -- all tests pass (existing 2122 + new ~55 tests)
- [ ] ruff check src/cognitia/multi_agent/ src/cognitia/runtime/cli/ examples/ -- clean
- [ ] mypy src/cognitia/multi_agent/ src/cognitia/runtime/cli/ -- clean
- [ ] New modules coverage >= 85%
- [ ] No import errors for new modules
- [ ] python -c "from cognitia.multi_agent import AgentToolResult, InMemoryTaskQueue, InMemoryAgentRegistry; from cognitia.runtime.cli import CliAgentRuntime" succeeds

### Commands:
```bash
pytest --tb=short -q
ruff check src/cognitia/multi_agent/ src/cognitia/runtime/cli/ examples/
mypy src/cognitia/multi_agent/ src/cognitia/runtime/cli/
pytest tests/unit/test_agent_tool_types.py tests/unit/test_agent_tool_contract.py tests/unit/test_task_queue_contract.py tests/unit/test_task_types.py tests/unit/test_agent_registry_contract.py tests/unit/test_agent_registry_types.py tests/unit/test_cli_parser.py tests/unit/test_cli_types.py tests/unit/test_cli_runtime.py tests/integration/test_agent_tool_integration.py tests/integration/test_task_queue_integration.py tests/integration/test_agent_registry_integration.py tests/integration/test_cli_runtime_integration.py --cov=cognitia.multi_agent --cov=cognitia.runtime.cli --cov-report=term-missing -v
```

---

## Dependency Graph

```
Stage 1 (examples) ───────────────────────────────────────────────────┐
Stage 2 (CHANGELOG) ──────────────────────────────────────────────────┤
Stage 3 (getting-started) ────────────────────────────────────────────┤
Stage 4 (mkdocs.yml) ─────────────────────────────────────────────────┤
                                                                      |
Stage 5 (9A types) ──> Stage 6 (9A contract) ──> Stage 7 ──> Stage 8 ┤
                                                  (9A impl)  (9A int) |
                                                                      |
Stage 9 (9B types) ──> Stage 10 (9B contract) ─> Stage 11 -> Stage 12┤
                                                  (9B impl)  (9B int) |
                                                                      |
Stage 13 (9C types) -> Stage 14 (9C contract) -> Stage 15 -> Stage 16┤
                                                  (9C impl)  (9C int) |
                                                                      |
Stage 17 (10A types) > Stage 18 (10A contract) > Stage 19 -> Stage 20┤
                                                  (10A impl) (10A tst)|
                                                                      |
                                                  Stage 21 (docs) ────┤
                                                                      |
                                                  Stage 22 (verify) <─┘
```

## Parallelization

| Phase | Stages | Agents |
|-------|--------|--------|
| 1 (DOC + Protocols) | 1, 2, 3, 4, 5, 9, 13, 17 | All 8 stages parallel -- 5 developers |
| 2 (Contract Tests) | 6, 10, 14, 18 | 4 testers in parallel |
| 3 (Implementation) | 7, 11, 15, 19 | 4 developers in parallel |
| 4 (Integration Tests) | 8, 12, 16, 20 | 4 testers in parallel |
| 5 (Docs + Verify) | 21, 22 | 1 developer sequential |

**Max parallelism:** 8 agents in Phase 1, 4 in Phases 2-4.

## Potential Merge Conflicts

- src/cognitia/protocols/multi_agent.py -- Stages 5, 9, 13 all modify this file. Resolve by having Stage 5 create the file, Stages 9 and 13 append to it. If parallel, each adds its own Protocol.
- src/cognitia/multi_agent/__init__.py -- Stages 5, 9, 11, 13, 15 update re-exports. Sequential within each 9x block.
- mkdocs.yml -- Stages 4 and 21 both modify nav. Stage 4 runs first (DOC block), Stage 21 depends on implementation.
- CHANGELOG.md -- Stages 2 and 21 both modify. Stage 2 adds v0.6/v0.7/v1.0-core, Stage 21 adds v1.1.0 entries.
- src/cognitia/runtime/registry.py -- Only Stage 19 modifies (adds cli registration).

## Checklist (copy to checklist.md)

- ⬜ Stage 1: examples/ runnable scripts (9 files)
- ⬜ Stage 2: CHANGELOG v0.6.0, v0.7.0, v1.0.0-core
- ⬜ Stage 3: Getting Started guide update
- ⬜ Stage 4: mkdocs.yml nav update
- ⬜ Stage 5: 9A Protocol + types (AgentTool, AgentToolResult)
- ⬜ Stage 6: 9A Contract tests (7 tests)
- ⬜ Stage 7: 9A Implementation (agent_tool.py + ThinRuntime.as_tool)
- ⬜ Stage 8: 9A Integration tests (4 tests)
- ⬜ Stage 9: 9B-MVP Protocol + types (TaskQueue, TaskItem, TaskStatus)
- ⬜ Stage 10: 9B-MVP Contract tests (11 tests)
- ⬜ Stage 11: 9B-MVP Implementation (InMemory + Sqlite)
- ⬜ Stage 12: 9B-MVP Integration tests (4 tests)
- ⬜ Stage 13: 9C-MVP Protocol + types (AgentRegistry, AgentRecord, AgentStatus)
- ⬜ Stage 14: 9C-MVP Contract tests (11 tests)
- ⬜ Stage 15: 9C-MVP Implementation (InMemoryAgentRegistry)
- ⬜ Stage 16: 9C-MVP Integration tests (3 tests)
- ⬜ Stage 17: 10A Protocol + types (CliConfig, NdjsonParser, ClaudeNdjsonParser)
- ⬜ Stage 18: 10A Contract tests (9 tests)
- ⬜ Stage 19: 10A Implementation (CliAgentRuntime + registry)
- ⬜ Stage 20: 10A Unit + Integration tests (12 tests)
- ⬜ Stage 21: 10A + 9 MVP docs (cli-runtime.md, multi-agent.md)
- ⬜ Stage 22: Full test suite + coverage + lint verification
