# Research Swarm — Multi-Agent Parallel Research

## Scenario
Three agents independently research different aspects of a technology (API design, performance characteristics, security model), then aggregate findings into a unified summary stored in memory.

## Steps

### 1. Register Research Agents
```
MCP tool: swarmline_team_register_agent
Input: { "agent_id": "researcher-api", "role": "researcher", "capabilities": ["api-analysis", "documentation-review"] }
```
```
MCP tool: swarmline_team_register_agent
Input: { "agent_id": "researcher-perf", "role": "researcher", "capabilities": ["benchmarking", "profiling"] }
```
```
MCP tool: swarmline_team_register_agent
Input: { "agent_id": "researcher-sec", "role": "researcher", "capabilities": ["security-audit", "threat-modeling"] }
```

### 2. Create Research Tasks
```
MCP tool: swarmline_team_create_task
Input: { "title": "Analyze FastAPI async patterns", "description": "Review FastAPI middleware, dependency injection, and async handler patterns. Document strengths and gotchas.", "priority": "high" }
```
```
MCP tool: swarmline_team_create_task
Input: { "title": "Benchmark FastAPI vs Starlette", "description": "Compare request throughput, memory usage, and cold start time under 1k concurrent connections.", "priority": "high" }
```
```
MCP tool: swarmline_team_create_task
Input: { "title": "Audit FastAPI security defaults", "description": "Review CORS, CSRF, auth middleware defaults. Identify gaps vs OWASP top 10.", "priority": "high" }
```

### 3. Agents Claim and Execute Tasks
```
MCP tool: swarmline_team_claim_task
Input: { "task_id": "task-1", "agent_id": "researcher-api" }
```
Each agent works independently, storing intermediate findings:
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "research-project", "fact_key": "fastapi-async-gotcha", "fact_value": "Background tasks do not propagate request context — use contextvars explicitly" }
```

### 4. Aggregate Findings
```
MCP tool: swarmline_memory_get_facts
Input: { "user_id": "research-project" }
```
Combine all facts into a structured summary:
```
MCP tool: swarmline_memory_save_summary
Input: { "user_id": "research-project", "session_id": "fastapi-research-2026", "summary": "API: strong DI, watch async context. Perf: 12k rps, 45MB baseline. Security: CORS permissive by default, add rate limiting." }
```

## Result
Three independent research streams produce a consolidated knowledge base. Future sessions retrieve the summary and facts without re-researching.
