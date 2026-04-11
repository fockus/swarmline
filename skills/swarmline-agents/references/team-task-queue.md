# Team Task Queue — Distribute Work Across Agents

## Scenario
A lead agent breaks down a migration project into 10 tasks and distributes them across 3 worker agents based on their capabilities. Tasks are claimed, processed, and tracked to completion.

## Steps

### 1. Register Worker Agents
```
MCP tool: swarmline_team_register_agent
Input: { "agent_id": "worker-frontend", "role": "developer", "capabilities": ["react", "typescript", "css"] }
```
```
MCP tool: swarmline_team_register_agent
Input: { "agent_id": "worker-backend", "role": "developer", "capabilities": ["python", "fastapi", "sqlalchemy"] }
```
```
MCP tool: swarmline_team_register_agent
Input: { "agent_id": "worker-infra", "role": "developer", "capabilities": ["docker", "terraform", "ci-cd"] }
```

### 2. Create Task Backlog
```
MCP tool: swarmline_team_create_task
Input: { "title": "Migrate user API from REST to GraphQL", "description": "Convert /api/users endpoints to GraphQL queries and mutations. Keep REST as deprecated fallback.", "priority": "high" }
```
```
MCP tool: swarmline_team_create_task
Input: { "title": "Update React components for GraphQL", "description": "Replace fetch calls with Apollo Client useQuery/useMutation hooks in UserList, UserProfile, UserSettings.", "priority": "high" }
```
```
MCP tool: swarmline_team_create_task
Input: { "title": "Add GraphQL schema validation to CI", "description": "Add schema linting and breaking change detection to the GitHub Actions pipeline.", "priority": "medium" }
```
```
MCP tool: swarmline_team_create_task
Input: { "title": "Update Docker compose for GraphQL service", "description": "Add graphql-server container, update nginx routing, add health check endpoint.", "priority": "medium" }
```
Continue creating remaining tasks with appropriate priorities.

### 3. Agents Claim Tasks by Capability
```
MCP tool: swarmline_team_claim_task
Input: { "task_id": "task-1", "agent_id": "worker-backend" }
```
```
MCP tool: swarmline_team_claim_task
Input: { "task_id": "task-2", "agent_id": "worker-frontend" }
```
```
MCP tool: swarmline_team_claim_task
Input: { "task_id": "task-3", "agent_id": "worker-infra" }
```

### 4. Monitor Progress
```
MCP tool: swarmline_team_list_tasks
Input: { "status": "in_progress" }
```
```
MCP tool: swarmline_team_list_tasks
Input: { "status": "pending" }
```

### 5. Reassign Stalled Tasks
Check for tasks that have been in_progress too long:
```
MCP tool: swarmline_team_list_tasks
Input: { "status": "in_progress" }
```
If a task is stalled, another agent can claim a pending task instead of waiting.

### 6. Verify Completion
```
MCP tool: swarmline_team_list_tasks
Input: { "status": "done" }
```
Confirm all 10 tasks show "done" status before declaring the migration complete.

## Result
Work is distributed by capability, processed in parallel, and tracked to completion. No task falls through the cracks. The lead agent has full visibility into progress at any time.
