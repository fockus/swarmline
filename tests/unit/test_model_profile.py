"""Tests for model profiles (context window, output limit, prompt cache) in the model registry.

Contract (CE-21): ``resolve_model_profile`` recognizes a model by its exact id, a
provider-prefixed id (``openrouter:``/``anthropic:``) or a registry alias, and returns
``None`` for anything it does not recognize -- it NEVER falls back to the default
model's profile, because a wrong window is worse than an explicit "unknown".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from swarmline.runtime import (
    UNKNOWN_MODEL_PROFILE,
    ModelProfile,
    ModelRegistry,
    resolve_model_profile,
)
from swarmline.runtime.provider_resolver import parse_provider_prefix


@pytest.fixture
def registry() -> ModelRegistry:
    """The shipped models.yaml -- profiles are data, the test pins the real file."""
    return ModelRegistry()


def _write_config(tmp_path: Path, profiles: dict[str, Any]) -> Path:
    config = {
        "default_model": "claude-sonnet-4-20250514",
        "providers": {
            "anthropic": {"claude-sonnet-4-20250514": {"aliases": ["sonnet"]}}
        },
        "profiles": profiles,
    }
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_profile_known_anthropic_model_returns_window_and_max_output(
    registry: ModelRegistry,
) -> None:
    profile = resolve_model_profile("claude-sonnet-4-20250514", registry)

    assert profile == ModelProfile(
        context_window=200_000,
        max_output_tokens=64_000,
        prompt_cache="explicit",
        vision=True,
    )


@pytest.mark.parametrize(
    ("raw", "expected_window"),
    [
        ("sonnet", 200_000),
        ("claude-sonnet-4-20250514", 200_000),
        ("  Claude-Sonnet-4-20250514 ", 200_000),
        ("anthropic:claude-sonnet-4-20250514", 200_000),
        ("openrouter:moonshotai/kimi-k2.5", 262_144),
        ("moonshotai/kimi-k2.5", 262_144),
        ("anthropic/claude-opus-4-5", 200_000),
        ("openrouter:deepseek/deepseek-v4.1-flash", 1_040_000),
        ("anthropic/claude-opus-4.5", 200_000),
        ("opus", 200_000),
        ("4o-mini", 128_000),
    ],
)
def test_profile_resolves_alias_and_provider_prefix(
    registry: ModelRegistry, raw: str, expected_window: int
) -> None:
    profile = resolve_model_profile(raw, registry)

    assert profile is not None, f"{raw!r} must resolve to a profile"
    assert profile.context_window == expected_window


def test_profile_prefixed_and_bare_kimi_resolve_to_the_same_profile(
    registry: ModelRegistry,
) -> None:
    assert resolve_model_profile(
        "moonshotai/kimi-k2.5", registry
    ) == resolve_model_profile("openrouter:moonshotai/kimi-k2.5", registry)


def test_profile_openrouter_opus_id_is_not_confused_with_native_opus_4(
    registry: ModelRegistry,
) -> None:
    openrouter_opus = resolve_model_profile("anthropic/claude-opus-4-5", registry)
    native_opus = resolve_model_profile("claude-opus-4-20250514", registry)

    assert openrouter_opus is not None and native_opus is not None
    assert openrouter_opus.max_output_tokens == 64_000
    assert native_opus.max_output_tokens == 32_000


@pytest.mark.parametrize(
    "raw",
    [
        "totally-unknown-model",
        "openrouter:vendor/unknown-model",
        "anthropic:claude-opus-4-5",
        "",
        "   ",
        None,
        # Greedy id-prefix matches the registry's resolve() would accept: a profile
        # must never be picked by "starts with" -- gpt-4 is not gpt-4o.
        "gpt-4",
        "g",
        "claude",
        "claude-sonnet-4",
        "gemini-2",
        "deepseek-",
        "o",
    ],
)
def test_profile_unknown_model_returns_none_not_default_model_profile(
    registry: ModelRegistry, raw: str | None
) -> None:
    assert resolve_model_profile(raw, registry) is None


def test_profile_uses_the_global_registry_when_none_is_passed() -> None:
    assert resolve_model_profile("sonnet") == resolve_model_profile(
        "sonnet", ModelRegistry()
    )


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (
            {"context_window": 0, "max_output_tokens": 1, "prompt_cache": "none"},
            "context_window",
        ),
        (
            {"context_window": -5, "max_output_tokens": 1, "prompt_cache": "none"},
            "context_window",
        ),
        (
            {"context_window": 1000, "max_output_tokens": 1000, "prompt_cache": "none"},
            "max_output_tokens",
        ),
        (
            {"context_window": 1000, "max_output_tokens": 0, "prompt_cache": "none"},
            "max_output_tokens",
        ),
        (
            {"context_window": 1000, "max_output_tokens": 10, "prompt_cache": "bogus"},
            "prompt_cache",
        ),
        (
            {"context_window": "1000", "max_output_tokens": 10, "prompt_cache": "none"},
            "context_window",
        ),
        (
            {"context_window": True, "max_output_tokens": 10, "prompt_cache": "none"},
            "context_window",
        ),
        ({"max_output_tokens": 10, "prompt_cache": "none"}, "context_window"),
        ("not-a-mapping", "mapping"),
    ],
)
def test_profile_invalid_entry_rejected_at_load(
    tmp_path: Path, entry: Any, message: str
) -> None:
    path = _write_config(tmp_path, {"broken/model-x": entry})

    with pytest.raises(ValueError, match=message) as excinfo:
        ModelRegistry(config_path=path)

    assert "broken/model-x" in str(excinfo.value), (
        "the error must name the offending model id"
    )


def test_profile_non_mapping_profiles_section_rejected_at_load(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump({"profiles": ["a", "b"]}), encoding="utf-8")

    with pytest.raises(ValueError, match="profiles"):
        ModelRegistry(config_path=path)


def test_profiles_section_leaves_extras_and_providers_unchanged(
    registry: ModelRegistry,
) -> None:
    assert registry.get_model_extras("gpt-4o") == {}
    assert registry.list_providers() == ["anthropic", "deepseek", "google", "openai"]
    assert "moonshotai/kimi-k2.5" not in registry.valid_models
    assert registry.get_provider("moonshotai/kimi-k2.5") == registry.get_provider(
        registry.default_model
    )
    assert "context_window" not in registry.get_model_extras("sonnet")


def test_every_provider_model_has_profile(registry: ModelRegistry) -> None:
    missing = [
        model for model in registry.list_models() if registry.get_profile(model) is None
    ]

    assert not missing, f"models without a profile: {missing}"


def test_registry_without_config_file_has_no_profiles(tmp_path: Path) -> None:
    registry = ModelRegistry(config_path=tmp_path / "absent.yaml")

    assert registry.get_profile("claude-sonnet-4-20250514") is None
    assert resolve_model_profile("sonnet", registry) is None


def test_unknown_model_profile_is_the_conservative_32k_4k_default() -> None:
    assert UNKNOWN_MODEL_PROFILE == ModelProfile(
        context_window=32_000, max_output_tokens=4_096, prompt_cache="none"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("openrouter:moonshotai/kimi-k2.5", ("openrouter", "moonshotai/kimi-k2.5")),
        ("Google_GenAI: gemini-2.5-pro", ("google", "gemini-2.5-pro")),
        ("moonshotai/kimi-k2.5", (None, "moonshotai/kimi-k2.5")),
        (
            "deepseek/deepseek-v4.1-flash:free",
            (None, "deepseek/deepseek-v4.1-flash:free"),
        ),
    ],
)
def test_parse_provider_prefix_is_public_and_strips_only_known_providers(
    raw: str, expected: tuple[str | None, str]
) -> None:
    assert parse_provider_prefix(raw) == expected


@pytest.mark.parametrize(
    "suffix", ["free", "batch", "nitro", "floor", "online", "thinking"]
)
@pytest.mark.parametrize(
    "base", ["deepseek/deepseek-v4.1-flash", "openrouter:deepseek/deepseek-v4.1-flash"]
)
def test_profile_openrouter_variant_suffix_resolves_to_base_model_profile(
    registry: ModelRegistry, base: str, suffix: str
) -> None:
    assert resolve_model_profile(f"{base}:{suffix}", registry) == resolve_model_profile(
        "deepseek/deepseek-v4.1-flash", registry
    )


def test_profile_unknown_variant_suffix_is_not_stripped(
    registry: ModelRegistry,
) -> None:
    assert resolve_model_profile("deepseek/deepseek-v4.1-flash:bogus", registry) is None


@pytest.mark.parametrize(
    ("raw", "context_window", "max_output_tokens"),
    [
        ("deepseek/deepseek-v4.1-flash", 1_040_000, 384_000),
        ("moonshotai/kimi-k2.5", 262_144, 235_929),
        ("anthropic/claude-opus-4.5", 200_000, 64_000),
        ("anthropic/claude-opus-4-5", 200_000, 64_000),
    ],
)
def test_profile_openrouter_models_match_the_catalog(
    registry: ModelRegistry, raw: str, context_window: int, max_output_tokens: int
) -> None:
    """Numbers from the OpenRouter catalog (GET /api/v1/models, top_provider, 2026-09-27)."""
    profile = resolve_model_profile(raw, registry)

    assert profile is not None
    assert (profile.context_window, profile.max_output_tokens) == (
        context_window,
        max_output_tokens,
    )


@pytest.mark.parametrize(
    ("alias", "model_id"),
    [
        ("gemini", "gemini-2.5-pro"),
        ("deepseek", "deepseek-chat"),
        ("sonnet", "claude-sonnet-4-20250514"),
        ("r1", "deepseek-reasoner"),
    ],
)
def test_profile_declared_alias_resolves_to_its_exact_target(
    registry: ModelRegistry, alias: str, model_id: str
) -> None:
    """Declared aliases (models.yaml ``aliases:``) are an exact mapping, not a prefix guess."""
    assert resolve_model_profile(alias, registry) == registry.get_profile(model_id)


# ---------------------------------------------------------------------------
# Vision flag (taskloom Sprint 7i S1, AGR-088): which models accept image input.
# ---------------------------------------------------------------------------

_VISION_MODELS = [
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-haiku-3-20250307",
    "anthropic/claude-opus-4.5",
    "anthropic/claude-opus-4-5",
    "gpt-4o",
    "gpt-4o-mini",
    "openai/gpt-4o-mini",
    "o3",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "deepseek/deepseek-v4.1-flash",
    "moonshotai/kimi-k2.5",
]
# Text-only in the OpenRouter catalog (architecture.input_modalities, 2026-09-28).
_TEXT_ONLY_MODELS = ["deepseek-chat", "deepseek-reasoner", "o3-mini", "codex-mini"]


def test_vision_defaults_false() -> None:
    profile = ModelProfile(
        context_window=1000, max_output_tokens=10, prompt_cache="none"
    )

    assert profile.vision is False


def test_vision_parsed_from_yaml(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {
            "vendor/seeing": {
                "context_window": 1000,
                "max_output_tokens": 10,
                "prompt_cache": "none",
                "vision": True,
            },
            "vendor/blind": {
                "context_window": 1000,
                "max_output_tokens": 10,
                "prompt_cache": "none",
            },
        },
    )
    registry = ModelRegistry(config_path=path)

    seeing = resolve_model_profile("openrouter:vendor/seeing", registry)
    blind = resolve_model_profile("vendor/blind", registry)

    assert seeing is not None and seeing.vision is True
    assert blind is not None and blind.vision is False


@pytest.mark.parametrize("raw_vision", ["yes", 1, None])
def test_vision_non_bool_rejected(tmp_path: Path, raw_vision: Any) -> None:
    path = _write_config(
        tmp_path,
        {
            "vendor/typo": {
                "context_window": 1000,
                "max_output_tokens": 10,
                "prompt_cache": "none",
                "vision": raw_vision,
            }
        },
    )

    with pytest.raises(ValueError, match="vision") as excinfo:
        ModelRegistry(config_path=path)

    assert "vendor/typo" in str(excinfo.value)


@pytest.mark.parametrize("model", _VISION_MODELS)
def test_dev_models_declare_vision(registry: ModelRegistry, model: str) -> None:
    profile = resolve_model_profile(model, registry)

    assert profile is not None and profile.vision is True


@pytest.mark.parametrize("model", _TEXT_ONLY_MODELS)
def test_text_only_models_do_not_declare_vision(
    registry: ModelRegistry, model: str
) -> None:
    profile = resolve_model_profile(model, registry)

    assert profile is not None and profile.vision is False
