"""Provider-aware model resolution for DeepAgents runtime."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from swarmline.runtime.model_registry import get_registry
from swarmline.runtime.types import RuntimeErrorData, resolve_model_name

SUPPORTED_DEEPAGENTS_PROVIDERS = frozenset({"anthropic", "openai", "google"})

_PROVIDER_PREFIX_MAP = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "google_genai": "google",
}

_PROVIDER_IMPORTS = {
    "anthropic": ("langchain_anthropic", "ChatAnthropic", "langchain-anthropic"),
    "openai": ("langchain_openai", "ChatOpenAI", "langchain-openai"),
    "google": (
        "langchain_google_genai",
        "ChatGoogleGenerativeAI",
        "langchain-google-genai",
    ),
}


@dataclass(frozen=True)
class DeepAgentsResolvedModel:
    """Model resolution result for DeepAgents runtime."""

    requested_model: str
    model_name: str
    provider: str


class DeepAgentsModelError(RuntimeError):
    """Typed error for provider/model resolution."""

    def __init__(self, error: RuntimeErrorData) -> None:
        super().__init__(error.message)
        self.error = error


def _parse_prefixed_model(raw_model: str | None) -> tuple[str | None, str | None]:
    """Parse provider:model notation."""
    if not raw_model:
        return None, None
    value = raw_model.strip()
    if ":" not in value:
        return None, value
    raw_provider, raw_name = value.split(":", 1)
    provider = _PROVIDER_PREFIX_MAP.get(raw_provider.strip().lower())
    if provider is None:
        raise DeepAgentsModelError(
            RuntimeErrorData(
                kind="capability_unsupported",
                message=(
                    "DeepAgents runtime не поддерживает provider " f"'{raw_provider.strip()}'."
                ),
                recoverable=False,
                details={"provider": raw_provider.strip().lower()},
            )
        )
    return provider, raw_name.strip()


def resolve_deepagents_model(raw_model: str | None) -> DeepAgentsResolvedModel:
    """Resolve the model and provider for DeepAgents runtime."""
    explicit_provider, unprefixed_model = _parse_prefixed_model(raw_model)
    model_name = (
        unprefixed_model
        if explicit_provider is not None and unprefixed_model
        else resolve_model_name(raw_model)
    )

    provider = explicit_provider
    if provider is None:
        provider = get_registry().get_provider(model_name)

    if provider not in SUPPORTED_DEEPAGENTS_PROVIDERS:
        raise DeepAgentsModelError(
            RuntimeErrorData(
                kind="capability_unsupported",
                message=(
                    "DeepAgents runtime пока поддерживает только providers: "
                    "anthropic, openai, google."
                ),
                recoverable=False,
                details={"provider": provider, "model": model_name},
            )
        )

    return DeepAgentsResolvedModel(
        requested_model=raw_model or "",
        model_name=model_name,
        provider=provider,
    )


def _load_provider_class(provider: str) -> type[Any]:
    """Load the provider-specific chat model class."""
    module_name, class_name, package_hint = _PROVIDER_IMPORTS[provider]

    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise DeepAgentsModelError(
            RuntimeErrorData(
                kind="dependency_missing",
                message=(
                    f"Для DeepAgents provider '{provider}' нужен пакет "
                    f"'{package_hint}'. Установите его отдельно."
                ),
                recoverable=False,
                details={"provider": provider, "package": package_hint},
            )
        ) from exc

    if module is None or not hasattr(module, class_name):
        raise DeepAgentsModelError(
            RuntimeErrorData(
                kind="dependency_missing",
                message=(
                    f"Для DeepAgents provider '{provider}' нужен пакет "
                    f"'{package_hint}'. Установите его отдельно."
                ),
                recoverable=False,
                details={"provider": provider, "package": package_hint},
            )
        )

    return getattr(module, class_name)


def build_deepagents_chat_model(
    raw_model: str | None,
    *,
    base_url: str | None = None,
) -> Any:
    """Create a provider-specific chat model for DeepAgents runtime."""
    resolved = resolve_deepagents_model(raw_model)

    if resolved.provider == "google":
        if base_url is not None:
            raise DeepAgentsModelError(
                RuntimeErrorData(
                    kind="capability_unsupported",
                    message=(
                        "DeepAgents google provider path не поддерживает " "base_url override."
                    ),
                    recoverable=False,
                    details={"provider": resolved.provider, "model": resolved.model_name},
                )
            )
    model_class = _load_provider_class(resolved.provider)
    kwargs: dict[str, Any] = {"model": resolved.model_name}

    if resolved.provider == "google":
        return model_class(**kwargs)

    if base_url is not None:
        kwargs["base_url"] = base_url
    return model_class(**kwargs)
