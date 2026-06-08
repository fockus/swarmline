"""Provider Resolver module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from swarmline.errors import UnknownModelError
from swarmline.runtime.model_registry import get_registry

SdkType = Literal["anthropic", "openai_compat", "google"]


@dataclass(frozen=True)
class ResolvedProvider:
    """Resolved Provider implementation."""

    model_id: str
    provider: str
    sdk_type: SdkType
    base_url: str | None
    api_key: str | None = None


_OPENAI_COMPAT_PROVIDERS: dict[str, str | None] = {
    "openai": None,  # standard OpenAI endpoint
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",  # dev-only default (local Ollama)
    "local": "http://localhost:8000/v1",  # dev-only default (local OpenAI-compat server)
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "polza": "https://polza.ai/api/v1",
}

# Provider -> SDK type
_PROVIDER_SDK_MAP: dict[str, SdkType] = {
    "anthropic": "anthropic",
    "google": "google",
    **{provider: "openai_compat" for provider in _OPENAI_COMPAT_PROVIDERS},
}


def _parse_prefix(raw: str) -> tuple[str | None, str]:
    """Parse prefix."""
    if ":" not in raw:
        return None, raw

    prefix, model_part = raw.split(":", 1)
    normalized = prefix.strip().lower()

    # google_genai → google
    if normalized == "google_genai":
        normalized = "google"

    if normalized in _PROVIDER_SDK_MAP:
        return normalized, model_part.strip()

    return None, raw


def _get_default_base_url(provider: str) -> str | None:
    """Get default base url."""
    return _OPENAI_COMPAT_PROVIDERS.get(provider)


def resolve_provider(
    raw_model: str | None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ResolvedProvider:
    """Resolve provider.

    Parameters
    ----------
    raw_model:
        Raw model slug, optionally prefixed with a provider name (e.g. ``polza:google/gemini-3.5-flash``).
    base_url:
        Override the provider's default base URL.  ``None`` uses the registered default.
    api_key:
        Per-config API key.  ``None`` means the adapter will fall back to the environment
        variable ``OPENAI_API_KEY`` (back-compat default).
    """
    registry = get_registry()

    if not raw_model or not raw_model.strip():
        default = registry.default_model
        provider = registry.get_provider(default)
        sdk_type = _PROVIDER_SDK_MAP.get(provider, "openai_compat")
        return ResolvedProvider(
            model_id=default,
            provider=provider,
            sdk_type=sdk_type,
            base_url=base_url,
            api_key=api_key,
        )

    explicit_provider, model_part = _parse_prefix(raw_model.strip())

    if explicit_provider is not None:
        model_id = model_part
        provider = explicit_provider
    elif registry.is_known(raw_model):
        model_id = registry.resolve(raw_model)
        provider = registry.get_provider(model_id)
    elif base_url is not None:
        # No provider prefix but an explicit base_url => an OpenAI-compatible custom endpoint
        # (OpenRouter / Together / vLLM / a proxy). Honor it and pass the slug through
        # unchanged, instead of ignoring base_url and silently substituting the registry
        # default (which routed unknown slugs to anthropic/claude-sonnet).
        return ResolvedProvider(
            model_id=raw_model.strip(),
            provider="openai_compat",
            sdk_type="openai_compat",
            base_url=base_url,
            api_key=api_key,
        )
    else:
        # No prefix, unknown slug, no base_url: FAIL LOUD instead of silently substituting the
        # default model+provider (the historical footgun). A typo or a missing provider prefix
        # must surface immediately rather than billing a different model.
        raise UnknownModelError(raw_model)

    sdk_type = _PROVIDER_SDK_MAP.get(provider, "openai_compat")
    effective_base_url = base_url if base_url is not None else _get_default_base_url(provider)

    return ResolvedProvider(
        model_id=model_id,
        provider=provider,
        sdk_type=sdk_type,
        base_url=effective_base_url,
        api_key=api_key,
    )
