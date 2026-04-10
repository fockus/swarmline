# Full Competitive Analysis: Swarmline vs 7 Agent Frameworks

**Date:** 2026-03-30
**Frameworks analyzed:** CrewAI, AutoGen, OpenAI Agents SDK, Claude Agent SDK, Semantic Kernel, Swarms, LangGraph Swarm
**Purpose:** Internal positioning for Swarmline (formerly Cognitia)

## Key Findings

### Swarmline unique advantages (no competitor has all of these):
- Clean Architecture with 20+ ISP protocols (≤5 methods each)
- Default-deny tool policy + CostBudget + GuardrailContext in OSS
- Episodic + Procedural memory + Consolidation pipeline
- Knowledge Bank with 5 ISP protocols and multi-backend search
- Graph Agents with governance (capabilities, permissions, limits)
- Pipeline Engine with budget gates
- 3200+ tests, 89%+ coverage, contract tests

### Frameworks entering maintenance mode (opportunity):
- AutoGen → Microsoft Agent Framework (Q1 2026 GA target)
- Semantic Kernel → Microsoft Agent Framework
- Both losing new features, communities migrating

### Biggest competitive threats:
1. CrewAI — 47K stars, $18M funding, Andrew Ng backing, enterprise SaaS
2. OpenAI Agents SDK — fast growth (20K stars in 1 year), good DX
3. Microsoft Agent Framework (SK+AutoGen merger) — enterprise backing

### Gaps to close:
1. CLI scaffolding (`swarmline create/run/train`)
2. Vector store / RAG connectors (LanceDB, Qdrant, Pinecone)
3. LiteLLM adapter (4 providers → 200+)
4. Flow/graph visualization
5. Training loop (learn from human feedback)
6. OpenAPI plugin import (swagger.json → tools)

### Anti-patterns observed:
- God Object Agent: Swarms (6175 LOC), CrewAI Crew (1650 LOC, 85 methods)
- No governance in OSS: CrewAI, Swarms, AutoGen, LangGraph Swarm
- Maintenance mode without migration: AutoGen, Semantic Kernel
- Telemetry without opt-out: Swarms, CrewAI (to their cloud)
- API instability: Swarms (10 majors/3yr), OpenAI SDK (pre-1.0)
