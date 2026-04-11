# Learning Agent — Build and Recall Review Patterns

## Scenario
An agent reviews code over multiple sessions, storing common issues as patterns. In future reviews, it recalls these patterns to catch known anti-patterns proactively.

## Steps

### 1. First Review Session — Discover Patterns
Review code and identify recurring issue:
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "review-patterns", "fact_key": "antipattern-bare-except", "fact_value": "Bare except clauses found 6 times in codebase. Always catch specific exceptions. At minimum use 'except Exception' to avoid catching SystemExit/KeyboardInterrupt." }
```
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "review-patterns", "fact_key": "antipattern-mutable-default", "fact_value": "Mutable default arguments (list/dict) found in 3 functions. Use None as default and create inside function body. Causes shared state bugs across calls." }
```
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "review-patterns", "fact_key": "antipattern-n-plus-1", "fact_value": "N+1 query pattern in user listing endpoint. SQLAlchemy relationships loaded lazily inside loop. Use joinedload() or selectinload() for collection access." }
```

### 2. Store Positive Patterns Too
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "review-patterns", "fact_key": "goodpattern-result-type", "fact_value": "Team uses Result[T, Error] for all service returns. Consistent error handling. Check new code follows this — no raw exception raising in service layer." }
```
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "review-patterns", "fact_key": "goodpattern-repo-naming", "fact_value": "Repository methods: get_by_id, list_by_filter, create, update, delete. No custom names like fetch_user or grab_orders. Enforce consistent naming." }
```

### 3. Save Session Learning Summary
```
MCP tool: swarmline_memory_save_summary
Input: { "user_id": "review-patterns", "session_id": "learning-session-1", "summary": "Identified 3 anti-patterns (bare-except, mutable-default, N+1) and 2 good patterns (Result type, repo naming). Stored for future review sessions." }
```

### 4. Future Review Session — Load Learned Patterns
```
MCP tool: swarmline_memory_get_facts
Input: { "user_id": "review-patterns" }
```
Agent now has a checklist of known patterns to scan for. Apply each pattern to the new code under review.

### 5. Update Patterns When New Ones Emerge
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "review-patterns", "fact_key": "antipattern-sync-in-async", "fact_value": "Synchronous file I/O inside async handlers blocks the event loop. Use aiofiles or run_in_executor. Found in upload and export endpoints." }
```

## Result
The agent builds a growing knowledge base of project-specific patterns. Each review session is more effective than the last because the agent checks against all previously discovered issues.
