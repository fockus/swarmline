"""Capability honesty tests (RUNTIME-PARITY-PLAN Workstream F2).

Both directions of the declared capability matrix are enforced against
``RuntimeFactory.validate_agent_config``:

- Overstatement guard: a config option whose capability dimension resolves to
  ``"none"`` for the selected runtime must raise ValueError (no silent drop).
- Understatement guard: a config option whose dimension resolves to at least
  the required level must NOT raise (the matrix must not under-declare what
  validation actually accepts).

The option -> dimension mapping mirrors
``RuntimeFactory._validate_config_against_capabilities``.

The matrix-level invariant that no dimension is dead across all runtimes
already lives in
``tests/unit/test_runtime_capabilities.py::TestBuiltinCapabilities::
test_no_dead_capability_dimensions`` — it is extended here (not duplicated)
by ``test_every_mappable_option_supported_somewhere``, which pins the same
guarantee to the config-mappable subset used by validation.
"""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.agent.config import AgentConfig
from swarmline.runtime.capabilities import (
    get_runtime_capabilities,
    parse_capability_flag,
)
from swarmline.runtime.factory import RuntimeFactory
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.runtime.thin.subagent_tool import SubagentToolConfig
from swarmline.runtime.types import ThinkingConfig

PUBLIC_RUNTIMES: tuple[str, ...] = (
    "thin",
    "claude_sdk",
    "deepagents",
    "cli",
    "openai_agents",
    "pi_sdk",
)

_SUPPORT_ORDER = {"none": 0, "emulated": 1, "native": 2}


async def _allow_everything(
    tool_name: str, tool_input: dict[str, Any], context: Any
) -> Any:
    return {"behavior": "allow"}


def _config_kwargs_for(option: str) -> dict[str, Any]:
    """Minimal AgentConfig kwargs exercising a single mappable option."""
    builders: dict[str, dict[str, Any]] = {
        "mcp_servers": {"mcp_servers": {"srv": {"command": "echo", "args": []}}},
        "output_format": {"output_format": {"type": "object", "properties": {}}},
        "thinking": {"thinking": ThinkingConfig(budget_tokens=1024)},
        "max_budget_usd": {"max_budget_usd": 1.0},
        "resume_session_id": {"resume_session_id": "sess-1"},
        "can_use_tool": {
            "can_use_tool": _allow_everything,
            # the callback is only consulted outside bypassPermissions
            "permission_mode": "default",
        },
        "native_agents": {
            "native_agents": {"helper": {"description": "d", "prompt": "p"}}
        },
        "subagent_config": {"subagent_config": SubagentToolConfig()},
        "coding_profile": {"coding_profile": CodingProfileConfig()},
        "project_instructions": {"project_instructions": True},
    }
    return builders[option]


#: option -> capability requirement flag, mirroring
#: RuntimeFactory._validate_config_against_capabilities.
_OPTION_TO_FLAG: dict[str, str] = {
    "mcp_servers": "mcp",
    "output_format": "structured_output",
    "thinking": "thinking_stream",
    "max_budget_usd": "cost_tracking",
    "resume_session_id": "resume",
    "can_use_tool": "permissions",
    "native_agents": "subagents:native",
    "subagent_config": "subagents",
    "coding_profile": "builtin_tools",
    "project_instructions": "project_instructions",
}

_CASES = [
    pytest.param(runtime, option, id=f"{runtime}-{option}")
    for runtime in PUBLIC_RUNTIMES
    for option in _OPTION_TO_FLAG
]


def _build_config(runtime: str, option: str) -> AgentConfig:
    return AgentConfig(
        system_prompt="test", runtime=runtime, **_config_kwargs_for(option)
    )


def _resolved_meets(runtime: str, option: str, config: AgentConfig) -> bool:
    """Does the runtime's resolved level satisfy the option's requirement?

    Uses resolve() with the constructed config: conditional capabilities
    (deepagents portable narrowing, thin provider narrowing, claude_sdk
    permission-mode narrowing) must be judged against the actual config.
    """
    dimension, min_level = parse_capability_flag(_OPTION_TO_FLAG[option])
    resolved = get_runtime_capabilities(runtime).resolve(config)
    return _SUPPORT_ORDER[resolved.level(dimension)] >= _SUPPORT_ORDER[min_level]


@pytest.mark.parametrize(("runtime", "option"), _CASES)
def test_overstatement_guard(runtime: str, option: str) -> None:
    """Options mapping to an unavailable capability must fail fast."""
    config = _build_config(runtime, option)
    if _resolved_meets(runtime, option, config):
        pytest.skip(
            f"{runtime} provides '{_OPTION_TO_FLAG[option]}' — "
            "covered by the understatement guard"
        )
    with pytest.raises(ValueError, match="unsupported by runtime"):
        RuntimeFactory().validate_agent_config(config)


@pytest.mark.parametrize(("runtime", "option"), _CASES)
def test_understatement_guard(runtime: str, option: str) -> None:
    """Options mapping to a declared capability must pass validation."""
    config = _build_config(runtime, option)
    if not _resolved_meets(runtime, option, config):
        pytest.skip(
            f"{runtime} does not provide '{_OPTION_TO_FLAG[option]}' — "
            "covered by the overstatement guard"
        )
    RuntimeFactory().validate_agent_config(config)  # must not raise


def test_every_mappable_option_supported_somewhere() -> None:
    """Every config-mappable capability is deliverable by >= 1 public runtime.

    Complements test_runtime_capabilities.py::test_no_dead_capability_dimensions
    for the exact (dimension, min_level) pairs validation enforces: an option
    nobody supports would make that AgentConfig field pure poison.
    """
    for option, flag in _OPTION_TO_FLAG.items():
        dimension, min_level = parse_capability_flag(flag)
        capable = [
            runtime
            for runtime in PUBLIC_RUNTIMES
            if _SUPPORT_ORDER[get_runtime_capabilities(runtime).level(dimension)]
            >= _SUPPORT_ORDER[min_level]
        ]
        assert capable, (
            f"No public runtime satisfies '{flag}' required by option '{option}'"
        )


def test_non_strict_mode_degrades_with_warning() -> None:
    """strict_capabilities=False downgrades the overstatement to a warning."""
    config = AgentConfig(
        system_prompt="test",
        runtime="cli",
        mcp_servers={"srv": {"command": "echo", "args": []}},
        strict_capabilities=False,
    )
    with pytest.warns(UserWarning, match="unsupported by runtime"):
        RuntimeFactory().validate_agent_config(config)
