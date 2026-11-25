"""Unit tests — per-config api_key threading end-to-end to OpenAI client.

REQ-PR-1/2: resolve_provider must carry an explicit api_key through to
OpenAICompatAdapter, which must forward it to AsyncOpenAI(**kwargs).
"""

from __future__ import annotations

from swarmline.runtime.provider_resolver import resolve_provider
from swarmline.runtime.thin import llm_providers


def test_resolve_provider_carries_explicit_api_key() -> None:
    """api_key kwarg must be stored in ResolvedProvider.api_key."""
    # Arrange / Act
    r = resolve_provider("polza:google/gemini-3.5-flash", api_key="pza_test_KEY")
    # Assert
    assert r.api_key == "pza_test_KEY"


def test_openai_adapter_passes_api_key_to_client(monkeypatch: object) -> None:
    """OpenAICompatAdapter must pass api_key to AsyncOpenAI constructor."""
    captured: dict = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncOpenAI)  # type: ignore[attr-defined]
    llm_providers.OpenAICompatAdapter(
        model="google/gemini-3.5-flash",
        base_url="https://polza.ai/api/v1",
        api_key="pza_test_KEY",
    )
    assert captured.get("api_key") == "pza_test_KEY"
    assert captured.get("base_url") == "https://polza.ai/api/v1"


def test_openai_adapter_without_api_key_omits_kwarg(monkeypatch: object) -> None:
    """When api_key=None, AsyncOpenAI is called without api_key (uses env OPENAI_API_KEY)."""
    captured: dict = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncOpenAI)  # type: ignore[attr-defined]
    llm_providers.OpenAICompatAdapter(
        model="google/gemini-3.5-flash",
        base_url="https://polza.ai/api/v1",
    )
    assert "api_key" not in captured


def test_resolve_provider_default_api_key_is_none() -> None:
    """Default api_key must be None (back-compat: env-key path unchanged)."""
    r = resolve_provider("polza:google/gemini-3.5-flash")
    assert r.api_key is None


def test_cache_key_differs_for_different_api_keys(monkeypatch: object) -> None:
    """Two different api_keys must produce different cached adapters (4-tuple cache key)."""
    import openai
    from swarmline.runtime.thin.llm_providers import get_cached_adapter, _adapter_cache

    # Clear cache to avoid cross-test pollution
    _adapter_cache.clear()

    call_count = 0

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            nonlocal call_count
            call_count += 1

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncOpenAI)  # type: ignore[attr-defined]

    r1 = resolve_provider("polza:google/gemini-3.5-flash", api_key="key_A")
    r2 = resolve_provider("polza:google/gemini-3.5-flash", api_key="key_B")

    a1 = get_cached_adapter(r1)
    a2 = get_cached_adapter(r2)

    # Different keys → different adapter instances
    assert a1 is not a2
    assert call_count == 2

    # Same key → same cached adapter instance
    a1_again = get_cached_adapter(r1)
    assert a1_again is a1
    assert call_count == 2  # no new construction


def test_anthropic_adapter_passes_api_key_to_client(monkeypatch) -> None:
    """AnthropicAdapter must pass api_key to AsyncAnthropic constructor (B6)."""
    captured: dict = {}

    class _FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import anthropic

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)
    llm_providers.AnthropicAdapter(
        model="claude-sonnet-4-20250514",
        base_url="https://proxy.example/api",
        api_key="sk-ant-test-KEY",
    )
    assert captured.get("api_key") == "sk-ant-test-KEY"
    assert captured.get("base_url") == "https://proxy.example/api"


def test_anthropic_adapter_without_api_key_omits_kwarg(monkeypatch) -> None:
    """When api_key=None, AsyncAnthropic must fall back to env (no api_key kwarg)."""
    captured: dict = {}

    class _FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import anthropic

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)
    llm_providers.AnthropicAdapter(model="claude-sonnet-4-20250514")
    assert "api_key" not in captured


def test_google_adapter_passes_api_key_to_client(monkeypatch) -> None:
    """GoogleAdapter must pass api_key to genai.Client constructor (B6)."""
    captured: dict = {}

    class _FakeGenaiClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import google.genai as genai

    monkeypatch.setattr(genai, "Client", _FakeGenaiClient)
    llm_providers.GoogleAdapter(model="gemini-2.0-flash", api_key="AIza-test-KEY")
    assert captured.get("api_key") == "AIza-test-KEY"


def test_google_adapter_without_api_key_omits_kwarg(monkeypatch) -> None:
    """When api_key=None, genai.Client must fall back to env (no api_key kwarg)."""
    captured: dict = {}

    class _FakeGenaiClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import google.genai as genai

    monkeypatch.setattr(genai, "Client", _FakeGenaiClient)
    llm_providers.GoogleAdapter(model="gemini-2.0-flash")
    assert "api_key" not in captured


def test_create_llm_adapter_wires_api_key_for_anthropic_and_google(monkeypatch) -> None:
    """create_llm_adapter must forward ResolvedProvider.api_key to both adapters."""
    from swarmline.runtime.provider_resolver import ResolvedProvider

    captured_anthropic: dict = {}
    captured_google: dict = {}

    class _FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            captured_anthropic.update(kwargs)

    class _FakeGenaiClient:
        def __init__(self, **kwargs: object) -> None:
            captured_google.update(kwargs)

    import anthropic
    import google.genai as genai

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)
    monkeypatch.setattr(genai, "Client", _FakeGenaiClient)

    llm_providers.create_llm_adapter(
        ResolvedProvider(
            model_id="claude-sonnet-4-20250514",
            provider="anthropic",
            sdk_type="anthropic",
            base_url=None,
            api_key="sk-ant-KEY",
        )
    )
    llm_providers.create_llm_adapter(
        ResolvedProvider(
            model_id="gemini-2.0-flash",
            provider="google",
            sdk_type="google",
            base_url=None,
            api_key="AIza-KEY",
        )
    )

    assert captured_anthropic.get("api_key") == "sk-ant-KEY"
    assert captured_google.get("api_key") == "AIza-KEY"
