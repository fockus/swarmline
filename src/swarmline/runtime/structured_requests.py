"""Provider-native structured request planning for ThinRuntime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from swarmline.runtime.provider_resolver import resolve_provider
from swarmline.runtime.structured_output import normalize_output_schema
from swarmline.runtime.types import ModelRequestOptions, RuntimeConfig

StructuredRequestMode = Literal["none", "prompt", "native_json_schema", "native_json_object"]


@dataclass(frozen=True)
class ProviderStructuredCapabilities:
    """Structured output capabilities for a provider."""

    json_schema: bool = False
    json_object: bool = False
    unsupported_schema_keywords: frozenset[str] = frozenset()
    default_provider_options: dict[str, Any] = field(default_factory=dict)
    default_plugins: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class StructuredRequestStrategy:
    """Resolved structured-output strategy for one runtime call."""

    mode: StructuredRequestMode
    provider: str
    model: str

    @property
    def is_native(self) -> bool:
        return self.mode in {"native_json_schema", "native_json_object"}


_SCHEMA_VALIDATION_ONLY_KEYWORDS = frozenset(
    {"minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength"}
)

_PROVIDER_CAPABILITIES: dict[str, ProviderStructuredCapabilities] = {
    "openai": ProviderStructuredCapabilities(json_schema=True, json_object=True),
    "openrouter": ProviderStructuredCapabilities(
        json_schema=True,
        json_object=True,
        unsupported_schema_keywords=_SCHEMA_VALIDATION_ONLY_KEYWORDS,
        default_provider_options={"require_parameters": True},
    ),
    "deepseek": ProviderStructuredCapabilities(json_schema=False, json_object=True),
    "anthropic": ProviderStructuredCapabilities(),
    "google": ProviderStructuredCapabilities(),
    "ollama": ProviderStructuredCapabilities(json_object=True),
    "local": ProviderStructuredCapabilities(json_object=True),
    "together": ProviderStructuredCapabilities(json_object=True),
    "groq": ProviderStructuredCapabilities(json_object=True),
    "fireworks": ProviderStructuredCapabilities(json_object=True),
}


def get_provider_structured_capabilities(provider: str) -> ProviderStructuredCapabilities:
    """Return structured-output capabilities for a provider."""
    return _PROVIDER_CAPABILITIES.get(provider, ProviderStructuredCapabilities())


def resolve_structured_request_strategy(config: RuntimeConfig) -> StructuredRequestStrategy:
    """Resolve structured-output strategy for the current provider/model."""
    if config.output_format is None and config.output_type is None:
        return StructuredRequestStrategy("none", "", str(config.model))
    if config.structured_mode == "prompt":
        return StructuredRequestStrategy("prompt", "", str(config.model))

    resolved = resolve_provider(config.model, base_url=config.base_url)
    capabilities = get_provider_structured_capabilities(resolved.provider)
    if capabilities.json_schema:
        return StructuredRequestStrategy("native_json_schema", resolved.provider, resolved.model_id)
    if capabilities.json_object:
        return StructuredRequestStrategy("native_json_object", resolved.provider, resolved.model_id)
    if config.structured_mode == "auto":
        return StructuredRequestStrategy("prompt", resolved.provider, resolved.model_id)

    msg = (
        f"Provider '{resolved.provider}' does not support native structured output "
        f"for model '{resolved.model_id}'."
    )
    raise ValueError(msg)


def build_llm_call_kwargs(config: RuntimeConfig) -> dict[str, Any]:
    """Build provider-neutral kwargs for the next LLM call."""
    kwargs = _request_options_to_kwargs(config.request_options)
    strategy = resolve_structured_request_strategy(config)

    if strategy.mode == "native_json_schema" and "response_format" not in kwargs:
        kwargs["response_format"] = _build_json_schema_response_format(config, strategy.provider)
    elif strategy.mode == "native_json_object" and "response_format" not in kwargs:
        kwargs["response_format"] = {"type": "json_object"}

    capabilities = get_provider_structured_capabilities(strategy.provider)
    extra_body = dict(kwargs.pop("extra_body", {}) or {})
    if capabilities.default_provider_options:
        extra_body.setdefault("provider", dict(capabilities.default_provider_options))
    if capabilities.default_plugins:
        extra_body.setdefault("plugins", list(capabilities.default_plugins))

    if config.request_options is not None:
        if config.request_options.provider_options:
            extra_body["provider"] = {
                **extra_body.get("provider", {}),
                **config.request_options.provider_options,
            }
        if config.request_options.plugins:
            extra_body["plugins"] = list(config.request_options.plugins)

    if extra_body:
        kwargs["extra_body"] = extra_body
    kwargs["_swarmline_structured_strategy"] = strategy.mode
    return kwargs


def structured_mode_uses_native(config: RuntimeConfig) -> bool:
    """Return True when the current config should accept raw provider JSON."""
    return resolve_structured_request_strategy(config).is_native


def _request_options_to_kwargs(options: ModelRequestOptions | None) -> dict[str, Any]:
    if options is None:
        return {}

    kwargs: dict[str, Any] = dict(options.extra)
    if options.max_tokens is not None:
        kwargs["max_tokens"] = options.max_tokens
    if options.temperature is not None:
        kwargs["temperature"] = options.temperature
    if options.timeout_sec is not None:
        kwargs["timeout"] = options.timeout_sec
    if options.response_format is not None:
        kwargs["response_format"] = options.response_format
    if options.reasoning is not None:
        kwargs["reasoning"] = options.reasoning
    return kwargs


def _build_json_schema_response_format(config: RuntimeConfig, provider: str) -> dict[str, Any]:
    schema = normalize_output_schema(config.output_format)
    if schema is None:
        schema = {}
    schema = _strip_unsupported_schema_keywords(
        schema,
        get_provider_structured_capabilities(provider).unsupported_schema_keywords,
    )
    return {
        "type": "json_schema",
        "json_schema": {
            "name": config.structured_schema_name or _default_schema_name(config),
            "strict": config.structured_strict,
            "schema": schema,
        },
    }


def _default_schema_name(config: RuntimeConfig) -> str:
    if config.output_type is not None:
        return getattr(config.output_type, "__name__", "structured_output")
    return "structured_output"


def _strip_unsupported_schema_keywords(value: Any, unsupported: frozenset[str]) -> Any:
    if not unsupported:
        return value
    if isinstance(value, dict):
        return {
            key: _strip_unsupported_schema_keywords(item, unsupported)
            for key, item in value.items()
            if key not in unsupported
        }
    if isinstance(value, list):
        return [_strip_unsupported_schema_keywords(item, unsupported) for item in value]
    return value
