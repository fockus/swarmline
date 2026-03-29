"""HttpxWebProvider - WebProvider implementation via httpx.

fetch: GET URL -> trafilatura/regex -> text (always works).
search: delegates to a pluggable WebSearchProvider (DIP).
Optional dependency: httpx, trafilatura.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

import structlog

from cognitia.tools.web_protocols import SearchResult, WebFetchProvider, WebSearchProvider

try:
    import trafilatura
except ImportError:
    trafilatura = None  # type: ignore[assignment]

_log = structlog.get_logger(component="web_httpx")


def _is_ip(hostname: str) -> bool:
    """Return True if hostname is already a literal IP address."""
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


def _extract_text(html: str) -> str:
    """Extract text from HTML: trafilatura -> improved regex fallback.

    Trafilatura (if installed) extracts the main page content,
    discarding navigation, footers, and ads.
    Without trafilatura, regex removes script/style/tags.
    """
    if trafilatura is not None:
        text = trafilatura.extract(html, include_links=True) or ""
        if text:
            return text[:50000]

    # Improved regex fallback: remove script, style, then tags
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:50000]


class HttpxWebProvider:
    """WebProvider via httpx (async HTTP client).

    fetch: GET -> trafilatura/regex -> text. Or delegate to fetch_provider (Jina/Crawl4AI).
    search: delegates to search_provider (DuckDuckGo, Tavily, SearXNG, Brave).
    """

    def __init__(
        self,
        timeout: int = 30,
        search_provider: WebSearchProvider | None = None,
        fetch_provider: WebFetchProvider | None = None,
    ) -> None:
        self._timeout = timeout
        self._search_provider = search_provider
        self._fetch_provider = fetch_provider

    @staticmethod
    def _validate_url(url: str) -> str | None:
        """Return rejection reason if URL targets a private/reserved network, else None.

        Checks:
        1. Cloud metadata endpoints (AWS, GCP, Azure)
        2. Literal localhost hostnames
        3. Direct IP addresses (private/loopback/link-local/reserved)
        4. DNS-resolved IPs — prevents DNS rebinding to private ranges
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
        except Exception:
            return "Invalid URL"

        # Block cloud metadata endpoints
        _BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal", "100.100.100.200"}
        if hostname in _BLOCKED_HOSTS:
            return f"Blocked host: {hostname}"

        # Block literal localhost hostnames
        if hostname in ("localhost", "localhost.localdomain"):
            return f"Blocked host: {hostname}"

        # Check if hostname is a direct IP address
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return f"Private/reserved IP blocked: {hostname}"
        except ValueError:
            pass  # hostname is a domain, not IP — resolve via DNS below

        # DNS resolution check: resolve hostname and validate all returned IPs
        if hostname and not _is_ip(hostname):
            try:
                addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
                for _family, _type, _proto, _canonname, sockaddr in addrs:
                    resolved = ipaddress.ip_address(sockaddr[0])
                    if (
                        resolved.is_private
                        or resolved.is_loopback
                        or resolved.is_link_local
                        or resolved.is_reserved
                    ):
                        return f"DNS resolves to private IP: {sockaddr[0]}"
            except socket.gaierror:
                pass  # Can't resolve — will fail on fetch anyway

        return None

    async def fetch(self, url: str) -> str:
        """Load a URL and return text content.

        If fetch_provider (Jina/Crawl4AI) is set, delegate to it.
        Otherwise, use httpx GET + trafilatura/regex.
        """
        # SSRF protection — block private IPs and cloud metadata
        rejection = self._validate_url(url)
        if rejection:
            _log.warning("ssrf_blocked", url=url[:200], reason=rejection)
            return f"URL blocked: {rejection}"

        if self._fetch_provider is not None:
            return await self._fetch_provider.fetch(url)

        try:
            import httpx
        except ImportError:
            return "httpx не установлен. pip install cognitia[web]"

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
                return _extract_text(html)
        except Exception as exc:
            _log.warning("httpx_fetch_failed", url=url[:200], error=str(exc))
            return ""

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search the internet via a pluggable provider.

        Delegates to search_provider when it is set.
        Returns an empty list when no provider is configured.
        """
        if self._search_provider is None:
            return []
        return await self._search_provider.search(query, max_results)
