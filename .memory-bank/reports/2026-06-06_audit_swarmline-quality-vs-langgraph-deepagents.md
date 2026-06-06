# Audit — swarmline quality / fitness, vs LangGraph & deepagents

**Date:** 2026-06-06
**Type:** audit / external review
**Trigger:** after fixing 3 swarmline bugs from the faberlic shopping-agent (mode routing, native tool-format, force-finalize), the maintainer asked for an honest assessment of swarmline's quality, convenience, universality and reliability for building such agents — benchmarked against LangGraph and deepagents.
**Method:** 3 parallel read-only explorer agents (architecture/quality map · developer-ergonomics trace · reliability/test-quality) + direct reads of `pyproject.toml`, `__init__.py`, faberlic's integration layer. Numbers below are measured, not estimated.

---

## TL;DR
swarmline is an **ambitious, broad, well-documented, CI-backed framework that is architecturally in the LangGraph category** (NOT actually "thin" — 53.9k LOC, 31 subpackages), at **Beta maturity with uneven depth of validation**. For the narrow faberlic use case (single tool-using shopping agent on OpenRouter + structured output) it is, post-fix, a good fit at the right altitude. Its reliability for the core tool-agent path was **not independently proven** until we hit and fixed real happy-path bugs — the single most important signal. Bus factor = it is effectively an in-house framework (`github.com/fockus/swarmline`, sole real consumer = faberlic).

## Measured facts
- **Size:** 387 `.py` files, **53,884 LOC**, 31 subpackages. "thin" is only ONE of 6 runtimes (`thin`/`claude_sdk`/`deepagents`/`cli`/`openai_agents`/`pi_sdk`).
- **God-files (our 400-line hard-gate):** 18 files > 400 lines (`runtime.py` 650, `memory/postgres.py` 662, `agent.py` 591, `llm_providers.py` 590, `react_strategy.py` 522, …); +18 more in the 300–400 soft zone.
- **Public API:** curated `__all__` of 12 names (good hygiene) + ~35 back-compat re-exports.
- **Packaging:** v1.5.0, Beta, MIT, **published to PyPI**, py≥3.11, hatchling. Core deps minimal (structlog/pyyaml/pydantic); ~20 optional extras (claude, thin, openai, google, deepagents[langchain+langgraph], openai-agents, postgres, sqlite, web*, e2b, docker, openshell, otel, mcp, cli, a2a, serve, nats, redis).
- **Docs:** README 715 lines, `docs/` 56 files (getting-started, design-patterns 37K, cookbook, hitl, migration), CHANGELOG 541 lines, SECURITY/CONTRIBUTING/CoC. Genuinely good for a solo framework.
- **CI:** `ci.yml` 5 jobs (lint=ruff src+tests, typecheck=ty src/swarmline strict, tests matrix py3.11/3.12/3.13 `-m "not live and not slow"`, architecture, audit=pip-audit) + publish + docs.
- **Tests:** ~4,950 functions across 353 files (unit 248/integration 85/e2e 18/arch 1/security 1). **No coverage gate / no `fail_under`.**

## Scorecard (subjective, by our own RULES criteria)
| Axis | Score | Basis |
|---|---|---|
| Minimal-path API ergonomics | 🟢 4/5 | `@tool` (auto-schema from type hints) + `Agent(AgentConfig(...))` + `query_structured(prompt, Model)`. DI via `RuntimeFactoryPort`. |
| Code hygiene / SOLID | 🟡 3/5 | Good layering intent + curated API, but 18 god-files by its own gate. |
| Documentation | 🟢 4/5 | Substantial README + docs site + CHANGELOG. |
| Test depth / trustworthiness | 🔴 2/5 | ~4,950 tests but a structural blind spot (below) + no coverage gate. |
| Proven reliability | 🟡 2.5/5 | 3 happy-path bugs in the primary tool-agent flow; single maintainer. Now hardened for our path. |
| Universality | 🟡 4/5 paper, 2.5/5 validated | Huge adapter surface; optional-dep matrix not continuously validated. |
| Fit for our task (post-fix) | 🟢 4/5 | ReAct + structured output at the right altitude. |

## The core reliability finding (L-022 class)
Not the bugs themselves but that **~5000 green tests could not catch them by construction.** Every test fake (faberlic `ScriptedRuntime` in `tests/infrastructure/fake_llm.py`; swarmline inline `MockLLM`/`FakeRuntime`) **replaces `ThinRuntime.run()` wholesale** — the real chain `mode-resolution → strategy dispatch → native adapter → HTTP wire-shape` was never exercised end-to-end. Before our fix there was **zero** test pinning the OpenAI tool wire-shape; `toolspecs_to_openai` was dead code. Classic **breadth > depth**.

Remaining robustness gaps (verified in code, post-fix):
- **Asymmetry:** native-path budget-exhaustion force-finalizes, but JSON-in-text path still `yield`s an error (loses accumulated context). `react_strategy.py`.
- Malformed native tool-call args: `json.loads(tc.function.arguments)` has **no try/except** → silent fallback to JSON-in-text, can hallucinate. No test. `llm_providers.py`.
- `GoogleAdapter.call()` sync/async `inspect.isawaitable` pattern is SDK-version-fragile.
- Optional-dep skip discipline inconsistent: `requires_*` markers are documentary (no skip hook); ~26 tests + 3 collection errors fail on a minimal install → CI must install `[all]` or the matrix is untested.

## swarmline vs LangGraph vs deepagents
Nuance most miss: **not strictly either-or** — swarmline has a `deepagents` runtime depending on `langgraph>=1.1.1,<1.2` + `langchain` (per its own extra), so it can WRAP them.

| Criterion | swarmline (thin) | LangGraph | deepagents |
|---|---|---|---|
| Maturity / adoption | Beta, 1 maintainer, 1 consumer | v1.x industry standard, thousands of teams | young (0.4.x) but on mature LangGraph, org-backed |
| Durable execution / persistence | ❌ none | ✅ checkpointers, resume | ✅ inherits |
| Human-in-the-loop | 🟡 `hitl/` Beta | ✅ first-class interrupts | ✅ |
| Observability / eval | 🟡 otel + `eval/` | ✅ LangSmith + Studio | ✅ via LangGraph |
| Provider-agnostic | 🟢 base_url, 3+ providers | 🟡 via LangChain layer | 🟡 Claude default |
| Weight for OUR task | 🟢 right-sized | 🔴 overkill (graph for 1-2 tool calls) | 🔴 built for long-horizon planning |
| Who fixes a bug | 🟢 us, instantly | 🔴 PR upstream / await release | 🔴 same |
| Routing philosophy | 🔴 was regex-guessing (now removed) | 🟢 explicit graph edges | 🟢 model-driven, tools always available |

**Read:** for the faberlic shape (one search tool + structured recommendation per turn) **both LangGraph and deepagents are overkill**, each differently; the `thin` runtime sits at the right abstraction. LangGraph is years ahead on maturity, durable execution, observability, ecosystem. swarmline's one decisive edge: **we own it and fix it in minutes**.

## Recommendation
- **Keep swarmline for faberlic** — hardened, behaviour-preserving; migrating one shopping agent to LangGraph is not justified (YAGNI).
- **Strategically, be honest about cost** of maintaining a general-purpose LangGraph competitor solo. Either (A) narrow swarmline's ambition to "best thin runtime" and delegate heavy needs (durable/HITL/observability) to the `deepagents`/LangGraph runtime, or (B) if self-standing, close PROCESS gaps not add features.
- **3 hardening moves:** add a coverage gate; add per-provider wire-shape contract tests (so fakes can't lie); either protect `importorskip` or run `[all]` in CI so the optional-dep matrix is actually exercised.

## Decision taken this session — `detect_mode` REMOVED
The regex `detect_mode` execution-mode router was the footgun that caused the prod bug (a tool-equipped agent silently denied its tools by phrasing) and an `if … план …`-style hijack into the planner. Verdict: it solved strategy-selection at the wrong layer (user-text regex), wrong mechanism (hardcoded patterns), wrong time (before the model decides). It had **zero production callers** for its `react_patterns`/`planner_patterns` seams and only ever decided the tool-less + no-hint case.

**Implemented (TDD, plan `plans/2026-06-06_refactor_mode-routing-tool-aware-primary.md`):** deleted `detect_mode`, `_REACT_PATTERNS`, `_PLANNER_PATTERNS`, and the dead ctor params. Mode is now purely structural in `ThinRuntime.run`:
```python
if mode_hint is not None and mode_hint in VALID_MODES:
    mode = mode_hint
elif active_tools:
    mode = "react"
else:
    mode = "conversational"
```
Priority: **explicit mode_hint > tools present → react > conversational.** `planner` is explicit-only (`mode_hint="planner"`). Behaviour-preserving for the with-tools recommend path. swarmline non-live 5253 passed (0 new regressions; 26 pre-existing optional-dep), ruff+ty clean; faberlic 616 passed / 92.98%.
