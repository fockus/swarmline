"""Integration: ThinRuntime multi-provider dispatch cherez ProviderResolver + LlmAdapter. Mocki - tolko on SDK klienty (vnotshnie servisy), not on nashi moduli.
Verifies full put: config.model -> resolve_provider -> get_cached_adapter -> adapter.call/stream.
"""

from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.runtime.provider_resolver import resolve_provider
from swarmline.runtime.thin.llm_providers import (
    AnthropicAdapter,
    GoogleAdapter,
    OpenAICompatAdapter,
    _adapter_cache,
    create_llm_adapter,
    get_cached_adapter,
)
from swarmline.runtime.types import RuntimeConfig

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clear_adapter_cache():
    """Clear kesh adapterov mezhdu testami."""
    _adapter_cache.clear()
    yield
    _adapter_cache.clear()


def _make_mock_anthropic_module() -> MagicMock:
    mock_module = MagicMock()
    mock_module.AsyncAnthropic.return_value = AsyncMock()
    mock_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
    mock_module.APIConnectionError = type("APIConnectionError", (Exception,), {})
    mock_module.APIStatusError = type("APIStatusError", (Exception,), {})
    return mock_module


def _make_mock_openai_module() -> MagicMock:
    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = AsyncMock()
    return mock_module


def _make_mock_google_module() -> MagicMock:
    mock_module = MagicMock()
    mock_types = MagicMock()
    mock_types.HttpOptions = MagicMock(side_effect=lambda **kwargs: kwargs)
    mock_module.types = mock_types
    mock_module.Client.return_value = MagicMock()
    return mock_module


def _make_mock_google_package(genai_module: MagicMock) -> types.ModuleType:
    google_pkg = types.ModuleType("google")
    google_pkg.genai = genai_module
    return google_pkg


class TestResolverToAdapterIntegration:
    """resolve_provider -> create_llm_adapter -> pravilnyy adapter."""

    def test_anthropic_alias_to_adapter(self) -> None:
        resolved = resolve_provider("sonnet")
        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic_module()}):
            adapter = create_llm_adapter(resolved)
            assert isinstance(adapter, AnthropicAdapter)
            assert resolved.sdk_type == "anthropic"

    def test_openai_prefix_to_adapter(self) -> None:
        resolved = resolve_provider("openai:gpt-4o")
        with patch.dict("sys.modules", {"openai": _make_mock_openai_module()}):
            adapter = create_llm_adapter(resolved)
            assert isinstance(adapter, OpenAICompatAdapter)
            assert adapter._model == "gpt-4o"
            assert adapter._base_url is None

    def test_ollama_prefix_to_adapter_with_base_url(self) -> None:
        resolved = resolve_provider("ollama:llama3")
        with patch.dict("sys.modules", {"openai": _make_mock_openai_module()}):
            adapter = create_llm_adapter(resolved)
            assert isinstance(adapter, OpenAICompatAdapter)
            assert adapter._base_url == "http://localhost:11434/v1"

    def test_openrouter_prefix_to_adapter(self) -> None:
        resolved = resolve_provider("openrouter:meta-llama/llama-3-70b")
        with patch.dict("sys.modules", {"openai": _make_mock_openai_module()}):
            adapter = create_llm_adapter(resolved)
            assert isinstance(adapter, OpenAICompatAdapter)
            assert adapter._base_url == "https://openrouter.ai/api/v1"

    def test_google_prefix_to_adapter(self) -> None:
        resolved = resolve_provider("google:gemini-2.5-pro")
        mock_google = _make_mock_google_module()
        with patch.dict(
            "sys.modules",
            {
                "google.genai": mock_google,
                "google": _make_mock_google_package(mock_google),
            },
        ):
            adapter = create_llm_adapter(resolved)
            assert isinstance(adapter, GoogleAdapter)
            assert adapter._model == "gemini-2.5-pro"

    def test_custom_base_url_overrides_default(self) -> None:
        resolved = resolve_provider("ollama:llama3", base_url="http://myhost:11434/v1")
        with patch.dict("sys.modules", {"openai": _make_mock_openai_module()}):
            adapter = create_llm_adapter(resolved)
            assert isinstance(adapter, OpenAICompatAdapter)
            assert adapter._base_url == "http://myhost:11434/v1"

    def test_google_custom_base_url_reaches_adapter(self) -> None:
        resolved = resolve_provider(
            "google:gemini-2.5-pro",
            base_url="https://proxy.example.com",
        )
        mock_google = _make_mock_google_module()
        with patch.dict(
            "sys.modules",
            {
                "google.genai": mock_google,
                "google": _make_mock_google_package(mock_google),
            },
        ):
            adapter = create_llm_adapter(resolved)
            assert isinstance(adapter, GoogleAdapter)
            assert adapter._base_url == "https://proxy.example.com"
            assert adapter._client is not None


class TestDefaultLlmCallEndToEnd:
    """default_llm_call: full put config -> adapter.call()."""

    @pytest.mark.asyncio
    async def test_anthropic_end_to_end(self) -> None:
        """config(model=sonnet) → AnthropicAdapter → SDK call."""
        from swarmline.runtime.thin.llm_client import default_llm_call

        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "Claude response"
        mock_response.content = [mock_block]

        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")

        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await default_llm_call(
                config,
                [{"role": "user", "content": "hello"}],
                "You are helpful",
            )
            assert result == "Claude response"
            mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_openai_end_to_end(self) -> None:
        """config(model=openai:gpt-4o) → OpenAICompatAdapter → SDK call."""
        from swarmline.runtime.thin.llm_client import default_llm_call

        mock_choice = MagicMock()
        mock_choice.message.content = "GPT response"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        config = RuntimeConfig(runtime_name="thin", model="openai:gpt-4o")

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await default_llm_call(
                config,
                [{"role": "user", "content": "hello"}],
                "You are helpful",
            )
            assert result == "GPT response"
            kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert kwargs["model"] == "gpt-4o"
            # system prompt injected as first message
            assert kwargs["messages"][0] == {
                "role": "system",
                "content": "You are helpful",
            }


class TestAdapterCachingIntegration:
    """get_cached_adapter keshiruet by (model_id, provider, base_url)."""

    def test_cache_hit(self) -> None:
        resolved = resolve_provider("openai:gpt-4o")
        with patch.dict("sys.modules", {"openai": _make_mock_openai_module()}):
            a1 = get_cached_adapter(resolved)
            a2 = get_cached_adapter(resolved)
            assert a1 is a2

    def test_cache_miss_on_different_model(self) -> None:
        r1 = resolve_provider("openai:gpt-4o")
        r2 = resolve_provider("openai:gpt-4o-mini")
        with patch.dict("sys.modules", {"openai": _make_mock_openai_module()}):
            a1 = get_cached_adapter(r1)
            a2 = get_cached_adapter(r2)
            assert a1 is not a2

    def test_cache_miss_on_different_google_base_url(self) -> None:
        r1 = resolve_provider(
            "google:gemini-2.5-pro", base_url="https://proxy-1.example.com"
        )
        r2 = resolve_provider(
            "google:gemini-2.5-pro", base_url="https://proxy-2.example.com"
        )
        mock_google = _make_mock_google_module()
        with patch.dict(
            "sys.modules",
            {
                "google.genai": mock_google,
                "google": _make_mock_google_package(mock_google),
            },
        ):
            a1 = get_cached_adapter(r1)
            a2 = get_cached_adapter(r2)
            assert a1 is not a2
