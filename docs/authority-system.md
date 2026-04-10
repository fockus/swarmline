# Authority & Capability System

Controls what agents can do within the agent graph — hiring, delegation, and capability inheritance.

## Overview

Two complementary systems govern agent permissions:

1. **AgentCapabilities** — per-agent permissions within the graph (used by graph nodes)
2. **AgentAuthority** — simplified authority config for HostAdapter spawning

## AgentCapabilities

Defined in `cognitia.multi_agent.graph_types`. Controls graph-level permissions for each agent node.

```python
from cognitia.multi_agent.graph_types import AgentCapabilities

caps = AgentCapabilities(
    can_hire=True,            # Can this agent add new agents to the graph?
    can_delegate=True,        # Can this agent delegate tasks?
    max_children=5,           # Max direct children (None = unlimited)
    max_depth=3,              # Per-agent depth limit (None = use global)
    can_delegate_authority=True,  # Can children also hire sub-agents?
    can_use_subagents=False,  # Runtime subagent capability
    can_use_team_mode=False,  # Runtime team mode capability
)
```

## AgentAuthority

Defined in `cognitia.protocols.host_adapter`. Simplified version for `HostAdapter.spawn_agent()`.

```python
from cognitia.protocols.host_adapter import AgentAuthority

authority = AgentAuthority(
    can_spawn=False,               # Can the spawned agent create sub-agents?
    max_children=0,                # Max sub-agents it can spawn
    max_depth=1,                   # 1 = only direct children
    can_delegate_authority=False,  # Can its children also spawn?
)
```

## Governance Checks

Three governance functions in `cognitia.multi_agent.graph_governance` enforce authority rules:

### `check_hire_allowed(config, parent_node, graph_query) -> str | None`

Checks if an agent can hire a new sub-agent. Validates:
- Dynamic hiring is globally enabled
- Parent has `can_hire` permission
- `max_children` limit not reached
- `max_depth` (global and per-agent) not exceeded
- `max_agents` total limit not reached

Returns `None` if allowed, error message string if denied.

### `check_authority_delegation(parent_caps, child_caps) -> str | None`

Checks if a parent can grant specific capabilities to a child:
- Parent without `can_hire` cannot grant `can_hire` to child
- Parent must have `can_delegate_authority` to grant `can_hire` to child

### `validate_capability_delegation(parent, child_tools, child_skills, child_hooks) -> str | None`

Validates that a child receives only a subset of the parent's capabilities:
- Child tools must be a subset of parent's `allowed_tools`
- Child skills must be a subset of parent's `skills`
- Child hooks must be a subset of parent's `hooks`

Empty parent tuple means "all allowed" (no restriction).

## Example: Org Chart with Authority Levels

```python
from cognitia.multi_agent.graph_builder import GraphBuilder
from cognitia.multi_agent.graph_types import AgentCapabilities, LifecycleMode

graph = (
    GraphBuilder()
    # CEO: full authority
    .add_agent("ceo", role="lead", capabilities=AgentCapabilities(
        can_hire=True,
        can_delegate=True,
        max_children=5,
        max_depth=3,
        can_delegate_authority=True,
    ))
    # VP: can hire, but cannot delegate hiring authority further
    .add_agent("vp-eng", role="lead", capabilities=AgentCapabilities(
        can_hire=True,
        can_delegate=True,
        max_children=3,
        can_delegate_authority=False,
    ))
    # Developer: no hiring, just execution
    .add_agent("dev-1", role="developer", capabilities=AgentCapabilities(
        can_hire=False,
        can_delegate=False,
    ))
    .set_root("ceo")
    .connect("ceo", "vp-eng")
    .connect("vp-eng", "dev-1")
    .build()
)
```

In this structure:
- **CEO** can hire agents and grant hiring authority to children
- **VP Engineering** can hire agents but cannot grant that right further
- **Developer** cannot hire or delegate — execution only
