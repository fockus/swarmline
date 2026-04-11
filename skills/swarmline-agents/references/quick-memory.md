# Quick Memory — Simple Fact Storage and Retrieval

## Scenario
Store quick reference facts during a coding session — API keys location, database schema notes, deployment commands — and retrieve them instantly when needed.

## Steps

### 1. Store Project Configuration Facts
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "dev-quickref", "fact_key": "db-connection", "fact_value": "PostgreSQL on port 5433 (non-standard). DB name: acme_dev. Schema: public + audit. Migrations in alembic/versions/." }
```
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "dev-quickref", "fact_key": "deploy-staging", "fact_value": "Deploy to staging: git push origin main triggers CI. Manual deploy: ./scripts/deploy.sh staging. Takes ~3 min. Health check: GET /api/health" }
```
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "dev-quickref", "fact_key": "api-auth-flow", "fact_value": "JWT with RS256. Access token: 15 min. Refresh token: 7 days. Keys in /etc/acme/keys/ on prod, env var JWT_PRIVATE_KEY locally." }
```

### 2. Store User Preferences
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "dev-quickref", "fact_key": "user-pref-style", "fact_value": "Prefers functional style over OOP. Use dataclasses not classes. Avoid inheritance, prefer composition. Type hints on all public functions." }
```

### 3. Recall a Specific Fact Later
```
MCP tool: swarmline_memory_get_facts
Input: { "user_id": "dev-quickref" }
```
Returns all stored facts. Agent can filter by key prefix to find relevant ones.

### 4. Update a Fact When It Changes
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "dev-quickref", "fact_key": "db-connection", "fact_value": "PostgreSQL on port 5432 (changed from 5433 after infra update). DB name: acme_dev. Schema: public + audit + analytics (new). Migrations in alembic/versions/." }
```
Upsert overwrites the previous value for the same key.

### 5. Save End-of-Day Summary
```
MCP tool: swarmline_memory_save_summary
Input: { "user_id": "dev-quickref", "session_id": "daily-2026-03-29", "summary": "Fixed auth token refresh bug. Updated DB port after infra migration. Added analytics schema. All tests passing." }
```

## Result
A lightweight personal knowledge base that eliminates the need to re-discover project details. Facts are updated in place when things change. Summaries provide session-level context.
