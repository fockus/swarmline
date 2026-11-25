"""I-097 — contract: "validated => translated => accepted" (re-audit 2026-07-04).

The 2026-07-04 runtime-parity re-audit found a systematic bug class:
an AgentConfig field passes capability validation and is then silently lost
in the AgentConfig -> RuntimeConfig translation ("validated, then dropped"),
or crashes a runtime constructor with an opaque TypeError. Root cause: three
surfaces (validator pairs, wiring translation, runtime constructors) with no
contract test forcing them to agree. This module is that contract.

Contract per (field, portable runtime) pair:
  1. If validation rejects the field -> loud ValueError, contract satisfied.
  2. If validation passes -> the field MUST leave an observable trace in the
     portable plan (RuntimeConfig / create_kwargs / active_tools), OR the pair
     is listed in the KNOWN_DROPPED ledger below (each entry maps to a backlog
     item). The ledger only shrinks: once a pair becomes observable the test
     fails until the entry is removed.
  3. factory.create(plan) must never raise TypeError — either a runtime
     instance or a loud ValueError. TypeError pairs live in CREATE_CRASHES
     with the same shrink-only discipline.

Surface covered here: the portable path (build_portable_runtime_plan ->
RuntimeFactory.create). The claude_sdk one-shot dispatch surface had its own
asymmetry (thinking/sandbox/max_thinking_tokens/output_type lost vs the
conversation path), tracked as I-099 and fixed in
tests/unit/test_sdk_query.py::TestStreamOneShotQueryParityOptions and
tests/unit/test_runtime_dispatch.py::TestStreamClaudeOneShotParity
(stream_one_shot_query now accepts thinking/sandbox/max_thinking_tokens and
stream_claude_one_shot derives output_format from output_type via
_effective_output_format). claude_sdk is not a portable runtime, so it does
not join PORTABLE_RUNTIMES / the ledgers in this module — the fix lives in
its own parity-guard tests instead of here.
"""

from __future__ import annotations

from typing import Any

import pytest
from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import (
    PortableRuntimePlan,
    build_portable_runtime_plan,
)
from swarmline.agent.tool import tool
from swarmline.commands.registry import CommandRegistry
from swarmline.hooks.registry import HookRegistry
from swarmline.runtime.factory import RuntimeFactory
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.runtime.thin.subagent_tool import SubagentToolConfig
from swarmline.runtime.types import ModelRequestOptions, ThinkingConfig

PORTABLE_RUNTIMES = ("thin", "deepagents", "openai_agents", "pi_sdk", "cli", "temporal")


@tool("contract_probe")
async def _probe_tool(text: str) -> str:
    """Echo probe tool for the translation contract."""
    return text


async def _probe_can_use_tool(tool_name: str, tool_input: dict, context: Any) -> Any:
    return {"behavior": "allow"}


def _probes() -> dict[str, dict[str, Any]]:
    """Field -> AgentConfig kwargs. Values chosen to pass validation where the
    capability is declared, so the drop (not the value) is what's under test."""
    return {
        "tools": {"tools": (_probe_tool.__tool_definition__,)},
        "mcp_servers": {"mcp_servers": {"srv": {"url": "https://mcp.example.com/sse"}}},
        "hooks": {"hooks": HookRegistry()},
        "command_registry": {"command_registry": CommandRegistry()},
        "subagent_config": {"subagent_config": SubagentToolConfig(), "cwd": "/tmp"},
        "coding_profile": {"coding_profile": CodingProfileConfig(enabled=True)},
        "thinking": {"thinking": ThinkingConfig(budget_tokens=1024)},
        "max_budget_usd": {"max_budget_usd": 1.5},
        "resume_session_id": {"resume_session_id": "sess-0001"},
        "can_use_tool": {"can_use_tool": _probe_can_use_tool},
        "native_agents": {"native_agents": {"helper": object()}},
        "base_url": {"base_url": "https://proxy.example.com/v1"},
        "api_key": {"api_key": "sk-contract-probe"},
        "max_turns": {"max_turns": 7},
        "output_format": {
            "output_format": {"type": "object", "properties": {"a": {"type": "string"}}}
        },
        "request_options": {"request_options": ModelRequestOptions(temperature=0.2)},
        # claude_sdk-specific fields: no capability dimension exists, so they
        # silently no-op on every portable runtime today (see ledgers below).
        "env": {"env": {"SWARMLINE_CONTRACT_PROBE": "1"}},
        "betas": {"betas": ("context-1m",)},
        "fallback_model": {"fallback_model": "haiku"},
        "fork_session": {"fork_session": True},
        "sandbox": {"sandbox": {"enabled": True}},
        "max_thinking_tokens": {"max_thinking_tokens": 2048},
        "cwd": {"cwd": "/tmp"},
    }


# ---------------------------------------------------------------------------
# Ledgers — the audited state of the world (2026-07-04). Shrink-only:
# fixing a drop makes the pair observable and this test then demands the
# entry's removal. Never add entries without a backlog item.
# ---------------------------------------------------------------------------

# (runtime, field) -> backlog item. Field passes validation, leaves no trace.
KNOWN_DROPPED: dict[tuple[str, str], str] = {
    # temporal cannot wire resume_session_id: the client never knows the
    # workflow run_id (worker-first design) -- this is a declaration/design
    # gap (I-101), not the "validated, then dropped" translation bug (I-098a
    # fixed the other portable-path pairs; see I-098a Stage 1 in the plan).
    ("temporal", "resume_session_id"): "I-101",
    ("pi_sdk", "coding_profile"): "I-103",
    # env has no capability dimension (I-101 declarations gap): only the
    # subprocess runtimes (pi_sdk, cli) translate it; the rest stay silently
    # dropped until I-101 gives env a capability to validate against.
    ("thin", "env"): "I-101",
    ("deepagents", "env"): "I-101",
    ("openai_agents", "env"): "I-101",
    ("temporal", "env"): "I-101",
}

# Fields with no capability dimension: silently ignored on every portable
# runtime (I-101 declarations; I-102 cwd). Partial fixes must move
# the remaining pairs into KNOWN_DROPPED.
DROPPED_EVERYWHERE: dict[str, str] = {
    "betas": "I-101",
    "fallback_model": "I-101",
    "fork_session": "I-101",
    "sandbox": "I-101",
    "max_thinking_tokens": "I-101",
    "cwd": "I-102",
}

# (runtime, field) -> backlog item. factory.create raises TypeError because
# the constructor does not accept the translated kwarg (I-100).
CREATE_CRASHES: dict[tuple[str, str], str] = {
    ("deepagents", "hooks"): "I-100",
    ("openai_agents", "hooks"): "I-100",
    ("pi_sdk", "hooks"): "I-100",
    ("cli", "hooks"): "I-100",
    ("deepagents", "command_registry"): "I-100",
    ("openai_agents", "command_registry"): "I-100",
    ("pi_sdk", "command_registry"): "I-100",
    ("cli", "command_registry"): "I-100",
}


def _build_plan(config: AgentConfig, runtime_name: str) -> PortableRuntimePlan:
    return build_portable_runtime_plan(config, runtime_name)


def _plans_differ(plan: PortableRuntimePlan, baseline: PortableRuntimePlan) -> bool:
    return (
        plan.config != baseline.config
        or plan.create_kwargs.keys() != baseline.create_kwargs.keys()
        or plan.create_kwargs != baseline.create_kwargs
        or plan.active_tools != baseline.active_tools
    )


@pytest.mark.parametrize("runtime_name", PORTABLE_RUNTIMES)
@pytest.mark.parametrize("field", sorted(_probes()))
def test_validated_field_is_translated_or_ledgered(
    runtime_name: str, field: str
) -> None:
    """A field that passes validation must be observable in the plan."""
    probes = _probes()
    baseline = _build_plan(
        AgentConfig(system_prompt="probe", runtime=runtime_name), runtime_name
    )
    config = AgentConfig(system_prompt="probe", runtime=runtime_name, **probes[field])
    try:
        plan = _build_plan(config, runtime_name)
    except ValueError:
        return  # loud rejection — contract satisfied

    observable = _plans_differ(plan, baseline)
    pair = (runtime_name, field)
    ledger_ref = KNOWN_DROPPED.get(pair) or DROPPED_EVERYWHERE.get(field)

    if observable and ledger_ref is not None:
        pytest.fail(
            f"'{field}' on runtime='{runtime_name}' is now translated — "
            f"remove the {ledger_ref} ledger entry from this contract."
        )
    assert observable or ledger_ref is not None, (
        f"validated-then-dropped: '{field}' passed capability validation on "
        f"runtime='{runtime_name}' but left no trace in the portable plan "
        f"(RuntimeConfig / create_kwargs / active_tools). Either translate it, "
        f"reject it loudly, or ledger it against a backlog item."
    )


# Fields whose translated kwargs actually reach runtime constructors; the
# remaining probes only alter RuntimeConfig, which every constructor accepts.
_CREATE_FIELDS = ("baseline", "tools", "mcp_servers", "hooks", "command_registry")


@pytest.mark.parametrize("runtime_name", PORTABLE_RUNTIMES)
@pytest.mark.parametrize("field", _CREATE_FIELDS)
def test_factory_create_never_raises_typeerror(runtime_name: str, field: str) -> None:
    """factory.create(plan) yields a runtime or a loud ValueError — never TypeError."""
    kwargs = {} if field == "baseline" else _probes()[field]
    config = AgentConfig(system_prompt="probe", runtime=runtime_name, **kwargs)
    try:
        plan = _build_plan(config, runtime_name)
    except ValueError:
        return  # rejected before creation — contract satisfied

    factory = RuntimeFactory()
    pair = (runtime_name, field)
    try:
        runtime = factory.create(config=plan.config, **plan.create_kwargs)
    except ValueError:
        return  # loud fail-fast — contract satisfied
    except ImportError as exc:  # optional runtime dependency absent
        pytest.skip(f"optional dependency missing for {runtime_name}: {exc}")
    except TypeError as exc:
        if pair in CREATE_CRASHES:
            return  # audited crash (I-100) — ledgered until fixed
        pytest.fail(
            f"constructor contract violation: factory.create for "
            f"runtime='{runtime_name}' with '{field}' raised TypeError ({exc}) "
            f"instead of accepting the kwarg or failing with ValueError."
        )
    if pair in CREATE_CRASHES:
        pytest.fail(
            f"'{field}' on runtime='{runtime_name}' no longer crashes — "
            f"remove the {CREATE_CRASHES[pair]} ledger entry from this contract."
        )
    assert runtime is not None
