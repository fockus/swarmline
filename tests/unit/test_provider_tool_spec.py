"""Contract tests for ProviderTool — the provider-executed (hosted) tool spec.

ProviderTool marks a tool as provider-executed (hosted): serialized untouched into the
provider request and run server-side, never locally. These tests pin the frozen-dataclass
contract (fields, defaults, immutability, to_dict serialization) and the dual import path
(domain_types + runtime.thin.native_tools re-export) BEFORE any implementation exists.
"""

from dataclasses import FrozenInstanceError

import pytest

from swarmline.domain_types import ProviderTool


def test_provider_tool_creation_with_defaults_has_empty_config():
    tool = ProviderTool("anthropic", "web_search_20250305")

    assert tool.provider == "anthropic"
    assert tool.type == "web_search_20250305"
    assert tool.name is None
    assert tool.config == {}


def test_provider_tool_is_frozen():
    tool = ProviderTool("anthropic", "web_search_20250305")

    with pytest.raises(FrozenInstanceError):
        tool.type = "code_execution_20250522"


def test_provider_tool_to_dict_omits_none_name_and_empty_config():
    tool = ProviderTool("openai", "web_search_preview")

    assert tool.to_dict() == {"provider": "openai", "type": "web_search_preview"}


def test_provider_tool_to_dict_includes_name_and_config_when_set():
    tool = ProviderTool(
        provider="anthropic",
        type="web_search_20250305",
        name="web_search",
        config={"max_uses": 5, "beta": "code-execution-2025-05-22"},
    )

    assert tool.to_dict() == {
        "provider": "anthropic",
        "type": "web_search_20250305",
        "name": "web_search",
        "config": {"max_uses": 5, "beta": "code-execution-2025-05-22"},
    }


def test_provider_tool_equal_fields_compare_equal_without_config_identity():
    a = ProviderTool(
        "anthropic", "web_search_20250305", name="web_search", config={"max_uses": 5}
    )
    b = ProviderTool(
        "anthropic", "web_search_20250305", name="web_search", config={"max_uses": 5}
    )

    assert a == b
    assert a.config is not b.config


def test_provider_tool_importable_from_domain_and_native_tools():
    from swarmline.runtime.thin.native_tools import ProviderTool as ReExported

    assert ReExported is ProviderTool
