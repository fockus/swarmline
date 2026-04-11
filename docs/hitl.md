# Human-in-the-Loop

Swarmline provides a pluggable approval system that lets you pause agent execution and request human confirmation before sensitive actions proceed. The HITL module ships with built-in policies, an approval gate middleware, and first-class integration with every supported runtime.

## Overview

The approval flow has three parts:

1. **ApprovalPolicy** decides *whether* an action needs approval (based on action type, tool name, estimated cost, or custom logic).
2. **ApprovalCallback** obtains the decision from a human (CLI prompt, web UI, Slack bot, or any async channel).
3. **ApprovalGate** ties them together: check the policy, call the callback if needed, return the verdict.

```
Agent action -> ApprovalGate.check()
                  |
                  +-- Policy says "no approval needed" -> proceed
                  |
                  +-- Policy says "approval required"
                        |
                        +-- Callback asks human -> ApprovalResponse
                              |
                              +-- approved=True  -> proceed
                              +-- approved=False -> deny (or raise ApprovalDeniedError)
```

## Quick Start

```python
from swarmline.hitl.gate import ApprovalGate
from swarmline.hitl.policies import ToolApprovalPolicy
from swarmline.hitl.types import ApprovalRequest, ApprovalResponse


# 1. Define a callback (how you ask the human)
class CliApprovalCallback:
    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        print(f"\n--- Approval Required ---")
        print(f"Action:      {request.action}")
        print(f"Description: {request.description}")
        if request.tool_name:
            print(f"Tool:        {request.tool_name}")
            print(f"Args:        {request.tool_args}")
        if request.estimated_cost_usd is not None:
            print(f"Est. cost:   ${request.estimated_cost_usd:.2f}")

        answer = input("Approve? [y/N]: ").strip().lower()
        return ApprovalResponse(
            approved=answer in ("y", "yes"),
            reason="" if answer in ("y", "yes") else "Human denied",
        )


# 2. Pick a policy
policy = ToolApprovalPolicy(tools=frozenset({"execute_code", "write_file"}))

# 3. Wire up the gate
gate = ApprovalGate(policy=policy, callback=CliApprovalCallback())

# 4. Use before sensitive actions
approved = await gate.check(
    "tool_call",
    {"tool_name": "execute_code", "tool_args": {"code": "rm -rf /tmp/data"}},
    description="Execute shell command that deletes files",
)
if approved:
    # proceed with the tool call
    ...
```

## Approval Policies

A policy is any object implementing the `ApprovalPolicy` protocol:

```python
class ApprovalPolicy(Protocol):
    def requires_approval(self, action: str, context: dict[str, Any]) -> bool: ...
```

### Built-in policies

| Policy | Module | Behavior |
|--------|--------|----------|
| `AlwaysApprovePolicy` | `swarmline.hitl.policies` | Never requires approval (fully autonomous) |
| `AlwaysDenyPolicy` | `swarmline.hitl.policies` | Always requires approval (safest mode) |
| `ToolApprovalPolicy` | `swarmline.hitl.policies` | Requires approval only for named tools |
| `CostApprovalPolicy` | `swarmline.hitl.policies` | Requires approval when estimated cost exceeds a threshold |

### AlwaysApprovePolicy

The agent runs without interruption. Useful for trusted environments or batch processing.

```python
from swarmline.hitl.policies import AlwaysApprovePolicy

policy = AlwaysApprovePolicy()
policy.requires_approval("tool_call", {})  # False
policy.requires_approval("plan_step", {})  # False
```

### AlwaysDenyPolicy

Every action is paused for approval. Use this during development or for high-risk deployments.

```python
from swarmline.hitl.policies import AlwaysDenyPolicy

policy = AlwaysDenyPolicy()
policy.requires_approval("tool_call", {})  # True
policy.requires_approval("plan_step", {})  # True
```

### ToolApprovalPolicy

Require approval only when the agent calls specific tools. Non-tool actions pass through.

```python
from swarmline.hitl.policies import ToolApprovalPolicy

policy = ToolApprovalPolicy(tools=frozenset({"execute_code", "write_file", "send_email"}))

# Triggers approval
policy.requires_approval("tool_call", {"tool_name": "execute_code"})  # True

# Passes through (tool not in the list)
policy.requires_approval("tool_call", {"tool_name": "web_search"})  # False

# Non-tool actions always pass through
policy.requires_approval("plan_step", {"tool_name": "execute_code"})  # False
```

### CostApprovalPolicy

Require approval when the estimated cost exceeds a USD threshold. Works with any action type.

```python
from swarmline.hitl.policies import CostApprovalPolicy

policy = CostApprovalPolicy(threshold_usd=0.50)

policy.requires_approval("query", {"estimated_cost_usd": 1.00})  # True
policy.requires_approval("query", {"estimated_cost_usd": 0.10})  # False
policy.requires_approval("query", {})                             # False (no cost info)
```

## ApprovalGate

`ApprovalGate` is the middleware that connects a policy and a callback. It builds an `ApprovalRequest` from the action context, passes it to the callback, and returns the verdict.

```python
from swarmline.hitl.gate import ApprovalGate, ApprovalDeniedError

gate = ApprovalGate(policy=my_policy, callback=my_callback)

# Returns True (approved or no approval needed) / False (denied)
ok = await gate.check("tool_call", {"tool_name": "execute_code"})

# Or raise on denial instead of returning False
try:
    await gate.check(
        "tool_call",
        {"tool_name": "execute_code", "tool_args": {"code": "..."}},
        description="Run user-supplied code",
        raise_on_deny=True,
    )
except ApprovalDeniedError as e:
    print(f"Denied: {e}")
    print(f"Request: {e.request}")
    print(f"Response: {e.response}")
```

### Context fields

The `context` dict passed to `gate.check()` can contain:

| Key | Type | Used by |
|-----|------|---------|
| `tool_name` | `str` | `ToolApprovalPolicy`, mapped to `ApprovalRequest.tool_name` |
| `tool_args` | `dict` | Mapped to `ApprovalRequest.tool_args` |
| `estimated_cost_usd` | `float` | `CostApprovalPolicy`, mapped to `ApprovalRequest.estimated_cost_usd` |

Any additional keys are stored in `ApprovalRequest.context` for custom policies.

## Integration with Runtimes

Swarmline surfaces HITL events uniformly across all runtimes through `RuntimeEvent` and `StreamEvent`.

### RuntimeEvent types

Two event types support HITL:

| Event type | Purpose | Key data fields |
|------------|---------|-----------------|
| `approval_required` | The runtime requests tool/action approval | `action_name`, `args`, `allowed_decisions`, `interrupt_id`, `description` |
| `user_input_requested` | The runtime requests free-form human input | `prompt`, `interrupt_id` |

```python
from swarmline.domain_types import RuntimeEvent

# Emitting an approval request (used inside runtime adapters)
event = RuntimeEvent.approval_required(
    action_name="edit_file",
    args={"path": "app.py"},
    allowed_decisions=["approve", "edit", "reject"],
    interrupt_id="int-001",
    description="Review file edit before applying",
)

# Emitting a free-form input request
event = RuntimeEvent.user_input_requested(
    prompt="What database password should I use?",
    interrupt_id="int-002",
)
```

### Runtime capabilities

Each runtime declares whether it supports HITL natively via the `supports_hitl` flag in `RuntimeCapabilities`. Use this to check at configuration time:

```python
from swarmline.runtime.capabilities import RuntimeCapabilities

caps = RuntimeCapabilities(supports_hitl=True)
assert caps.supports("hitl")
```

### DeepAgents (LangGraph) runtime

The DeepAgents runtime has native HITL support through LangGraph's interrupt mechanism. When the graph pauses for human review, Swarmline translates the interrupt payloads into standard `RuntimeEvent` objects.

**Configuration requirement:** LangGraph interrupts require a checkpointer. Swarmline validates this at startup and emits a clear error if `interrupt_on` is configured without a checkpointer:

```python
from swarmline.runtime.deepagents_hitl import validate_hitl_config

# This will return an error — interrupt_on without checkpointer
error = validate_hitl_config({"interrupt_on": {"edit_file": True}})
# error.kind == "capability_unsupported"
# error.message contains "checkpointer"

# This is valid — checkpointer is present
error = validate_hitl_config({
    "interrupt_on": {"edit_file": True},
    "checkpointer": my_checkpointer,
})
# error is None
```

**Interrupt-to-event mapping:**

| LangGraph interrupt payload | Swarmline event |
|-----------------------------|----------------|
| `{"action_requests": [...], "review_configs": [...]}` | `approval_required` (one per action) |
| `str` (plain text prompt) | `user_input_requested` |
| Other | `native_notice` (unrecognized payload warning) |

Example of how a LangGraph interrupt becomes Swarmline events:

```python
# LangGraph emits an interrupt with action_requests + review_configs:
# {
#     "action_requests": [{"name": "edit_file", "args": {"path": "app.py"}, "description": "Review file edit"}],
#     "review_configs": [{"action_name": "edit_file", "allowed_decisions": ["approve", "edit", "reject"]}],
# }
#
# Swarmline translates this into:
# RuntimeEvent(
#     type="approval_required",
#     data={
#         "action_name": "edit_file",
#         "args": {"path": "app.py"},
#         "allowed_decisions": ["approve", "edit", "reject"],
#         "interrupt_id": "interrupt-1",
#         "description": "Review file edit",
#     }
# )
```

### Thin runtime

The Thin runtime does not have native interrupt support. Use `ApprovalGate` as application-level middleware in your tool or hook handlers:

```python
from swarmline.hitl.gate import ApprovalGate
from swarmline.hitl.policies import ToolApprovalPolicy

gate = ApprovalGate(
    policy=ToolApprovalPolicy(tools=frozenset({"execute_code"})),
    callback=my_callback,
)

# In a PreToolUse hook or tool wrapper:
approved = await gate.check(
    "tool_call",
    {"tool_name": "execute_code", "tool_args": args},
    description="Execute user code in sandbox",
)
if not approved:
    return "Action denied by human reviewer"
```

### Claude Agent SDK runtime

The Claude Agent SDK runtime handles approvals through its own hook system (`PreToolUse` / `PostToolUse`). Swarmline's hook registry integrates with it:

```python
from swarmline.hooks.registry import HookRegistry

hooks = HookRegistry()

# Register a pre-tool hook that checks approval
async def approval_hook(tool_name: str, tool_input: dict) -> dict | None:
    approved = await gate.check(
        "tool_call",
        {"tool_name": tool_name, "tool_args": tool_input},
    )
    if not approved:
        return {"denied": True}  # Signal denial to the runtime
    return None  # Proceed

hooks.on_pre_tool_use(approval_hook, matcher="execute_code")
```

### Multi-agent graph orchestrator

The `GraphOrchestrator` accepts an optional `approval_gate` parameter. When set, it checks approval before delegating work to any agent:

```python
from swarmline.multi_agent.graph_orchestrator import GraphOrchestrator

orchestrator = GraphOrchestrator(
    graph=agent_graph,
    task_board=task_board,
    agent_runner=runner,
    approval_gate=gate,  # ApprovalGate instance
)

# Before delegating to an agent, the orchestrator calls:
#   gate.check("delegate", {"agent_id": "...", "goal": "..."})
# If denied, the execution is marked FAILED with "Denied by approval gate"
```

## Custom Approval Handlers

### Protocol

Any class implementing `ApprovalCallback` works as a handler:

```python
from swarmline.hitl.types import ApprovalCallback, ApprovalRequest, ApprovalResponse


class SlackApprovalCallback:
    """Send approval requests to a Slack channel and wait for reaction."""

    def __init__(self, channel: str, slack_client: Any) -> None:
        self._channel = channel
        self._client = slack_client

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        msg = await self._client.post_message(
            self._channel,
            text=(
                f"*Approval Required*\n"
                f"Action: `{request.action}`\n"
                f"Tool: `{request.tool_name or 'N/A'}`\n"
                f"Description: {request.description}\n"
                f"React with :white_check_mark: to approve or :x: to deny"
            ),
        )
        reaction = await self._client.wait_for_reaction(msg.ts, timeout=300)

        return ApprovalResponse(
            approved=reaction == "white_check_mark",
            reason=f"Slack reaction: {reaction}",
        )
```

### Custom policies

Implement the `ApprovalPolicy` protocol for domain-specific rules:

```python
from swarmline.hitl.types import ApprovalPolicy


class BusinessHoursPolicy:
    """Require approval outside business hours."""

    def requires_approval(self, action: str, context: dict) -> bool:
        from datetime import datetime
        hour = datetime.now().hour
        return hour < 9 or hour >= 18


class SensitiveDataPolicy:
    """Require approval when tools access PII tables."""

    SENSITIVE_TABLES = frozenset({"users", "payments", "credentials"})

    def requires_approval(self, action: str, context: dict) -> bool:
        if action != "tool_call":
            return False
        args = context.get("tool_args", {})
        query = str(args.get("query", "")).lower()
        return any(table in query for table in self.SENSITIVE_TABLES)
```

### Composing policies

Combine multiple policies with simple logic:

```python
class CompositePolicy:
    """Require approval if ANY sub-policy says so."""

    def __init__(self, *policies: ApprovalPolicy) -> None:
        self._policies = policies

    def requires_approval(self, action: str, context: dict) -> bool:
        return any(p.requires_approval(action, context) for p in self._policies)


policy = CompositePolicy(
    ToolApprovalPolicy(tools=frozenset({"execute_code"})),
    CostApprovalPolicy(threshold_usd=1.00),
    BusinessHoursPolicy(),
)
```

## Examples

### Gating expensive operations

```python
from swarmline.hitl.gate import ApprovalGate
from swarmline.hitl.policies import CostApprovalPolicy

gate = ApprovalGate(
    policy=CostApprovalPolicy(threshold_usd=0.50),
    callback=CliApprovalCallback(),
)

# Before an expensive LLM call
approved = await gate.check(
    "llm_call",
    {"estimated_cost_usd": 2.35, "model": "claude-opus-4-20250514"},
    description="Large context query (~$2.35 estimated)",
)
```

### Processing approval events from a stream

When consuming agent output through the streaming API, handle HITL events inline:

```python
from swarmline import Agent, AgentConfig

agent = Agent(AgentConfig(runtime="deepagents"))

async for event in agent.stream("Refactor the codebase"):
    if event.type == "approval_required":
        print(f"Agent wants to: {event.text}")
        print(f"Tool: {event.tool_name}, Args: {event.tool_input}")
        print(f"Options: {event.allowed_decisions}")
        # Resume with the user's decision via the runtime's resume mechanism
        ...

    elif event.type == "user_input_requested":
        print(f"Agent asks: {event.text}")
        # Provide the answer and resume
        ...

    elif event.type == "text_delta":
        print(event.text, end="", flush=True)
```

### Raising on denial

Use `raise_on_deny=True` when denial should abort the entire operation:

```python
from swarmline.hitl.gate import ApprovalDeniedError, ApprovalGate

gate = ApprovalGate(policy=my_policy, callback=my_callback)

try:
    await gate.check(
        "tool_call",
        {"tool_name": "delete_database", "tool_args": {"db": "production"}},
        description="DROP all tables in production database",
        raise_on_deny=True,
    )
    # If we get here, the human approved
    await delete_database("production")
except ApprovalDeniedError as e:
    logger.warning("Operation denied: %s", e)
    # e.request — the ApprovalRequest that was denied
    # e.response — the ApprovalResponse with reason
```

### ApprovalResponse with modifications

The human can approve with modifications, allowing the agent to adjust its action:

```python
class ReviewAndModifyCallback:
    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        print(f"Tool: {request.tool_name}")
        print(f"Args: {request.tool_args}")

        choice = input("[a]pprove / [m]odify / [d]eny: ").strip().lower()

        if choice == "a":
            return ApprovalResponse(approved=True)
        elif choice == "m":
            # Let the human adjust arguments
            new_path = input(f"New path (was {request.tool_args.get('path')}): ")
            return ApprovalResponse(
                approved=True,
                modifications={"path": new_path},
            )
        else:
            reason = input("Reason for denial: ")
            return ApprovalResponse(approved=False, reason=reason)
```

## API Reference

### Types (`swarmline.hitl.types`)

| Class | Description |
|-------|-------------|
| `ApprovalRequest` | Frozen dataclass: `action`, `description`, `tool_name`, `tool_args`, `estimated_cost_usd`, `context` |
| `ApprovalResponse` | Frozen dataclass: `approved`, `reason`, `modifications` |
| `ApprovalCallback` | Protocol with `async request_approval(ApprovalRequest) -> ApprovalResponse` |
| `ApprovalPolicy` | Protocol with `requires_approval(action, context) -> bool` |

### Gate (`swarmline.hitl.gate`)

| Class | Description |
|-------|-------------|
| `ApprovalGate` | Middleware: `__init__(policy, callback)`, `async check(action, context, *, description, raise_on_deny) -> bool` |
| `ApprovalDeniedError` | Exception with `.request` and `.response` attributes |

### Policies (`swarmline.hitl.policies`)

| Class | Parameters | Logic |
|-------|------------|-------|
| `AlwaysApprovePolicy` | none | Always returns `False` (no approval needed) |
| `AlwaysDenyPolicy` | none | Always returns `True` (approval always needed) |
| `ToolApprovalPolicy` | `tools: frozenset[str]` | `True` when `action == "tool_call"` and `tool_name` is in the set |
| `CostApprovalPolicy` | `threshold_usd: float` | `True` when `estimated_cost_usd > threshold` |

### RuntimeEvent helpers (`swarmline.domain_types`)

| Factory method | Event type |
|----------------|------------|
| `RuntimeEvent.approval_required(action_name, args, allowed_decisions, interrupt_id, description)` | `"approval_required"` |
| `RuntimeEvent.user_input_requested(prompt, interrupt_id)` | `"user_input_requested"` |

### DeepAgents HITL (`swarmline.runtime.deepagents_hitl`)

| Function | Description |
|----------|-------------|
| `validate_hitl_config(native_config)` | Returns `RuntimeErrorData` if `interrupt_on` is set without a `checkpointer`, else `None` |
| `build_interrupt_events(chunk)` | Converts LangGraph `__interrupt__` payloads into a list of `RuntimeEvent` objects |
