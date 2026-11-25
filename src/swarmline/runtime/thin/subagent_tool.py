"""Subagent tool: spawn_agent ToolSpec + executor for LLM-initiated subagents.

Provides SUBAGENT_TOOL_SPEC (the ToolSpec registered with the runtime)
and create_subagent_executor() which returns an async callable that the
ToolExecutor invokes when the LLM calls spawn_agent.

Design:
- max_depth guard prevents infinite recursion
- All errors → JSON, executor NEVER raises
- Tool inheritance: LLM selects tools by name from parent_tools
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from swarmline.domain_types import ToolSpec
from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.tools.types import SandboxConfig

if TYPE_CHECKING:
    from swarmline.governance.protocols import SecretBoundaryPort
    from swarmline.policy.toolset_policy import ToolsetPolicy


@dataclass(frozen=True)
class SubagentToolConfig:
    """Configuration for the spawn_agent tool."""

    max_concurrent: int = 4
    max_worktrees: int = 5
    max_depth: int = 3
    timeout_seconds: float = 300.0
    base_path: str | None = None
    background_timeout: float | None = None
    sandbox_config: SandboxConfig | None = None


SUBAGENT_TOOL_SPEC = ToolSpec(
    name="spawn_agent",
    description="Spawn a child agent to execute a subtask",
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task for the child agent to execute",
            },
            "system_prompt": {
                "type": "string",
                "description": "System prompt for the child agent",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names the child agent can use (defaults to all parent tools)",
            },
            "isolation": {
                "type": "string",
                "enum": ["worktree"],
                "description": "Isolation mode for child agent. 'worktree' runs in a dedicated git worktree.",
            },
            "run_in_background": {
                "type": "boolean",
                "description": "If true, spawn agent in background and return immediately with agent_id.",
            },
            "runtime_name": {
                "type": "string",
                "description": (
                    "Named runtime to spawn the subagent on, resolved via RuntimeRegistry "
                    "(e.g. 'thin', 'codex', 'claude_sdk'). When omitted, the default thin "
                    "runtime is used."
                ),
            },
        },
        "required": ["task"],
    },
    is_local=True,
)


MONITOR_AGENT_TOOL_SPEC = ToolSpec(
    name="monitor_agent",
    description="Check status and retrieve output of a background agent",
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "The agent_id returned by spawn_agent with run_in_background=true",
            },
        },
        "required": ["agent_id"],
    },
    is_local=True,
)

# Tool names that must never be advertised to a spawned child: no production
# path today wires a real executor for them into the child's own runtime
# (`_ThinWorkerRuntime.run()` never forwards `subagent_config`), so inheriting
# them (legacy full-inheritance, or a policy that happens to include them)
# would advertise a tool the child cannot actually call. Stripped from
# `child_tools` unconditionally, in every branch below.
_CHILD_UNADVERTISABLE_TOOLS: frozenset[str] = frozenset(
    {SUBAGENT_TOOL_SPEC.name, MONITOR_AGENT_TOOL_SPEC.name}
)

# Arguments that express a HOST limit, never a model choice. None of them is in
# `SUBAGENT_TOOL_SPEC` today, so a well-behaved model never sends one — but a
# schema that grows later, or a model that guesses, must not be able to widen
# its own timeout, pick its own routing, or reset its own recursion depth.
# Rejected loudly rather than dropped: a silently ignored `timeout` looks to the
# model like a limit it successfully raised.
_HOST_CONTROLLED_ARGS: frozenset[str] = frozenset(
    {"timeout", "timeout_seconds", "routing", "depth", "current_depth", "max_depth"}
)


def _json_error(error: str, agent_id: str | None = None) -> str:
    """Build a JSON error response."""
    payload: dict[str, Any] = {"status": "error", "error": error}
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return json.dumps(payload)


def create_subagent_executor(
    orchestrator: Any,
    config: SubagentToolConfig,
    parent_tools: list[ToolSpec],
    current_depth: int = 0,
    allowed_runtimes: frozenset[str] | None = None,
    toolset_policy: ToolsetPolicy | None = None,
    spawn_role: str = "default",
    secret_boundary: SecretBoundaryPort | None = None,
) -> Callable[[dict[str, Any]], Coroutine[Any, Any, str]]:
    """Create an async callable that spawns a child agent via the orchestrator.

    Args:
        orchestrator: ThinSubagentOrchestrator (or compatible duck-type).
        config: SubagentToolConfig with limits.
        parent_tools: Tools available to the parent — child inherits a subset.
        current_depth: Current recursion depth (0 = top-level agent).
        allowed_runtimes: Explicit allowlist for LLM-initiated runtime selection
            (RCA-SEC-01). Default None = DEFAULT-DENY: any LLM-provided
            runtime_name is rejected. Pass a non-empty frozenset to permit
            specific runtimes. The trusted programmatic SubagentSpec path is
            NOT affected by this gate.
        toolset_policy: Role→allowed-tool-names policy for LLM-initiated spawns
            (REQ-ORC-040/041/042). Default None preserves LEGACY full
            inheritance: an LLM `spawn_agent` call with no `tools=` argument
            gets the parent's entire toolset (opt-in security — unchanged
            behavior for callers that do not wire a policy). When a policy IS
            provided, the no-`tools=` branch DEFAULT-DENIES full inheritance
            and resolves to `toolset_policy.allowed_tools(spawn_role)`
            (intersected with what the parent actually has) instead. Explicit
            `tools=` requests are always intersected with the policy set when
            one is wired in. The trusted programmatic SubagentSpec path
            (`SubagentSpec.tools` set directly by host code via
            `orchestrator.spawn(spec, ...)`) is NOT affected by this gate.
            Regardless of policy/legacy branch, `spawn_agent`/`monitor_agent`
            are always stripped from the resolved child tools — no production
            path today wires a working executor for them into a spawned
            child, so advertising them would offer the child a tool it cannot
            actually call.
        spawn_role: Role name used to look up the toolset policy entry
            (e.g. "researcher"). Ignored when `toolset_policy` is None.
        secret_boundary: Optional secret/injection scanner (REQ-ORC-044)
            applied to the child's raw return before it is embedded in the
            JSON response — an untrusted subagent's return is treated as
            untrusted content whether it completed (`result.output`) OR
            failed (`result.status.error`): a failed child's exception text
            can just as easily echo a leaked secret or an injection marker
            picked up from a tool. Default None preserves legacy behavior
            (both fields returned as-is, byte-identical for callers that do
            not wire a boundary).

    Returns:
        Async callable(args: dict) -> str (always valid JSON, never raises).
    """
    tools_by_name: dict[str, ToolSpec] = {t.name: t for t in parent_tools}

    async def _execute(args: dict[str, Any]) -> str:
        agent_id: str | None = None
        try:
            # --- depth guard ---
            if current_depth >= config.max_depth:
                return _json_error(
                    f"Maximum subagent depth ({config.max_depth}) exceeded. "
                    f"Current depth: {current_depth}."
                )

            # --- host-controlled arguments are not the model's to set ---
            supplied_host_args = sorted(_HOST_CONTROLLED_ARGS & set(args))
            if supplied_host_args:
                return _json_error(
                    "argument(s) "
                    + ", ".join(repr(a) for a in supplied_host_args)
                    + " are host-controlled and cannot be set by the caller model."
                )

            # --- validate task ---
            task = args.get("task")
            if not task or not str(task).strip():
                return _json_error(
                    "Missing required argument: 'task' must be a non-empty string."
                )

            task = str(task).strip()
            system_prompt = str(
                args.get("system_prompt", "You are a helpful assistant")
            ).strip()

            # --- resolve tools (default-deny, REQ-ORC-041) ---
            # An ABSENT policy is an EMPTY allowlist, not "inherit everything".
            # Both branches below resolve against the same set, so naming tools
            # explicitly cannot buy what the policy does not grant — otherwise
            # the default would be bypassable by typing tool names.
            policy_allowed = (
                toolset_policy.allowed_tools(spawn_role)
                if toolset_policy is not None
                else frozenset()
            )
            requested_names: list[str] | None = args.get("tools")
            if requested_names is not None:
                names = [
                    n
                    for n in requested_names
                    if n in tools_by_name and n in policy_allowed
                ]
                child_tools = [tools_by_name[n] for n in names]
            else:
                child_tools = [t for t in parent_tools if t.name in policy_allowed]

            # --- strip tools with no working child-side executor (REQ-ORC-043) ---
            child_tools = [
                t for t in child_tools if t.name not in _CHILD_UNADVERTISABLE_TOOLS
            ]

            # --- isolation mode (optional) ---
            isolation: str | None = args.get("isolation")

            # --- run_in_background flag ---
            run_in_background: bool = bool(args.get("run_in_background", False))

            # --- named runtime (optional, REQ-RCA-050) ---
            runtime_name: str | None = args.get("runtime_name") or None

            # --- allowlist gate (RCA-SEC-01): default-deny at the LLM boundary ---
            # Trusted host code sets SubagentSpec.runtime_name directly (bypasses
            # this gate). Only LLM-provided values arrive here.
            if runtime_name is not None:
                if not allowed_runtimes or runtime_name not in allowed_runtimes:
                    permitted = sorted(allowed_runtimes) if allowed_runtimes else []
                    return _json_error(
                        f"runtime '{runtime_name}' is not permitted for agent-initiated "
                        f"spawns; allowed: {{{', '.join(repr(r) for r in permitted)}}}"
                    )

            # --- build spec & spawn ---
            spec_kwargs: dict[str, Any] = {
                "name": f"subagent-depth-{current_depth + 1}",
                "system_prompt": system_prompt,
                "tools": child_tools,
                "depth": current_depth + 1,
            }
            if isolation is not None:
                spec_kwargs["isolation"] = isolation
            if run_in_background:
                spec_kwargs["run_in_background"] = True
            if config.sandbox_config is not None:
                spec_kwargs["sandbox_config"] = config.sandbox_config
            if runtime_name is not None:
                spec_kwargs["runtime_name"] = runtime_name
            spec = SubagentSpec(**spec_kwargs)
            agent_id = await orchestrator.spawn(spec, task)

            # --- background: return immediately ---
            if run_in_background:
                return json.dumps(
                    {
                        "agent_id": agent_id,
                        "status": "spawned",
                        "message": "Agent spawned in background. Use monitor_agent to check status.",
                    }
                )

            # --- foreground: wait with timeout ---
            result = await asyncio.wait_for(
                orchestrator.wait(agent_id),
                timeout=config.timeout_seconds,
            )

            # --- map result to JSON ---
            state = result.status.state
            if state == "failed":
                error_text = result.status.error or "Unknown error"
                if secret_boundary is not None:
                    error_text = secret_boundary.redact(error_text)
                return json.dumps(
                    {
                        "agent_id": result.agent_id,
                        "status": "failed",
                        "error": error_text,
                    }
                )

            output = result.output
            if secret_boundary is not None:
                output = secret_boundary.redact(output)

            return json.dumps(
                {
                    "agent_id": result.agent_id,
                    "status": "completed",
                    "result": output,
                }
            )

        except asyncio.TimeoutError:
            if agent_id is not None:
                await orchestrator.cancel(agent_id)
            return _json_error(
                f"Timeout: subagent did not complete within {config.timeout_seconds}s.",
                agent_id=agent_id,
            )
        except Exception as exc:
            return _json_error(str(exc), agent_id=agent_id)

    return _execute


def create_monitor_executor(
    orchestrator: Any,
    secret_boundary: SecretBoundaryPort | None = None,
) -> Callable[[dict[str, Any]], Coroutine[Any, Any, str]]:
    """Create the monitor_agent tool executor.

    Checks status and retrieves output of a background agent
    via MONITOR_AGENT_TOOL_SPEC.

    Args:
        orchestrator: ThinSubagentOrchestrator (or compatible duck-type).
        secret_boundary: Optional secret/injection scanner (REQ-ORC-044),
            mirroring `create_subagent_executor`'s parameter — a background
            agent monitored via `monitor_agent` is the SAME untrusted child
            as one monitored via the foreground `spawn_agent` wait path, so
            its `output`/`error`/`result` fields get the same scan before
            being embedded in the JSON response. Default None preserves
            legacy raw passthrough.

    Returns:
        Async callable(args: dict) -> str (always valid JSON, never raises).
    """

    async def _execute(args: dict[str, Any]) -> str:
        try:
            agent_id = args.get("agent_id")
            if not agent_id or not str(agent_id).strip():
                return _json_error(
                    "Missing required argument: 'agent_id' must be a non-empty string."
                )

            agent_id = str(agent_id).strip()
            status = await orchestrator.get_status(agent_id)
            output = orchestrator.get_output(agent_id)
            if secret_boundary is not None:
                output = secret_boundary.redact(output)

            payload: dict[str, Any] = {
                "agent_id": agent_id,
                "state": status.state,
                "output": output,
            }
            if status.error is not None:
                error_text = status.error
                if secret_boundary is not None:
                    error_text = secret_boundary.redact(error_text)
                payload["error"] = error_text
            if status.result is not None:
                result_text = status.result
                if secret_boundary is not None:
                    result_text = secret_boundary.redact(result_text)
                payload["result"] = result_text

            return json.dumps(payload)
        except Exception as exc:
            return _json_error(str(exc))

    return _execute
