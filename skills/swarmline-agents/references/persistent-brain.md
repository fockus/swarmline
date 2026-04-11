# Persistent Brain — Architecture Decision Memory

## Scenario
Store architecture decisions, coding conventions, and project-specific patterns so they persist across coding sessions. New sessions start by loading this knowledge instead of re-discovering it.

## Steps

### 1. Store Architecture Decision
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "project-acme", "fact_key": "arch-db-choice", "fact_value": "PostgreSQL chosen over MongoDB. Reason: relational integrity for financial data, ACID compliance, team expertise." }
```

### 2. Store Coding Convention
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "project-acme", "fact_key": "convention-error-handling", "fact_value": "All service methods return Result[T, AppError]. Never raise exceptions across module boundaries. Use match/case at API layer." }
```

### 3. Store Discovered Pattern
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "project-acme", "fact_key": "pattern-repo-layer", "fact_value": "Repository classes accept SQLAlchemy AsyncSession via constructor. One repo per aggregate root. No raw SQL outside repos." }
```

### 4. Save Session Summary
```
MCP tool: swarmline_memory_save_summary
Input: { "user_id": "project-acme", "session_id": "session-2026-03-29", "summary": "Established DB layer patterns. Created UserRepo and OrderRepo. Added Result type to shared module. All tests green." }
```

### 5. New Session — Load Brain
```
MCP tool: swarmline_memory_get_summary
Input: { "user_id": "project-acme", "session_id": "session-2026-03-29" }
```
```
MCP tool: swarmline_memory_get_facts
Input: { "user_id": "project-acme" }
```
The agent now has full context: DB choice rationale, error handling convention, repository pattern, and last session's progress.

## Result
Zero ramp-up time for new sessions. Architecture decisions are never forgotten or contradicted. Conventions stay consistent across all code changes.
