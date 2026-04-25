# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project

**Swarmline** — LLM-agnostic Python framework for building AI agents with pluggable runtimes, persistent memory, tool management, and structured observability. Python 3.11+. Published on [PyPI](https://pypi.org/project/swarmline/).

## Commands

```bash
# Install (dev)
pip install -e ".[dev,all]"

# Tests
pytest                                          # all offline tests (default: -m "not live")
pytest tests/unit/test_foo.py -v                # single file
pytest tests/unit/test_foo.py::TestBar::test_baz -v  # single test
pytest -k "test_name" -v                        # by name pattern
pytest -m integration -v                        # by marker
pytest -m "requires_claude_sdk" -v              # SDK-specific
pytest --cov=swarmline --cov-report=term-missing # with coverage

# Lint & format
ruff check src/ tests/                          # lint
ruff check --fix src/ tests/                    # auto-fix
ruff format src/ tests/                         # format

# Type checking
ty check src/swarmline/
```

**Test markers:** `security`, `requires_claude_sdk`, `requires_anthropic`, `requires_langchain`, `live`, `integration`.

## Architecture

Clean Architecture with strict dependency direction: **Infrastructure → Application → Domain** (never reverse).

### Layers

- **Domain** (`protocols.py`, `types.py`, `memory/types.py`): Core protocols and frozen dataclasses. Zero external dependencies (stdlib only). 14 ISP-compliant protocols (≤5 methods each).
- **Application** (`agent/`, `orchestration/`, `bootstrap/`): Agent facade (`query`/`stream`/`conversation`), planning, subagents, teams. Depends only on Domain.
- **Infrastructure** (`runtime/`, `memory/{sqlite,postgres}.py`, `tools/`): Concrete implementations. Framework/IO code lives here.

### Key Abstractions

**Runtimes** (swappable execution loops):
- `thin/` — built-in lightweight loop, multi-provider (Anthropic, OpenAI-compat, Google Gemini, DeepSeek)
- `claude_code.py` — Claude Agent SDK adapter (subprocess + MCP)
- `deepagents.py` — LangChain/LangGraph adapter

All runtimes implement the same async generator contract: `async def run(...) -> AsyncIterator[RuntimeEvent]`.

**Memory providers** (swappable storage): InMemory ↔ SQLite ↔ PostgreSQL. Protocols split by ISP: `MessageStore`, `FactStore`, `GoalStore`, `SummaryStore`, `SessionStateStore`, `ToolEventStore`.

**Tools**: `@tool` decorator, dynamic loading, default-deny policy. Builtin: sandbox, web, thinking.

### Source Layout

```
src/swarmline/
├── protocols.py      # All 14 domain protocols
├── types.py          # Core types (TurnContext, ContextPack, SkillSet)
├── agent/            # Agent facade, config, middleware, result, conversation
├── runtime/          # thin/, claude_code, deepagents adapters + models.yaml
├── memory/           # Providers: inmemory, sqlite, postgres + types
├── bootstrap/        # SwarmlineStack factory
├── orchestration/    # Planning, subagents, teams, code verification
├── tools/            # Builtin tools (sandbox, web, thinking)
├── skills/           # MCP skill registration & YAML loading
├── hooks/            # Lifecycle hooks (PreToolUse, PostToolUse)
├── context/          # Token-aware context building
├── policy/           # Default-deny tool policy, tool selector
├── routing/          # Role-based router
├── session/          # Session management & rehydration
├── resilience/       # Circuit breaker
└── observability/    # Structured logging (structlog)
```

Tests mirror source: `tests/unit/`, `tests/integration/`, `tests/e2e/`, `tests/security/`.

## Conventions

- **Async-first**: all runtime and storage APIs are async. pytest-asyncio with `asyncio_mode = "auto"`.
- **Frozen dataclasses** for all domain objects — no mutation.
- **Protocol-first**: `@runtime_checkable class MyPort(Protocol)` with ≤5 methods.
- **Lazy imports** for optional dependencies (inside functions, not at module level).
- **Test naming**: `test_<what>_<condition>_<result>`. Arrange-Act-Assert. `@parametrize` over copy-paste.
- **Model registry**: aliases like `"sonnet"` → resolved via `runtime/models.yaml`.
- **Contract-first**: Protocol/ABC → contract tests → implementation. Tests must pass for ANY correct implementation.

## Git Workflow & Releasing

Two-repo model: private development + public release. Full process in `docs/releasing.md`.

```
swarmline-dev (private)  ──sync──  swarmline (public)  ──CI──  PyPI
  all branches                      main only                   package
  + Memory Bank, specs              filtered (no private files)
```

### Branching

```
main (stable, tested, releasable)
  ├── feat/<name>       ← feature development
  ├── fix/<name>        ← bug fixes
  └── release/vX.Y.Z   ← version bump + changelog before tag
```

### Versioning (Strict SemVer)

| Bump | When | Examples |
|------|------|----------|
| **MAJOR** | Breaking public API change | Remove/rename export, change Protocol, incompatible config |
| **MINOR** | New user-facing feature | New module, runtime, CLI command, deprecation |
| **PATCH** | Bug/security/perf fix | Bug fix, dependency bump |

**NOT a version bump**: refactoring, tests, CI, docs, Memory Bank, lint fixes, dev tooling.

**Batching**: 1-2 minor releases per month max. Group features. Patches ship immediately.

### Release flow

1. Develop on feature branches → merge to `main` (must be green)
2. `release/vX.Y.Z` branch → bump `pyproject.toml` + CHANGELOG → merge → tag
3. `./scripts/sync-public.sh --tags` → filters private files → pushes to public → GitHub Actions → PyPI

### Private vs Public

| Content | Private | Public |
|---------|---------|--------|
| Source code | all branches | main only |
| `.memory-bank/`, `CLAUDE.md`, `RULES.md`, `.specs/`, `.planning/`, `.factory/` | tracked | **excluded** |
| `AGENTS.md` | full version | replaced with `AGENTS.public.md` |
