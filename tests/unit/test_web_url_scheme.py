"""Tests for HttpxWebProvider URL scheme allowlist.

Stage 4 of plans/2026-04-27_fix_security-audit.md — closes audit finding P2 #4
(non-HTTP schemes pass _validate_url and reach delegated browser-capable
fetch providers like Crawl4AI, allowing file://, ftp://, data: targets).

The fix tightens _validate_url with an explicit scheme allowlist
(``{"http", "https"}``, case-insensitive) BEFORE host/IP/DNS checks.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from swarmline.tools.web_httpx import HttpxWebProvider


class TestValidateUrlSchemeAllowlist:
    """_validate_url rejects every non-(http|https) scheme."""

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "file:///C:/Windows/System32/drivers/etc/hosts",
            "ftp://internal.corp/secret.tar",
            "ftps://example.com/x",
            "data:text/plain;base64,SGVsbG8=",
            "javascript:alert(1)",
            "gopher://internal:70/0/x",
            "ssh://attacker@example.com/",
            "smb://share/secret",
            "ws://example.com/socket",
            "wss://example.com/socket",
        ],
    )
    def test_validate_url_rejects_non_http_schemes(self, url: str) -> None:
        rejection = HttpxWebProvider._validate_url(url)
        assert rejection is not None, f"expected rejection for {url!r}"
        assert "scheme" in rejection.lower() or "blocked" in rejection.lower()

    def test_validate_url_rejects_schemeless_url(self) -> None:
        """Schemeless inputs (`example.com`) must be rejected — operators must
        pass full URLs so we never silently default to http://."""
        rejection = HttpxWebProvider._validate_url("example.com")
        assert rejection is not None

    @pytest.mark.parametrize("url", ["http://example.com", "https://example.com/x"])
    def test_validate_url_accepts_http_and_https_for_public_host(
        self, url: str
    ) -> None:
        """http and https schemes are allowed (host check applies separately)."""
        # Public domain — passes scheme check; downstream may still block via
        # SSRF/DNS rules, but scheme guard returns None.
        result = HttpxWebProvider._validate_url(url)
        # If rejection is non-None, it must NOT be about scheme
        if result is not None:
            assert "scheme" not in result.lower()

    @pytest.mark.parametrize("url", ["HTTP://example.com", "HTTPS://example.com/x"])
    def test_validate_url_accepts_uppercase_schemes(self, url: str) -> None:
        """Scheme matching is case-insensitive per RFC 3986."""
        result = HttpxWebProvider._validate_url(url)
        if result is not None:
            assert "scheme" not in result.lower()


class TestFetchBlocksFileSchemeWithDelegatedProvider:
    """End-to-end: file:// must be blocked even when a delegated provider
    (Crawl4AI / Jina / Tavily) is set, because those providers may have
    browser engines capable of opening local files."""

    async def test_fetch_blocks_file_scheme_with_crawl4ai_provider(self) -> None:
        """file:///etc/passwd must NOT reach the delegated fetch_provider."""
        delegated = AsyncMock()
        delegated.fetch = AsyncMock(return_value="HOSTILE: read /etc/passwd")
        provider = HttpxWebProvider(fetch_provider=delegated)

        result = await provider.fetch("file:///etc/passwd")

        assert "blocked" in result.lower()
        delegated.fetch.assert_not_called()

    async def test_fetch_blocks_data_scheme_with_delegated_provider(self) -> None:
        delegated = AsyncMock()
        delegated.fetch = AsyncMock()
        provider = HttpxWebProvider(fetch_provider=delegated)

        result = await provider.fetch("data:text/plain;base64,SGVsbG8=")

        assert "blocked" in result.lower()
        delegated.fetch.assert_not_called()

    async def test_fetch_blocks_javascript_scheme(self) -> None:
        delegated = AsyncMock()
        delegated.fetch = AsyncMock()
        provider = HttpxWebProvider(fetch_provider=delegated)

        result = await provider.fetch("javascript:alert(1)")

        assert "blocked" in result.lower()
        delegated.fetch.assert_not_called()
