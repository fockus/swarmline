"""Fix A/C: AgentConfig → RuntimeConfig propagation of use_native_tools + max_iterations.

These guard the single-knob public surface: ``structured_mode`` drives native tools,
``use_native_tools`` is an optional advanced override, and ``max_turns`` lifts the react
iteration budget (``max_iterations``). Both wiring paths must behave identically.
"""

from __future__ import annotations

import pytest

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan


def _rc(cfg: AgentConfig):
    # PortableRuntimePlan.config IS the RuntimeConfig (runtime_wiring.py:24).
    return build_portable_runtime_plan(cfg, "thin").config


@pytest.mark.parametrize(
    "mode,expected", [("auto", True), ("native", True), ("prompt", False)]
)
def test_use_native_tools_derived_from_structured_mode(
    mode: str, expected: bool
) -> None:
    cfg = AgentConfig(system_prompt="x", runtime="thin", structured_mode=mode)
    assert _rc(cfg).use_native_tools is expected


def test_explicit_use_native_tools_overrides_derive() -> None:
    cfg = AgentConfig(
        system_prompt="x",
        runtime="thin",
        structured_mode="auto",
        use_native_tools=False,
    )
    assert _rc(cfg).use_native_tools is False


def test_max_turns_maps_to_max_iterations() -> None:
    cfg = AgentConfig(system_prompt="x", runtime="thin", max_turns=20)
    assert _rc(cfg).max_iterations == 20


def test_max_iterations_defaults_to_six_without_max_turns() -> None:
    cfg = AgentConfig(system_prompt="x", runtime="thin")
    assert _rc(cfg).max_iterations == 6


def test_build_runtime_config_path_matches_wiring() -> None:
    cfg = AgentConfig(
        system_prompt="x", runtime="thin", structured_mode="auto", max_turns=15
    )
    rc = Agent(cfg)._build_runtime_config("thin", cfg)
    assert rc.use_native_tools is True
    assert rc.max_iterations == 15
