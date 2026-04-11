# Technology Stack

**Analysis Date:** 2026-04-12

## Languages

**Primary:**
- Python 3.10+ - All source code in `src/swarmline/`
- YAML - Model registry (`src/swarmline/runtime/models.yaml`), skills config

**Secondary:**
- Type stubs (`src/swarmline/py.typed`) - PEP 561 typed package marker

## Runtime

**Environment:**
- Python >=3.10, tested on 3.10/3.11/3.12/3.13

**Package Manager:**
- pip / hatchling build backend (`pyproject.toml`)
- Lockfile: Not present (library package, not application)

## Frameworks

**Build:**
- hatchling `>=latest` - build backend, declared in `pyproject.toml` `[build-system]`

**Validation:**
- pydantic `>=2.11` - A2A protocol types (`src/swarmline/a2a/types.py`), structured output

**Observability/Logging:**
- structlog `>=25.1.0` - structured logging throughout all modules

**Config:**
- pyyaml `>=6.0.2` - model registry loading (`src/swarmline/runtime/models.yaml`)

**HTTP:**
- httpx `>=0.28` (thin extra / web extra) - MCP client, web fetch, Brave/SearXNG search

**Async:**
- asyncio (stdlib) - all runtime and storage APIs are async-first

**Testing:**
- pytest `>=8.0` + pytest-asyncio `>=0.24` + pytest-cov `>=5.0`
- `asyncio_mode = "auto"` in `pyproject.toml`

**Linting/Formatting:**
- ruff `>=0.8` - lint and format

**Type Checking:**
- mypy `>=1.10`

**HTTP Serving:**
- starlette `>=0.40` + uvicorn `>=0.30` (`serve` extra) - `src/swarmline/serve/app.py`

## Key Dependencies

**Core (always installed):**
- `structlog>=25.1.0` - structured logging
- `pyyaml>=6.0.2` - model registry
- `pydantic>=2.11` - data validation (A2A types)

**LLM Provider SDKs (optional extras):**
- `anthropic>=0.86` - Anthropic Messages API, used by `AnthropicAdapter` in `src/swarmline/runtime/thin/llm_providers.py`
- `openai>=2.29` - OpenAI / OpenAI-compat providers, `OpenAICompatAdapter`
- `google-genai>=1.68` - Google Gemini, `GoogleAdapter`
- `claude-agent-sdk>=0.1.51` - Claude Code subprocess runtime (`src/swarmline/runtime/claude_code.py`)
- `deepagents>=0.4.12` + `langchain>=1.2.11` + `langgraph>=1.1.1,<1.2.0` + `langchain-anthropic>=1.3.4` - DeepAgents LangGraph runtime (`src/swarmline/runtime/deepagents.py`)
- `openai-agents>=0.1,<1.0` - OpenAI Agents SDK runtime (`src/swarmline/runtime/openai_agents/`)

**Storage:**
- `aiosqlite>=0.20` + `sqlalchemy[asyncio]>=2.0.45` - SQLite memory provider (`src/swarmline/memory/sqlite.py`)
- `asyncpg>=0.30.0` + `sqlalchemy[asyncio]>=2.0.45` - PostgreSQL memory provider (`src/swarmline/memory/postgres.py`)

**Web Tools:**
- `httpx>=0.27` - base HTTP (web extra)
- `ddgs>=9.0` - DuckDuckGo search (`src/swarmline/tools/web_providers/duckduckgo.py`)
- `tavily-python` - Tavily AI search (`src/swarmline/tools/web_providers/tavily.py`)
- `crawl4ai>=0.8` + Playwright - Crawl4AI fetch (`src/swarmline/tools/web_providers/crawl4ai.py`)
- `trafilatura>=2.0` - HTML text extraction (web-extract extra)

**Sandboxes:**
- `e2b>=1.0` - E2B Firecracker VM cloud sandbox (`src/swarmline/tools/sandbox_e2b.py`)
- `docker>=7.0` - Docker container sandbox (`src/swarmline/tools/sandbox_docker.py`)
- `openshell>=0.0.16` - NVIDIA OpenShell kernel isolation (`src/swarmline/tools/sandbox_openshell.py`)

**Observability:**
- `opentelemetry-api>=1.29` + `opentelemetry-sdk>=1.29` - OTel tracing (`src/swarmline/observability/otel_exporter.py`)

**Event Bus:**
- `nats-py>=2.0` - NATS distributed pub/sub (`src/swarmline/observability/event_bus_nats.py`)
- `redis>=5.0` - Redis pub/sub (`src/swarmline/observability/event_bus_redis.py`)

**A2A Protocol:**
- `starlette>=0.40` + `httpx>=0.28` - Agent-to-Agent protocol server/client (`src/swarmline/a2a/`)

**MCP:**
- `fastmcp>=2.0` - FastMCP STDIO server (`src/swarmline/mcp/`)

**CLI:**
- `click>=8.1` - CLI entry point (`src/swarmline/cli/`)

## Configuration

**Environment:**
- No `.env` file required for core library
- Provider API keys passed as constructor arguments or read from env by SDK clients:
  - `ANTHROPIC_API_KEY` (Anthropic SDK auto-reads)
  - `OPENAI_API_KEY` (OpenAI SDK auto-reads)
  - `GOOGLE_API_KEY` (Google GenAI SDK auto-reads)
  - `TAVILY_API_KEY` - required for `TavilySearchProvider`
  - `BRAVE_SEARCH_API_KEY` - required for `BraveSearchProvider`
  - `JINA_API_KEY` - required for `JinaReaderFetchProvider`
  - `SEARXNG_URL` - required for `SearXNGSearchProvider`
  - `E2B_API_KEY` - required for E2B sandbox

**Build:**
- `pyproject.toml` - single source of truth for metadata, deps, pytest, ruff, mypy
- `src/swarmline/runtime/models.yaml` - model registry (aliases, default model)

## Platform Requirements

**Development:**
- Python 3.10+
- `pip install -e ".[dev,all]"` for full dev setup
- Optional: Docker (for Docker sandbox tests), E2B API key (for E2B tests)

**Production:**
- Python 3.10+ runtime
- Install only the extras needed (e.g. `swarmline[thin,sqlite]` for lightweight)
- Default model: `claude-sonnet-4-20250514` (set in `src/swarmline/runtime/models.yaml`)

## CLI Entry Points

- `swarmline` → `swarmline.cli:main`
- `swarmline-mcp` → `swarmline.mcp:main`
- `swarmline-daemon` → `swarmline.daemon.cli_entry:main`

---

*Stack analysis: 2026-04-12*
