# Phase 12: Tool Surface Expansion — Context

## Goal

Agents can search the web, fetch URL content, and read MCP server resources as built-in capabilities, extending the tool surface without new infrastructure.

## Requirements

- **WEBT-01**: Agent can call web_search tool and receive search results from configured web provider
- **WEBT-02**: Agent can call web_fetch tool and receive rendered page content from a URL
- **WEBT-03**: Domain allow/block lists control which URLs web_fetch can access
- **WEBT-04**: Web tools properly integrated with ThinRuntime tool policy and capabilities
- **MCPR-01**: Agent can call read_mcp_resource tool to read a resource by URI from a connected MCP server
- **MCPR-02**: MCP resource list is cached per-connection and available for tool discovery
- **MCPR-03**: MCP resource tool integrates with existing tool policy and naming conventions

## What Already Exists

### Web Tools (MOSTLY DONE)
- `src/swarmline/tools/builtin.py:353-410` — `create_web_tools()` factory producing web_fetch and web_search tools
- `src/swarmline/tools/web_protocols.py` — WebSearchProvider, WebFetchProvider, WebProvider protocols
- `src/swarmline/tools/web_httpx.py` — HttpxWebProvider with full SSRF protection (272 lines)
- `src/swarmline/tools/web_providers/` — 4 search providers (duckduckgo, tavily, searxng, brave) + 3 fetch providers (default, jina, crawl4ai)
- `src/swarmline/bootstrap/capabilities.py` — `collect_capability_tools(web_provider=...)` wiring
- `src/swarmline/policy/tool_policy.py` — web_fetch/web_search in ALWAYS_DENIED, whitelisted via allowed_system_tools

### MCP Client (PARTIAL)
- `src/swarmline/runtime/thin/mcp_client.py` — McpClient with call_tool() + list_tools() (208 lines)
- `src/swarmline/runtime/mcp_bridge.py` — McpBridge library facade (104 lines)
- Tool naming: `mcp__{server_id}__{tool_name}`
- NO resource reading capability

### Network Safety
- `src/swarmline/network_safety.py` — SSRF validation, IP checks (93 lines)
- HttpxWebProvider DNS rebinding prevention, redirect validation

## Gaps to Fill

### WEBT-03: Domain Allow/Block Lists (NEW)
- HttpxWebProvider has SSRF protection but NO domain-level filtering
- Need: `allowed_domains: list[str] | None` and `blocked_domains: list[str] | None` on web_fetch
- Semantics: if allowed_domains set, ONLY those domains work; blocked_domains always rejected
- Wire through RuntimeConfig or tool construction

### MCPR-01..03: MCP Resource Reading (NEW)
- McpClient.read_resource(server_url, uri) → content
- McpClient.list_resources(server_url) → list of resource descriptors
- Cache resources list per-connection (same TTL pattern as tools cache)
- New tool: read_mcp_resource(server_id, uri) registered in ToolExecutor
- Tool naming: `mcp__{server_id}__read_resource` or separate tool

## Integration Points

1. **HttpxWebProvider** — extend with domain filtering (allowed/blocked domains)
2. **McpClient** — add list_resources() and read_resource() methods
3. **ToolExecutor** — register read_mcp_resource tool alongside MCP tool calls
4. **RuntimeConfig** — domain filter config for web tools
5. **DefaultToolPolicy** — web tools remain deny-by-default, whitelist via allowed_system_tools

## Design Decisions

1. **Domain filter location**: HttpxWebProvider level (before request), not policy level. Policy controls access to the tool; domain filter controls what the tool can reach.
2. **MCP resource vs MCP tool**: read_mcp_resource is a SEPARATE built-in tool, not an MCP tool. It uses McpClient internally but appears as a local tool.
3. **Resource cache**: Same cache pattern as tools (dict with TTL), separate from tools cache.
4. **Backward compatibility**: All new config fields optional with None defaults. Existing behavior unchanged.

## Success Criteria

1. Agent can call web_search tool and receive search results from configured web provider
2. Agent can call web_fetch tool and receive rendered page content from a URL
3. Domain allow/block lists control which URLs web_fetch can access
4. Agent can call read_mcp_resource tool to read a resource by URI from a connected MCP server
5. MCP resource list is cached per-connection and available for tool discovery

## Files Expected to Change

- `src/swarmline/tools/web_httpx.py` — domain filtering
- `src/swarmline/runtime/thin/mcp_client.py` — resource reading methods
- `src/swarmline/runtime/thin/executor.py` — read_mcp_resource tool registration
- `src/swarmline/runtime/types.py` — domain filter config field
- `tests/unit/test_web_domain_filter.py` — NEW
- `tests/unit/test_mcp_resource_reading.py` — NEW
- `tests/integration/test_tool_surface_expansion.py` — NEW
