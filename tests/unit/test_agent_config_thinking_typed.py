"""Stage 17 (T3.5) — AgentConfig.thinking accepts both dict (deprecated) and the
typed ``ThinkingConfig`` dataclass.

Reality check: ``ThinkingConfigEnabled`` / ``ThinkingConfigAdaptive`` /
``ThinkingConfigDisabled`` from ``runtime.options_builder`` are TypedDicts
(re-exported from claude_agent_sdk). They cannot be ``isinstance``-checked at
runtime — they are dicts. The typed dataclass alternative for users is
``swarmline.runtime.types.ThinkingConfig`` (the domain dataclass), which has a
single ``budget_tokens`` field.

This stage:
1. Accepts ``AgentConfig.thinking`` as either dict (deprecated, warning fires)
   or the domain ``ThinkingConfig`` dataclass.
2. Converts dataclass → dict internally so downstream consumers still see dict.
3. Emits ``DeprecationWarning`` when a raw dict is passed.
"""

from __future__ import annotations

import warnings

from swarmline.agent.config import AgentConfig
from swarmline.runtime.types import ThinkingConfig


def test_thinking_default_is_none() -> None:
    cfg = AgentConfig(system_prompt="x")
    assert cfg.thinking is None


def test_thinking_dict_is_accepted_with_deprecation_warning() -> None:
    """Passing a dict still works in v1.5.0 but raises DeprecationWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = AgentConfig(
            system_prompt="x",
            thinking={"type": "enabled", "budget_tokens": 4096},
        )
    assert any(issubclass(w.category, DeprecationWarning) for w in caught), (
        "expected a DeprecationWarning when passing thinking= as a dict"
    )
    # Dict is preserved as-is for downstream consumers.
    assert cfg.thinking == {"type": "enabled", "budget_tokens": 4096}


def test_thinking_dataclass_accepted_no_warning() -> None:
    """The domain ThinkingConfig dataclass is the v1.5 preferred form."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = AgentConfig(
            system_prompt="x",
            thinking=ThinkingConfig(budget_tokens=2048),
        )
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations == [], "no deprecation warning expected for typed dataclass"
    # Dataclass is converted to the canonical dict form for downstream consumers.
    assert cfg.thinking == {"type": "enabled", "budget_tokens": 2048}


def test_thinking_dataclass_default_budget() -> None:
    """ThinkingConfig() with default budget_tokens → enabled with that default."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        cfg = AgentConfig(system_prompt="x", thinking=ThinkingConfig())
    assert isinstance(cfg.thinking, dict)
    assert cfg.thinking["type"] == "enabled"
    assert cfg.thinking["budget_tokens"] == 10_000  # ThinkingConfig default


def test_thinking_dict_adaptive_preserved() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        cfg = AgentConfig(system_prompt="x", thinking={"type": "adaptive"})
    assert cfg.thinking == {"type": "adaptive"}


def test_thinking_dict_disabled_preserved() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        cfg = AgentConfig(system_prompt="x", thinking={"type": "disabled"})
    assert cfg.thinking == {"type": "disabled"}


def test_thinking_config_dataclass_exported_from_runtime_types() -> None:
    """The dataclass form is re-exported from swarmline.runtime.types."""
    cfg = ThinkingConfig(budget_tokens=512)
    assert cfg.budget_tokens == 512
