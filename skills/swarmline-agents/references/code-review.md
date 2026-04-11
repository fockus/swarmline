# Code Review Pipeline — Systematic Multi-File Review

## Scenario
Systematically review 8 changed files in a pull request using a task queue. Each file gets a dedicated review task with findings stored in memory for the final summary.

## Steps

### 1. Register Reviewer Agent
```
MCP tool: swarmline_team_register_agent
Input: { "agent_id": "reviewer-main", "role": "code-reviewer", "capabilities": ["python", "security", "performance"] }
```

### 2. Create Review Tasks from Changed Files
```
MCP tool: swarmline_team_create_task
Input: { "title": "Review src/auth/handlers.py", "description": "Check auth flow, token validation, error responses. Verify no secrets in code.", "priority": "high" }
```
```
MCP tool: swarmline_team_create_task
Input: { "title": "Review src/auth/middleware.py", "description": "Check middleware ordering, async safety, request context propagation.", "priority": "high" }
```
```
MCP tool: swarmline_team_create_task
Input: { "title": "Review src/db/migrations/042_add_roles.py", "description": "Check migration reversibility, index usage, data preservation.", "priority": "medium" }
```
Repeat for remaining 5 files with appropriate descriptions.

### 3. Process Tasks Sequentially
```
MCP tool: swarmline_team_claim_task
Input: { "task_id": "task-1", "agent_id": "reviewer-main" }
```
Review the file, then store finding:
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "pr-review-147", "fact_key": "handlers-issue-1", "fact_value": "CRITICAL: JWT secret loaded from env at import time, not per-request. Will fail in serverless cold start. Line 23." }
```
Mark task done and move to next:
```
MCP tool: swarmline_team_claim_task
Input: { "task_id": "task-2", "agent_id": "reviewer-main" }
```

### 4. Generate Review Summary
```
MCP tool: swarmline_memory_get_facts
Input: { "user_id": "pr-review-147" }
```
Compile all findings into a structured review comment with severity levels.

### 5. Track Review Completion
```
MCP tool: swarmline_team_list_tasks
Input: { "status": "done" }
```
Verify all 8 tasks completed before submitting the review.

## Result
Every file receives focused attention. No files are skipped. All findings are persisted and aggregated into a comprehensive review with zero information loss.
