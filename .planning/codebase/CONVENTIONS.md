# Coding Conventions

**Analysis Date:** 2026-04-12

## Naming Patterns

**Files:**
- `snake_case.py` throughout: `agent_config.py`, `thin_runtime.py`, `inmemory.py`
- Test files prefixed with `test_`: `test_agent_facade.py`, `test_thin_runtime.py`
- Contract/protocol tests include `_contract` suffix: `test_activity_log_contract.py`, `test_agent_tool_contract.py`
- Private helpers prefixed with `_`: `_helpers.py`, `_stubs.py`, `_tools_code.py`

**Classes:**
- `PascalCase`: `AgentConfig`, `ThinRuntime`, `InMemoryMemoryProvider`
- Protocols end with the port role: `MessageStore`, `FactStore`, `RuntimePort`, `AgentRuntime`
- Errors end with `Error`: `BudgetExceededError`, `ThinLlmError`, `StructuredOutputError`, `SandboxViolation`
- ABC/base classes use plain names: `Middleware` (not `BaseMiddleware`)

**Functions and methods:**
- `snake_case`: `build_middleware_stack`, `default_llm_call`, `run_guardrails`
- Private helpers prefixed with `_`: `_ensure_async`, `_infer_schema`, `_extract_description`, `_should_buffer_postprocessing`
- Factory functions named `build_*` or `create_*`: `build_runtime_factory`, `create_thin_builtin_tools`

**Variables:**
- `snake_case`: `session_id`, `total_cost_usd`, `active_skill_ids`
- Sentinel/constants: `UPPER_SNAKE_CASE` used sparingly (e.g., `_TYPE_MAP`)

**Types:**
- `PascalCase` for dataclasses, type aliases
- `Protocol` suffix omitted — ports use domain role names: `MessageStore` not `MessageStoreProtocol`

## Code Style

**Formatting:**
- Tool: `ruff format src/ tests/`
- No explicit `.prettierrc` or line-length override detected — ruff defaults (88 chars)

**Linting:**
- Tool: `ruff check src/ tests/` with `ruff check --fix` for auto-fixable issues
- Config in `pyproject.toml`

**Type checking:**
- `mypy src/swarmline/` — strict mypy with `py.typed` marker present at `src/swarmline/py.typed`

## Import Organization

**Universal first line:**
```python
from __future__ import annotations
```
This is present in virtually every source file (~250 files) — it is **mandatory**.

**Order (enforced by ruff):**
1. `from __future__ import annotations`
2. stdlib (`asyncio`, `json`, `re`, `dataclasses`, `collections`, `typing`)
3. third-party (`pydantic`, `structlog`, `yaml`)
4. internal (`from swarmline.X import Y`)

**Lazy imports for optional dependencies** — inside functions/methods, not at module level:
```python
# In module body: only check
aiosqlite = pytest.importorskip("aiosqlite", reason="aiosqlite not installed")

# In source: inside function
def get_provider():
    from swarmline.memory.sqlite import SQLiteMemoryProvider  # lazy
    return SQLiteMemoryProvider()
```

**TYPE_CHECKING guard** for forward-reference / circular-import avoidance:
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from swarmline.agent.config import AgentConfig
    from swarmline.agent.tool import ToolDefinition
```
Used in `agent/config.py`, `agent/middleware.py`, `protocols/runtime.py`, and ~20 other files.

**Path aliases:** None. All internal imports use full `swarmline.*` paths.

## Domain Objects

**Frozen dataclasses** for all domain types — no mutation allowed:
```python
@dataclass(frozen=True)
class TurnContext:
    user_id: str
    topic_id: str
    role_id: str
    model: str
    active_skill_ids: tuple[str, ...]  # tuple, never list
```

**Key rule:** collections inside frozen dataclasses use `tuple[T, ...]` not `list[T]`. Fields that need mutability use `field(default_factory=dict)` only in non-frozen configs (`AgentConfig`).

**Result type** is also frozen:
```python
@dataclass(frozen=True)
class Result:
    text: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
```

## Protocol Design (ISP)

All protocols are `@runtime_checkable` and have **≤5 methods**:
```python
@runtime_checkable
class MessageStore(Protocol):
    async def save_message(self, user_id: str, topic_id: str, role: str, content: str, ...) -> None: ...
    async def get_messages(self, user_id: str, topic_id: str, limit: int = 10) -> list[MemoryMessage]: ...
    async def count_messages(self, user_id: str, topic_id: str) -> int: ...
    async def delete_messages_before(self, ...) -> int: ...
```

Protocols live in `src/swarmline/protocols/` split by domain: `memory.py`, `routing.py`, `multi_agent.py`, `runtime.py`, `session.py`, `tools.py`. All re-exported from `src/swarmline/protocols/__init__.py`.

## Async Patterns

**Async-first**: all runtime, storage, and tool APIs are `async def`.

Runtime contracts return `AsyncIterator[RuntimeEvent]`:
```python
async def run(
    self,
    *,
    messages: list[Message],
    system_prompt: str,
    active_tools: list[ToolSpec],
    config: RuntimeConfig | None = None,
    mode_hint: str | None = None,
) -> AsyncIterator[RuntimeEvent]:
    ...
    yield RuntimeEvent.assistant_delta("text")
    yield RuntimeEvent.final(text="done")
```

## Middleware Pattern

Base class with passthrough defaults — subclasses override only needed methods:
```python
class Middleware:
    async def before_query(self, prompt: str, config: AgentConfig) -> str:
        return prompt  # passthrough

    async def after_result(self, result: Result) -> Result:
        return result  # passthrough

    def get_hooks(self) -> HookRegistry | None:
        return None
```

Concrete implementations: `CostTracker`, `SecurityGuard`, `ToolOutputCompressor` in `src/swarmline/agent/middleware.py`.

## Error Handling

**Domain errors**: custom subclasses of stdlib exceptions:
- `BudgetExceededError(RuntimeError)` — in `src/swarmline/agent/middleware.py`
- `ThinLlmError` — in `src/swarmline/runtime/thin/errors.py`
- `StructuredOutputError(Exception)` — in `src/swarmline/agent/structured.py`
- `SandboxViolation` — in `src/swarmline/tools/types.py`

**Agent-level errors**: converted to `Result(error=str(exc))` rather than propagated:
```python
except Exception as exc:
    logger.exception("%s error", error_context)
    # returns Result with error=str(exc), ok=False
```

**Fail-fast validation**: `AgentConfig.__post_init__` raises `ValueError` on empty `system_prompt`.

**Guard pattern** for optional deps:
```python
except ImportError:
    # return None or raise with helpful message
```

## Logging

**Two coexisting systems:**
1. `structlog` via `AgentLogger` / `configure_logging()` — for structured JSON output in `src/swarmline/observability/logger.py`
2. `logging.getLogger(__name__)` — in ~20 infrastructure modules for standard stdlib logging

**Usage:**
```python
# stdlib pattern (infrastructure)
logger = logging.getLogger(__name__)
logger.exception("stream_claude_one_shot error")

# structlog pattern (application/observability)
import structlog
log = structlog.get_logger()
```

`configure_logging(level="info", fmt="json")` sets up both systems together.

## Module Design

**Barrel files**: every subpackage has `__init__.py` re-exporting public API. Example from `src/swarmline/agent/__init__.py`:
```python
from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.middleware import BudgetExceededError, CostTracker, Middleware, SecurityGuard
from swarmline.agent.tool import tool
```

**`__all__`**: defined in `__init__.py` files that re-export from `protocols/`.

**`py.typed` marker**: present at `src/swarmline/py.typed` — package declares full type support.

## Comments and Docstrings

**Module docstrings**: always present, one-sentence to multi-line, in Russian or English mixed:
```python
"""InMemoryMemoryProvider - dev-mode memory provider without a DB (R-521).

All data is stored in process-memory dicts.
Ideal for development, tests, and demos without Postgres.
"""
```

**Class docstrings**: brief description of purpose.

**Method docstrings**: used for `@tool` description extraction when `description=None`:
```python
@tool(name="search")
async def search(query: str) -> str:
    """Search for documents matching the query."""
    ...
```

**Inline comments**: short single-line explaining non-obvious logic, in Russian or English.

---

*Convention analysis: 2026-04-12*
