# Web Tools

Swarmline provides pluggable web access through two ISP-compliant protocols: **search** (find information) and **fetch** (extract page content). Mix and match providers independently.

## Architecture

```
HttpxWebProvider (WebProvider)
    ├── search_provider: WebSearchProvider (pluggable)
    │   ├── DuckDuckGoSearchProvider   # no API key, 9 search engines
    │   ├── BraveSearchProvider        # BRAVE_SEARCH_API_KEY
    │   ├── TavilySearchProvider       # TAVILY_API_KEY
    │   └── SearXNGSearchProvider      # self-hosted, no limits
    │
    └── fetch_provider: WebFetchProvider (pluggable)
        ├── (default) httpx + trafilatura  # built-in, no extra deps
        ├── JinaReaderFetchProvider    # JINA_API_KEY, markdown output
        └── Crawl4AIFetchProvider      # Playwright, JS-heavy sites
```

## Protocols

### WebSearchProvider

```python
@runtime_checkable
class WebSearchProvider(Protocol):
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...
```

### WebFetchProvider

```python
@runtime_checkable
class WebFetchProvider(Protocol):
    async def fetch(self, url: str) -> str: ...
```

### SearchResult

```python
@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
```

## Quick Start

### Default (httpx only, no search)

```python
from swarmline.tools.web_httpx import HttpxWebProvider

web = HttpxWebProvider(timeout=30)
# web.fetch(url) works (httpx + trafilatura)
# web.search(query) returns [] (no search provider)
```

### With DuckDuckGo Search (no API key)

```python
from swarmline.tools.web_httpx import HttpxWebProvider
from swarmline.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider

web = HttpxWebProvider(
    timeout=30,
    search_provider=DuckDuckGoSearchProvider(timeout=15),
)

results = await web.search("Python async frameworks", max_results=5)
for r in results:
    print(f"{r.title}: {r.url}")
    print(f"  {r.snippet}")
```

### With Jina Reader Fetch

```python
from swarmline.tools.web_httpx import HttpxWebProvider
from swarmline.tools.web_providers.jina import JinaReaderFetchProvider

web = HttpxWebProvider(
    fetch_provider=JinaReaderFetchProvider(api_key="jina_..."),
)

content = await web.fetch("https://example.com/article")
print(content)  # Clean markdown with tables, code, links
```

### Full Setup (search + fetch)

```python
from swarmline.tools.web_httpx import HttpxWebProvider
from swarmline.tools.web_providers.tavily import TavilySearchProvider
from swarmline.tools.web_providers.crawl4ai import Crawl4AIFetchProvider

web = HttpxWebProvider(
    timeout=30,
    search_provider=TavilySearchProvider(api_key="tvly-..."),
    fetch_provider=Crawl4AIFetchProvider(timeout=30),
)
```

### Using the Factory

Create providers by name (useful for configuration-driven setup):

```python
from swarmline.tools.web_providers.factory import create_search_provider, create_fetch_provider

search = create_search_provider("duckduckgo")
search = create_search_provider("tavily", api_key="tvly-...")
search = create_search_provider("brave", api_key="BSA...")
search = create_search_provider("searxng", base_url="https://searx.example.com")

fetch = create_fetch_provider("default")    # None (use built-in httpx)
fetch = create_fetch_provider("jina", api_key="jina_...")
fetch = create_fetch_provider("crawl4ai")
```

## Search Providers

### DuckDuckGo

Meta-search across 9 engines (Bing, Google, Brave, Yandex, Yahoo, Mojeek, Wikipedia, Grokipedia). No API key required.

```python
from swarmline.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider

provider = DuckDuckGoSearchProvider(timeout=15)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timeout` | `int` | `15` | Search timeout in seconds |

**Install:** `pip install swarmline[web-duckduckgo]`
**Dependency:** `ddgs`
**Rate limit:** None (but may be throttled by DuckDuckGo)

### Brave Search

Fast, privacy-focused search with free tier (2,000 requests/month).

```python
from swarmline.tools.web_providers.brave import BraveSearchProvider

provider = BraveSearchProvider(api_key="BSA...", timeout=15)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_key` | `str` | required | Brave Search API key (`BRAVE_SEARCH_API_KEY`) |
| `timeout` | `int` | `15` | Request timeout in seconds |

**Install:** `pip install swarmline[web]` (uses httpx)
**Rate limit:** 2,000 req/month (free), higher on paid plans

### Tavily

AI-optimized search designed specifically for LLM agents. Returns pre-processed, relevant content.

```python
from swarmline.tools.web_providers.tavily import TavilySearchProvider

provider = TavilySearchProvider(api_key="tvly-...")
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_key` | `str` | required | Tavily API key (`TAVILY_API_KEY`) |

**Install:** `pip install swarmline[web-tavily]`
**Dependency:** `tavily-python`
**Rate limit:** 1,000 req/month (free)

### SearXNG

Self-hosted meta-search engine. No API keys, no rate limits, full control.

```python
from swarmline.tools.web_providers.searxng import SearXNGSearchProvider

provider = SearXNGSearchProvider(base_url="https://searx.example.com", timeout=15)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_url` | `str` | required | URL of your SearXNG instance (`SEARXNG_URL`) |
| `timeout` | `int` | `15` | Request timeout in seconds |

**Install:** `pip install swarmline[web]` (uses httpx)
**Requirements:** Self-hosted SearXNG instance with JSON API enabled

## Fetch Providers

### Default (httpx + trafilatura)

Built-in fetch using httpx for HTTP requests and trafilatura for content extraction. Falls back to regex-based extraction if trafilatura is not installed.

```python
# No explicit provider needed — it's the default
web = HttpxWebProvider(timeout=30)
content = await web.fetch("https://example.com")
```

- Extracts main content, strips navigation/ads/footers (via trafilatura)
- Falls back to regex tag stripping without trafilatura
- Content truncated to 50,000 characters

**Install:** `pip install swarmline[web]`

### Jina Reader

Converts any URL to clean, LLM-friendly markdown via Jina AI Reader API. Supports tables, code blocks, LaTeX, 29 languages.

```python
from swarmline.tools.web_providers.jina import JinaReaderFetchProvider

provider = JinaReaderFetchProvider(api_key="jina_...", timeout=30)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_key` | `str` | required | Jina API key (`JINA_API_KEY`) |
| `timeout` | `int` | `30` | Request timeout in seconds |

**Install:** `pip install swarmline[web-jina]`
**Free tier:** 1M tokens

### Crawl4AI

Playwright-based crawler for JavaScript-heavy sites. Renders pages in a real browser before extracting content.

```python
from swarmline.tools.web_providers.crawl4ai import Crawl4AIFetchProvider

provider = Crawl4AIFetchProvider(timeout=30)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timeout` | `int` | `30` | Crawl timeout in seconds |

**Install:** `pip install swarmline[web-crawl4ai]`
**Dependency:** `crawl4ai` (includes Playwright)

Best for: SPAs, dynamic content, sites that require JavaScript rendering.

## Comparison

### Search Providers

| Provider | API Key | Free Tier | Best For |
|----------|---------|-----------|----------|
| **DuckDuckGo** | None | Unlimited | Quick start, no setup |
| **Brave** | Required | 2,000/month | Fast, privacy-focused |
| **Tavily** | Required | 1,000/month | AI-optimized results |
| **SearXNG** | None | Unlimited | Full control, self-hosted |

### Fetch Providers

| Provider | API Key | Best For |
|----------|---------|----------|
| **Default (httpx)** | None | Most websites, static content |
| **Jina Reader** | Required | Clean markdown, tables, LaTeX |
| **Crawl4AI** | None | JS-heavy sites, SPAs |

## Using with SwarmlineStack

```python
from swarmline.bootstrap.stack import SwarmlineStack
from swarmline.tools.web_httpx import HttpxWebProvider
from swarmline.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider

web = HttpxWebProvider(
    timeout=30,
    search_provider=DuckDuckGoSearchProvider(),
)

stack = SwarmlineStack.create(
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),
    web_provider=web,
    # ... other config
)
# Agent now has: web_fetch(url) and web_search(query) tools
```

## Writing a Custom Provider

Implement one of the protocols:

```python
from swarmline.tools.web_protocols import WebSearchProvider, WebFetchProvider, SearchResult

class MySearchProvider:
    """Custom search provider — just implement the protocol."""

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        # Your search logic here
        return [
            SearchResult(title="Result", url="https://...", snippet="...")
        ]

class MyFetchProvider:
    """Custom fetch provider — just implement the protocol."""

    async def fetch(self, url: str) -> str:
        # Your fetch logic here
        return "Page content as text or markdown"
```

Then plug it in:

```python
web = HttpxWebProvider(
    search_provider=MySearchProvider(),
    fetch_provider=MyFetchProvider(),
)
```

## Environment Variables

| Variable | Provider | Description |
|----------|----------|-------------|
| `BRAVE_SEARCH_API_KEY` | Brave | API key for Brave Search |
| `TAVILY_API_KEY` | Tavily | API key for Tavily |
| `JINA_API_KEY` | Jina | API key for Jina Reader |
| `SEARXNG_URL` | SearXNG | URL of self-hosted SearXNG instance |
