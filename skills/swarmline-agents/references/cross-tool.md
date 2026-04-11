# Cross-Tool Integration — Plans + Memory + Tasks for Feature Development

## Scenario
Implement a user notification feature end-to-end. Use plans for structure, tasks for work breakdown, and memory for decisions and patterns discovered during implementation.

## Steps

### 1. Load Prior Context
```
MCP tool: swarmline_memory_get_facts
Input: { "user_id": "project-acme" }
```
Retrieve architecture decisions (e.g., "use Result type", "one repo per aggregate").

### 2. Create Feature Plan
```
MCP tool: swarmline_plan_create
Input: {
  "goal": "Implement user notification system with email and in-app channels",
  "steps": [
    "Define NotificationPort protocol and NotificationEvent domain type",
    "Implement InAppNotificationAdapter with SQLite storage",
    "Implement EmailNotificationAdapter with SMTP client",
    "Create NotificationService application layer with channel routing",
    "Add API endpoints: POST /notifications, GET /notifications/{user_id}",
    "Write integration tests for both adapters",
    "Wire into DI container and verify production startup"
  ]
}
```
```
MCP tool: swarmline_plan_approve
Input: { "plan_id": "plan-1" }
```

### 3. Create Parallel Work Tasks
```
MCP tool: swarmline_team_create_task
Input: { "title": "Define domain types and protocol", "description": "NotificationPort, NotificationEvent, NotificationChannel enum", "priority": "high" }
```
```
MCP tool: swarmline_team_create_task
Input: { "title": "Implement InAppNotificationAdapter", "description": "SQLite-backed, implements NotificationPort", "priority": "high" }
```
```
MCP tool: swarmline_team_create_task
Input: { "title": "Implement EmailNotificationAdapter", "description": "SMTP client, implements NotificationPort", "priority": "medium" }
```

### 4. Execute with Progress Tracking
```
MCP tool: swarmline_plan_update_step
Input: { "plan_id": "plan-1", "step_index": 0, "status": "in_progress" }
```
```
MCP tool: swarmline_team_claim_task
Input: { "task_id": "task-1", "agent_id": "dev-agent" }
```
While implementing, store a discovered pattern:
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "project-acme", "fact_key": "pattern-notification-routing", "fact_value": "Route by user preference stored in UserSettings. Default: in-app. Premium users: email + in-app. Use strategy pattern." }
```

### 5. Mark Progress Across All Three Systems
```
MCP tool: swarmline_plan_update_step
Input: { "plan_id": "plan-1", "step_index": 0, "status": "done" }
```
Continue through remaining plan steps and tasks, storing decisions in memory as they arise.

### 6. Final Summary
```
MCP tool: swarmline_memory_save_summary
Input: { "user_id": "project-acme", "session_id": "notification-feature", "summary": "Notification system complete. 2 adapters (in-app, email), strategy-based routing, 94% test coverage. Wired into DI. Ready for review." }
```

## Result
A fully implemented feature with tracked progress, discoverable decisions, and a summary that future sessions can use to understand the notification system architecture.
