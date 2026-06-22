"""Tests for ProviderResolver - shared provider resolution for vseh runtaymov."""

from __future__ import annotations

import pytest

from swarmline.errors import SwarmlineError, UnknownModelError
from swarmline.runtime.provider_resolver import (
    ResolvedProvider,
    resolve_provider,
)


class TestResolveProviderAnthropicByAlias:
    """Anthropic models rezolvyatsya cherez alias from ModelRegistry."""

    def test_resolve_sonnet_alias(self) -> None:
        r = resolve_provider("sonnet")
        assert r.provider == "anthropic"
        assert r.sdk_type == "anthropic"
        assert r.model_id == "claude-sonnet-4-20250514"
        assert r.base_url is None

    def test_resolve_opus_alias(self) -> None:
        r = resolve_provider("opus")
        assert r.provider == "anthropic"
        assert r.sdk_type == "anthropic"
        assert r.model_id == "claude-opus-4-20250514"

    def test_resolve_haiku_alias(self) -> None:
        r = resolve_provider("haiku")
        assert r.provider == "anthropic"
        assert r.sdk_type == "anthropic"


class TestResolveProviderWithExplicitPrefix:
    """Explicit 'provider:model' notation."""

    def test_openai_prefix(self) -> None:
        r = resolve_provider("openai:gpt-4o")
        assert r.provider == "openai"
        assert r.sdk_type == "openai_compat"
        assert r.model_id == "gpt-4o"
        assert r.base_url is None

    def test_anthropic_prefix(self) -> None:
        r = resolve_provider("anthropic:claude-sonnet-4-20250514")
        assert r.provider == "anthropic"
        assert r.sdk_type == "anthropic"
        assert r.model_id == "claude-sonnet-4-20250514"

    def test_google_prefix(self) -> None:
        r = resolve_provider("google:gemini-2.5-pro")
        assert r.provider == "google"
        assert r.sdk_type == "google"
        assert r.model_id == "gemini-2.5-pro"


class TestResolveProviderOpenRouterAutoBaseUrl:
    """OpenRouter avtomaticheski gets base_url."""

    def test_openrouter_prefix(self) -> None:
        r = resolve_provider("openrouter:meta-llama/llama-3-70b")
        assert r.provider == "openrouter"
        assert r.sdk_type == "openai_compat"
        assert r.model_id == "meta-llama/llama-3-70b"
        assert r.base_url == "https://openrouter.ai/api/v1"


class TestResolveProviderOllamaAutoBaseUrl:
    """Ollama avtomaticheski gets localhost base_url."""

    def test_ollama_prefix(self) -> None:
        r = resolve_provider("ollama:llama3")
        assert r.provider == "ollama"
        assert r.sdk_type == "openai_compat"
        assert r.model_id == "llama3"
        assert r.base_url == "http://localhost:11434/v1"


class TestResolveProviderCustomBaseUrl:
    """Custom base_url overwrites auto-detected."""

    def test_custom_overrides_default(self) -> None:
        r = resolve_provider("openrouter:llama3", base_url="https://my-proxy.com/v1")
        assert r.base_url == "https://my-proxy.com/v1"

    def test_custom_base_url_for_openai(self) -> None:
        r = resolve_provider("openai:gpt-4o", base_url="https://proxy.example.com/v1")
        assert r.base_url == "https://proxy.example.com/v1"

    def test_custom_base_url_for_anthropic(self) -> None:
        r = resolve_provider(
            "anthropic:claude-sonnet-4-20250514", base_url="https://proxy.com"
        )
        assert r.base_url == "https://proxy.com"


class TestResolveProviderGoogleSpecifics:
    """Google: sdk_type=google, aliasy work."""

    def test_gemini_alias(self) -> None:
        r = resolve_provider("gemini")
        assert r.provider == "google"
        assert r.sdk_type == "google"

    def test_flash_alias(self) -> None:
        r = resolve_provider("flash")
        assert r.provider == "google"
        assert r.sdk_type == "google"


class TestResolveProviderDeepSeek:
    """DeepSeek ispolzuet openai_compat SDK."""

    def test_deepseek_uses_openai_compat(self) -> None:
        r = resolve_provider("deepseek-chat")
        assert r.provider == "deepseek"
        assert r.sdk_type == "openai_compat"

    def test_deepseek_r1_alias(self) -> None:
        r = resolve_provider("r1")
        assert r.provider == "deepseek"
        assert r.sdk_type == "openai_compat"


class TestResolveProviderOpenAICompatProviders:
    """Provaydery with openai-compatible API."""

    def test_together_prefix(self) -> None:
        r = resolve_provider("together:meta-llama/Meta-Llama-3-70B")
        assert r.sdk_type == "openai_compat"
        assert r.base_url == "https://api.together.xyz/v1"

    def test_groq_prefix(self) -> None:
        r = resolve_provider("groq:llama-3.3-70b-versatile")
        assert r.sdk_type == "openai_compat"
        assert r.base_url == "https://api.groq.com/openai/v1"

    def test_fireworks_prefix(self) -> None:
        r = resolve_provider("fireworks:accounts/fireworks/models/llama-v3-70b")
        assert r.sdk_type == "openai_compat"
        assert r.base_url == "https://api.fireworks.ai/inference/v1"

    def test_local_prefix(self) -> None:
        r = resolve_provider("local:my-model")
        assert r.sdk_type == "openai_compat"
        assert r.base_url == "http://localhost:8000/v1"


class TestResolveProviderDefaultModel:
    """None ili empty string -> default model."""

    def test_none_returns_default(self) -> None:
        r = resolve_provider(None)
        assert r.model_id == "claude-sonnet-4-20250514"
        assert r.provider == "anthropic"

    def test_empty_string_returns_default(self) -> None:
        r = resolve_provider("")
        assert r.model_id == "claude-sonnet-4-20250514"
        assert r.provider == "anthropic"


class TestResolveProviderUnknownModel:
    """Unknown model WITHOUT a provider prefix: FAIL LOUD instead of silent substitution.

    Previously an unrecognized bare slug silently became the registry default
    (claude-sonnet-4 / anthropic) — so a typo or a missing ``provider:`` prefix routed to a
    completely different model+provider than intended (wrong billing / confusing auth error).
    It now raises ``UnknownModelError`` so the misconfiguration surfaces immediately.
    """

    def test_unknown_model_no_prefix_no_base_url_raises(self) -> None:
        with pytest.raises(UnknownModelError):
            resolve_provider("nonexistent-model-xyz")

    def test_unknown_model_error_is_a_swarmline_error_and_value_error(self) -> None:
        """Catchable both as ``SwarmlineError`` (lib-wide) and as ``ValueError`` (bad arg)."""
        with pytest.raises(SwarmlineError):
            resolve_provider("nonexistent-model-xyz")
        with pytest.raises(ValueError):
            resolve_provider("nonexistent-model-xyz")

    def test_unknown_model_error_message_names_the_slug(self) -> None:
        """The message includes the offending slug so the misconfig is obvious."""
        with pytest.raises(UnknownModelError) as exc_info:
            resolve_provider("nonexistent-model-xyz")
        assert "nonexistent-model-xyz" in str(exc_info.value)


class TestResolveProviderHonorsExplicitBaseUrlForUnknownSlug:
    """No provider prefix + an explicit ``base_url`` => OpenAI-compatible custom endpoint.

    A custom ``base_url`` without a provider prefix means an OpenAI-compatible server
    (OpenRouter / Together / vLLM / a proxy). Honor it: route through ``openai_compat`` and
    pass the slug through unchanged, instead of ignoring ``base_url`` and silently
    substituting the anthropic default. Safety net for callers who pass ``base_url`` but
    forget the ``openrouter:`` prefix.
    """

    def test_unknown_slug_with_base_url_routes_openai_compat(self) -> None:
        r = resolve_provider(
            "google/gemini-3.5-flash", base_url="https://openrouter.ai/api/v1"
        )
        assert r.sdk_type == "openai_compat"
        assert r.provider == "openai_compat"
        assert r.model_id == "google/gemini-3.5-flash"
        assert r.base_url == "https://openrouter.ai/api/v1"

    def test_known_alias_with_base_url_keeps_its_native_provider(self) -> None:
        """Honoring ``base_url`` must NOT hijack a KNOWN model: 'sonnet' stays anthropic."""
        r = resolve_provider("sonnet", base_url="https://proxy.example.com/v1")
        assert r.provider == "anthropic"
        assert r.sdk_type == "anthropic"
        assert r.base_url == "https://proxy.example.com/v1"


class TestResolvedProviderDataclass:
    """ResolvedProvider — frozen dataclass."""

    def test_frozen(self) -> None:
        r = ResolvedProvider(
            model_id="gpt-4o",
            provider="openai",
            sdk_type="openai_compat",
            base_url=None,
        )
        with pytest.raises(AttributeError):
            r.model_id = "gpt-4o-mini"  # type: ignore[misc]

    def test_equality(self) -> None:
        r1 = ResolvedProvider("gpt-4o", "openai", "openai_compat", None)
        r2 = ResolvedProvider("gpt-4o", "openai", "openai_compat", None)
        assert r1 == r2
