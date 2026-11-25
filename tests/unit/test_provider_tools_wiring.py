"""Stage E1.3: AgentConfig.provider_tools -> RuntimeConfig.provider_tools wiring.

Guards the additive `provider_tools` field on both frozen configs plus the
auto-enable-native derivation in ``build_portable_runtime_plan``: non-empty
``provider_tools`` forces ``use_native_tools=True`` unless the caller set it
explicitly (explicit always wins). Empty ``provider_tools`` (the default)
must reproduce the pre-existing ``use_native_tools`` derivation byte-for-byte
(see ``test_native_tools_wiring.py``).
"""

from __future__ import annotations

import dataclasses

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan
from swarmline.domain_types import ProviderTool
from swarmline.runtime.types import RuntimeConfig

_PT = ProviderTool("anthropic", "web_search_20250305", name="web_search")


def _rc(cfg: AgentConfig):
    # PortableRuntimePlan.config IS the RuntimeConfig (runtime_wiring.py:24).
    return build_portable_runtime_plan(cfg, "thin").config


def test_agent_config_provider_tools_defaults_empty() -> None:
    assert AgentConfig(system_prompt="x").provider_tools == ()


def test_runtime_config_provider_tools_defaults_empty() -> None:
    assert RuntimeConfig(runtime_name="thin").provider_tools == ()


def test_build_plan_copies_provider_tools_into_runtime_config() -> None:
    cfg = AgentConfig(system_prompt="x", runtime="thin", provider_tools=(_PT,))
    assert _rc(cfg).provider_tools == (_PT,)


def test_provider_tools_auto_enable_native_when_mode_prompt() -> None:
    cfg = AgentConfig(
        system_prompt="x",
        runtime="thin",
        structured_mode="prompt",
        use_native_tools=None,
        provider_tools=(_PT,),
    )
    assert _rc(cfg).use_native_tools is True


def test_explicit_use_native_tools_false_overrides_provider_tools_autoenable() -> None:
    cfg = AgentConfig(
        system_prompt="x",
        runtime="thin",
        structured_mode="prompt",
        use_native_tools=False,
        provider_tools=(_PT,),
    )
    assert _rc(cfg).use_native_tools is False


def test_no_provider_tools_preserves_legacy_native_derivation() -> None:
    cfg = AgentConfig(
        system_prompt="x",
        runtime="thin",
        structured_mode="prompt",
        provider_tools=(),
    )
    assert _rc(cfg).use_native_tools is False


def test_runtime_config_provider_tools_is_last_field() -> None:
    # Regression: provider_tools MUST be the last field. RuntimeConfig is not
    # frozen -- inserting it mid-struct shifts every subsequent field's
    # positional slot, silently corrupting any existing positional
    # RuntimeConfig(...) construction (review finding, fix-cycle).
    assert dataclasses.fields(RuntimeConfig)[-1].name == "provider_tools"


def test_agent_config_provider_tools_is_last_field() -> None:
    # Same invariant on AgentConfig (frozen, but positional construction still
    # depends on field order) -- pinned so a future edit can't reintroduce a
    # mid-struct insertion.
    assert dataclasses.fields(AgentConfig)[-1].name == "provider_tools"
