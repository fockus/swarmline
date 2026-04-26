# DX Audit — swarmline v1.4.1 vs FastAPI baseline

**Verdict:** GOOD WITH CAVEATS — strong technical foundation and intentional surface API for `query / stream / conversation`, but multiple cognitive cliffs and naming inconsistencies prevent FastAPI-grade DX. **Not yet at FastAPI level for v1.5.0 broad adoption.**

**Date:** 2026-04-25
**Auditor:** Code Reviewer

---

## TL;DR

swarmline has a **solid 3-line happy path** (the docs sell it well), and `@tool` with auto-inferred JSON Schema from type hints + docstring is genuinely FastAPI-grade. However, **51 top-level exports**, an **AgentConfig with 35 fields**, a **dual default runtime story** (`runtime="claude_sdk"` in code, `runtime="thin"` in docs), and **three different ways to register hooks/tools** create a steep cognitive cliff once developers leave the README. There is no equivalent of FastAPI's `Depends()`, no `@hook` decorator, and `@tool` is the only true semantic-sugar decorator in the framework.

---

## Hello-world comparison

| Framework | Min LOC | Imports | Cognitive overhead |
|-----------|---------|---------|--------------------|
| FastAPI   | 5       | 1       | Low (1 decorator, return value)         |
| swarmline (docs README) | 5  | 1 | Low |
| swarmline (`examples/01_agent_basics.py`) | **176** | **9** | **Very high** |

### FastAPI 5-liner (gold standard)
```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def read_root():
    return {"hello": "world"}
```
Run: `uvicorn main:app`. **Zero conceptual prerequisites.**

### swarmline 5-liner (from `docs/agent-facade.md` line 7-13)
```python
from swarmline import Agent, AgentConfig, tool
agent = Agent(AgentConfig(runtime="thin"))
result = await agent.query("Hello!")
print(result.text)
```
**Verdict on the docs version**: parity with FastAPI **only if** the user accepts `system_prompt` requirement (which AgentConfig's `__post_init__` enforces — see `src/swarmline/agent/config.py:104`, contradicting the docs claim that "only `runtime` is typically required" at `docs/agent-facade.md:36`). **This is a documentation bug.** Try the docs example as-is and it raises `ValueError("system_prompt must not be empty")`.

### swarmline canonical example (`01_agent_basics.py`)
176 lines. **80 lines** of `_MockBasicsRuntime` boilerplate, runtime registration ceremony, and capabilities wiring before the user ever sees `agent.query()`. **First-time-reader DX: catastrophic.** A new developer landing on `examples/01_agent_basics.py` from PyPI will think this is what they need to write.

---

## Decorator inventory

| Decorator       | Purpose                              | Source                                 | DX score 1-5 |
|-----------------|--------------------------------------|----------------------------------------|--------------|
| `@tool(name, ...)` | Register tool; auto-infer JSON Schema | `agent/tool.py:45-83`                  | **5** — best-in-class, on par with FastAPI `@app.get()`. Auto-extracts description from docstring, parses Google-style `Args:`, infers Pydantic + Enum + `list[T]` + `Optional[T]`. |
| `@dataclass(frozen=True)` | Used directly as cargo-cult        | many places                            | n/a (stdlib) |
| `@hook` | **ABSENT**                                  | n/a                                    | 0  |
| `@middleware` | **ABSENT** (use class subclass instead)  | `agent/middleware.py:20`               | 0  |
| `@guardrail` | **ABSENT** (instantiate class instead)    | `examples/07_guardrails.py`            | 0  |
| `@output_schema` / `@response_model` | **ABSENT** (passed via kwarg) | `agent.query_structured(prompt, Type)` | 2 |
| `@agent` (class-based registration) | **ABSENT**                  | n/a                                    | 0  |
| `Depends()` equivalent | **ABSENT**                          | n/a                                    | 0  |

**Critical DX gap**: `@tool` is the *only* semantic-sugar decorator. Hooks register via `HookRegistry().on_pre_tool_use(callback)` — three method calls per hook. FastAPI users expect `@hook("pre_tool")` symmetry.

### Comparison: registering a hook
```python
# swarmline (current — examples/05_hooks.py:42-49)
hooks = HookRegistry()
hooks.on_pre_tool_use(audit_pre_tool)
hooks.on_pre_tool_use(block_dangerous)
hooks.on_post_tool_use(audit_post_tool)
hooks.on_stop(on_stop)
config = AgentConfig(system_prompt="...", hooks=hooks)

# What FastAPI users would expect (proposed)
@agent.hook("pre_tool", matcher="bash")
async def audit_pre_tool(event): ...
```

---

## API ergonomics

| Category                              | Score   | Evidence                                                         |
|---------------------------------------|---------|------------------------------------------------------------------|
| Import discoverability                | **3/5** | 51 top-level exports — too noisy. FastAPI exports ~7 user-facing names. Many swarmline exports are infrastructure (e.g. `RoleRouter`, `SessionFactory`, `ToolEventStore`) that **should not be in `__all__`**. |
| Type hints on public API              | **5/5** | Excellent. Frozen dataclasses everywhere, `Protocol`-based ports, `from __future__ import annotations`. |
| `Agent.query` / `stream` / `conversation` naming | **4/5** | Coherent triad. **But** `query_structured` (`agent.py:123`) is awkwardly named — FastAPI/Pydantic users would expect `query(prompt, response_model=Sentiment)`, mirroring the stdlib pattern. |
| `Result` type | **4/5** | Frozen dataclass. `result.ok` property is great. `result.text`, `result.usage`, `result.total_cost_usd`, `result.structured_output` all clean. **Lost point**: `Result` has 7 fields; the docstring (line 9-14) doesn't list any of them. |
| Async-first | **5/5** | Consistent — every Agent method is async. `pytest-asyncio mode=auto`. |
| `__aenter__/__aexit__` cleanup | **4/5** | Both `Agent` and `Conversation` support `async with`. **Missing**: many examples (e.g. `01_agent_basics.py:126`) construct Agent without context manager — easy to leak runtime subprocess. |

---

## AgentConfig cognitive load

`src/swarmline/agent/config.py` defines **35 fields** in a single frozen dataclass. Inventory:

```
1  system_prompt (required)
2-3  model, runtime
4  base_url
5-6  tools, middleware
7-8  mcp_servers, hooks
9-10 max_turns, max_budget_usd
11-17 output_format, output_type, structured_mode, structured_schema_name,
       structured_strict, max_model_retries, request_options
18-19 cwd, env
20-25 betas, sandbox, thinking, max_thinking_tokens (deprecated), fallback_model,
       permission_mode, setting_sources
26  tool_policy
27  subagent_config
28  command_registry
29  coding_profile
30-35 feature_mode, require_capabilities, allow_native_features, native_config,
       runtime_options
```

**Compare FastAPI**:
```python
app = FastAPI(title="My API", version="1.0", debug=False, openapi_url="/openapi.json")
```
~10 most-common params, hierarchical (FastAPI -> APIRouter -> route).

**Verdict 2/5**: AgentConfig is a god-class. Should be split: `AgentConfig` (10 essentials) + `RuntimeOptions` + `StructuredConfig` + `SandboxConfig`. The `replace(self._config, **overrides)` pattern in `agent.py:169` already implies users will need to override piecewise.

**Default runtime mismatch (BUG)**: `AgentConfig.runtime: str = "claude_sdk"` (`config.py:35`), but **all** examples and docs use `runtime="thin"`. This is a hidden trap: the user reads docs, doesn't pass `runtime`, gets a different runtime than they expected. Fix: change default to `"thin"` for v1.5.0 (or document why claude_sdk is the default).

---

## Error message quality

| Error site | Message | Quality |
|------------|---------|---------|
| `config.py:105` | `"system_prompt must not be empty"` | **3/5** — actionable but no code example. |
| `runtime_wiring.py:91-94` | `"AgentConfig.cwd is required when subagent_config is enabled. Set cwd to a git repository path so worktree isolation can be initialized."` | **5/5** — exemplary. |
| `runtime_wiring.py:121-124` | `"AgentConfig.cwd is required when coding_profile is enabled. Set cwd to the working directory for the coding agent."` | **5/5** |
| `runtime_wiring.py:207` | `"runtime='pi_sdk' expects runtime_options=PiSdkOptions(...)"` | **4/5** |
| `agent.py:177-179` | `f"Failed to parse structured output as {output_type.__name__}. Raw text: {result.text[:200]}"` | **5/5** — includes raw text. |
| `conversation.py:66-69` | `"Cannot resume: no message_store configured. Pass message_store to Conversation.__init__."` | **5/5** |
| `runtime/thin/errors.py:45` | `f"Ошибка LLM API ({provider}): {type(exc).__name__}: {exc}"` | **2/5** — **Russian text in user-facing error** in otherwise-English codebase. |

**Custom exception hierarchy**: 11 custom exception classes found, **but no shared `SwarmlineError` base class**. Means users can't write `except SwarmlineError:`. Each module has its own:
- `BudgetExceededError(RuntimeError)` (middleware)
- `BudgetExceededError(RuntimeError)` (pipeline) — **duplicate name!**
- `StructuredOutputError(Exception)`
- `ThinLlmError(RuntimeError)`
- `DeepAgentsModelError(RuntimeError)`
- etc.

**Recommendation**: introduce `class SwarmlineError(Exception)` as base; subclass everything from it. Critical for production users who need broad exception handling.

---

## Naming review

### Inconsistencies & confusions

1. **`tool` vs `ToolDefinition` vs `ToolFunction` vs `ToolSpec`** (4 distinct concepts, unclear for newcomers).
2. **`Agent.query` vs `Conversation.say`** — different verbs for the same operation. Both return `Result`. **Inconsistent.**
3. **`Agent.query_structured(prompt, Type)`** — should be `Agent.query(prompt, response_model=Type)` to mirror FastAPI mental model.
4. **`runtime="claude_sdk"` default disagrees with all documentation** (which uses `"thin"`).
5. **`AgentConfig.thinking: dict[str, Any]`** — should be a typed `ThinkingConfig` dataclass (which exists at top-level export!).
6. **`max_thinking_tokens: int | None = None  # Deprecated`** still in AgentConfig — **remove for v1.5.0**.

---

## Documentation in code

| Public API | Class docstring | Method docstrings | Inline example | Score |
|------------|-----------------|-------------------|----------------|-------|
| `Agent`    | 5 lines, lists 3 methods | Yes (numpy-style) | No example in class docstring | 3/5 |
| `AgentConfig` | 4 lines, mentions defaults | n/a (dataclass) | No example | 2/5 |
| `Conversation` | 5 lines | Yes | No example | 3/5 |
| `Result` | 4 lines | n/a (dataclass) | No example | 2/5 |
| `tool` | 6 lines | Yes (Args/Returns) | No example | 4/5 |
| `HookRegistry` | 4 lines | Yes | No example | 3/5 |
| `Middleware` | 5 lines | Yes (passthrough notes) | No example | 4/5 |
| `StructuredOutputError` | 8 lines incl. attrs | n/a | Yes via parent module | **5/5** |

**Module-level docstrings**: `swarmline/__init__.py` docstring is `"""Swarmline — LLM-agnostic framework for building AI agents."""` — should include a runnable example so `help(swarmline)` shows quickstart.

---

## 5-task LOC comparison

| Task | swarmline LOC | FastAPI-equivalent LOC | DX delta |
|------|---------------|------------------------|----------|
| (a) Hello-world agent + 1 tool | **8 lines** | **5 lines** | **-3** modest |
| (b) Pydantic structured output | **6 lines** (`agent.query_structured(prompt, Model)`) | **4 lines** (`response_model=Model`) | **-2** good |
| (c) Custom hook | **~12 lines** (HookRegistry + on_pre_tool_use + register) | **~5 lines** in FastAPI middleware | **-7** poor |
| (d) Multi-agent delegation | **~20 lines** + `examples/21_agent_as_tool.py` | n/a (FastAPI doesn't have agent-as-tool) | n/a |
| (e) Agent with persistent memory | **~15 lines** (asymmetric Agent vs Conversation memory wiring) | **~10 lines** (FastAPI + SQLAlchemy session DI) | **-5** moderate |

---

## What's missing vs FastAPI

| FastAPI feature | swarmline equivalent | Gap |
|-----------------|----------------------|-----|
| Auto-generated OpenAPI | None — Pydantic schemas only used internally for tools | **Critical**: no manifest endpoint (`/v1/tools`). |
| Swagger UI / Redoc | None | n/a — but `swarmline.serve` could expose self-describing endpoint. |
| `TestClient(app)` | `_MockBasicsRuntime` boilerplate copy-pasted across examples | **Major gap**: should ship `MockRuntime` in `swarmline.testing`. |
| `Depends()` for DI | None — pass everything via AgentConfig | **Conceptual gap**. |
| `swarmline init my-agent` CLI scaffold | **Yes!** `cli/init_cmd.py` (`--full`, `--runtime`, `--memory`) | **5/5** parity. ✓ |

---

## Strengths

- ✅ **`@tool` decorator** — one of the cleanest type-hint→JSON-Schema mappings in the Python ecosystem.
- ✅ **3-line happy path** in docs is genuine; works for the 80% case.
- ✅ **Frozen dataclass discipline** — `Result`, `AgentConfig`, `ToolDefinition`, `Message` all immutable.
- ✅ **Async-first end-to-end**.
- ✅ **`async with agent` and `async with conv`** — cleanup-by-construction.
- ✅ **Runtime swappability is real** — same `Agent.query()` works for `thin`, `claude_sdk`, `deepagents`, `cli`. **Genuine FastAPI-class abstraction.**
- ✅ **Structured-output retry loop** with `query_structured` — value-add over FastAPI.
- ✅ **`swarmline init` CLI** is on par with `fastapi-cli`.

---

## Critical DX gaps (BLOCKERS for FastAPI-level DX)

### Pre-v1.5.0 (must-fix)

1. ❌ **Default runtime mismatch**: `AgentConfig.runtime = "claude_sdk"` but every doc/example uses `"thin"`. **Change default to `"thin"`**.
2. ❌ **Russian error string** at `runtime/thin/errors.py:45` — fix to English.
3. ❌ **`__all__` is too noisy** (51 names). Trim to ~12 names: `Agent`, `AgentConfig`, `Conversation`, `Result`, `tool`, `Message`, `RuntimeEvent`, `ToolSpec`, `SwarmlineStack`, plus 3 typed dataclasses.
4. ❌ **`docs/agent-facade.md:36`** says "Only `runtime` is typically required" but `__post_init__` rejects empty `system_prompt`. Fix the docs.
5. ❌ **`examples/01_agent_basics.py` is 176 lines** — mostly mock boilerplate. Move 80-line mock into `swarmline.testing.MockRuntime`.

### v1.5.0 - v1.6.0 (should-fix)

6. ⚠️ **No `SwarmlineError` base class** — users can't `except SwarmlineError:`.
7. ⚠️ **Hook registration verbosity** — add `@agent.hook("pre_tool")` decorator sugar.
8. ⚠️ **`AgentConfig` has 35 fields** — split into composed configs.
9. ⚠️ **`Agent.query_structured(prompt, Type)`** should be `Agent.query(prompt, response_model=Type)`.
10. ⚠️ **`Conversation.say` should be `Conversation.query`** — verb consistency.
11. ⚠️ **Class docstrings should contain runnable examples**.
12. ⚠️ **Promote `AgentConfig.thinking: dict` → `ThinkingConfig`**.
13. ⚠️ **Remove deprecated `max_thinking_tokens`** for the major-feeling v1.5.0.

### v1.7.0+ (could-fix)

14. 💭 Self-describing tool manifest endpoint (analog to `/openapi.json`).
15. 💭 `swarmline.testing.MockRuntime` + `TestAgent`.
16. 💭 `Depends()`-style DI for memory store / sandbox / web provider.

---

## Recommendations (prioritized)

| # | Recommendation | Effort | Impact | Pre-v1.5.0? |
|---|----------------|--------|--------|-------------|
| 1 | Change `AgentConfig.runtime` default to `"thin"` | 1h | **Critical** | **YES** |
| 2 | Fix Russian error string in `thin/errors.py:45` | 5min | High | **YES** |
| 3 | Trim `__all__` from 51 to ~12 names | 2h | High | **YES** |
| 4 | Fix `agent-facade.md:36` lie about `system_prompt` optional | 5min | High | **YES** |
| 5 | Add `examples/00_hello_world.py` — 10-line truly-minimal example | 30min | High | **YES** |
| 6 | Move 80-line mock from `01_agent_basics.py` to `swarmline.testing.MockRuntime` | 4h | High | **YES** |
| 7 | Add `SwarmlineError` base exception class | 2h | Medium | YES |
| 8 | Add class-level runnable examples in docstrings | 2h | Medium | YES |
| 9 | Add `@agent.hook("pre_tool")` decorator API | 6h | High | next minor |
| 10 | Split `AgentConfig` into 4 composed configs | 12h + breaking | High | v2.0 |
| 11 | Unify `Agent.query` + `Agent.query_structured` (`response_model=Type`) | 3h | High | next minor |
| 12 | Remove deprecated `max_thinking_tokens` | 30min | Low | YES |
| 13 | Promote `AgentConfig.thinking: dict` → `ThinkingConfig` | 1h | Medium | YES |
| 14 | Tool catalog endpoint in `swarmline.serve` | 6h | Medium | next minor |
| 15 | `swarmline.testing` module with `MockRuntime`, `TestAgent` | 8h | High | v1.6.0 |

---

## Sign-off

**DX готов к broad adoption?** **WITH CAVEATS — not yet at FastAPI level.**

The framework is **technically excellent** (clean architecture, type safety, async-first, runtime swappability — all best-in-class). The decorator `@tool` is FastAPI-grade. **But three release-blocking DX bugs** (default runtime mismatch, Russian error string, docs-vs-`__post_init__` lie) plus **boilerplate-heavy examples** mean a developer landing on the project today will hit friction on minute one.

**Verdict**: with items 1-8 above (≈11 hours of work) merged into v1.5.0, swarmline reaches **"FastAPI-class DX for the agent space"**. Without them, it's still a strong framework — just not one that competes with FastAPI's first-impression magic.

---

**Files referenced (absolute paths):**
- `src/swarmline/__init__.py` (51 exports — too many)
- `src/swarmline/agent/agent.py:123` (`query_structured`)
- `src/swarmline/agent/config.py:35` (default `runtime="claude_sdk"` mismatch)
- `src/swarmline/agent/config.py:78-79` (`thinking: dict`, deprecated `max_thinking_tokens`)
- `src/swarmline/agent/config.py:104-105` (system_prompt enforcement)
- `src/swarmline/agent/conversation.py:84` (`Conversation.say` — verb inconsistency)
- `src/swarmline/agent/result.py:9-14` (Result class missing field docs)
- `src/swarmline/agent/structured.py:22-37` (good error class — exemplary)
- `src/swarmline/agent/tool.py:45-83` (the `@tool` decorator — best DX in the framework)
- `src/swarmline/runtime/thin/errors.py:45` (Russian text)
- `src/swarmline/agent/runtime_wiring.py:91-94` (best-in-class error message)
- `src/swarmline/hooks/registry.py:31-45` (verbose hook registration)
- `src/swarmline/cli/init_cmd.py:425-505` (good CLI scaffold)
- `examples/01_agent_basics.py` (176 lines — mostly mock boilerplate)
- `examples/02_tool_decorator.py` (clean example, good template)
- `examples/05_hooks.py` (verbose hook registration)
- `docs/getting-started.md:101-107` (working 5-line snippet — good)
- `docs/agent-facade.md:36` (incorrect claim about `runtime` being only required field)
