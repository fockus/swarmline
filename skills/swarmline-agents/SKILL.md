---
name: swarmline-agents
description: Swarmline agent infrastructure — persistent memory, structured plans, team coordination, and code execution for AI coding agents
mcp-servers:
  - name: swarmline
    transport: stdio
    command: swarmline-mcp
    args: ["--mode", "auto"]
---

# Swarmline Agent Infrastructure

You have access to Swarmline tools for agent infrastructure. Use them to enhance your coding workflow with persistent memory, structured planning, team coordination, and safe code execution.

## Quick Start

### Memory — Persist Knowledge Across Sessions
- `swarmline_memory_upsert_fact` — Store a fact (architecture decisions, user preferences, project patterns)
- `swarmline_memory_get_facts` — Recall facts by user_id
- `swarmline_memory_save_message` — Save conversation messages for context continuity
- `swarmline_memory_get_messages` — Retrieve conversation history
- `swarmline_memory_save_summary` — Store session summaries
- `swarmline_memory_get_summary` — Get previous summaries

### Plans — Structured Task Execution
- `swarmline_plan_create` — Create a plan with goal and steps
- `swarmline_plan_get` — Get plan details with step status
- `swarmline_plan_list` — List all plans
- `swarmline_plan_approve` — Approve a plan for execution
- `swarmline_plan_update_step` — Mark steps as in_progress/done/failed

### Team — Multi-Agent Coordination
- `swarmline_team_register_agent` — Register an agent with role and capabilities
- `swarmline_team_list_agents` — List registered agents
- `swarmline_team_create_task` — Create a task with priority
- `swarmline_team_claim_task` — Claim a pending task by agent
- `swarmline_team_list_tasks` — List tasks with status filter

### Code — Safe Execution
- `swarmline_exec_code` — Execute Python code in subprocess with timeout

### Status
- `swarmline_status` — Get server mode and capabilities

### Agents (Full Mode Only — requires API key)
- `swarmline_agent_create` — Create a sub-agent with system prompt
- `swarmline_agent_query` — Query an existing agent
- `swarmline_agent_list` — List created agents

## Usage Patterns

### Pattern 1: Research with Memory
When starting a research task:
1. Check memory for previous findings: `swarmline_memory_get_facts`
2. Store new discoveries as you go: `swarmline_memory_upsert_fact`
3. Save session summary when done: `swarmline_memory_save_summary`

### Pattern 2: Structured Development Plan
For multi-step implementation tasks:
1. Create a plan: `swarmline_plan_create` with steps broken down
2. Approve it: `swarmline_plan_approve`
3. Work through steps, updating status: `swarmline_plan_update_step`
4. Track overall progress: `swarmline_plan_get`

### Pattern 3: Code Review Pipeline
For reviewing multiple files:
1. Register yourself as reviewer: `swarmline_team_register_agent`
2. Create tasks per file: `swarmline_team_create_task`
3. Claim and process tasks: `swarmline_team_claim_task`
4. Store findings in memory: `swarmline_memory_upsert_fact`

### Pattern 4: Cross-Session Continuity
When resuming work across sessions:
1. Load previous summary: `swarmline_memory_get_summary`
2. Check unfinished plans: `swarmline_plan_list`
3. Resume from last completed step: `swarmline_plan_get` + `swarmline_plan_update_step`

### Pattern 5: Safe Code Execution
For running analysis scripts, tests, or data processing:
1. Execute code: `swarmline_exec_code` with timeout
2. Parse stdout result
3. Store results in memory if needed

## Important Notes
- **Headless mode** (default): Memory, plans, team, code execution work without any API key
- **Full mode**: Set ANTHROPIC_API_KEY or OPENAI_API_KEY to enable agent creation
- All state is in-memory per server session — restart clears state
- Use memory tools to persist important findings across steps
- Plans follow a state machine: draft → approved → steps can be updated
- Team tasks follow: pending → in_progress → done/failed
