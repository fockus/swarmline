# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Swarmline** — LLM-agnostic Python framework for building AI agents with pluggable runtimes, persistent memory, tool management, and structured observability. Version 1.4.1, Python 3.10+.

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
├── policy/          # Default-deny tool policy, tool selector
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

Two remotes: private development + public release. Full release process documented in `docs/releasing.md`.

```
origin  → github.com/fockus/swarmline-dev  (private, all branches)
public  → github.com/fockus/swarmline      (public, stable main only)
```

### Branching

```
main (stable, tested, releasable)
  ├── feat/<name>       ← feature development
  ├── fix/<name>        ← bug fixes
  └── release/vX.Y.Z   ← version bump + changelog before tag
```

### Development → Publication flow

1. Develop on feature branches, push to `origin` (private) freely
2. Merge to `main` — must always be green (tests, lint, types)
3. When ready to release: `release/vX.Y.Z` branch → bump `pyproject.toml` version + CHANGELOG → merge → tag
4. `./scripts/sync-public.sh --tags` — filters private files, pushes to public repo
5. GitHub Actions on public repo auto-publishes to PyPI via OIDC Trusted Publishing

### Versioning (Strict SemVer)

| Bump | When | Examples |
|------|------|----------|
| **MAJOR** | Breaking public API change | Remove/rename export, change Protocol method, incompatible config |
| **MINOR** | New user-facing feature (backward-compatible) | New module, new runtime, new CLI command, deprecation |
| **PATCH** | Bug fix, security fix, perf fix | Bug fix, dependency bump, docs typo in docstrings |

**NOT a version bump** (commit freely, no release): refactoring, tests, CI, docs/, Memory Bank, CLAUDE.md, lint fixes, dev tooling.

**Batching rule**: aim for 1-2 minor releases per month. Group related features into one release. Patches ship immediately for security/bugs.

### Private vs Public

| Content | Private (`origin`) | Public (`public`) |
|---------|-------------------|-------------------|
| Source code | all branches | main only |
| `.memory-bank/`, `CLAUDE.md`, `RULES.md` | tracked | **filtered out** by sync script |
| `AGENTS.md` | full version | **replaced** with `AGENTS.public.md` |
| `.specs/`, `.planning/`, `.factory/` | tracked | **filtered out** by sync script |
| WIP / feature branches | pushed | never pushed |

### Quick reference

```bash
# Daily development
git checkout -b feat/my-feature && git push origin feat/my-feature

# Release (see docs/releasing.md for full checklist)
git checkout -b release/v1.5.0
# bump pyproject.toml version + finalize CHANGELOG.md
git checkout main && git merge release/v1.5.0
git tag v1.5.0 && git push origin main --tags
./scripts/sync-public.sh --tags       # → public repo → PyPI
```

## Memory Bank

Active at `.memory-bank/`. Core files: `STATUS.md`, `checklist.md`, `plan.md`, `RESEARCH.md`. Use `/mb start` to load context, `/mb done` to close session.

<!-- GSD:project-start source:PROJECT.md -->
## Project

**ThinRuntime Claude Code Parity**

Доработка ThinRuntime модуля в swarmline (Python LLM-agnostic agent framework) до полноценного runtime, сравнимого по возможностям с Claude Code. Включает систему хуков (PreToolUse/PostToolUse/Stop/UserPromptSubmit), LLM-initiated субагентов, slash-команд, tool policy enforcement и native tool calling API. Целевая аудитория — разработчики, использующие swarmline с thin runtime для multi-provider AI агентов.

**Core Value:** ThinRuntime должен обеспечивать безопасное и полнофункциональное выполнение агентов с контролем инструментов через hooks и policy, возможностью делегирования задач через субагентов, и поддержкой native tool calling API провайдеров.

### Constraints

- **Обратная совместимость**: все 4263 существующих тестов должны проходить на каждом этапе. Все новые поля optional с None default.
- **TDD**: тесты → реализация → рефакторинг. Каждая фаза начинается с red tests.
- **Contract-first**: Protocol/ABC → contract tests → implementation.
- **Clean Architecture**: Domain (protocols) → Application → Infrastructure. Hooks/policy = domain, wiring = infrastructure.
- **ISP**: Protocol ≤ 5 methods. HookDispatcher Protocol — max 5 methods.
- **Python 3.10+**: min version, type hints, async-first.
- **Versioning**: вся работа = один minor release v1.5.0. Без промежуточных бампов.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->
## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
