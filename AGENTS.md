# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project

**Cognitia** — LLM-agnostic Python framework for building AI agents with pluggable runtimes, persistent memory, tool management, and structured observability. Version 1.0.0, Python 3.10+.

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
pytest --cov=cognitia --cov-report=term-missing # with coverage

# Lint & format
ruff check src/ tests/                          # lint
ruff check --fix src/ tests/                    # auto-fix
ruff format src/ tests/                         # format

# Type checking
mypy src/cognitia/
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
- `Codex.py` — Codex Agent SDK adapter (subprocess + MCP)
- `deepagents.py` — LangChain/LangGraph adapter

All runtimes implement the same async generator contract: `async def run(...) -> AsyncIterator[RuntimeEvent]`.

**Memory providers** (swappable storage): InMemory ↔ SQLite ↔ PostgreSQL. Protocols split by ISP: `MessageStore`, `FactStore`, `GoalStore`, `SummaryStore`, `SessionStateStore`, `ToolEventStore`.

**Tools**: `@tool` decorator, dynamic loading, default-deny policy. Builtin: sandbox, web, thinking.

### Source Layout

```
src/cognitia/
├── protocols.py      # All 14 domain protocols
├── types.py          # Core types (TurnContext, ContextPack, SkillSet)
├── agent/            # Agent facade, config, middleware, result, conversation
├── runtime/          # thin/, Codex, deepagents adapters + models.yaml
├── memory/           # Providers: inmemory, sqlite, postgres + types
├── bootstrap/        # CognitiaStack factory
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

## Git Workflow

Two remotes: private development + public release.

```
origin  → github.com/fockus/cognitia-dev  (private, all branches)
public  → github.com/fockus/cognitia      (public, stable main only)
```

### Branching (GitHub Flow + release branches)

```
main (stable, tested, releasable)
  ├── feat/<name>       ← feature development
  ├── fix/<name>        ← bug fixes
  └── release/vX.Y.Z   ← version bump + changelog before tag
```

**Rules:**
- `main` = always green (tests pass, lint clean, can `pip install`)
- Private repo (`origin`): push directly to `main` or feature branches — **no PRs required**
- Push only stable `main` to `public`: `./scripts/sync-public.sh`
- Release: branch `release/vX.Y.Z` → version bump + changelog → merge → tag → `sync-public.sh --tags`
- Hotfix: branch from tag → fix → merge to main → new tag

### Private vs Public

| Content | Private (`origin`) | Public (`public`) |
|---------|-------------------|-------------------|
| Source code | all branches | main only |
| `.memory-bank/` | tracked, all branches | **filtered out** by sync script |
| `CLAUDE.md`, `RULES.md` | tracked, all branches | **filtered out** by sync script |
| `.claude/` | local only (.gitignore) | excluded |
| `AGENTS.md` | tracked, all branches | included (public-safe) |
| WIP / feature branches | pushed | never pushed |
| Tags / releases | all | stable only |

`sync-public.sh` creates a temporary branch without private files, force-pushes it as `main` to public, then cleans up. Supports `--dry-run` to preview.

### Commands

```bash
# Daily development
git checkout -b feat/my-feature       # new feature branch
git push origin feat/my-feature       # push to private
# ... PR → merge to main

# Sync stable main to public
./scripts/sync-public.sh              # tests + push main
./scripts/sync-public.sh --tags       # + push tags

# Release
git checkout -b release/v1.0.0
# ... version bump, changelog
git checkout main && git merge release/v1.0.0
git tag v1.0.0
./scripts/sync-public.sh --tags
```

## Memory Bank

Active at `.memory-bank/`. Core files: `STATUS.md`, `checklist.md`, `plan.md`, `RESEARCH.md`. Use `/mb start` to load context, `/mb done` to close session.
