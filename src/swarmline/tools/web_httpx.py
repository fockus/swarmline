"""HttpxWebProvider - WebProvider implementation via httpx.

fetch: GET URL -> trafilatura/regex -> text (always works).
search: delegates to a pluggable WebSearchProvider (DIP).
Optional dependency: httpx, trafilatura.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import structlog

from swarmline.observability.security import log_security_decision
from swarmline.tools.web_protocols import (
    SearchResult,
    WebFetchProvider,
    WebSearchProvider,
)

try:
    import trafilatura  # ty: ignore[unresolved-import]  # optional dep
except ImportError:
    trafilatura = None  # type: ignore[assignment]

_log = structlog.get_logger(component="web_httpx")


def _log_network_target_denied(url: str, reason: str) -> None:
    parsed = urlparse(url)
    log_security_decision(
        _log,
        component="web_httpx",
        event_name="security.network_target_denied",
        reason=reason,
        target=parsed.hostname or "",
        url=url,
    )


def _is_ip(hostname: str) -> bool:
    """Return True if hostname is already a literal IP address."""
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


def _is_blocked_ip(value: str) -> bool:
    """Return True when an IP falls into a non-public range."""
    addr = ipaddress.ip_address(value)
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


def _resolve_public_connect_host(hostname: str) -> str | None:
    """Resolve hostname and return a concrete public IP for the request path.

    Returns ``None`` when the hostname cannot be resolved. The caller may still
    use the original hostname in that case and rely on a normal network error.
    """
    if not hostname or _is_ip(hostname):
        return hostname or None

    try:
        addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
    except socket.gaierror:
        return None

    public_addrs: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in addrs:
        resolved = sockaddr[0]
        if not isinstance(resolved, str):
            continue
        if _is_blocked_ip(resolved):
            msg = f"DNS resolves to private IP: {resolved}"
            raise ValueError(msg)
        public_addrs.append(resolved)

    return public_addrs[0] if public_addrs else None


def _build_safe_request_target(
    url: str,
) -> tuple[str, dict[str, str], dict[str, object]]:
    """Bind a request to a validated IP while preserving Host/SNI semantics."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not hostname:
        msg = "Invalid URL"
        raise ValueError(msg)

    connect_host = _resolve_public_connect_host(hostname)
    if connect_host is None or connect_host == hostname:
        return url, {}, {}

    port = parsed.port
    credentials = ""
    if parsed.username:
        credentials = parsed.username
        if parsed.password:
            credentials = f"{credentials}:{parsed.password}"
        credentials = f"{credentials}@"

    connect_netloc = f"{credentials}{connect_host}"
    if port is not None:
        connect_netloc = f"{connect_netloc}:{port}"

    default_port = (
        80 if parsed.scheme == "http" else 443 if parsed.scheme == "https" else None
    )
    host_header = hostname
    if port is not None and port != default_port:
        host_header = f"{host_header}:{port}"

    safe_url = parsed._replace(netloc=connect_netloc).geturl()
    extensions: dict[str, object] = {}
    if parsed.scheme == "https":
        extensions["sni_hostname"] = hostname
    return safe_url, {"host": host_header}, extensions


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
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
    ) -> None:
        self._timeout = timeout
        self._search_provider = search_provider
        self._fetch_provider = fetch_provider
        self._allowed_domains = (
            frozenset(d.lower() for d in allowed_domains)
            if allowed_domains
            else frozenset()
        )
        self._blocked_domains = (
            frozenset(d.lower() for d in blocked_domains)
            if blocked_domains
            else frozenset()
        )

    def _is_domain_blocked(self, url: str) -> str | None:
        """Return rejection reason if URL domain is not allowed by filter, else None.

        Rules:
        - No lists configured (both empty) → allow all.
        - Blocked list checked first — blocked takes precedence over allowed.
        - Matching is case-insensitive with subdomain support:
          hostname "sub.example.com" matches entry "example.com".
        """
        if not self._allowed_domains and not self._blocked_domains:
            return None

        try:
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower()
        except Exception:
            return "Invalid URL"

        if not hostname:
            return "Invalid URL: no hostname"

        def _matches(domain: str, entries: frozenset[str]) -> bool:
            """Check if domain matches any entry (exact or as subdomain)."""
            if domain in entries:
                return True
            return any(domain.endswith("." + entry) for entry in entries)

        if self._blocked_domains and _matches(hostname, self._blocked_domains):
            return f"Domain blocked: {hostname}"

        if self._allowed_domains and not _matches(hostname, self._allowed_domains):
            return f"Domain not in allowed list: {hostname}"

        return None

    @staticmethod
    def _validate_url(url: str) -> str | None:
        """Return rejection reason if URL targets a private/reserved network, else None.

        Checks (in order — fail fast):
        0. Scheme allowlist — only ``http`` and ``https`` (case-insensitive). Blocks
           ``file://``, ``ftp://``, ``data:``, ``javascript:``, ``gopher://``, ``ssh://``,
           ``smb://``, ``ws[s]://``, etc. Closes audit finding P2 #4 — without this,
           non-HTTP schemes pass to delegated browser providers (Crawl4AI) which can
           open local files or non-web targets.
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

        # Scheme allowlist — http/https only
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            return f"Scheme blocked: {parsed.scheme!r} (only http/https allowed)"

        # Block cloud metadata endpoints
        _BLOCKED_HOSTS = {
            "169.254.169.254",
            "metadata.google.internal",
            "100.100.100.200",
        }
        if hostname in _BLOCKED_HOSTS:
            return f"Blocked host: {hostname}"

        # Block literal localhost hostnames
        if hostname in ("localhost", "localhost.localdomain"):
            return f"Blocked host: {hostname}"

        # Check if hostname is a direct IP address
        try:
            addr = ipaddress.ip_address(hostname)
            if _is_blocked_ip(str(addr)):
                return f"Private/reserved IP blocked: {hostname}"
        except ValueError:
            pass  # hostname is a domain, not IP — resolve via DNS below

        # DNS resolution check: resolve hostname and validate all returned IPs
        if hostname and not _is_ip(hostname):
            try:
                addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
                for _family, _type, _proto, _canonname, sockaddr in addrs:
                    resolved = sockaddr[0]
                    if not isinstance(resolved, str):
                        continue
                    if _is_blocked_ip(resolved):
                        return f"DNS resolves to private IP: {resolved}"
            except socket.gaierror:
                pass  # Can't resolve — will fail on fetch anyway

        return None

    async def fetch(self, url: str) -> str:
        """Load a URL and return text content.

        If fetch_provider (Jina/Crawl4AI) is set, delegate to it.
        Otherwise, use httpx GET + trafilatura/regex.
        """
        # Domain allow/block filter — fail fast before SSRF check
        domain_rejection = self._is_domain_blocked(url)
        if domain_rejection:
            _log_network_target_denied(url, domain_rejection)
            return f"URL blocked: {domain_rejection}"

        # SSRF protection — block private IPs and cloud metadata
        rejection = self._validate_url(url)
        if rejection:
            _log_network_target_denied(url, rejection)
            return f"URL blocked: {rejection}"

        if self._fetch_provider is not None:
            return await self._fetch_provider.fetch(url)

        try:
            import httpx
        except ImportError:
            return "httpx не установлен. pip install swarmline[web]"

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False
            ) as client:
                current_url = url
                for _redirect_hop in range(6):
                    rejection = self._validate_url(current_url)
                    if rejection:
                        _log_network_target_denied(current_url, rejection)
                        return f"URL blocked: {rejection}"

                    try:
                        safe_url, headers, extensions = _build_safe_request_target(
                            current_url
                        )
                    except ValueError as exc:
                        _log_network_target_denied(current_url, str(exc))
                        return f"URL blocked: {exc}"

                    request = client.build_request(
                        "GET",
                        safe_url,
                        headers=headers or None,
                        extensions=extensions or None,
                    )
                    response = await client.send(request)

                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            response.raise_for_status()
                        current_url = urljoin(current_url, location)
                        continue

                    response.raise_for_status()
                    html = response.text
                    return _extract_text(html)

                _log.warning(
                    "httpx_fetch_failed", url=url[:200], error="Too many redirects"
                )
                return ""
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
