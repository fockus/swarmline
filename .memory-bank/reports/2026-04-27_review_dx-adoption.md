# Developer Experience Review — swarmline v1.5.0

Date: 2026-04-27
Scope: README, docs/, examples/, public API, OSS health, deployment story, brand surface
Reviewer: Developer Advocate subagent

---

## Executive Summary

- **DX score: 7.5 / 10** — strong technical fundamentals, polished docs surface, but several adoption-critical OSS health gaps prevent a 9+ rating.
- **Adoption readiness: WARN** — package is ready to ship to PyPI; community infrastructure (SECURITY, CODE_OF_CONDUCT, Dockerfile, status badges) needs ~1 day of work to reach OSS-mature standard.
- **Top 3 friction points**
  1. **Two competing 3-line snippets**, neither demonstrably runnable for a brand-new user — README requires `ANTHROPIC_API_KEY` (silent failure mode), `docs/agent-facade.md:10` shows `AgentConfig(runtime="thin")` without `system_prompt` which raises `ValueError` at runtime (the doc was patched in v1.5.0 to clarify, but the snippet itself remains misleading on a quick scan).
  2. **`AgentConfig` has 35 fields** in a single frozen dataclass (`src/swarmline/agent/config.py`, 148 LOC). FastAPI's analogous `FastAPI()` has ~10. New users see a wall of options when they `Ctrl+Space` in their IDE.
  3. **No SECURITY.md, no CODE_OF_CONDUCT.md, no Dockerfile, no status badges from CI.** The 5 README badges are static / mocked (`tests-4200%2B%20passed-brightgreen`, not a live CI badge). This signals "amateur OSS" to security-conscious enterprise adopters.
- **Top 3 wins**
  1. **`@tool` decorator** is genuinely best-in-class — auto-infers JSON Schema from Python type hints, parses Google-style `Args:`, supports Pydantic + Enum + `list[T]` + `Optional[T]`. Better than CrewAI/AutoGen tool registration, on par with FastAPI's `@app.get()`.
  2. **34 standalone runnable examples** (`examples/00`–`examples/33`) with mock runtime by default — a new user can `git clone && python examples/00_hello_world.py` with zero API keys. This is exceptional and underused as a marketing surface.
  3. **Curated 12-name public API in `__all__`** — clean `from swarmline import *` behaviour. 79 names are still importable for power users, but only the canonical 12 leak through wildcard imports and Sphinx-style doc generators.

---

## First-Time Experience

- **Quick-start clarity: WARN**
- **Time-to-first-agent (estimate):**
  - Best path (`pip install swarmline[thin]` → README 3-liner with `ANTHROPIC_API_KEY` set): ~3 min if user reads carefully.
  - Likely first attempt (`pip install swarmline` then run README example): **~12-20 min** because `swarmline` core has no runtime — `AgentConfig(runtime="thin")` will fail to construct the runtime until `[thin]` extra is added. The error message tells you to install the extra, but the README install block lists `pip install swarmline` first as if it's enough.
  - With `swarmline init my-agent` CLI scaffold (mentioned at `docs/getting-started.md:62`): ~2 min, but this requires `pip install swarmline[cli]` which is a separate step not surfaced in the README.
- **Common pitfalls visible: WARN**
  - `system_prompt` is required (raises `ValueError("system_prompt must not be empty")`) — README always supplies it, but `docs/agent-facade.md:10` shows `AgentConfig(runtime="thin")` without it. A new user who copies that snippet hits an error immediately.
  - `swarmline` (core) without `[thin]` extra cannot run any agent. The README install block lists 6 install variants and doesn't bold the recommended starting point. Suggest: highlight `pip install swarmline[thin]` as the canonical "if you don't know what you want, use this" install.
  - Async-first APIs but README snippets call `await agent.query(...)` from top-level code — first-time Python users may copy-paste this into a file and get `SyntaxError: 'await' outside function`. Wrap snippets in `async def main()` + `asyncio.run(main())` like `examples/00_hello_world.py` does.
  - `OPENROUTER_API_KEY` vs `OPENAI_API_KEY` confusion — the README section "Thin + OpenRouter" tells users to `export OPENAI_API_KEY=sk-or-...`. This is correct (OpenRouter is OpenAI-compatible), but a brand-new user sees the OpenAI variable set to a `sk-or-` value and pauses — a one-sentence "OpenAI-compatible providers all use OPENAI_API_KEY" framing would help.

---

## Documentation Quality

- **Coverage: GOOD** — 56 markdown files in `docs/`, covering every advertised feature. README is exhaustive (719 lines) with embedded comparison tables.
- **API reference: mkdocs-material + readthedocs** — a `.readthedocs.yaml` exists, `mkdocs.yml` is configured, deployed via GitHub Pages (`docs.yml` workflow). No Sphinx autodoc, so the API reference is a hand-written `docs/api-reference.md` (20K). This will drift from code over time; consider adding `mkdocstrings-python` for auto-generated reference from docstrings.
- **Migration guides: GOOD** — `docs/migration/v1.4-to-v1.5.md` is exemplary (TL;DR, breaking changes called out clearly, before/after code blocks, "Why this changed" rationale, "How to migrate" steps). This is one of the strongest assets in the repo.
- **Examples: 34 runnable scripts (00–33), all with `MockRuntime` offline default.** Quality is excellent. README at `examples/README.md` indexes them with categories (Getting Started, Pipeline, Data & Context, Safety & Resilience, Observability, Runtimes, Orchestration, Complex Scenarios). The complex scenarios `24_deep_research.py` (18.8K), `25_shopping_agent.py` (18K), `26_code_project_team.py` (15K), `27_nano_claw.py` (17K) are showcase-quality.
- **Outdated content found:**
  - `LICENSE` line 4 says "Copyright (c) 2024-2026 cognitia contributors" — should be "swarmline contributors" post-rename.
  - README "Runtime Feature Matrix" diagram (lines 404–432) only shows 3 runtimes (`claude_sdk`, `deepagents`, `thin`), but the framework now has 6 (`cli`, `openai_agents`, `pi_sdk` added in v1.5.0). Inconsistent with the runtime list above (lines 363–381).
  - README install block for `npm install -g @mariozechner/pi-coding-agent` at line 55 is presented inline with `pip install` commands — easy to miss the runtime change, easy to confuse package managers.
  - README references `cognitia` once (line 530 in why-cognitia.md doc filename + `docs/why-cognitia.md` exists alongside `docs/why-swarmline.md`) — leftover from the rename. Recommend removing `docs/why-cognitia.md` or marking it as historical.
  - `.memory-bank/STATUS.md` says "Tag pushed to private origin" — the public sync to PyPI was pending at the time of this review. Verify before publishing.

---

## API Ergonomics

- **Typical use case (3-line agent):**
  ```python
  from swarmline import Agent, AgentConfig
  agent = Agent(AgentConfig(system_prompt="You are helpful.", runtime="thin"))
  result = await agent.query("What is 2+2?")
  ```
  Clean, FastAPI-grade for the happy path.

- **Streaming pattern:**
  ```python
  async for event in agent.stream("Explain quantum computing"):
      if event.type == "text_delta":
          print(event.text, end="", flush=True)
  ```
  The string-typed `event.type` discriminator is friction — should be a `Literal` or `enum.Enum` for autocomplete + type-safety. New users will guess at event names ("text_delta"? "text"? "delta"?) without IDE hints. Suggest exporting `RuntimeEventType` enum.

- **Tool registration (best in class):**
  ```python
  @tool(name="calculate", description="...")
  async def calculate(expression: str) -> str:
      return str(eval(expression))
  ```

- **Hooks (worst in class):**
  ```python
  hooks = HookRegistry()
  hooks.on_pre_tool_use(audit_pre_tool)
  hooks.on_post_tool_use(audit_post_tool)
  config = AgentConfig(system_prompt="...", hooks=hooks)
  ```
  No `@hook("pre_tool")` decorator. The asymmetry with `@tool` is jarring. (Captured by `2026-04-25_audit-dx-fastapi-comparison.md` finding "Critical DX gap".)

- **Friction points:**
  - 35-field `AgentConfig` is overwhelming. Consider a `from swarmline.config import minimal, production, secure_by_default` factory pattern, or split into `AgentConfig` (5 fields) + `AgentExtras(...)` (rest).
  - `result.usage` typed as `dict | None` rather than a typed dataclass like `Usage(input_tokens, output_tokens, ...)` — IDE doesn't help users discover keys.
  - `query_structured(prompt, model_class)` is awkward — Pydantic users expect `query(prompt, response_model=Sentiment)` like FastAPI's `response_model=`. (Confirmed in prior DX audit.)
  - **No `agent.session_id` accessor** — to resume a conversation, users must pluck `result.session_id` from a result and remember to pass it to `Conversation.resume(...)`. A first-class `agent.last_session_id` property would be cleaner.
  - Error messages **do** include actionable hints post-v1.5.0 audit (secret redaction shipped, runtime/CLI/serve error paths sanitized, `AUTH_FAILED` and 6 P1/P2 findings closed). This is a real win — call it out more prominently in the README.

- **Type hints: GOOD** — 5/5. `from __future__ import annotations` consistently, all public domain types are frozen dataclasses, `py.typed` marker shipped in wheel (`pyproject.toml` `force-include`).

---

## Configuration UX

- **YAML/Python balance: GOOD** — `runtime/models.yaml` for model alias resolution, Python config (`AgentConfig`) for everything else. No XML-style YAML config nightmare.
- **Defaults sensibility: GOOD with caveats**
  - Default `runtime="thin"` (changed in v1.5.0) is correct — works without claude-agent-sdk install. Good migration framing in `docs/migration/v1.4-to-v1.5.md`.
  - But: `runtime="thin"` requires `pip install swarmline[thin]` which installs `anthropic`, `openai`, AND `google-genai` SDKs eagerly (~75MB combined). For users who only want OpenAI, this is wasteful. Consider `swarmline[thin-openai]`, `swarmline[thin-anthropic]`, `swarmline[thin-google]` granular extras (the `openai-provider` and `google-provider` extras exist but `[thin]` doesn't compose from them — DRY violation in `pyproject.toml:58-63` vs `:65-77`).
  - Model alias `"sonnet"` resolves to `claude-sonnet-4-20250514` — sensible, but version-locked. Document the model registry refresh cadence (when does `"sonnet"` start pointing at Claude 5?).
- **Env var requirements clear: WARN**
  - The README "Credentials & Provider Setup" section (lines 65–94) is good but buried below the install section. New users frequently hit "what env var do I need?" before they read. Suggest a 5-line "API Keys" callout at the top of the README, before "Quick Start".
  - `docs/credentials.md` is the canonical reference (8.7K) — well-written but not linked from `docs/getting-started.md` until line 119. Move the link earlier.

---

## Discoverability

- **Public exports: 79 names accessible via `dir(swarmline)`, 12 in `__all__`.** Curation is good: `Agent`, `AgentConfig`, `ContextPack`, `Conversation`, `Message`, `Result`, `RuntimeEvent`, `SkillSet`, `SwarmlineStack`, `ToolSpec`, `TurnContext`, `tool`. New users hit `from swarmline import *` and see exactly the right surface.
- **`__all__` declared: YES** — at `src/swarmline/__init__.py:93-106`. Excellent hygiene.
- **IDE autocomplete: GOOD** — type hints are pervasive, `py.typed` marker is shipped. Pylance/Pyright/PyCharm should give clean completions. `RuntimeEvent.type` being string-typed is the main friction (covered above).
- **API surface size:** 79 importable names is on the high end. FastAPI exports ~7. LangChain exports ~50 from `langchain_core`. Consider whether `RoleRouter`, `SessionFactory`, `ToolEventStore`, `PhaseStore`, `UserStore`, `ToolIdCodec`, `ResourceDescriptor` (all in current re-exports) really need to be at the top level — they're protocols 99% of users will never implement.

---

## Open-Source Health

- [x] LICENSE (MIT, but copyright still says "cognitia contributors" — needs rename to "swarmline")
- [x] CONTRIBUTING.md (good — 109 lines, covers setup/tests/style/PR process/optional deps)
- [ ] CODE_OF_CONDUCT.md — **MISSING.** Add Contributor Covenant 2.1 (standard 1-file boilerplate). Critical for community trust.
- [ ] SECURITY.md — **MISSING.** v1.5.0 closed 6 security findings (2× P1, 4× P2) and shipped redaction infrastructure. This deserves a SECURITY.md describing: how to report vulnerabilities, supported versions, response SLA. Without it, security researchers default to public GitHub issues for sensitive disclosures.
- [x] CHANGELOG.md (Keep a Changelog format, 35K lines, exemplary detail — security audit closure section is a model for other OSS projects)
- [x] Issue templates (`.github/ISSUE_TEMPLATE/bug_report.md` + `feature_request.md`) — both well-structured.
- [x] PR template (`.github/PULL_REQUEST_TEMPLATE.md` — 30 lines, good checklist).
- [x] GitHub Actions: `ci.yml` (lint + typecheck + tests on 3.11/3.12/3.13 + architecture meta-tests + pip-audit), `docs.yml` (mkdocs-material → GitHub Pages), `publish.yml` (build + test-install + PyPI via Trusted Publishing OIDC + GitHub Release auto-generation). Excellent — better than 90% of OSS Python projects.
- [ ] Status badges from live CI — **MISSING.** README has 5 badges but they're static (`tests-4200%2B%20passed-brightgreen` is hardcoded). Replace with:
  ```
  ![CI](https://github.com/fockus/swarmline/actions/workflows/ci.yml/badge.svg)
  ![Docs](https://github.com/fockus/swarmline/actions/workflows/docs.yml/badge.svg)
  ![PyPI Downloads](https://img.shields.io/pypi/dm/swarmline)
  ```
- [ ] Roadmap visibility — **WARN.** Roadmap exists in `.memory-bank/roadmap.md` but is filtered from the public sync. No public-facing roadmap. New users can't tell "is this project still alive? what's coming next?" Suggest: `docs/roadmap.md` (subset of the private roadmap, public-safe).
- [ ] FUNDING.yml — **MISSING** (`.github/FUNDING.yml`). Optional but useful if you want sponsorship.

**Findings: what's missing/weak**
1. SECURITY.md (critical — blocks responsible vulnerability disclosure)
2. CODE_OF_CONDUCT.md (critical — community signal)
3. Live CI/coverage badges (high — credibility)
4. Public roadmap (high — adoption confidence)
5. Dockerfile + `docs/deployment/` (medium — production users need this)
6. `LICENSE` copyright string outdated (low — 2-line fix)

---

## Competitive Positioning

- **Differentiators (per your own README, lines 35–46 + competitive analysis report):**
  1. True multi-provider (Anthropic + OpenAI + Google + DeepSeek) without LangChain wrapper tax.
  2. Clean Architecture with 14+ ISP-compliant Protocols (≤5 methods each).
  3. 6 swappable runtimes (`thin`, `claude_sdk`, `deepagents`, `cli`, `openai_agents`, `pi_sdk`).
  4. Default-deny tool policy + budget enforcement + secret redaction baked in (production safety).
  5. Episodic + procedural + consolidation memory (no other OSS framework has this combo).
  6. Hierarchical agent graphs with governance (capabilities, max_depth, can_delegate).

- **Hidden in README/docs: NO** — all six are surfaced in the README "Why Swarmline?" section. Good.

- **Compared to top 3 competitors:**
  - **vs LangChain/LangGraph**:
    - Our advantage: smaller surface, no LangChain version churn, Clean Architecture, governance built-in.
    - Their advantage: 100+ vector store integrations, 200+ tool integrations, LangSmith observability ecosystem, far larger community (~80K+ stars combined).
    - **Recommendation:** add a short "Coming from LangChain?" migration guide. The opportunity is users frustrated with LangChain bloat.
  - **vs LlamaIndex**:
    - Our advantage: agent-first (LlamaIndex is RAG-first), more flexible memory model.
    - Their advantage: best-in-class RAG, vector store integrations, document parsers.
    - **Recommendation:** position swarmline as "agents that can use any RAG library" rather than competing on RAG features. Add a `cookbook/llamaindex_as_tool.md` showing LlamaIndex as a swarmline tool.
  - **vs pydantic-ai**:
    - Our advantage: multi-runtime, governance, multi-agent graphs, more mature memory story.
    - Their advantage: simpler API surface, type-safety-first messaging, smaller cognitive load, Anthropic+Pydantic team backing, faster growing.
    - **Recommendation:** pydantic-ai is the closest spiritual competitor. Acknowledge them in the comparison table (currently absent from README's framework comparison block at line 638). Position swarmline as "pydantic-ai when you need multi-agent + governance + persistent memory".
  - **vs CrewAI**: covered well in README. CrewAI's $18M funding and Andrew Ng backing is a real threat — your "no vendor cloud lock-in" angle is strong.
  - **vs OpenAI Agents SDK**: you've already shipped `runtime="openai_agents"` — frame this as "use OpenAI Agents SDK *through* swarmline" to capture both audiences.

---

## Deployment Story

- **PyPI install: PASS** — `pip install swarmline` works (sdist + wheel via hatchling, `force-include` for `models.yaml`/`bridge.mjs`/`py.typed`). Smoke-test job in `publish.yml:38-58` validates `from swarmline import Agent, AgentConfig` after fresh install.
- **Extras clarity: WARN** — 22 optional extras listed in `pyproject.toml`. README has a clear table (lines 612–632) but a new user must read 6 lines of `pip install` variants before getting started. Suggest: highlight `swarmline[thin]` as the default, demote others to "advanced".
- **Docker: FAIL** — no Dockerfile. For production users (especially in Kubernetes-shop enterprises), a multi-stage `Dockerfile` (slim Python base + `pip install swarmline[thin,postgres,otel]` → entrypoint) is table-stakes. Even a simple `examples/Dockerfile` would help.
- **Cloud guides: FAIL** — no AWS/GCP/Azure deployment docs. `docs/production-safety.md` exists (9.1K) and is good, but doesn't cover the deployment topology question. Consider:
  - `docs/deployment/aws-ecs.md` (swarmline serve + ALB + RDS Postgres)
  - `docs/deployment/kubernetes.md` (Helm chart or kustomize manifests)
  - `docs/deployment/lambda.md` (long-running daemon vs Lambda — tradeoff guide)

---

## Top 10 UX Issues (prioritized)

| # | Issue | Impact | Effort | Priority |
|---|-------|--------|--------|----------|
| 1 | Missing SECURITY.md (blocks responsible vuln disclosure post-audit) | High | 1h | P0 |
| 2 | Missing CODE_OF_CONDUCT.md (community signal) | High | 30min | P0 |
| 3 | Static CI badges in README (5 hardcoded badges look amateur) | High | 30min | P0 |
| 4 | LICENSE copyright says "cognitia contributors" | Low | 5min | P0 |
| 5 | `docs/agent-facade.md:10` snippet `AgentConfig(runtime="thin")` raises `ValueError` (wrong without `system_prompt`) | High | 10min | P0 |
| 6 | README install block doesn't bold `swarmline[thin]` as canonical default | Medium | 15min | P1 |
| 7 | `RuntimeEvent.type` is string-typed (no `Literal` / enum for IDE autocomplete) | Medium | 4h | P1 |
| 8 | Hooks API has no `@hook` decorator (asymmetry vs `@tool`) | Medium | 6h | P1 |
| 9 | No public roadmap (private roadmap is filtered out by sync script) | Medium | 1h | P1 |
| 10 | No Dockerfile / cloud deployment guides | Medium | 2 days | P2 |

---

## Top 5 DX Wins (already great)

1. **`@tool` auto-schema inference** — best-in-class, on par with FastAPI `@app.get`. Auto-extracts description from docstring, parses Google-style `Args:`, infers Pydantic + Enum + `list[T]` + `Optional[T]`.
2. **34 runnable examples with offline `MockRuntime`** — a new user can `git clone && python examples/00_hello_world.py` with zero API keys and zero ceremony. Underused as a marketing surface.
3. **CHANGELOG.md security audit closure section** — exemplary. Lists each P1/P2 finding, the fix, the test count, and a reference to the plan file. Other OSS Python projects could learn from this.
4. **GitHub Actions pipeline** — full lint + typecheck + tests + architecture meta-tests + pip-audit + matrix Python 3.11/3.12/3.13 + Trusted Publishing OIDC. Better than 90% of OSS Python projects.
5. **Curated `__all__` of 12 names** — `from swarmline import *` is clean. New users see exactly the right surface in IDE autocomplete and Sphinx docs.

---

## Release Readiness Verdict

- **Required for PyPI publish: PASS** — package builds, smoke-test passes, OIDC trusted publishing configured, version 1.5.0 in `pyproject.toml`. Can ship today.
- **Required for community traction: WARN** — SECURITY.md, CODE_OF_CONDUCT.md, live CI badges, public roadmap missing. Without these, the project reads as "amateur" to enterprise evaluators despite the strong technical foundation. ~1 day of work to close.
- **Required for production adoption: WARN** — no Dockerfile, no cloud deployment guides, no observability cookbook (`docs/observability.md` exists but is library-level, not "deploy-on-AWS-with-OTel" level). Production users will adopt despite this gap, but you're losing the long tail of "I just want to run this on my K8s cluster" users.

---

## Recommendations

### Quick wins (< 1 day, before v1.5.1)

1. **Add SECURITY.md** (Anthropic-style — supported versions, vuln reporting via private GitHub Security Advisory, response SLA). Reference the v1.5.0 security audit closure as proof of investment.
2. **Add CODE_OF_CONDUCT.md** (Contributor Covenant 2.1, standard boilerplate). Signal community-readiness.
3. **Replace 5 static README badges** with live CI badges (`actions/workflows/ci.yml/badge.svg`), `pypi/v/swarmline`, `pypi/dm/swarmline` (downloads/month after launch), `python-versions/swarmline`.
4. **Fix LICENSE copyright** — `cognitia contributors` → `swarmline contributors`.
5. **Fix `docs/agent-facade.md:10`** — change `AgentConfig(runtime="thin")` to `AgentConfig(system_prompt="...", runtime="thin")` so the snippet is copy-paste-runnable.
6. **Bold `swarmline[thin]` as canonical install** in README. Add a one-line "If you don't know what you want, use this:" callout.
7. **Update README runtime feature matrix** (lines 404–432) to include `cli`, `openai_agents`, `pi_sdk` runtimes (currently only shows 3 of 6).
8. **Add public `docs/roadmap.md`** — subset of `.memory-bank/roadmap.md`, safe-to-publish quarterly buckets.
9. **Add `docs/migration/from-langchain.md` and `docs/migration/from-crewai.md`** — capture frustrated migrants from competitors.
10. **Move `docs/credentials.md` link** to the top of `docs/getting-started.md` (currently buried at line 119).

### Medium efforts (< 1 week, v1.5.1–v1.6.0)

1. **Granular `[thin]` extras** — `[thin-anthropic]`, `[thin-openai]`, `[thin-google]`. Compose `[thin]` from those. Saves ~50MB on minimal installs.
2. **Add `RuntimeEventType` Literal/Enum** — replace string-typed `event.type` with typed discriminator for autocomplete + type-safety.
3. **Add `@hook` decorator** — `@agent.hook("pre_tool", matcher="bash")` to mirror `@tool`. Closes the asymmetry called out in the prior DX audit.
4. **Add Dockerfile + `docs/deployment/docker.md`** — multi-stage slim build, entry point for `swarmline serve`.
5. **Add `mkdocstrings-python`** to mkdocs config — auto-generate API reference from docstrings, replace hand-maintained `docs/api-reference.md`.
6. **Add `cookbook/` directory** with 5–10 high-leverage recipes:
   - "Build a chatbot with persistent memory in 50 lines"
   - "RAG with LlamaIndex as a swarmline tool"
   - "Multi-agent code review pipeline"
   - "Streaming agent in a FastAPI endpoint"
   - "Production deployment with observability"
7. **Refactor `AgentConfig`** — split into `AgentConfig(system_prompt, runtime, model, tools, middleware)` (5 fields) + `AgentConfig.with_extras(...)` builder for advanced users. Reduces cognitive load from 35 → 5 for the common case.
8. **Add `pydantic-ai` to the README framework comparison table** (currently absent — the closest spiritual competitor).
9. **Public-facing GitHub Discussions** + Discord/Slack — community Q&A surface beyond GitHub Issues.
10. **Performance benchmarks page** — `docs/benchmarks.md` comparing thin runtime overhead vs raw `anthropic` SDK calls; reassures users that "Clean Architecture" doesn't mean "slow".

### Long-term investments (v2.0.0+)

1. **`swarmline.create()` factory function** — `swarmline.create(prompt="...", runtime="thin")` returns a fully-configured agent with sensible production defaults. Hide the 35-field config behind a smart factory.
2. **Visual graph debugger** — for hierarchical agent graphs, a web UI showing live agent state, task board, and message flow. Differentiator vs LangGraph (which has LangSmith but it's paid).
3. **LiteLLM integration** — `pip install swarmline[litellm]` adds 200+ providers. Closes the "we only have 4 LLMs" gap vs LangChain.
4. **Vector store integrations** — `swarmline.memory.vector` with adapters for Qdrant, Pinecone, LanceDB, Chroma, pgvector. Closes the "we don't have RAG out of the box" gap vs LlamaIndex.
5. **Hosted swarmline.cloud** — managed service for users who don't want to run `swarmline serve` themselves. Revenue path.

---

## Conclusion

Swarmline v1.5.0 is **technically excellent and ready for PyPI publication**. The core API (`Agent`, `AgentConfig`, `@tool`, `query`/`stream`/`conversation`) is genuinely well-designed, the test coverage (5532 passing) is enviable, the security audit closure in CHANGELOG.md is exemplary, and the 34 runnable examples with offline `MockRuntime` is a marketing asset most OSS frameworks would envy. **The framework deserves adoption.**

But to achieve broad open-source traction, **community-trust signals are missing**: no SECURITY.md (despite a thorough audit), no CODE_OF_CONDUCT.md, static fake-looking CI badges, no public roadmap, no Dockerfile. These are 1-day fixes that disproportionately impact "should I trust this project?" perception in enterprise evaluations. Ship them in v1.5.1 alongside the LICENSE copyright fix and the `docs/agent-facade.md:10` snippet bug.

The medium-term DX wins — `@hook` decorator, typed `RuntimeEvent.type`, granular `[thin-*]` extras, `cookbook/`, `from-langchain.md` migration guide — should anchor the v1.6.0 roadmap. They convert "interested" developers into "advocating" developers, which is how a framework crosses the 1K star adoption threshold.

**DX score: 7.5 / 10. With the quick wins above shipped: 8.5 / 10. With v1.6.0 medium efforts: 9 / 10.**
