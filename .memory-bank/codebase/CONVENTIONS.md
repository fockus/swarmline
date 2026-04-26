# Coding Conventions

**Generated:** `2026-04-25T10:16:27Z`
**Graph:** not-used (missing)

## Naming
- **Files:** `snake_case.py` — e.g. `graph_task_board_sqlite.py`, `llm_providers.py`
- **Functions/Methods:** `snake_case` — e.g. `dispatch_runtime`, `create_thin_builtin_tools`
- **Variables:** `snake_case`
- **Types/Classes:** `PascalCase` — e.g. `SwarmlineStack`, `AgentConfig`, `GraphTaskBoard`
- **Protocols:** `PascalCase` with descriptive suffix — e.g. `MessageStore`, `RuntimePort`, `HostAdapter`
- **Constants:** `UPPER_SNAKE_CASE` — e.g. `CODING_TODO_TOOL_NAMES` in `src/swarmline/runtime/thin/coding_toolpack.py`

## Style
- **Formatter:** `ruff format` — config in `pyproject.toml` `[tool.ruff]` (target `py311`)
- **Linter:** `ruff check` — extended rules `UP007`, `UP037`, `UP045` for modern type annotations
- **Type checker:** `ty check src/swarmline/` — strict, `error-on-warning = true` in `[tool.ty.terminal]`

## Imports
- **Order:** stdlib → third-party → local (`swarmline.*`)
- **Future annotations:** `from __future__ import annotations` at top of every file
- **Lazy imports:** optional dependencies imported inside functions/methods, not at module level (e.g. `anthropic`, `openai`, `langchain` imports inside runtime adapters)
- **TYPE_CHECKING guard:** heavy runtime imports deferred with `if TYPE_CHECKING:` (e.g. `src/swarmline/runtime/thin/runtime.py`)

## Testing
- **Runner:** `pytest` — config at `pyproject.toml` `[tool.pytest.ini_options]`; `asyncio_mode = "auto"`
- **Location:** `tests/unit/`, `tests/integration/`, `tests/e2e/`, `tests/security/`, `tests/architecture/`
- **Naming:** `test_<what>_<condition>_<result>` — enforced by convention
- **Mocking:** mock only external services; prefer real components (Testing Trophy: integration > unit > e2e)
- **Markers:** `security`, `requires_claude_sdk`, `requires_anthropic`, `requires_langchain`, `live`, `integration`, `slow`
- **Default run:** excludes `live` tests (`addopts = ["-m", "not live"]` in `pyproject.toml`)
- **Coverage:** `pytest --cov=swarmline --cov-report=term-missing`; target 85%+ overall, 95%+ core
- **Run:** `pytest` (offline), `pytest -m integration` (integration), `pytest -m live` (network)

## Error Handling
- Domain exceptions raised directly (e.g. `StructuredOutputError`, `ThinLlmError` in `src/swarmline/runtime/thin/errors.py`)
- Agent boundary wraps in `Result` dataclass: `src/swarmline/agent/result.py`
- Circuit breaker pattern in `src/swarmline/resilience/circuit_breaker.py`

## Comments
- Non-obvious WHY only, not WHAT
- Public classes/functions: docstrings explaining purpose and contracts
- Module-level docstrings on every public module (e.g. `src/swarmline/bootstrap/stack.py` opening docstring)

## Function Design
- **Async-first:** all runtime and storage APIs are `async def`
- **Frozen dataclasses** for domain objects — no mutation after construction
- **Protocol-first:** define `@runtime_checkable` Protocol before implementation; ≤5 methods per Protocol (ISP)
- **Dependency injection via constructor:** accept abstractions, not concrete classes (DIP)
