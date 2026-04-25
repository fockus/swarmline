# ty strict-mode — 3 canonical patterns
Date: 2026-04-25 (Sprint 1A complete)

## What was done
- Sprint 1A reduced `ty check src/swarmline/` 75 → 62 (Stages 2-5: 11 critical bugs fixed, 4 `# type: ignore[attr-defined]` removed, 3 new Protocol contracts introduced)
- 21 new tests across architecture / unit / integration layers locking each fix

## New knowledge — 3 reusable patterns for Sprint 1B

### Pattern OptDep — `unresolved-import` от опциональных deps
**Symptom:** `error[unresolved-import]: Cannot resolve imported module 'tavily'` (тоже для crawl4ai, ddgs, openshell, docker, ...).
**Fix:**
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tavily import TavilyClient

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None  # type: ignore[unresolved-import,assignment]  # optional dep
```
**Why:** ty resolves through site-packages; opt deps absent in clean install. Comment must include `# optional dep` reason.

### Pattern DecoratedTool — `unresolved-attribute` на декорированных функциях
**Symptom:** `__tool_definition__`, `__handler__`, etc. attributes added by decorators but invisible to type checker.
**Fix:** introduce `Protocol` declaring the post-decoration contract, change decorator return type:
```python
@runtime_checkable
class ToolFunction(Protocol):
    __tool_definition__: ToolDefinition
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...

def tool(...) -> Callable[[Callable[..., Any]], ToolFunction]:
    ...
```
Downstream usage: direct attribute access (`fn.__tool_definition__`) works without `cast` or `# type: ignore`. Reference: `src/swarmline/agent/tool_protocol.py` + Stage 4.

### Pattern CallableUnion — `__name__` / attribute access на `partial | callable`
**Symptom:** `error[unresolved-attribute]: Attribute '__name__' is not defined on '(...) -> Awaitable[Any]' in union 'Unknown | callable'`. Triggered by `functools.partial` (no `__name__`) or class instances with `__call__`.
**Fix:** defensive helper with `getattr(..., default)`:
```python
def _hook_name(hook: object) -> str:
    return getattr(hook, "__name__", repr(hook))

# Use:
logger.warning("Hook %r raised", _hook_name(entry.callback))
```
Reference: `src/swarmline/hooks/_helpers.py` + Stage 5. Apply to ANY `<callable>.__name__` access in log messages.
