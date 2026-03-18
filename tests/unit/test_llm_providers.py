"""Tests for LLM provider adapters - multi-provider support for ThinRuntime."""

from __future__ import annotations

import types
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cognitia.runtime.thin.llm_providers import (
    AnthropicAdapter,
    GoogleAdapter,
    LlmAdapter,
    OpenAICompatAdapter,
    create_llm_adapter,
)
from cognitia.runtime.thin.errors import ThinLlmError
from cognitia.runtime.provider_resolver import ResolvedProvider
from cognitia.runtime.types import RuntimeErrorData


async def _collect_stream(stream: AsyncIterator[str]) -> list[str]:
    """Helper: collect all chunks from an async iterator."""
    return [chunk async for chunk in stream]


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


@pytest.fixture(autouse=True)
def _clear_adapter_cache() -> None:
    from cognitia.runtime.thin.llm_providers import _adapter_cache

    _adapter_cache.clear()
    yield
    _adapter_cache.clear()


# ---------------------------------------------------------------------------
# LlmAdapter protocol
# ---------------------------------------------------------------------------


class TestLlmAdapterProtocol:
    """Vse adaptery realizuyut LlmAdapter protocol."""

    def test_anthropic_is_llm_adapter(self) -> None:
        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic_module()}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            assert isinstance(adapter, LlmAdapter)

    def test_openai_is_llm_adapter(self) -> None:
        with patch.dict("sys.modules", {"openai": _make_mock_openai_module()}):
            adapter = OpenAICompatAdapter(model="gpt-4o")
            assert isinstance(adapter, LlmAdapter)

    def test_google_is_llm_adapter(self) -> None:
        mock_google = _make_mock_google_module()
        with patch.dict(
            "sys.modules",
            {
                "google.genai": mock_google,
                "google": _make_mock_google_package(mock_google),
            },
        ):
            adapter = GoogleAdapter(model="gemini-2.5-pro")
            assert isinstance(adapter, LlmAdapter)


# ---------------------------------------------------------------------------
# AnthropicAdapter
# ---------------------------------------------------------------------------


class TestAnthropicAdapterCall:
    """AnthropicAdapter vyzyvaet anthropic SDK."""

    @pytest.fixture
    def mock_anthropic(self):
        mock_module = MagicMock()
        mock_client = AsyncMock()
        # Response structure
        mock_block = MagicMock()
        mock_block.text = "Hello from Claude"
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_module.AsyncAnthropic.return_value = mock_client
        mock_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
        mock_module.APIConnectionError = type("APIConnectionError", (Exception,), {})
        mock_module.APIStatusError = type("APIStatusError", (Exception,), {})
        return mock_module, mock_client

    @pytest.mark.asyncio
    async def test_call_invokes_messages_create(self, mock_anthropic) -> None:
        mock_module, mock_client = mock_anthropic
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
            )
            mock_client.messages.create.assert_called_once()
            kwargs = mock_client.messages.create.call_args.kwargs
            assert kwargs["model"] == "claude-sonnet-4-20250514"
            assert kwargs["system"] == "test"
            assert result == "Hello from Claude"

    @pytest.mark.asyncio
    async def test_call_with_base_url(self, mock_anthropic) -> None:
        mock_module, mock_client = mock_anthropic
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            AnthropicAdapter(
                model="claude-sonnet-4-20250514",
                base_url="https://proxy.example.com",
            )
            mock_module.AsyncAnthropic.assert_called_with(
                base_url="https://proxy.example.com"
            )

    @pytest.mark.asyncio
    async def test_call_concatenates_multiple_text_blocks(self, mock_anthropic) -> None:
        mock_module, mock_client = mock_anthropic
        block1 = MagicMock()
        block1.text = "Hello "
        block2 = MagicMock()
        block2.text = "world"
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(content=[block1, block2])
        )
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
            )
            assert result == "Hello world"


# ---------------------------------------------------------------------------
# OpenAICompatAdapter
# ---------------------------------------------------------------------------


class TestOpenAICompatAdapterCall:
    """OpenAICompatAdapter vyzyvaet openai SDK."""

    @pytest.fixture
    def mock_openai(self):
        mock_module = MagicMock()
        mock_client = AsyncMock()
        # Response structure
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello from GPT"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_module.AsyncOpenAI.return_value = mock_client
        return mock_module, mock_client

    @pytest.mark.asyncio
    async def test_call_invokes_chat_completions(self, mock_openai) -> None:
        mock_module, mock_client = mock_openai
        with patch.dict("sys.modules", {"openai": mock_module}):
            adapter = OpenAICompatAdapter(model="gpt-4o")
            adapter._client = mock_client
            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
            )
            mock_client.chat.completions.create.assert_called_once()
            kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert kwargs["model"] == "gpt-4o"
            # system prompt as first message
            assert kwargs["messages"][0]["role"] == "system"
            assert kwargs["messages"][0]["content"] == "test"
            assert result == "Hello from GPT"

    @pytest.mark.asyncio
    async def test_call_with_custom_base_url(self, mock_openai) -> None:
        mock_module, mock_client = mock_openai
        with patch.dict("sys.modules", {"openai": mock_module}):
            OpenAICompatAdapter(
                model="llama3",
                base_url="http://localhost:11434/v1",
            )
            call_kwargs = mock_module.AsyncOpenAI.call_args.kwargs
            assert call_kwargs["base_url"] == "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# GoogleAdapter
# ---------------------------------------------------------------------------


class TestGoogleAdapterCall:
    """GoogleAdapter vyzyvaet google-genai SDK."""

    @pytest.fixture
    def mock_google(self):
        mock_module = MagicMock()
        mock_types = MagicMock()
        mock_types.HttpOptions = MagicMock(side_effect=lambda **kwargs: kwargs)
        mock_module.types = mock_types
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello from Gemini"
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)
        mock_module.Client.return_value = mock_client
        return mock_module, mock_client

    @pytest.mark.asyncio
    async def test_call_invokes_generate_content(self, mock_google) -> None:
        mock_module, mock_client = mock_google
        with patch.dict(
            "sys.modules",
            {"google.genai": mock_module, "google": _make_mock_google_package(mock_module)},
        ):
            adapter = GoogleAdapter(model="gemini-2.5-pro")
            adapter._client = mock_client
            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
            )
            assert result == "Hello from Gemini"

    def test_call_with_custom_base_url(self, mock_google) -> None:
        mock_module, _mock_client = mock_google
        with patch.dict(
            "sys.modules",
            {"google.genai": mock_module, "google": _make_mock_google_package(mock_module)},
        ):
            GoogleAdapter(
                model="gemini-2.5-pro",
                base_url="https://proxy.example.com",
            )
            call_kwargs = mock_module.Client.call_args.kwargs
            assert call_kwargs["http_options"]["base_url"] == "https://proxy.example.com"

    def test_call_without_base_url_keeps_default_constructor(self, mock_google) -> None:
        mock_module, _mock_client = mock_google
        with patch.dict(
            "sys.modules",
            {"google.genai": mock_module, "google": _make_mock_google_package(mock_module)},
        ):
            GoogleAdapter(model="gemini-2.5-pro")
            assert mock_module.Client.call_args.kwargs == {}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestCreateLlmAdapter:
    """create_llm_adapter() dispatches by sdk_type."""

    def test_anthropic_type(self) -> None:
        resolved = ResolvedProvider("claude-sonnet-4-20250514", "anthropic", "anthropic", None)
        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic_module()}):
            adapter = create_llm_adapter(resolved)
            assert isinstance(adapter, AnthropicAdapter)

    def test_openai_compat_type(self) -> None:
        resolved = ResolvedProvider("gpt-4o", "openai", "openai_compat", None)
        with patch.dict("sys.modules", {"openai": _make_mock_openai_module()}):
            adapter = create_llm_adapter(resolved)
            assert isinstance(adapter, OpenAICompatAdapter)

    def test_google_type(self) -> None:
        resolved = ResolvedProvider("gemini-2.5-pro", "google", "google", None)
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

    def test_openai_compat_with_base_url(self) -> None:
        resolved = ResolvedProvider("llama3", "ollama", "openai_compat", "http://localhost:11434/v1")
        with patch.dict("sys.modules", {"openai": _make_mock_openai_module()}):
            adapter = create_llm_adapter(resolved)
            assert isinstance(adapter, OpenAICompatAdapter)
            assert adapter._base_url == "http://localhost:11434/v1"

    def test_unknown_sdk_type_raises(self) -> None:
        resolved = ResolvedProvider("x", "x", "unknown", None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="sdk_type"):
            create_llm_adapter(resolved)


# ---------------------------------------------------------------------------
# Missing packages
# ---------------------------------------------------------------------------


class TestMissingPackageErrors:
    """Ponyatnye errors pri otsutstvii SDK paketov."""

    def test_missing_anthropic_package(self) -> None:
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(ThinLlmError, match=r"cognitia\[thin\]") as exc:
                AnthropicAdapter(model="claude-sonnet-4-20250514")
        assert exc.value.error.kind == "dependency_missing"

    def test_missing_openai_package(self) -> None:
        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(ThinLlmError, match=r"cognitia\[thin\]") as exc:
                OpenAICompatAdapter(model="gpt-4o")
        assert exc.value.error.kind == "dependency_missing"

    def test_missing_google_package(self) -> None:
        with patch.dict("sys.modules", {"google.genai": None, "google": None}):
            with pytest.raises(ThinLlmError, match=r"cognitia\[thin\]") as exc:
                GoogleAdapter(model="gemini-2.5-pro")
        assert exc.value.error.kind == "dependency_missing"


# ---------------------------------------------------------------------------
# default_llm_call — multi-provider dispatch
# ---------------------------------------------------------------------------


class TestAdapterCaching:
    """create_llm_adapter keshiruet adaptery by (model_id, provider, base_url)."""

    def test_same_provider_returns_cached(self) -> None:
        """Odin and tot zhe ResolvedProvider -> tot zhe adapter."""
        from cognitia.runtime.thin.llm_providers import get_cached_adapter

        r1 = ResolvedProvider("claude-sonnet-4-20250514", "anthropic", "anthropic", None)
        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic_module()}):
            a1 = get_cached_adapter(r1)
            a2 = get_cached_adapter(r1)
            assert a1 is a2

    def test_different_model_returns_new(self) -> None:
        """Raznye model_id -> raznye adaptery."""
        from cognitia.runtime.thin.llm_providers import get_cached_adapter

        r1 = ResolvedProvider("claude-sonnet-4-20250514", "anthropic", "anthropic", None)
        r2 = ResolvedProvider("claude-opus-4-20250514", "anthropic", "anthropic", None)
        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic_module()}):
            a1 = get_cached_adapter(r1)
            a2 = get_cached_adapter(r2)
            assert a1 is not a2

    def test_different_base_url_returns_new(self) -> None:
        """Raznye base_url -> raznye adaptery."""
        from cognitia.runtime.thin.llm_providers import get_cached_adapter

        r1 = ResolvedProvider("gpt-4o", "openai", "openai_compat", None)
        r2 = ResolvedProvider("gpt-4o", "openai", "openai_compat", "https://proxy.com/v1")
        with patch.dict("sys.modules", {"openai": _make_mock_openai_module()}):
            a1 = get_cached_adapter(r1)
            a2 = get_cached_adapter(r2)
            assert a1 is not a2


class TestDefaultLlmCallDispatch:
    """default_llm_call() ispolzuet ProviderResolver + create_llm_adapter."""

    @pytest.mark.asyncio
    async def test_anthropic_model_dispatches_to_adapter(self) -> None:
        """Anthropic model -> AnthropicAdapter.call()."""
        from cognitia.runtime.thin.llm_client import default_llm_call
        from cognitia.runtime.types import RuntimeConfig

        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")
        with patch(
            "cognitia.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory:
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            result = await default_llm_call(
                config,
                [{"role": "user", "content": "hi"}],
                "system",
            )
            mock_factory.assert_called_once()
            mock_adapter.call.assert_called_once()
            assert result == "response"

    @pytest.mark.asyncio
    async def test_openai_model_dispatches_correctly(self) -> None:
        """OpenAI model cherez prefix -> OpenAICompatAdapter."""
        from cognitia.runtime.thin.llm_client import default_llm_call
        from cognitia.runtime.types import RuntimeConfig

        config = RuntimeConfig(runtime_name="thin", model="openai:gpt-4o")
        with patch(
            "cognitia.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory:
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="gpt response")
            mock_factory.return_value = mock_adapter

            result = await default_llm_call(
                config,
                [{"role": "user", "content": "hi"}],
                "system",
            )
            assert result == "gpt response"

    @pytest.mark.asyncio
    async def test_base_url_passed_to_resolver(self) -> None:
        """config.base_url peredaetsya in resolve_provider()."""
        from cognitia.runtime.thin.llm_client import default_llm_call
        from cognitia.runtime.types import RuntimeConfig

        config = RuntimeConfig(
            runtime_name="thin",
            model="gpt-4o",
            base_url="https://proxy.example.com/v1",
        )
        with patch(
            "cognitia.runtime.thin.llm_client.resolve_provider"
        ) as mock_resolve, patch(
            "cognitia.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory:
            mock_resolve.return_value = ResolvedProvider(
                "gpt-4o", "openai", "openai_compat", "https://proxy.example.com/v1"
            )
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="ok")
            mock_factory.return_value = mock_adapter

            await default_llm_call(
                config,
                [{"role": "user", "content": "hi"}],
                "system",
            )
            mock_resolve.assert_called_once_with(
                "gpt-4o", base_url="https://proxy.example.com/v1"
            )

    @pytest.mark.asyncio
    async def test_adapter_error_raises_typed_runtime_crash(self) -> None:
        """Error adaptera -> ThinLlmError(kind=runtime_crash)."""
        from cognitia.runtime.thin.llm_client import default_llm_call
        from cognitia.runtime.types import RuntimeConfig

        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")
        with patch(
            "cognitia.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory:
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(side_effect=Exception("API Error"))
            mock_factory.return_value = mock_adapter

            with pytest.raises(ThinLlmError, match="Ошибка LLM API") as exc:
                await default_llm_call(
                    config,
                    [{"role": "user", "content": "hi"}],
                    "system",
                )
        assert exc.value.error.kind == "runtime_crash"


# ---------------------------------------------------------------------------
# Streaming — LlmAdapter.stream()
# ---------------------------------------------------------------------------


class TestAnthropicAdapterStream:
    """AnthropicAdapter.stream() yields text chunks."""

    @pytest.fixture
    def mock_anthropic_stream(self):
        mock_module = MagicMock()
        mock_client = AsyncMock()

        # Simulate streaming: async context manager → text_stream
        async def _text_stream():
            yield "Hello "
            yield "from "
            yield "Claude"

        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_stream_cm)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)
        mock_stream_cm.text_stream = _text_stream()

        mock_client.messages.stream = MagicMock(return_value=mock_stream_cm)
        mock_module.AsyncAnthropic.return_value = mock_client
        mock_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
        mock_module.APIConnectionError = type("APIConnectionError", (Exception,), {})
        mock_module.APIStatusError = type("APIStatusError", (Exception,), {})
        return mock_module, mock_client, mock_stream_cm

    @pytest.mark.asyncio
    async def test_stream_yields_text_chunks(self, mock_anthropic_stream) -> None:
        mock_module, mock_client, mock_stream_cm = mock_anthropic_stream
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            chunks = await _collect_stream(
                adapter.stream(
                    messages=[{"role": "user", "content": "hi"}],
                    system_prompt="test",
                )
            )
            assert chunks == ["Hello ", "from ", "Claude"]
            mock_client.messages.stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_passes_model_and_system(self, mock_anthropic_stream) -> None:
        mock_module, mock_client, mock_stream_cm = mock_anthropic_stream
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            # Consume stream
            async for _ in adapter.stream(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="sys prompt",
            ):
                pass
            kwargs = mock_client.messages.stream.call_args.kwargs
            assert kwargs["model"] == "claude-sonnet-4-20250514"
            assert kwargs["system"] == "sys prompt"


class TestOpenAICompatAdapterStream:
    """OpenAICompatAdapter.stream() yields text chunks."""

    @pytest.fixture
    def mock_openai_stream(self):
        mock_module = MagicMock()
        mock_client = AsyncMock()

        # OpenAI streaming: response is async iterable of chunks
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "Hello "

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = "from GPT"

        chunk3 = MagicMock()
        chunk3.choices = [MagicMock()]
        chunk3.choices[0].delta.content = None  # final chunk

        async def _aiter_chunks():
            yield chunk1
            yield chunk2
            yield chunk3

        mock_client.chat.completions.create = AsyncMock(return_value=_aiter_chunks())
        mock_module.AsyncOpenAI.return_value = mock_client
        return mock_module, mock_client

    @pytest.mark.asyncio
    async def test_stream_yields_text_chunks(self, mock_openai_stream) -> None:
        mock_module, mock_client = mock_openai_stream
        with patch.dict("sys.modules", {"openai": mock_module}):
            adapter = OpenAICompatAdapter(model="gpt-4o")
            adapter._client = mock_client
            chunks = await _collect_stream(
                adapter.stream(
                    messages=[{"role": "user", "content": "hi"}],
                    system_prompt="test",
                )
            )
            assert chunks == ["Hello ", "from GPT"]

    @pytest.mark.asyncio
    async def test_stream_passes_stream_true(self, mock_openai_stream) -> None:
        mock_module, mock_client = mock_openai_stream
        with patch.dict("sys.modules", {"openai": mock_module}):
            adapter = OpenAICompatAdapter(model="gpt-4o")
            adapter._client = mock_client
            async for _ in adapter.stream(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
            ):
                pass
            kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert kwargs["stream"] is True


class TestGoogleAdapterStream:
    """GoogleAdapter.stream() yields text chunks."""

    @pytest.fixture
    def mock_google_stream(self):
        mock_module = MagicMock()
        mock_client = MagicMock()

        # Google streaming: response is async iterable of chunks with .text
        chunk1 = MagicMock()
        chunk1.text = "Hello "
        chunk2 = MagicMock()
        chunk2.text = "from Gemini"

        async def _aiter_chunks():
            yield chunk1
            yield chunk2

        mock_client.models.generate_content_stream = AsyncMock(return_value=_aiter_chunks())
        mock_module.Client.return_value = mock_client
        return mock_module, mock_client

    @pytest.mark.asyncio
    async def test_stream_yields_text_chunks(self, mock_google_stream) -> None:
        mock_module, mock_client = mock_google_stream
        with patch.dict(
            "sys.modules",
            {"google.genai": mock_module, "google": _make_mock_google_package(mock_module)},
        ):
            adapter = GoogleAdapter(model="gemini-2.5-pro")
            adapter._client = mock_client
            chunks = await _collect_stream(
                adapter.stream(
                    messages=[{"role": "user", "content": "hi"}],
                    system_prompt="test",
                )
            )
            assert chunks == ["Hello ", "from Gemini"]


# ---------------------------------------------------------------------------
# try_stream_llm_call with adapter.stream()
# ---------------------------------------------------------------------------


class TestDefaultLlmCallStreaming:
    """default_llm_call with stream=True -> adapter.stream()."""

    @pytest.mark.asyncio
    async def test_stream_true_returns_async_iterator(self) -> None:
        from cognitia.runtime.thin.llm_client import default_llm_call
        from cognitia.runtime.types import RuntimeConfig

        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")

        async def _fake_stream(*a, **kw):
            yield "chunk1"
            yield "chunk2"

        with patch(
            "cognitia.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory:
            mock_adapter = MagicMock()
            mock_adapter.stream = MagicMock(return_value=_fake_stream())
            mock_factory.return_value = mock_adapter

            result = await default_llm_call(
                config,
                [{"role": "user", "content": "hi"}],
                "system",
                stream=True,
            )
            # Should return async iterator, not string
            assert hasattr(result, "__aiter__")
            chunks = [c async for c in result]
            assert chunks == ["chunk1", "chunk2"]

    @pytest.mark.asyncio
    async def test_stream_false_returns_string(self) -> None:
        from cognitia.runtime.thin.llm_client import default_llm_call
        from cognitia.runtime.types import RuntimeConfig

        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")
        with patch(
            "cognitia.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory:
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            result = await default_llm_call(
                config,
                [{"role": "user", "content": "hi"}],
                "system",
            )
            assert isinstance(result, str)
            assert result == "response"

    @pytest.mark.asyncio
    async def test_stream_init_failure_raises_typed_error(self) -> None:
        from cognitia.runtime.thin.llm_client import default_llm_call
        from cognitia.runtime.types import RuntimeConfig

        config = RuntimeConfig(runtime_name="thin", model="google:gemini-2.5-pro")
        thin_error = ThinLlmError(
            RuntimeErrorData(
                kind="dependency_missing",
                message="google-genai SDK не установлен. Установите: pip install cognitia[thin]",
                recoverable=False,
            )
        )
        with patch(
            "cognitia.runtime.thin.llm_client.get_cached_adapter",
            side_effect=thin_error,
        ):
            with pytest.raises(ThinLlmError, match="google-genai SDK"):
                await default_llm_call(
                    config,
                    [{"role": "user", "content": "hi"}],
                    "system",
                    stream=True,
                )


class TestTryStreamLlmCallWithAdapter:
    """try_stream_llm_call uses adapter.stream() when available."""

    @pytest.mark.asyncio
    async def test_try_stream_uses_adapter_stream(self) -> None:
        """try_stream_llm_call should use adapter-based streaming."""
        from cognitia.runtime.thin.llm_client import try_stream_llm_call

        async def _fake_stream():
            yield "chunk1"
            yield "chunk2"

        mock_llm_call = AsyncMock(return_value=_fake_stream())

        result = await try_stream_llm_call(
            mock_llm_call,
            [{"role": "user", "content": "hi"}],
            "system",
        )
        assert result is not None
        chunks, full = result
        assert chunks == ["chunk1", "chunk2"]
        assert full == "chunk1chunk2"

    @pytest.mark.asyncio
    async def test_try_stream_propagates_typed_thin_error(self) -> None:
        """ThinLlmError not should maskirovatsya kak uspeshnyy stream."""
        from cognitia.runtime.thin.llm_client import try_stream_llm_call

        thin_error = ThinLlmError(
            RuntimeErrorData(
                kind="dependency_missing",
                message="openai SDK не установлен. Установите: pip install cognitia[thin]",
                recoverable=False,
            )
        )
        mock_llm_call = AsyncMock(side_effect=thin_error)

        with pytest.raises(ThinLlmError, match="openai SDK"):
            await try_stream_llm_call(
                mock_llm_call,
                [{"role": "user", "content": "hi"}],
                "system",
            )
