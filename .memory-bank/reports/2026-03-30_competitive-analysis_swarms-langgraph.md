# Competitive Analysis: Swarmline vs Swarms vs LangGraph Swarm

**Date:** 2026-03-30
**Context:** Rebranding swarmline → swarmline, positioning analysis

## Summary

| | **Swarmline** | **Swarms** (Kye Gomez) | **LangGraph Swarm** |
|---|---|---|---|
| Суть | Full-stack agent toolkit, Clean Arch | Монолитный multi-agent framework | Thin layer (~10KB) поверх LangGraph |
| Stars | — (private) | 6.1K | 1.4K |
| Версия | 1.2.0 (semver) | 10.0.1 (10 majors/3yr) | 0.1.0 |

## Architecture

- **Swarms**: God Object Agent (6175 LOC, 100+ params), no layering, circular deps
- **LangGraph Swarm**: ~300 LOC convenience layer, tight LangChain coupling
- **Swarmline**: 20+ ISP protocols, 3-layer Clean Architecture, middleware/hooks

## Orchestration

- **Swarms**: 17+ patterns via SwarmRouter (wide but shallow)
- **LangGraph Swarm**: 1 pattern (handoff), 1 active agent at a time
- **Swarmline**: Graph + teams + subagents + pipeline (deep)

## Memory

- **Swarms**: In-memory list + JSON files. External swarms-memory abandoned.
- **LangGraph Swarm**: LangGraph checkpointer only
- **Swarmline**: 8 memory protocols + 5 knowledge protocols, 3 backends, episodic+procedural+consolidation

## Security

- **Swarms**: None in core. SAFETY_PROMPT (text only). Telemetry without clear opt-out.
- **LangGraph Swarm**: None. LangGraph interrupt for HITL.
- **Swarmline**: Default-deny tool policy, CostBudget, GuardRails, HITL ApprovalGate, ActivityLog

## Ideas to Borrow

From Swarms:
- SwarmRouter — single entry point for strategy selection
- AgentRearrange string DSL — "A -> B, C -> D"
- MixtureOfAgents — parallel experts + aggregator
- auto swarm selection — LLM picks strategy

From LangGraph Swarm:
- Command handoff pattern — atomic navigation + state update
- Agent-isolated message keys

## Anti-patterns to Avoid

- God Object Agent (Swarms)
- 10 major versions in 3 years (Swarms)
- Telemetry without opt-out (Swarms)
- 0 tests/security (LangGraph Swarm)
- Tight vendor coupling (LangGraph Swarm → LangChain)
