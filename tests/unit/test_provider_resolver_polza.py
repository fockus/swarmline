"""Unit tests — polza provider registration in _OPENAI_COMPAT_PROVIDERS."""

from __future__ import annotations

from swarmline.runtime.provider_resolver import resolve_provider


def test_resolve_provider_polza_prefix_resolves_to_openai_compat_with_polza_base_url() -> (
    None
):
    """polza: prefix must resolve to provider=polza, sdk_type=openai_compat, polza base URL."""
    # Arrange / Act
    r = resolve_provider("polza:google/gemini-3.5-flash")
    # Assert
    assert r.provider == "polza"
    assert r.sdk_type == "openai_compat"
    assert r.base_url == "https://polza.ai/api/v1"
    assert r.model_id == "google/gemini-3.5-flash"
