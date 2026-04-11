"""Tests for ModelRegistry - multi-provider registry of LLM models."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from swarmline.runtime.model_registry import ModelRegistry, get_registry, reset_registry

# ---------------------------------------------------------------------------
# Fixture: temp config
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Create temporary models.yaml for tests."""
    config = {
        "default_model": "claude-sonnet-4-20250514",
        "providers": {
            "anthropic": {
                "claude-sonnet-4-20250514": {
                    "aliases": ["sonnet", "sonnet-4"],
                    "description": "Быстрая модель",
                },
                "claude-opus-4-20250514": {
                    "aliases": ["opus"],
                    "description": "Мощная модель",
                },
            },
            "openai": {
                "gpt-4o": {
                    "aliases": ["4o", "gpt4o"],
                    "description": "Флагман OpenAI",
                },
                "gpt-4o-mini": {
                    "aliases": ["4o-mini"],
                },
            },
            "google": {
                "gemini-2.5-pro": {
                    "aliases": ["gemini", "gemini-pro"],
                },
            },
        },
    }
    path = tmp_path / "models.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


@pytest.fixture
def registry(tmp_config: Path) -> ModelRegistry:
    """ModelRegistry from temp config."""
    return ModelRegistry(config_path=tmp_config)


# ---------------------------------------------------------------------------
# Basic tests
# ---------------------------------------------------------------------------


class TestModelRegistryBasic:
    """Basic behavior: loading, default, valid models."""

    def test_default_model(self, registry: ModelRegistry) -> None:
        assert registry.default_model == "claude-sonnet-4-20250514"

    def test_valid_models_contains_all(self, registry: ModelRegistry) -> None:
        valid = registry.valid_models
        assert "claude-sonnet-4-20250514" in valid
        assert "claude-opus-4-20250514" in valid
        assert "gpt-4o" in valid
        assert "gpt-4o-mini" in valid
        assert "gemini-2.5-pro" in valid

    def test_list_providers(self, registry: ModelRegistry) -> None:
        providers = registry.list_providers()
        assert "anthropic" in providers
        assert "openai" in providers
        assert "google" in providers

    def test_list_models_all(self, registry: ModelRegistry) -> None:
        models = registry.list_models()
        assert len(models) == 5

    def test_list_models_by_provider(self, registry: ModelRegistry) -> None:
        anthropic = registry.list_models("anthropic")
        assert len(anthropic) == 2
        assert "claude-sonnet-4-20250514" in anthropic

        openai = registry.list_models("openai")
        assert len(openai) == 2
        assert "gpt-4o" in openai


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------


class TestModelRegistryResolve:
    """resolve() — alias, prefix, full name, fallback."""

    def test_alias_sonnet(self, registry: ModelRegistry) -> None:
        assert registry.resolve("sonnet") == "claude-sonnet-4-20250514"

    def test_alias_opus(self, registry: ModelRegistry) -> None:
        assert registry.resolve("opus") == "claude-opus-4-20250514"

    def test_alias_gpt4o(self, registry: ModelRegistry) -> None:
        assert registry.resolve("4o") == "gpt-4o"

    def test_alias_gemini(self, registry: ModelRegistry) -> None:
        assert registry.resolve("gemini") == "gemini-2.5-pro"

    def test_full_name_exact(self, registry: ModelRegistry) -> None:
        assert registry.resolve("gpt-4o") == "gpt-4o"
        assert registry.resolve("claude-opus-4-20250514") == "claude-opus-4-20250514"

    def test_prefix_match(self, registry: ModelRegistry) -> None:
        result = registry.resolve("claude-opus")
        assert result == "claude-opus-4-20250514"

    def test_case_insensitive(self, registry: ModelRegistry) -> None:
        assert registry.resolve("SONNET") == "claude-sonnet-4-20250514"
        assert registry.resolve("Opus") == "claude-opus-4-20250514"

    def test_none_returns_default(self, registry: ModelRegistry) -> None:
        assert registry.resolve(None) == "claude-sonnet-4-20250514"

    def test_empty_returns_default(self, registry: ModelRegistry) -> None:
        assert registry.resolve("") == "claude-sonnet-4-20250514"

    def test_invalid_returns_default(self, registry: ModelRegistry) -> None:
        assert registry.resolve("llama-70b") == "claude-sonnet-4-20250514"

    def test_whitespace_trimmed(self, registry: ModelRegistry) -> None:
        assert registry.resolve("  sonnet  ") == "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


class TestModelRegistryProvider:
    """get_provider() - definition of provider by model_id."""

    def test_anthropic(self, registry: ModelRegistry) -> None:
        assert registry.get_provider("claude-sonnet-4-20250514") == "anthropic"

    def test_openai(self, registry: ModelRegistry) -> None:
        assert registry.get_provider("gpt-4o") == "openai"

    def test_google(self, registry: ModelRegistry) -> None:
        assert registry.get_provider("gemini-2.5-pro") == "google"

    def test_alias_resolves_provider(self, registry: ModelRegistry) -> None:
        assert registry.get_provider("sonnet") == "anthropic"
        assert registry.get_provider("4o") == "openai"
        assert registry.get_provider("gemini") == "google"

    def test_unknown_model_falls_back_to_default_provider(self, registry: ModelRegistry) -> None:
        """Not known model -> resolve fallback on default -> provider default models."""
        # "llama-70b" resolves in default (claude-sonnet) -> provider = anthropic
        assert registry.get_provider("llama-70b") == "anthropic"


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------


class TestModelRegistryDescription:
    """get_description() - description of models."""

    def test_has_description(self, registry: ModelRegistry) -> None:
        assert "Быстрая" in registry.get_description("claude-sonnet-4-20250514")

    def test_empty_description(self, registry: ModelRegistry) -> None:
        # gpt-4o-mini does not have a description in the config
        assert registry.get_description("gpt-4o-mini") == ""


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------


class TestModelRegistryAliases:
    """list_aliases() - full mapping alias -> model."""

    def test_aliases_count(self, registry: ModelRegistry) -> None:
        aliases = registry.list_aliases()
        # sonnet, sonnet-4, opus, 4o, gpt4o, 4o-mini, gemini, gemini-pro
        assert len(aliases) == 8

    def test_aliases_mapping(self, registry: ModelRegistry) -> None:
        aliases = registry.list_aliases()
        assert aliases["sonnet"] == "claude-sonnet-4-20250514"
        assert aliases["4o"] == "gpt-4o"
        assert aliases["gemini"] == "gemini-2.5-pro"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestModelRegistryEdgeCases:
    """Edge cases: missing file, empty YAML, bad data."""

    def test_missing_config_file(self, tmp_path: Path) -> None:
        """Missing YAML -> fallback on Anthropic default."""
        reg = ModelRegistry(config_path=tmp_path / "nonexistent.yaml")
        assert reg.default_model == "claude-sonnet-4-20250514"
        assert "claude-sonnet-4-20250514" in reg.valid_models
        assert reg.resolve("anything") == "claude-sonnet-4-20250514"

    def test_empty_config_file(self, tmp_path: Path) -> None:
        """Empty YAML -> fallback."""
        path = tmp_path / "empty.yaml"
        path.write_text("")
        reg = ModelRegistry(config_path=path)
        assert reg.default_model == "claude-sonnet-4-20250514"

    def test_config_without_providers(self, tmp_path: Path) -> None:
        """YAML without providers -> empty registry, default works."""
        path = tmp_path / "no_providers.yaml"
        with open(path, "w") as f:
            yaml.dump({"default_model": "my-model"}, f)
        reg = ModelRegistry(config_path=path)
        assert reg.default_model == "my-model"
        assert reg.resolve("anything") == "my-model"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestModelRegistrySingleton:
    """get_registry() / reset_registry() - singleton."""

    def test_get_registry_returns_same_instance(self) -> None:
        reset_registry()
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_reset_registry_clears(self, tmp_config: Path) -> None:
        reset_registry()
        r1 = get_registry()
        reset_registry()
        r2 = get_registry(config_path=tmp_config)
        assert r1 is not r2

    def test_custom_config_overrides(self, tmp_config: Path) -> None:
        reset_registry()
        reg = get_registry(config_path=tmp_config)
        assert "gpt-4o" in reg.valid_models
        reset_registry()


# ---------------------------------------------------------------------------
# Production config (models.yaml next to model_registry.py)
# ---------------------------------------------------------------------------


class TestProductionConfig:
    """Check that production models.yaml is loaded correctly."""

    def test_production_config_loads(self) -> None:
        """Production models.yaml exists and contains the expected models."""
        reset_registry()
        reg = get_registry()

        # Anthropic
        assert "claude-sonnet-4-20250514" in reg.valid_models
        assert "claude-opus-4-20250514" in reg.valid_models
        assert "claude-haiku-3-20250307" in reg.valid_models

        # OpenAI
        assert "gpt-4o" in reg.valid_models
        assert "gpt-4o-mini" in reg.valid_models

        # Google
        assert "gemini-2.5-pro" in reg.valid_models

        # DeepSeek
        assert "deepseek-chat" in reg.valid_models
        assert "deepseek-reasoner" in reg.valid_models

        reset_registry()

    def test_production_aliases_work(self) -> None:
        """Production alias work."""
        reset_registry()
        reg = get_registry()

        assert reg.resolve("sonnet") == "claude-sonnet-4-20250514"
        assert reg.resolve("gpt-4o") == "gpt-4o"
        assert reg.resolve("gemini") == "gemini-2.5-pro"
        assert reg.resolve("r1") == "deepseek-reasoner"

        reset_registry()
