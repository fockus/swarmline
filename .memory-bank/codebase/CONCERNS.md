# Codebase Concerns

**Generated:** `2026-04-25T10:16:27Z`
**Graph:** not-used (missing)

## Tech Debt

**ThinRuntime complexity:**
- Issue: `src/swarmline/runtime/thin/runtime.py` is 636 lines — near SRP limit (300-line rule)
- Files: `src/swarmline/runtime/thin/runtime.py`, `src/swarmline/runtime/thin/react_strategy.py` (431 lines)
- Impact: high cognitive load when adding new strategy or hook behaviour
- Fix: extract hook orchestration and strategy dispatch into dedicated classes (already partially started)

**Multi-agent graph board duplication:**
- Issue: SQLite and PostgreSQL task board implementations share ~80% logic with minimal abstraction
- Files: `src/swarmline/multi_agent/graph_task_board_sqlite.py` (590 lines), `src/swarmline/multi_agent/graph_task_board_postgres.py` (633 lines)
- Impact: bug fixes must be applied twice; divergence risk
- Fix: extract shared SQL-agnostic logic into `graph_task_board_shared.py` (partially exists at `src/swarmline/multi_agent/graph_task_board_shared.py`)

**Type suppression count:**
- Issue: 20 `# type: ignore` comments across source (`src/swarmline/`)
- Impact: silent type unsafety in those locations; `ty` errors masked
- Fix: address per-file, convert to proper type narrowing or protocol bounds

## Security Considerations

**Tool policy default-deny:**
- Risk: misconfigured tool policy could allow unintended tool execution
- Files: `src/swarmline/policy/` — `DefaultToolPolicy`
- Current mitigation: default-deny policy enforced, tests in `tests/integration/test_policy_chain.py`
- Recommended: maintain security regression tests in `tests/security/test_security_regression.py`

**Sandbox isolation:**
- Risk: E2B/Docker/OpenShell sandboxes are infrastructure adapters; weak sandbox = RCE risk
- Files: `src/swarmline/tools/` sandbox adapters
- Current mitigation: provider-parity tests in `tests/security/test_security_provider_parity.py`

## Performance Hotspots

**Memory providers — PostgreSQL:**
- Files: `src/swarmline/memory/postgres.py` (662 lines), `src/swarmline/memory/episodic_postgres.py`
- Cause: N+1 query risk if callers iterate messages in a loop without bulk fetch
- Improvement path: add bulk read methods to `MessageStore` protocol

**LLM providers initialization:**
- Files: `src/swarmline/runtime/thin/llm_providers.py` (558 lines)
- Cause: provider selection and client setup on every runtime instantiation
- Improvement path: cache provider clients at stack level via `SwarmlineStack`

## Fragile Areas

**Runtime adapter wiring:**
- Files: `src/swarmline/agent/runtime_wiring.py`, `src/swarmline/agent/runtime_dispatch.py`, `src/swarmline/agent/runtime_factory_port.py`
- Why fragile: three files share responsibility for routing to the correct runtime; signature changes in one ripple to others
- Safe change: add integration test in `tests/integration/test_runtime_capability_wiring.py` before modifying

**Hook dispatcher:**
- Files: `src/swarmline/hooks/dispatcher.py`, `src/swarmline/hooks/registry.py`
- Why fragile: hooks are cross-cutting; incorrect dispatch order silently skips pre/post events
- Test gaps: thin hooks covered in `tests/integration/test_thin_hooks_integration.py`, but multi-runtime hook parity not fully tested

## Test Coverage Gaps

**Observability / OTel exporter:**
- Files: `src/swarmline/observability/otel_exporter.py` (8KB), `src/swarmline/observability/event_bus_nats.py`, `src/swarmline/observability/event_bus_redis.py`
- What is not tested: NATS/Redis event bus under failure conditions; OTel export with real collector
- Risk level: Medium

**CLI init command:**
- Files: `src/swarmline/cli/init_cmd.py` (508 lines)
- What is not tested: interactive scaffolding paths end-to-end
- Risk level: Low

## Scaling Limits

**In-memory task queue:**
- Current capacity: single-process only (`src/swarmline/multi_agent/task_queue.py`)
- Breaking point: not suitable for multi-process or distributed agent deployments
- Path to scale: use SQLite (`src/swarmline/multi_agent/graph_task_board_sqlite.py`) or PostgreSQL backend
