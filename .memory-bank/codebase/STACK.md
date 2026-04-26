# Technology Stack

**Generated:** `2026-04-25T10:16:27Z`
**Graph:** not-used (missing)

## Languages & Runtime
- **Primary:** Python 3.11+ — all source in `src/swarmline/`
- **Secondary:** JavaScript (ESM) — `src/swarmline/runtime/pi_sdk/bridge.mjs` (Node subprocess bridge)
- **Runtime:** CPython 3.11 / 3.12 / 3.13 supported (`pyproject.toml` classifiers)
- **Package manager:** pip / hatchling (`pyproject.toml` build-backend)

## Frameworks
- `pydantic>=2.11` — config validation and structured output (`src/swarmline/agent/config.py`, `src/swarmline/runtime/structured_output.py`)
- `structlog>=25.1.0` — structured logging (`src/swarmline/observability/logger.py`)
- `pyyaml>=6.0.2` — model registry and skill config (`src/swarmline/runtime/models.yaml`, `src/swarmline/skills/`)
- `fastmcp>=2.0` — MCP server (optional extra `mcp`, `src/swarmline/mcp/`)
- `starlette + uvicorn` — HTTP serving and A2A protocol (optional extras `serve`, `a2a`, `src/swarmline/serve/`, `src/swarmline/a2a/`)
- `click>=8.1` — CLI entry point (optional extra `cli`, `src/swarmline/cli/`)

## Key Dependencies
- `anthropic>=0.86` — Anthropic provider for ThinRuntime (optional extra `thin`)
- `openai>=2.29` — OpenAI-compatible provider (optional extra `openai-provider`)
- `google-genai>=1.68` — Google Gemini provider (optional extra `google-provider`)
- `langchain / langgraph` — DeepAgents runtime adapter (optional extra `deepagents`)
- `openai-agents>=0.1` — OpenAI Agents SDK runtime (optional extra `openai-agents`)
- `asyncpg + sqlalchemy[asyncio]>=2.0` — PostgreSQL storage (optional extra `postgres`)
- `aiosqlite + sqlalchemy[asyncio]` — SQLite storage (optional extra `sqlite`)
- `opentelemetry-api/sdk` — tracing export (optional extra `otel`, `src/swarmline/observability/otel_exporter.py`)
- `nats-py / redis` — event bus backends (optional extras `nats`, `redis`)

## External Integrations
- **Anthropic API** — LLM calls, auth via `ANTHROPIC_API_KEY`, client at `src/swarmline/runtime/thin/llm_providers.py`
- **OpenAI API** — LLM + Agents SDK, auth via `OPENAI_API_KEY`, client at `src/swarmline/runtime/thin/llm_providers.py`
- **Google GenAI** — Gemini provider, auth via `GOOGLE_API_KEY`, client at `src/swarmline/runtime/thin/llm_providers.py`
- **PostgreSQL** — persistent memory/tasks, connection via `DATABASE_URL`, ORM at `src/swarmline/memory/postgres.py`
- **E2B / Docker / OpenShell** — sandbox execution, auth via `E2B_API_KEY`, adapters at `src/swarmline/tools/`
- **Tavily / DuckDuckGo / Brave** — web search, auth via `TAVILY_API_KEY` / `BRAVE_API_KEY`, at `src/swarmline/tools/web_providers/`

## Configuration
- **Env files:** none present (`.env*` absent in project root)
- **Config files:** `pyproject.toml`, `src/swarmline/runtime/models.yaml` (model aliases)
- **Required env vars:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `DATABASE_URL`, `E2B_API_KEY`

## Platform
- **Dev:** `pip install -e ".[dev,all]"`, pytest, ruff, ty
- **Prod:** PyPI distribution via GitHub Actions + OIDC Trusted Publishing; public repo at `github.com/fockus/swarmline`
