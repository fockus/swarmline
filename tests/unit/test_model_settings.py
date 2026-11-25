"""Tests for ModelSettings + ModelSettingsResolver (RCA Task 2).

Covers: REQ-RCA-010 (weak-model aux routing), REQ-RCA-012 (editor_model exposed),
REQ-RCA-070 (byte-identical default when enable_model_tiering=False).

Naming: test_<what>_<condition>_<result>
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

from swarmline.runtime.model_registry import ModelRegistry, get_registry, reset_registry
from swarmline.runtime.model_settings import (
    ModelSettings,
    ModelSettingsResolver,
    select_aux_model,
)
from swarmline.runtime.thin.coding_profile import CodingProfileConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_yaml(tmp_path: Path) -> Path:
    """Create a temp models.yaml with per-model settings fields on select entries."""
    config = {
        "default_model": "claude-sonnet-4-20250514",
        "providers": {
            "anthropic": {
                "claude-sonnet-4-20250514": {
                    "aliases": ["sonnet", "sonnet-4"],
                    "description": "Main model",
                    "edit_format": "diff",
                    "weak_model": "claude-haiku-3-20250307",
                    "editor_model": "claude-opus-4-20250514",
                    "use_repo_map": True,
                },
                "claude-opus-4-20250514": {
                    "aliases": ["opus"],
                    "description": "Powerful model",
                    "edit_format": "whole",
                    "use_repo_map": False,
                    # no weak_model, no editor_model
                },
                "claude-haiku-3-20250307": {
                    "aliases": ["haiku"],
                    "description": "Fast cheap model",
                    # no per-model extras
                },
            },
        },
    }
    path = tmp_path / "models.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


@pytest.fixture
def registry(settings_yaml: Path) -> ModelRegistry:
    """ModelRegistry loaded from the per-model settings fixture."""
    return ModelRegistry(config_path=settings_yaml)


@pytest.fixture
def resolver(registry: ModelRegistry) -> ModelSettingsResolver:
    """ModelSettingsResolver wrapping the per-model settings registry."""
    return ModelSettingsResolver(registry=registry)


# ---------------------------------------------------------------------------
# ModelSettings dataclass contract
# ---------------------------------------------------------------------------


class TestModelSettingsDataclass:
    """ModelSettings is a frozen dataclass with correct field defaults."""

    def test_model_settings_is_frozen_dataclass(self) -> None:
        """ModelSettings is a frozen dataclass."""
        assert dataclasses.is_dataclass(ModelSettings)
        s = ModelSettings(name="test-model")
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.name = "other"  # type: ignore[misc]

    def test_model_settings_defaults_are_none_and_true(self) -> None:
        """Default fields: edit_format=None, weak/editor=None, use_repo_map=True."""
        s = ModelSettings(name="test-model")
        assert s.edit_format is None
        assert s.weak_model_name is None
        assert s.editor_model_name is None
        assert s.use_repo_map is True

    def test_model_settings_full_construction(self) -> None:
        """All fields accepted."""
        s = ModelSettings(
            name="my-model",
            edit_format="diff",
            weak_model_name="haiku",
            editor_model_name="opus",
            use_repo_map=False,
        )
        assert s.name == "my-model"
        assert s.edit_format == "diff"
        assert s.weak_model_name == "haiku"
        assert s.editor_model_name == "opus"
        assert s.use_repo_map is False

    def test_model_settings_equality_is_value_based(self) -> None:
        """Two ModelSettings with identical fields are equal."""
        a = ModelSettings(name="m", edit_format="diff")
        b = ModelSettings(name="m", edit_format="diff")
        assert a == b

    def test_model_settings_inequality_on_different_name(self) -> None:
        """Different names → not equal."""
        a = ModelSettings(name="m1")
        b = ModelSettings(name="m2")
        assert a != b


# ---------------------------------------------------------------------------
# ModelSettingsResolver — declared fields
# ---------------------------------------------------------------------------


class TestModelSettingsResolverDeclaredSettings:
    """Resolver returns all declared per-model fields for known models."""

    def test_resolver_returns_edit_format_for_model_that_declares_it(
        self, resolver: ModelSettingsResolver
    ) -> None:
        settings = resolver.resolve("claude-sonnet-4-20250514")
        assert settings.edit_format == "diff"

    def test_resolver_returns_weak_model_name_when_declared(
        self, resolver: ModelSettingsResolver
    ) -> None:
        settings = resolver.resolve("claude-sonnet-4-20250514")
        assert settings.weak_model_name == "claude-haiku-3-20250307"

    def test_resolver_returns_editor_model_name_when_declared(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """REQ-RCA-012: editor_model_name is exposed (Task 3 will consume it)."""
        settings = resolver.resolve("claude-sonnet-4-20250514")
        assert settings.editor_model_name == "claude-opus-4-20250514"

    def test_resolver_returns_use_repo_map_declared_true(
        self, resolver: ModelSettingsResolver
    ) -> None:
        settings = resolver.resolve("claude-sonnet-4-20250514")
        assert settings.use_repo_map is True

    def test_resolver_returns_use_repo_map_declared_false(
        self, resolver: ModelSettingsResolver
    ) -> None:
        settings = resolver.resolve("claude-opus-4-20250514")
        assert settings.use_repo_map is False

    def test_resolver_returns_partial_settings_when_only_some_declared(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """Opus has edit_format + use_repo_map but no weak/editor model."""
        settings = resolver.resolve("claude-opus-4-20250514")
        assert settings.edit_format == "whole"
        assert settings.weak_model_name is None
        assert settings.editor_model_name is None

    def test_resolver_returns_none_tiers_for_model_with_no_extras(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """Haiku has no per-model extras → all optional fields are None or default."""
        settings = resolver.resolve("claude-haiku-3-20250307")
        assert settings.edit_format is None
        assert settings.weak_model_name is None
        assert settings.editor_model_name is None
        assert settings.use_repo_map is True


# ---------------------------------------------------------------------------
# ModelSettingsResolver — match priority: alias → exact → prefix → default
# ---------------------------------------------------------------------------


class TestModelSettingsResolverMatchPriority:
    """Resolution priority: alias exact-match → model-id exact → prefix → generic default."""

    def test_alias_resolves_to_canonical_model_settings(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """Alias 'sonnet' resolves to claude-sonnet-4-20250514 settings."""
        by_alias = resolver.resolve("sonnet")
        by_full_id = resolver.resolve("claude-sonnet-4-20250514")
        assert by_alias == by_full_id

    def test_prefix_resolves_to_matching_model_settings(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """Prefix 'claude-opus' matches claude-opus-4-20250514 and returns its settings."""
        settings = resolver.resolve("claude-opus")
        assert settings.name == "claude-opus-4-20250514"
        assert settings.edit_format == "whole"

    def test_exact_model_id_beats_prefix_interpretation(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """Exact model-id always returns settings for that model (no prefix ambiguity)."""
        exact = resolver.resolve("claude-sonnet-4-20250514")
        assert exact.name == "claude-sonnet-4-20250514"

    def test_unknown_model_returns_sane_generic_default(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """Unknown model → ModelSettings(name=<raw>) with None tiers, use_repo_map=True."""
        settings = resolver.resolve("some-unknown-llm-xyz-9999")
        # name is the raw input (not coerced to default model)
        assert settings.name == "some-unknown-llm-xyz-9999"
        assert settings.edit_format is None
        assert settings.weak_model_name is None
        assert settings.editor_model_name is None
        assert settings.use_repo_map is True

    def test_none_input_returns_default_model_settings(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """None input → default model settings."""
        settings = resolver.resolve(None)
        # default model is claude-sonnet-4-20250514 which has declared settings
        assert settings.name == "claude-sonnet-4-20250514"
        assert settings.edit_format == "diff"

    def test_empty_string_returns_default_model_settings(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """Empty string input → default model settings."""
        settings = resolver.resolve("")
        assert settings.name == "claude-sonnet-4-20250514"

    def test_alias_haiku_resolves_without_extras(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """Alias 'haiku' resolves to haiku model with None extras."""
        settings = resolver.resolve("haiku")
        assert settings.name == "claude-haiku-3-20250307"
        assert settings.weak_model_name is None


# ---------------------------------------------------------------------------
# select_aux_model — REQ-RCA-010
# ---------------------------------------------------------------------------


class TestSelectAuxModel:
    """select_aux_model returns weak model when declared, else main model."""

    def test_returns_weak_model_when_declared(self) -> None:
        """REQ-RCA-010: aux tasks route to weak_model when declared."""
        settings = ModelSettings(
            name="claude-sonnet-4-20250514",
            weak_model_name="claude-haiku-3-20250307",
        )
        result = select_aux_model(settings, "claude-sonnet-4-20250514")
        assert result == "claude-haiku-3-20250307"

    def test_returns_main_model_when_no_weak_model(self) -> None:
        """When no weak_model declared, main model is returned unchanged."""
        settings = ModelSettings(name="claude-opus-4-20250514")
        result = select_aux_model(settings, "claude-opus-4-20250514")
        assert result == "claude-opus-4-20250514"

    def test_returns_main_model_for_all_none_settings(self) -> None:
        """Unknown model settings (all None) → main model returned — byte-identical."""
        settings = ModelSettings(name="some-unknown-llm")
        result = select_aux_model(settings, "some-unknown-llm")
        assert result == "some-unknown-llm"

    def test_weak_model_independent_of_main_model_name(self) -> None:
        """Weak model override is independent of the main model name passed."""
        settings = ModelSettings(
            name="model-a",
            weak_model_name="model-b-cheap",
        )
        result = select_aux_model(settings, "model-a-different-ref")
        assert result == "model-b-cheap"

    @pytest.mark.parametrize(
        "weak, main, expected",
        [
            ("haiku", "sonnet", "haiku"),
            (None, "sonnet", "sonnet"),
            (None, "gpt-4o", "gpt-4o"),
            ("gpt-4o-mini", "gpt-4o", "gpt-4o-mini"),
        ],
    )
    def test_select_aux_model_parametrized(
        self, weak: str | None, main: str, expected: str
    ) -> None:
        settings = ModelSettings(name=main, weak_model_name=weak)
        assert select_aux_model(settings, main) == expected


# ---------------------------------------------------------------------------
# editor_model_name exposed — REQ-RCA-012 (Task 3 consumes it, not Task 2)
# ---------------------------------------------------------------------------


class TestEditorModelExposure:
    """REQ-RCA-012: editor_model_name is accessible; Task 2 does NOT activate architect mode."""

    def test_editor_model_name_is_accessible_on_settings(
        self, resolver: ModelSettingsResolver
    ) -> None:
        settings = resolver.resolve("claude-sonnet-4-20250514")
        assert settings.editor_model_name == "claude-opus-4-20250514"

    def test_editor_model_none_when_not_declared(
        self, resolver: ModelSettingsResolver
    ) -> None:
        settings = resolver.resolve("claude-opus-4-20250514")
        assert settings.editor_model_name is None

    def test_model_settings_field_editor_model_name_is_str_or_none(self) -> None:
        """editor_model_name accepts str or None — no architect mode built here."""
        s_with = ModelSettings(name="m", editor_model_name="editor-model")
        s_without = ModelSettings(name="m")
        assert s_with.editor_model_name == "editor-model"
        assert s_without.editor_model_name is None


# ---------------------------------------------------------------------------
# CodingProfileConfig — enable_model_tiering opt-in flag (REQ-RCA-070)
# ---------------------------------------------------------------------------


class TestCodingProfileModelTiering:
    """enable_model_tiering=False is the default; OFF means byte-identical behavior."""

    def test_enable_model_tiering_defaults_to_false(self) -> None:
        """REQ-RCA-070: default runtime path unchanged when flag is off."""
        cfg = CodingProfileConfig()
        assert cfg.enable_model_tiering is False

    def test_enable_model_tiering_can_be_set_true(self) -> None:
        """Flag can be enabled explicitly."""
        cfg = CodingProfileConfig(enable_model_tiering=True)
        assert cfg.enable_model_tiering is True

    def test_enable_model_tiering_config_is_still_frozen(self) -> None:
        cfg = CodingProfileConfig(enable_model_tiering=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.enable_model_tiering = False  # type: ignore[misc]

    def test_flag_off_select_aux_returns_main_model(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """REQ-RCA-070: with enable_model_tiering=False, aux-task model == main model."""
        main_model = "claude-sonnet-4-20250514"
        settings = resolver.resolve(main_model)
        cfg = CodingProfileConfig(enable_model_tiering=False)

        # Caller pattern: gate on the flag before calling select_aux_model
        aux = (
            main_model
            if not cfg.enable_model_tiering
            else select_aux_model(settings, main_model)
        )
        assert aux == main_model

    def test_flag_on_select_aux_returns_weak_model(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """When enable_model_tiering=True and weak_model declared, aux routes to it."""
        main_model = "claude-sonnet-4-20250514"
        settings = resolver.resolve(main_model)
        cfg = CodingProfileConfig(enable_model_tiering=True)

        aux = (
            main_model
            if not cfg.enable_model_tiering
            else select_aux_model(settings, main_model)
        )
        # sonnet's weak_model is haiku
        assert aux == "claude-haiku-3-20250307"

    def test_flag_on_no_weak_model_falls_back_to_main(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """When flag is ON but no weak_model declared, main model is unchanged."""
        main_model = "claude-haiku-3-20250307"
        settings = resolver.resolve(main_model)
        cfg = CodingProfileConfig(enable_model_tiering=True)

        aux = (
            main_model
            if not cfg.enable_model_tiering
            else select_aux_model(settings, main_model)
        )
        assert aux == main_model

    def test_existing_coding_profile_flags_unchanged(self) -> None:
        """Adding enable_model_tiering does not break existing flag defaults."""
        cfg = CodingProfileConfig()
        assert cfg.enabled is True
        assert cfg.allow_host_execution is True
        assert cfg.edit_strategy == "legacy"
        assert cfg.enable_auto_lint_test is False
        assert cfg.enable_model_tiering is False


# ---------------------------------------------------------------------------
# Regression: existing models.yaml entries without new keys still load
# ---------------------------------------------------------------------------


class TestRegressionExistingYaml:
    """Backward-compatibility: production models.yaml (no per-model extras) loads fine."""

    def test_production_yaml_loads_without_new_keys(self) -> None:
        """ModelRegistry backward compat: existing entries without new fields work."""
        reset_registry()
        reg = get_registry()
        assert reg.resolve("sonnet") == "claude-sonnet-4-20250514"
        assert reg.resolve("haiku") == "claude-haiku-3-20250307"
        assert reg.resolve("4o") == "gpt-4o"
        reset_registry()

    def test_resolver_with_production_yaml_models_without_extras_return_defaults(
        self,
    ) -> None:
        """Models that have no per-model extras in production yaml return None tiers."""
        reset_registry()
        reg = get_registry()
        r = ModelSettingsResolver(registry=reg)
        # gpt-4o and gemini-2.5-pro have no extras in production models.yaml
        for model in ["gpt-4o", "gemini-2.5-pro", "claude-haiku-3-20250307"]:
            s = r.resolve(model)
            assert isinstance(s, ModelSettings)
            assert s.edit_format is None
            assert s.weak_model_name is None
            assert s.editor_model_name is None
            assert s.use_repo_map is True
        reset_registry()

    def test_resolver_with_production_yaml_sonnet_has_declared_extras(self) -> None:
        """Production claude-sonnet has declared extras (edit_format, weak, editor)."""
        reset_registry()
        reg = get_registry()
        r = ModelSettingsResolver(registry=reg)
        s = r.resolve("claude-sonnet-4-20250514")
        assert isinstance(s, ModelSettings)
        assert s.edit_format == "diff"
        assert s.weak_model_name == "claude-haiku-3-20250307"
        assert s.editor_model_name == "claude-opus-4-20250514"
        reset_registry()

    def test_model_registry_get_model_extras_returns_empty_for_models_without_extras(
        self,
    ) -> None:
        """ModelRegistry.get_model_extras on entries without extras returns {}."""
        reset_registry()
        reg = get_registry()
        # gpt-4o has no extra keys in production yaml
        extras = reg.get_model_extras("gpt-4o")
        assert extras == {}
        reset_registry()

    def test_settings_yaml_entries_with_extras_load_correctly(
        self, registry: ModelRegistry
    ) -> None:
        """Fixture registry correctly exposes per-model extras via get_model_extras."""
        extras = registry.get_model_extras("claude-sonnet-4-20250514")
        assert extras.get("edit_format") == "diff"
        assert extras.get("weak_model") == "claude-haiku-3-20250307"
        assert extras.get("editor_model") == "claude-opus-4-20250514"
        assert extras.get("use_repo_map") is True
        # aliases and description must NOT appear in extras
        assert "aliases" not in extras
        assert "description" not in extras

    def test_settings_yaml_entries_without_extras_return_empty(
        self, registry: ModelRegistry
    ) -> None:
        """Haiku in fixture has no extras — get_model_extras returns {}."""
        extras = registry.get_model_extras("claude-haiku-3-20250307")
        assert extras == {}

    def test_resolver_no_crash_on_unknown_model_is_deterministic(
        self, resolver: ModelSettingsResolver
    ) -> None:
        """Resolver never raises on any model name — always returns a ModelSettings."""
        for name in ["", None, "zzz-unknown-9999", "  ", "a"]:
            s = resolver.resolve(name)  # type: ignore[arg-type]
            assert isinstance(s, ModelSettings)


# ---------------------------------------------------------------------------
# build_aux_llm_call — REQ-RCA-010 (aux LLM adapter for weak-model routing)
# ---------------------------------------------------------------------------


class TestBuildAuxLlmCall:
    """build_aux_llm_call returns an async adapter routing aux tasks to the weak model."""

    async def test_adapter_calls_raw_with_weak_model_config(self) -> None:
        """Adapter invokes raw_llm_call with config.model == weak_model_name."""
        from swarmline.runtime.model_settings import build_aux_llm_call
        from swarmline.runtime.types import RuntimeConfig

        captured: dict[str, object] = {}

        async def spy_raw(
            messages: list[dict],
            prompt: str,
            *,
            config: object = None,
            **kwargs: object,
        ) -> str:
            captured["config"] = config
            captured["messages"] = messages
            captured["prompt"] = prompt
            return "summary text"

        base_config = RuntimeConfig(model="claude-sonnet-4-20250514")
        adapter = build_aux_llm_call(spy_raw, base_config, "claude-haiku-3-20250307")

        result = await adapter("My summarize prompt", "Some long dialog text")

        assert result == "summary text"
        assert hasattr(captured["config"], "model")
        assert captured["config"].model == "claude-haiku-3-20250307"  # type: ignore[union-attr]
        assert captured["messages"] == [
            {"role": "user", "content": "Some long dialog text"}
        ]
        assert captured["prompt"] == "My summarize prompt"

    async def test_adapter_extracts_text_from_llm_call_result_like_object(self) -> None:
        """Result with .text attribute → its text is returned."""
        from types import SimpleNamespace

        from swarmline.runtime.model_settings import build_aux_llm_call
        from swarmline.runtime.types import RuntimeConfig

        llm_result = SimpleNamespace(text="extracted summary")

        async def spy_raw(messages: list, prompt: str, **kwargs: object) -> object:
            return llm_result

        adapter = build_aux_llm_call(spy_raw, RuntimeConfig(model="m"), "weak-m")
        result = await adapter("prompt", "dialog")
        assert result == "extracted summary"

    async def test_adapter_consumes_async_iterator_result(self) -> None:
        """Streaming AsyncIterator result → chunks are joined and returned."""
        from swarmline.runtime.model_settings import build_aux_llm_call
        from swarmline.runtime.types import RuntimeConfig

        async def spy_raw(messages: list, prompt: str, **kwargs: object):  # noqa: ANN201
            async def _gen():
                yield "chunk1"
                yield " chunk2"

            return _gen()

        adapter = build_aux_llm_call(spy_raw, RuntimeConfig(model="m"), "weak-m")
        result = await adapter("prompt", "dialog")
        assert result == "chunk1 chunk2"

    async def test_adapter_does_not_use_base_model(self) -> None:
        """Raw call receives weak_model_name in config, NOT base_config.model."""
        from swarmline.runtime.model_settings import build_aux_llm_call
        from swarmline.runtime.types import RuntimeConfig

        received_models: list[str] = []

        async def spy_raw(
            messages: list, prompt: str, *, config: object = None, **kwargs: object
        ) -> str:
            if config is not None and hasattr(config, "model"):
                received_models.append(config.model)  # type: ignore[union-attr]
            return "ok"

        base = RuntimeConfig(model="big-expensive-model")
        adapter = build_aux_llm_call(spy_raw, base, "tiny-cheap-model")
        await adapter("p", "d")

        assert received_models == ["tiny-cheap-model"]

    def test_build_aux_llm_call_returns_callable(self) -> None:
        """build_aux_llm_call is synchronous and returns a callable immediately."""
        from swarmline.runtime.model_settings import build_aux_llm_call
        from swarmline.runtime.types import RuntimeConfig

        async def noop(messages: list, prompt: str, **kwargs: object) -> str:
            return ""

        adapter = build_aux_llm_call(noop, RuntimeConfig(model="x"), "y")
        assert callable(adapter)


# ---------------------------------------------------------------------------
# codex R1 [3 MAJOR] — build_aux_llm_call maps auth/network-class provider
# failures to SummarizerAbortError (duck-typed, no ThinLlmError import here).
# ---------------------------------------------------------------------------


class TestBuildAuxLlmCallAbortMapping:
    async def test_timeout_error_remapped_to_summarizer_abort_error(self) -> None:
        from swarmline.compaction import SummarizerAbortError
        from swarmline.runtime.model_settings import build_aux_llm_call
        from swarmline.runtime.types import RuntimeConfig

        async def raw(messages: list, prompt: str, **kwargs: object) -> str:
            raise TimeoutError("upstream timed out")

        adapter = build_aux_llm_call(raw, RuntimeConfig(model="m"), "weak-m")
        with pytest.raises(SummarizerAbortError):
            await adapter("prompt", "dialog")

    async def test_thinllmerror_shaped_auth_failure_remapped(self) -> None:
        """A ThinLlmError-shaped exception (duck-typed via .error.details
        .exception_type) with an auth-sounding provider class name is
        remapped, without this module importing ThinLlmError itself."""
        from types import SimpleNamespace

        from swarmline.compaction import SummarizerAbortError
        from swarmline.runtime.model_settings import build_aux_llm_call
        from swarmline.runtime.types import RuntimeConfig

        class _FakeThinLlmError(Exception):
            def __init__(self) -> None:
                super().__init__("LLM API error")
                self.error = SimpleNamespace(
                    details={"exception_type": "AuthenticationError"}
                )

        async def raw(messages: list, prompt: str, **kwargs: object) -> str:
            raise _FakeThinLlmError()

        adapter = build_aux_llm_call(raw, RuntimeConfig(model="m"), "weak-m")
        with pytest.raises(SummarizerAbortError):
            await adapter("prompt", "dialog")

    async def test_generic_failure_not_remapped(self) -> None:
        """A non-auth/network failure (e.g. bad JSON) propagates AS-IS —
        only abort-worthy failures get remapped."""
        from swarmline.runtime.model_settings import build_aux_llm_call
        from swarmline.runtime.types import RuntimeConfig

        async def raw(messages: list, prompt: str, **kwargs: object) -> str:
            raise ValueError("malformed response")

        adapter = build_aux_llm_call(raw, RuntimeConfig(model="m"), "weak-m")
        with pytest.raises(ValueError, match="malformed response"):
            await adapter("prompt", "dialog")


# ---------------------------------------------------------------------------
# ThinRuntime wiring — REQ-RCA-010 (compaction_llm_call seam)
# ---------------------------------------------------------------------------


class TestThinRuntimeModelTieringWiring:
    """ThinRuntime builds _compaction_llm_call when enable_model_tiering is True."""

    def _make_fake_llm(self) -> object:
        """Return a minimal fake llm_call."""

        async def _fake(messages: list, prompt: str, **kwargs: object) -> str:
            import json

            return json.dumps({"type": "final", "final_message": "done"})

        return _fake

    def test_compaction_llm_call_set_when_tiering_on_and_weak_model_declared(
        self,
    ) -> None:
        """_compaction_llm_call is non-None when tiering enabled + weak model declared."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        runtime = ThinRuntime(
            config=RuntimeConfig(model="claude-sonnet-4-20250514"),
            llm_call=self._make_fake_llm(),
            coding_profile=CodingProfileConfig(enable_model_tiering=True),
        )
        # claude-sonnet declares weak_model in production models.yaml
        assert runtime._compaction_llm_call is not None
        assert callable(runtime._compaction_llm_call)

    def test_compaction_llm_call_is_none_when_tiering_off(self) -> None:
        """REQ-RCA-070: _compaction_llm_call is None when enable_model_tiering=False."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        runtime = ThinRuntime(
            config=RuntimeConfig(model="claude-sonnet-4-20250514"),
            llm_call=self._make_fake_llm(),
            coding_profile=CodingProfileConfig(enable_model_tiering=False),
        )
        assert runtime._compaction_llm_call is None

    def test_compaction_llm_call_is_none_when_no_coding_profile(self) -> None:
        """Default path (no coding_profile) → _compaction_llm_call is None."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        runtime = ThinRuntime(
            config=RuntimeConfig(model="claude-sonnet-4-20250514"),
            llm_call=self._make_fake_llm(),
        )
        assert runtime._compaction_llm_call is None

    def test_compaction_llm_model_native_config_works_without_coding_profile(
        self,
    ) -> None:
        """codex R1 [6 MAJOR]: native_config["compaction_llm_model"] gives
        Stage 6's compaction cascade a working Tier 2 WITHOUT requiring the
        coding-agent model-tiering machinery at all (no coding_profile)."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        runtime = ThinRuntime(
            config=RuntimeConfig(
                model="gpt-4o",  # no weak_model declared — tiering path is a no-op
                native_config={"compaction_llm_model": "gpt-4o-mini"},
            ),
            llm_call=self._make_fake_llm(),
        )
        assert runtime._compaction_llm_call is not None
        assert callable(runtime._compaction_llm_call)

    def test_compaction_llm_model_absent_is_a_hard_no_op(self) -> None:
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        runtime = ThinRuntime(
            config=RuntimeConfig(model="gpt-4o"),
            llm_call=self._make_fake_llm(),
        )
        assert runtime._compaction_llm_call is None

    async def test_compaction_llm_model_native_config_actually_invokes_aux_model(
        self,
    ) -> None:
        """codex R2 [6]: prove Tier 2 REALLY executes through
        ``native_config["compaction_llm_model"]`` without coding_profile —
        not merely that ``_compaction_llm_call is not None``/``callable``.
        Invokes the resolved adapter directly and asserts the underlying
        raw llm_call was actually called, with the declared aux model name
        forwarded, and its return value passed straight through."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        received_models: list[str] = []

        async def spy_llm(
            messages: list, prompt: str, *, config: object = None, **kwargs: object
        ) -> str:
            if config is not None and hasattr(config, "model"):
                received_models.append(config.model)  # type: ignore[union-attr]
            return "aux-model-summary-output"

        runtime = ThinRuntime(
            config=RuntimeConfig(
                model="gpt-4o",  # no weak_model declared — tiering path is a no-op
                native_config={"compaction_llm_model": "gpt-4o-mini"},
            ),
            llm_call=spy_llm,
        )
        assert runtime._compaction_llm_call is not None

        result = await runtime._compaction_llm_call("summarize this", "dialog text")

        assert received_models == ["gpt-4o-mini"], (
            "aux call must actually reach the underlying llm_call with the "
            f"native_config model, got: {received_models}"
        )
        assert result == "aux-model-summary-output", (
            "adapter must pass the real summarizer output straight through"
        )

    def test_coding_profile_tiering_takes_priority_over_native_config(self) -> None:
        """When BOTH are viable, the pre-existing coding_profile/tiering
        path wins (native_config is a fallback only, never overrides an
        already-resolved weak model)."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        runtime = ThinRuntime(
            config=RuntimeConfig(
                model="claude-sonnet-4-20250514",
                native_config={"compaction_llm_model": "should-not-be-used"},
            ),
            llm_call=self._make_fake_llm(),
            coding_profile=CodingProfileConfig(enable_model_tiering=True),
        )
        assert runtime._compaction_llm_call is not None

    async def test_coding_profile_tiering_priority_uses_tiering_model_not_native_config(
        self,
    ) -> None:
        """codex R2 [6]: the priority test above only asserted non-None —
        strengthen it to assert the SPECIFIC model actually used is the
        coding_profile/tiering-resolved weak model (claude-haiku, per
        production models.yaml's declared weak_model for claude-sonnet-4),
        never the native_config placeholder ("should-not-be-used")."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        received_models: list[str] = []

        async def spy_llm(
            messages: list, prompt: str, *, config: object = None, **kwargs: object
        ) -> str:
            if config is not None and hasattr(config, "model"):
                received_models.append(config.model)  # type: ignore[union-attr]
            return "tiering-summary-output"

        runtime = ThinRuntime(
            config=RuntimeConfig(
                model="claude-sonnet-4-20250514",
                native_config={"compaction_llm_model": "should-not-be-used"},
            ),
            llm_call=spy_llm,
            coding_profile=CodingProfileConfig(enable_model_tiering=True),
        )

        result = await runtime._compaction_llm_call("summarize this", "dialog text")

        assert received_models == ["claude-haiku-3-20250307"], (
            "coding_profile/tiering must win priority over native_config "
            f"when both are viable, got: {received_models}"
        )
        assert result == "tiering-summary-output"

    def test_compaction_llm_call_is_none_when_model_has_no_weak_model(self) -> None:
        """No weak_model declared → _compaction_llm_call is None even with tiering on."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import RuntimeConfig

        # gpt-4o has no weak_model in production models.yaml
        runtime = ThinRuntime(
            config=RuntimeConfig(model="gpt-4o"),
            llm_call=self._make_fake_llm(),
            coding_profile=CodingProfileConfig(enable_model_tiering=True),
        )
        assert runtime._compaction_llm_call is None

    async def test_run_passes_non_none_llm_call_to_filter_when_tiering_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In run(), ConversationCompactionFilter receives llm_call != None when tiering on."""
        import json

        from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        captured: dict[str, object] = {}
        original_init = ConversationCompactionFilter.__init__

        def _spy_init(
            self_f: ConversationCompactionFilter,
            config: object = None,
            llm_call: object = None,
            compression_history: object = None,
        ) -> None:
            captured["llm_call"] = llm_call
            original_init(
                self_f,
                config=config,
                llm_call=llm_call,
                compression_history=compression_history,
            )

        monkeypatch.setattr(ConversationCompactionFilter, "__init__", _spy_init)

        async def _fake_llm(messages: list, prompt: str, **kwargs: object) -> str:
            return json.dumps({"type": "final", "final_message": "done"})

        runtime = ThinRuntime(
            config=RuntimeConfig(
                model="claude-sonnet-4-20250514",
                compaction=CompactionConfig(enabled=True),
            ),
            llm_call=_fake_llm,
            coding_profile=CodingProfileConfig(enable_model_tiering=True),
        )

        async for _ in runtime.run(
            messages=[Message(role="user", content="hello")],
            system_prompt="test",
            active_tools=[],
        ):
            pass

        assert "llm_call" in captured
        assert captured["llm_call"] is not None

    async def test_run_passes_none_llm_call_to_filter_when_tiering_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REQ-RCA-070: llm_call=None is passed to filter when tiering is off (byte-identical)."""
        import json

        from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        captured: dict[str, object] = {"llm_call": "UNSET"}
        original_init = ConversationCompactionFilter.__init__

        def _spy_init(
            self_f: ConversationCompactionFilter,
            config: object = None,
            llm_call: object = None,
            compression_history: object = None,
        ) -> None:
            captured["llm_call"] = llm_call
            original_init(
                self_f,
                config=config,
                llm_call=llm_call,
                compression_history=compression_history,
            )

        monkeypatch.setattr(ConversationCompactionFilter, "__init__", _spy_init)

        async def _fake_llm(messages: list, prompt: str, **kwargs: object) -> str:
            return json.dumps({"type": "final", "final_message": "done"})

        runtime = ThinRuntime(
            config=RuntimeConfig(
                model="claude-sonnet-4-20250514",
                compaction=CompactionConfig(enabled=True),
            ),
            llm_call=_fake_llm,
            coding_profile=CodingProfileConfig(enable_model_tiering=False),
        )

        async for _ in runtime.run(
            messages=[Message(role="user", content="hello")],
            system_prompt="test",
            active_tools=[],
        ):
            pass

        assert captured["llm_call"] is None


# ---------------------------------------------------------------------------
# Integration: build_aux_llm_call through the REAL make_default_llm_call wrapper
# ---------------------------------------------------------------------------


class TestBuildAuxLlmCallWithRealWrapper:
    """Prove weak-model routing through the production make_default_llm_call path.

    This closes the gap left by spy-based tests: if make_default_llm_call ever
    stopped honouring the ``config=`` override (the ``effective = config or
    fallback_config`` path), the spy tests would silently pass but the real
    routing would break.  This test uses the REAL wrapper so that regression
    is impossible to miss.
    """

    async def test_real_make_default_llm_call_honors_weak_model_config_override(
        self,
    ) -> None:
        """build_aux_llm_call + make_default_llm_call → llm_impl receives weak model.

        Drives: make_default_llm_call(fallback_config, llm_impl=<recording fake>)
        so the production ``effective = config or fallback_config`` path is exercised.
        Asserts: the recording fake sees config.model == weak_model (not main model).
        """
        from swarmline.runtime.model_settings import build_aux_llm_call
        from swarmline.runtime.thin.runtime_support import make_default_llm_call
        from swarmline.runtime.types import RuntimeConfig

        recorded: dict[str, str] = {}
        canned_response = "weak-model summary output"

        async def recording_llm_impl(
            config: RuntimeConfig,
            messages: list[dict],
            system_prompt: str,
            **kwargs: object,
        ) -> str:
            # Record the model that the production wrapper selected.
            recorded["model"] = config.model
            recorded["system_prompt"] = system_prompt
            recorded["first_message_content"] = (
                messages[0]["content"] if messages else ""
            )
            return canned_response

        main_model = "claude-sonnet-4-20250514"
        weak_model = "claude-haiku-3-20250307"

        fallback_config = RuntimeConfig(model=main_model)
        # Build the production wrapper exactly as ThinRuntime does.
        raw_llm_call = make_default_llm_call(
            fallback_config, llm_impl=recording_llm_impl
        )

        # Build the aux adapter (the function under test).
        aux = build_aux_llm_call(raw_llm_call, fallback_config, weak_model)

        # Invoke through the full chain.
        result = await aux("summarize this", "dialog text")

        # The canned response must survive the coercion path.
        assert result == canned_response

        # The REAL wrapper must have passed weak_model to llm_impl, not main_model.
        assert recorded["model"] == weak_model, (
            f"Expected llm_impl to receive model={weak_model!r} "
            f"but got {recorded.get('model')!r}. "
            "make_default_llm_call is not honouring the config= override."
        )
        assert recorded["model"] != main_model

        # Sanity: messages and prompt were forwarded correctly.
        assert recorded["first_message_content"] == "dialog text"
        assert recorded["system_prompt"] == "summarize this"
