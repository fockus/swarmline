"""Tests provider/model resolver for DeepAgents."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest
from cognitia.runtime.deepagents_models import (
    DeepAgentsModelError,
    build_deepagents_chat_model,
    resolve_deepagents_model,
)


def _make_provider_module(class_name: str, sink: dict[str, Any]) -> ModuleType:
    """Create fake provider module with modelnym klassom."""
    module = ModuleType(f"fake_{class_name.lower()}")

    class FakeModel:
        def __init__(self, **kwargs: Any) -> None:
            sink["kwargs"] = kwargs

    setattr(module, class_name, FakeModel)
    return module


class TestResolveDeepAgentsModel:
    """resolve_deepagents_model — provider-aware model resolution."""

    def test_resolve_registry_alias_google(self) -> None:
        """Alias from ModelRegistry rezolvitsya in supported google provider."""
        resolved = resolve_deepagents_model("gemini")
        assert resolved.provider == "google"
        assert resolved.model_name == "gemini-2.5-pro"

    def test_resolve_prefixed_provider_model(self) -> None:
        """Prefiks provider:model supportssya yavno."""
        resolved = resolve_deepagents_model("google_genai:gemini-2.5-flash")
        assert resolved.provider == "google"
        assert resolved.model_name == "gemini-2.5-flash"

    def test_resolve_unknown_provider_raises_typed_error(self) -> None:
        """Notpodderzhivaemyy provider -> capability_unsupported."""
        with pytest.raises(DeepAgentsModelError) as exc:
            resolve_deepagents_model("mistral:mistral-large")

        assert exc.value.error.kind == "capability_unsupported"
        assert "mistral" in exc.value.error.message.lower()


class TestBuildDeepAgentsChatModel:
    """build_deepagents_chat_model — provider-specific builder."""

    def test_builds_anthropic_model_with_base_url(self) -> None:
        """Anthropic builder gets model and base_url."""
        captured: dict[str, Any] = {}
        fake_module = _make_provider_module("ChatAnthropic", captured)

        with patch.dict(sys.modules, {"langchain_anthropic": fake_module}):
            model = build_deepagents_chat_model("sonnet", base_url="https://proxy.test")

        assert type(model).__name__ == "FakeModel"
        assert captured["kwargs"] == {
            "model": "claude-sonnet-4-20250514",
            "base_url": "https://proxy.test",
        }

    def test_builds_openai_model_with_base_url(self) -> None:
        """OpenAI builder gets model and base_url."""
        captured: dict[str, Any] = {}
        fake_module = _make_provider_module("ChatOpenAI", captured)

        with patch.dict(sys.modules, {"langchain_openai": fake_module}):
            model = build_deepagents_chat_model("openai:gpt-4o", base_url="https://proxy.test")

        assert type(model).__name__ == "FakeModel"
        assert captured["kwargs"] == {
            "model": "gpt-4o",
            "base_url": "https://proxy.test",
        }

    def test_builds_google_model_without_base_url(self) -> None:
        """Google builder gets tolko model."""
        captured: dict[str, Any] = {}
        fake_module = _make_provider_module("ChatGoogleGenerativeAI", captured)

        with patch.dict(sys.modules, {"langchain_google_genai": fake_module}):
            model = build_deepagents_chat_model("google_genai:gemini-2.5-flash")

        assert type(model).__name__ == "FakeModel"
        assert captured["kwargs"] == {"model": "gemini-2.5-flash"}

    def test_google_base_url_rejected_with_typed_error(self) -> None:
        """Google path not prinimaet base_url silently."""
        with pytest.raises(DeepAgentsModelError) as exc:
            build_deepagents_chat_model(
                "google_genai:gemini-2.5-flash",
                base_url="https://proxy.test",
            )

        assert exc.value.error.kind == "capability_unsupported"
        assert "base_url" in exc.value.error.message

    def test_missing_provider_package_raises_dependency_error(self) -> None:
        """Missing provider package -> dependency_missing."""
        with (
            patch.dict(sys.modules, {"langchain_openai": None}),
            pytest.raises(DeepAgentsModelError) as exc,
        ):
            build_deepagents_chat_model("openai:gpt-4o")

        assert exc.value.error.kind == "dependency_missing"
        assert "langchain-openai" in exc.value.error.message
