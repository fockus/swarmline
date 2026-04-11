# External Integrations

**Analysis Date:** 2026-04-12

## LLM Providers

**Anthropic:**
- Service: Anthropic Messages API (claude-sonnet-4, claude-opus-4, claude-haiku-3)
- SDK: `anthropic>=0.86` (lazy import inside `AnthropicAdapter.__init__`)
- Adapter: `src/swarmline/runtime/thin/llm_providers.py` → `AnthropicAdapter`
- Auth: `ANTHROPIC_API_KEY` (read automatically by the Anthropic SDK)
- Custom base_url: supported via `base_url` constructor arg

**OpenAI / OpenAI-compatible:**
- Service: OpenAI API and any OpenAI-compat endpoint
- SDK: `openai>=2.29` (lazy import inside `OpenAICompatAdapter.__init__`)
- Adapter: `src/swarmline/runtime/thin/llm_providers.py` → `OpenAICompatAdapter`
- Auth: `OPENAI_API_KEY` (read automatically by the OpenAI SDK)
- Supported providers and their default base URLs (set in `src/swarmline/runtime/provider_resolver.py`):
  - `openai` → standard OpenAI endpoint
  - `openrouter` → `https://openrouter.ai/api/v1`
  - `ollama` → `http://localhost:11434/v1` (local dev)
  - `local` → `http://localhost:8000/v1` (local dev)
  - `together` → `https://api.together.xyz/v1`
  - `groq` → `https://api.groq.com/openai/v1`
  - `fireworks` → `https://api.fireworks.ai/inference/v1`
  - `deepseek` → `https://api.deepseek.com/v1`

**Google Gemini:**
- Service: Google GenAI API (gemini-2.5-pro, gemini-2.5-flash)
- SDK: `google-genai>=1.68` (lazy import inside `GoogleAdapter.__init__`)
- Adapter: `src/swarmline/runtime/thin/llm_providers.py` → `GoogleAdapter`
- Auth: `GOOGLE_API_KEY` (read automatically by Google GenAI SDK)
- Custom base_url: supported via `HttpOptions(base_url=...)` in constructor

**Claude Agent SDK (subprocess):**
- Service: Claude Code runtime via subprocess
- SDK: `claude-agent-sdk>=0.1.51` (`claude` extra)
- Runtime: `src/swarmline/runtime/claude_code.py` → `ClaudeCodeRuntime`
- Auth: managed by SDK (inherits ANTHROPIC_API_KEY from environment)

**OpenAI Agents SDK:**
- Service: OpenAI Codex / Agents SDK
- SDK: `openai-agents>=0.1,<1.0` (`openai-agents` extra)
- Runtime: `src/swarmline/runtime/openai_agents/runtime.py`
- Auth: `OPENAI_API_KEY`

**LangChain / LangGraph (DeepAgents):**
- Service: LangGraph-backed agent execution with LangChain Anthropic model
- SDK: `deepagents>=0.4.12` + `langchain>=1.2.11` + `langgraph>=1.1.1,<1.2.0` + `langchain-anthropic>=1.3.4`
- Runtime: `src/swarmline/runtime/deepagents.py` → `DeepAgentsRuntime`
- Auth: `ANTHROPIC_API_KEY` (via langchain-anthropic)

## Web Search Providers

**DuckDuckGo (default, no API key):**
- SDK: `ddgs>=9.0` (`web-duckduckgo` extra)
- Provider: `src/swarmline/tools/web_providers/duckduckgo.py` → `DuckDuckGoSearchProvider`
- Auth: None required

**Tavily (AI-optimized):**
- API: `https://api.tavily.com` (called via `tavily-python` SDK)
- SDK: `tavily-python` (`web-tavily` extra)
- Provider: `src/swarmline/tools/web_providers/tavily.py` → `TavilySearchProvider`
- Auth: `TAVILY_API_KEY` (passed as constructor arg, free tier: 1000 req/month)

**Brave Search:**
- API: `https://api.search.brave.com/res/v1/web/search`
- HTTP: httpx (no extra SDK, uses `web` extra httpx)
- Provider: `src/swarmline/tools/web_providers/brave.py` → `BraveSearchProvider`
- Auth: `BRAVE_SEARCH_API_KEY` (free tier: 2000 req/month)

**SearXNG (self-hosted):**
- API: User-provided SearXNG instance URL
- HTTP: httpx
- Provider: `src/swarmline/tools/web_providers/searxng.py` → `SearXNGSearchProvider`
- Auth: `SEARXNG_URL` (no API key, self-hosted only)

## Web Fetch Providers

**Default (httpx + trafilatura):**
- Provider: `src/swarmline/tools/web_httpx.py`
- `factory.create_fetch_provider("default")` returns None → falls back to built-in path
- Deps: `httpx>=0.27` + optional `trafilatura>=2.0`

**Jina Reader:**
- API: `https://r.jina.ai/{url}` (URL-to-markdown conversion)
- HTTP: httpx
- Provider: `src/swarmline/tools/web_providers/jina.py` → `JinaReaderFetchProvider`
- Auth: `JINA_API_KEY` (free tier: 1M tokens)

**Crawl4AI:**
- SDK: `crawl4ai>=0.8` + Playwright (`web-crawl4ai` extra)
- Provider: `src/swarmline/tools/web_providers/crawl4ai.py` → `Crawl4AIFetchProvider`
- Auth: None

## Data Storage

**In-Memory:**
- Provider: `src/swarmline/memory/inmemory.py`
- No external dependencies (stdlib only)

**SQLite:**
- Client: `aiosqlite>=0.20` + `sqlalchemy[asyncio]>=2.0.45` (`sqlite` extra)
- Provider: `src/swarmline/memory/sqlite.py`
- Activity log: `src/swarmline/observability/activity_log.py` → `SqliteActivityLog`

**PostgreSQL:**
- Client: `asyncpg>=0.30.0` + `sqlalchemy[asyncio]>=2.0.45` (`postgres` extra)
- Provider: `src/swarmline/memory/postgres.py`
- Connection: connection string passed at construction time (env var not hardcoded)

## Code Execution Sandboxes

**Local (no isolation):**
- Provider: `src/swarmline/tools/sandbox_local.py`
- Auth: None

**Docker:**
- SDK: `docker>=7.0` (`docker` extra)
- Provider: `src/swarmline/tools/sandbox_docker.py` → `DockerSandboxProvider`
- Auth: local Docker daemon socket (no API key)

**E2B (cloud Firecracker VM):**
- SDK: `e2b>=1.0` (`e2b` extra)
- Provider: `src/swarmline/tools/sandbox_e2b.py` → `E2BSandboxProvider`
- Auth: `E2B_API_KEY`

**OpenShell (NVIDIA kernel-level isolation):**
- SDK: `openshell>=0.0.16` (`openshell` extra)
- Provider: `src/swarmline/tools/sandbox_openshell.py`
- Auth: None (local kernel module)

## Observability & Monitoring

**OpenTelemetry:**
- SDK: `opentelemetry-api>=1.29` + `opentelemetry-sdk>=1.29` (`otel` extra)
- Exporter: `src/swarmline/observability/otel_exporter.py` → `OTelExporter`
- Follows OTel GenAI Semantic Conventions (v1.37+)
- Bridges internal `EventBus` events (llm_call_start/end, tool_call_start/end) to OTel spans
- Uses global or injected `TracerProvider`

**Logging:**
- structlog (always installed) — structured JSON-compatible logging
- Logger configured via `src/swarmline/observability/logger.py` → `configure_logging()`
- Security decisions logged via `src/swarmline/observability/security.py`

## Event Bus Backends

**In-Memory (default):**
- `src/swarmline/observability/event_bus.py` → `InMemoryEventBus`
- No external deps

**NATS:**
- SDK: `nats-py>=2.0` (`nats` extra, lazy import)
- `src/swarmline/observability/event_bus_nats.py` → `NatsEventBus`
- NATS subject pattern: `swarmline.{event_type}`
- Connection: `nats_url` constructor arg (e.g. `nats://my-nats:4222`)

**Redis:**
- SDK: `redis>=5.0` (`redis` extra, lazy import)
- `src/swarmline/observability/event_bus_redis.py` → `RedisEventBus`
- Channel pattern: `swarmline:{event_type}`
- Connection: `redis_url` constructor arg (e.g. `redis://my-redis:6379/0`)

## Agent-to-Agent (A2A) Protocol

**Server:**
- Framework: starlette `>=0.40` (`a2a` extra)
- Implementation: `src/swarmline/a2a/server.py`
- Discovery endpoint: `/.well-known/agent.json` → `AgentCard`
- Protocol: JSON-RPC 2.0 over HTTP, SSE for streaming
- Types: `src/swarmline/a2a/types.py` (pydantic models, Google A2A spec 2024-2025)

**Client:**
- HTTP: httpx `>=0.28`
- Implementation: `src/swarmline/a2a/client.py`

## MCP (Model Context Protocol)

**MCP Client (HTTP/SSE):**
- HTTP: httpx (already in `thin` extra)
- Client: `src/swarmline/runtime/thin/mcp_client.py` → `McpClient`
- Protocol: JSON-RPC 2.0 over HTTP POST
- Tool naming: `mcp__{server_id}__{tool_name}` format
- URL validation via `src/swarmline/network_safety.py`

**MCP Server (STDIO):**
- SDK: `fastmcp>=2.0` (`mcp` extra)
- Entry point: `swarmline-mcp` → `src/swarmline/mcp/__main__.py`
- Tools exposed: agent query, memory, plans, team ops (`src/swarmline/mcp/_tools_*.py`)

## HTTP Serving

**swarmline serve:**
- Framework: starlette `>=0.40` + uvicorn `>=0.30` (`serve` extra)
- App factory: `src/swarmline/serve/app.py`
- Auth: optional Bearer token middleware (`_BearerAuthMiddleware`)
- Exempt paths: `/v1/health`, `/v1/info`

## CI/CD & Deployment

**Hosting:** GitHub (`github.com/fockus/swarmline` public, `github.com/fockus/cognitia-dev` private)
**CI Pipeline:** Not detected in codebase (no `.github/workflows/` checked)
**Release script:** `scripts/sync-public.sh` — filters private files and force-pushes stable main to public remote

## Environment Configuration Summary

| Variable | Used By | Required |
|----------|---------|----------|
| `ANTHROPIC_API_KEY` | Anthropic SDK (auto) | Yes, for Anthropic models |
| `OPENAI_API_KEY` | OpenAI SDK (auto) | Yes, for OpenAI models |
| `GOOGLE_API_KEY` | Google GenAI SDK (auto) | Yes, for Gemini models |
| `TAVILY_API_KEY` | `TavilySearchProvider` constructor | Yes, for Tavily search |
| `BRAVE_SEARCH_API_KEY` | `BraveSearchProvider` constructor | Yes, for Brave search |
| `JINA_API_KEY` | `JinaReaderFetchProvider` constructor | Yes, for Jina fetch |
| `SEARXNG_URL` | `SearXNGSearchProvider` constructor | Yes, for SearXNG |
| `E2B_API_KEY` | E2B SDK (auto) | Yes, for E2B sandbox |

## Webhooks & Callbacks

**Incoming:** A2A server at user-configured path (starlette app), MCP STDIO server
**Outgoing:** None (all outbound calls are request-response, not push webhooks)

---

*Integration audit: 2026-04-12*
