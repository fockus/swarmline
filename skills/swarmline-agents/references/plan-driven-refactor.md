# Plan-Driven Refactor — Step-by-Step Execution with Progress Tracking

## Scenario
Refactor authentication from session-based to JWT tokens across a web application. Use a structured plan to ensure every step is completed and verified before moving to the next.

## Steps

### 1. Create Detailed Refactoring Plan
```
MCP tool: swarmline_plan_create
Input: {
  "goal": "Migrate authentication from session-based to JWT. Zero downtime. Both mechanisms work during transition.",
  "steps": [
    "Add JWT utility module: generate_token, verify_token, refresh_token with RS256",
    "Create JWTAuthMiddleware that accepts both session cookies and Bearer tokens",
    "Update login endpoint to return JWT alongside session cookie (dual mode)",
    "Add /auth/refresh endpoint for token renewal",
    "Update all protected API endpoints to use new middleware",
    "Add integration tests for JWT flow: login, access, refresh, expiry",
    "Update frontend to store and send JWT in Authorization header",
    "Monitor dual-mode for 1 week, then remove session fallback",
    "Remove session-related code and database session table",
    "Update API documentation with new auth flow"
  ]
}
```

### 2. Approve and Begin
```
MCP tool: swarmline_plan_approve
Input: { "plan_id": "plan-1" }
```
```
MCP tool: swarmline_plan_update_step
Input: { "plan_id": "plan-1", "step_index": 0, "status": "in_progress" }
```

### 3. Complete Step and Verify
After implementing JWT utility module:
```
MCP tool: swarmline_exec_code
Input: {
  "code": "import subprocess\nresult = subprocess.run(['python', '-m', 'pytest', 'tests/unit/test_jwt_utils.py', '-v'], capture_output=True, text=True, timeout=30)\nprint(result.stdout)\nprint(result.stderr)",
  "timeout": 35
}
```
Tests pass — mark step done:
```
MCP tool: swarmline_plan_update_step
Input: { "plan_id": "plan-1", "step_index": 0, "status": "done" }
```

### 4. Store Decision Made During Implementation
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "auth-refactor", "fact_key": "jwt-key-rotation", "fact_value": "RS256 key pair rotated via JWKS endpoint. Old keys valid for 24h after rotation. Key ID (kid) in token header for lookup." }
```

### 5. Handle a Failed Step
If step 5 (update endpoints) fails tests:
```
MCP tool: swarmline_plan_update_step
Input: { "plan_id": "plan-1", "step_index": 4, "status": "failed" }
```
Fix the issue, then retry:
```
MCP tool: swarmline_plan_update_step
Input: { "plan_id": "plan-1", "step_index": 4, "status": "in_progress" }
```
After fix:
```
MCP tool: swarmline_plan_update_step
Input: { "plan_id": "plan-1", "step_index": 4, "status": "done" }
```

### 6. Check Overall Progress
```
MCP tool: swarmline_plan_get
Input: { "plan_id": "plan-1" }
```
Response shows which steps are done, in_progress, or pending. Provides a clear picture of remaining work.

## Result
A zero-downtime auth migration executed with full traceability. Every step verified before proceeding. Failed steps are retried without losing progress on completed work. Decisions made during implementation are preserved in memory.
