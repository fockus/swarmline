"""Tests for HttpxWebProvider domain allow/block filter.

Covers:
- Allowed domains list (whitelist mode)
- Blocked domains list (blacklist mode)
- Both lists together (blocked takes precedence)
- Subdomain matching (sub.example.com matches example.com)
- Case-insensitive matching
- No filter configured = all pass
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from swarmline.tools.web_httpx import HttpxWebProvider


def _make_provider(
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> HttpxWebProvider:
    """Create HttpxWebProvider with domain filter config and mocked fetch_provider."""
    mock_fetch = AsyncMock()
    mock_fetch.fetch = AsyncMock(return_value="fetched content")
    return HttpxWebProvider(
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
        fetch_provider=mock_fetch,
    )


class TestDomainFilterAllowedList:
    """Allowed domains list — whitelist mode."""

    async def test_fetch_allowed_domain_passes(self) -> None:
        """URL on allowed list succeeds — fetch returns content."""
        provider = _make_provider(allowed_domains=["example.com"])
        result = await provider.fetch("https://example.com/page")
        assert result == "fetched content"

    async def test_fetch_allowed_list_rejects_unlisted(self) -> None:
        """URL NOT on allowed list is rejected with descriptive message."""
        provider = _make_provider(allowed_domains=["example.com"])
        result = await provider.fetch("https://other.com/page")
        assert "blocked" in result.lower()
        assert "other.com" in result.lower()

    async def test_fetch_subdomain_of_allowed_domain_passes(self) -> None:
        """Subdomain of allowed domain matches — sub.example.com allowed when example.com is in list."""
        provider = _make_provider(allowed_domains=["example.com"])
        result = await provider.fetch("https://sub.example.com/page")
        assert result == "fetched content"


class TestDomainFilterBlockedList:
    """Blocked domains list — blacklist mode."""

    async def test_fetch_blocked_domain_rejected(self) -> None:
        """URL on blocked list returns error message."""
        provider = _make_provider(blocked_domains=["evil.com"])
        result = await provider.fetch("https://evil.com/malware")
        assert "blocked" in result.lower()
        assert "evil.com" in result.lower()

    async def test_fetch_blocked_list_allows_unlisted(self) -> None:
        """URL NOT on blocked list passes through normally."""
        provider = _make_provider(blocked_domains=["evil.com"])
        result = await provider.fetch("https://safe.com/page")
        assert result == "fetched content"

    async def test_fetch_subdomain_of_blocked_domain_rejected(self) -> None:
        """Subdomain of blocked domain is also blocked — sub.evil.com blocked when evil.com is in list."""
        provider = _make_provider(blocked_domains=["evil.com"])
        result = await provider.fetch("https://sub.evil.com/page")
        assert "blocked" in result.lower()


class TestDomainFilterBothLists:
    """Both allowed and blocked lists — blocked takes precedence."""

    async def test_fetch_both_lists_blocked_takes_precedence(self) -> None:
        """Domain in both allowed AND blocked lists is rejected — blocked wins."""
        provider = _make_provider(
            allowed_domains=["example.com"],
            blocked_domains=["example.com"],
        )
        result = await provider.fetch("https://example.com/page")
        assert "blocked" in result.lower()

    async def test_fetch_allowed_but_subdomain_blocked(self) -> None:
        """Parent allowed, specific subdomain blocked — blocked wins."""
        provider = _make_provider(
            allowed_domains=["example.com"],
            blocked_domains=["admin.example.com"],
        )
        result = await provider.fetch("https://admin.example.com/secret")
        assert "blocked" in result.lower()

    async def test_fetch_allowed_subdomain_not_blocked_passes(self) -> None:
        """Allowed domain, different subdomain not blocked — passes."""
        provider = _make_provider(
            allowed_domains=["example.com"],
            blocked_domains=["admin.example.com"],
        )
        result = await provider.fetch("https://api.example.com/data")
        assert result == "fetched content"


class TestDomainFilterNoConfig:
    """No filter configured — all domains pass."""

    async def test_fetch_no_filter_passes_all(self) -> None:
        """No allowed/blocked lists configured = all URLs pass."""
        provider = _make_provider()
        result = await provider.fetch("https://anything.com/page")
        assert result == "fetched content"

    async def test_fetch_empty_lists_passes_all(self) -> None:
        """Empty allowed/blocked lists = same as no filter."""
        provider = _make_provider(allowed_domains=[], blocked_domains=[])
        result = await provider.fetch("https://anything.com/page")
        assert result == "fetched content"


class TestDomainFilterCaseInsensitive:
    """Case-insensitive domain matching."""

    @pytest.mark.parametrize(
        ("url", "allowed"),
        [
            ("https://EXAMPLE.COM/page", ["example.com"]),
            ("https://example.com/page", ["EXAMPLE.COM"]),
            ("https://Example.Com/page", ["example.com"]),
            ("https://SUB.EXAMPLE.COM/page", ["example.com"]),
        ],
        ids=[
            "uppercase_url_lowercase_list",
            "lowercase_url_uppercase_list",
            "mixed_case_url",
            "uppercase_subdomain",
        ],
    )
    async def test_fetch_case_insensitive_matching(self, url: str, allowed: list[str]) -> None:
        """Domain matching is case-insensitive for both URL and list entries."""
        provider = _make_provider(allowed_domains=allowed)
        result = await provider.fetch(url)
        assert result == "fetched content"

    async def test_fetch_blocked_case_insensitive(self) -> None:
        """Blocked domain matching is also case-insensitive."""
        provider = _make_provider(blocked_domains=["EVIL.COM"])
        result = await provider.fetch("https://evil.com/page")
        assert "blocked" in result.lower()


class TestDomainFilterEdgeCases:
    """Edge cases for domain filter."""

    async def test_fetch_domain_with_port_matches(self) -> None:
        """URL with port — domain matching ignores port."""
        provider = _make_provider(allowed_domains=["example.com"])
        result = await provider.fetch("https://example.com:8443/page")
        assert result == "fetched content"

    async def test_fetch_invalid_url_rejected(self) -> None:
        """Invalid URL without hostname is handled gracefully."""
        provider = _make_provider(allowed_domains=["example.com"])
        result = await provider.fetch("not-a-url")
        assert "blocked" in result.lower() or "invalid" in result.lower()

    async def test_fetch_domain_filter_before_ssrf_check(self) -> None:
        """Domain filter runs BEFORE SSRF validation (fail fast)."""
        provider = _make_provider(blocked_domains=["evil.com"])
        with patch.object(HttpxWebProvider, "_validate_url") as mock_validate:
            result = await provider.fetch("https://evil.com/page")
            mock_validate.assert_not_called()
        assert "blocked" in result.lower()

    async def test_fetch_exact_domain_does_not_match_suffix(self) -> None:
        """notexample.com should NOT match allowed domain example.com."""
        provider = _make_provider(allowed_domains=["example.com"])
        result = await provider.fetch("https://notexample.com/page")
        assert "blocked" in result.lower()
