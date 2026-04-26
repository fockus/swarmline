"""Provider Resolver module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from swarmline.runtime.model_registry import get_registry

SdkType = Literal["anthropic", "openai_compat", "google"]


@dataclass(frozen=True)
class ResolvedProvider:
    """Resolved Provider implementation."""

    model_id: str
    provider: str
    sdk_type: SdkType
    base_url: str | None


_OPENAI_COMPAT_PROVIDERS: dict[str, str | None] = {
    "openai": None,  # standard OpenAI endpoint
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",  # dev-only default (local Ollama)
    "local": "http://localhost:8000/v1",  # dev-only default (local OpenAI-compat server)
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "deepseek": "https://api.deepseek.com/v1",
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
) -> ResolvedProvider:
    """Resolve provider."""
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
        )

    explicit_provider, model_part = _parse_prefix(raw_model.strip())

    if explicit_provider is not None:
        model_id = model_part
        provider = explicit_provider
    else:
        model_id = registry.resolve(raw_model)
        provider = registry.get_provider(model_id)

    sdk_type = _PROVIDER_SDK_MAP.get(provider, "openai_compat")
    effective_base_url = (
        base_url if base_url is not None else _get_default_base_url(provider)
    )

    return ResolvedProvider(
        model_id=model_id,
        provider=provider,
        sdk_type=sdk_type,
        base_url=effective_base_url,
    )
