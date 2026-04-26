"""Model Registry module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_DEFAULT_CONFIG_PATH = Path(__file__).parent / "models.yaml"


class ModelRegistry:
    """Model Registry implementation."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._default_model: str = ""
        # full_model_id → provider
        self._model_to_provider: dict[str, str] = {}
        # alias → full_model_id
        self._aliases: dict[str, str] = {}

        self._descriptions: dict[str, str] = {}

        self._valid_models: frozenset[str] = frozenset()

        self._load()

    def _load(self) -> None:
        """Load config from YAML."""
        if not self._config_path.exists():
            # Fallback: Anthropic default
            self._default_model = "claude-sonnet-4-20250514"
            self._valid_models = frozenset({self._default_model})
            return

        with open(self._config_path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        self._default_model = data.get("default_model", "claude-sonnet-4-20250514")

        models: dict[str, str] = {}
        aliases: dict[str, str] = {}
        descriptions: dict[str, str] = {}

        providers = data.get("providers", {})
        for provider_name, provider_models in providers.items():
            if not isinstance(provider_models, dict):
                continue
            for model_id, model_info in provider_models.items():
                models[model_id] = provider_name

                if isinstance(model_info, dict):
                    for alias in model_info.get("aliases", []):
                        aliases[alias.lower()] = model_id
                    desc = model_info.get("description", "")
                    if desc:
                        descriptions[model_id] = desc

        self._model_to_provider = models
        self._aliases = aliases
        self._descriptions = descriptions
        self._valid_models = frozenset(models.keys())

    @property
    def default_model(self) -> str:
        """Default model."""
        return self._default_model

    @property
    def valid_models(self) -> frozenset[str]:
        """Valid models."""
        return self._valid_models

    def resolve(self, raw: str | None) -> str:
        """Resolve."""
        if not raw:
            return self._default_model

        name = raw.strip().lower()

        # 1. Alias
        if name in self._aliases:
            return self._aliases[name]

        if name in self._valid_models:
            return name

        for full_name in sorted(self._valid_models):
            if full_name.startswith(name):
                return full_name

        return self._default_model

    def get_provider(self, model_id: str) -> str:
        """Get provider."""

        if model_id in self._model_to_provider:
            return self._model_to_provider[model_id]

        resolved = self.resolve(model_id)
        return self._model_to_provider.get(resolved, "unknown")

    def get_description(self, model_id: str) -> str:
        """Get description."""
        resolved = self.resolve(model_id)
        return self._descriptions.get(resolved, "")

    def list_models(self, provider: str | None = None) -> list[str]:
        """List models."""
        if provider:
            return sorted(
                m for m, p in self._model_to_provider.items() if p == provider
            )
        return sorted(self._valid_models)

    def list_aliases(self) -> dict[str, str]:
        """List aliases."""
        return dict(self._aliases)

    def list_providers(self) -> list[str]:
        """List providers."""
        return sorted(set(self._model_to_provider.values()))


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

_registry: ModelRegistry | None = None


def get_registry(config_path: Path | None = None) -> ModelRegistry:
    """Get registry."""
    global _registry
    if _registry is None or config_path is not None:
        _registry = ModelRegistry(config_path=config_path)
    return _registry


def reset_registry() -> None:
    """Reset registry."""
    global _registry
    _registry = None
