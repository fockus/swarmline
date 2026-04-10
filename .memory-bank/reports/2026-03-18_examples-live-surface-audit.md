# Examples Live Surface Audit

## Scope

- `examples/17_runtime_switching.py`
- `examples/18_custom_runtime.py`
- `examples/19_cli_runtime.py`
- `examples/24_deep_research.py`
- `examples/25_shopping_agent.py`
- `examples/26_code_project_team.py`
- `examples/27_nano_claw.py`
- Related seams: `src/cognitia/agent/agent.py`, `src/cognitia/agent/conversation.py`, `src/cognitia/runtime/cli/runtime.py`, `src/cognitia/orchestration/workflow_graph.py`

## Defendable Findings

1. `examples/README.md:5` overstates live/full-mode support for complex scenarios.
   - README says `24-27` run mock pipelines by default and have a full mode behind an API key.
   - Actual code:
     - `27_nano_claw.py` has a real `--live` path.
     - `24_deep_research.py` only contains a commented-out agent example.
     - `25_shopping_agent.py` and `26_code_project_team.py` are explicitly mock-only.
   - Impact: users reading README will spend time looking for runnable live modes that do not exist.

2. `examples/24_deep_research.py:4` promises “Requires ANTHROPIC_API_KEY for full execution”, but the executable script has no live entrypoint.
   - `main()` always runs the mock workflow.
   - The only “live” path is commented guidance around lines `437-455`.
   - Impact: this example advertises an execution mode that cannot actually be invoked.

3. `examples/27_nano_claw.py:340-342` fail-opens on missing `ANTHROPIC_API_KEY`.
   - `python examples/27_nano_claw.py --live` prints an error and exits with code `0`.
   - Impact: shell scripts and users cannot distinguish “live mode unavailable” from a successful run.

4. `examples/27_nano_claw.py:285-291` drops real usage/cost metadata on streamed turns.
   - `NanoClaw.run_turn()` streams through `Conversation.stream()` and then fabricates `Result(text=..., session_id=...)` before running middleware.
   - `CostTracker.after_result()` only accumulates `result.total_cost_usd`, so the live `/cost` command and `TurnLogger` cannot reflect actual spend.
   - Impact: the example’s cost-tracking story is wrong exactly in the live streaming mode it advertises.

## Verified Safe

- `examples/17_runtime_switching.py` runs cleanly and matches the currently registered runtime names/capabilities.
- `examples/18_custom_runtime.py` cleanly demonstrates registry registration, runtime execution, and unregister flow.
- `examples/19_cli_runtime.py` is self-contained and does not require external CLI availability for the demonstrated path.
- Default/mock invocations of `examples/24`, `25`, `26`, and `27` complete successfully without `stderr`.
- `examples/27_nano_claw.py` does guard missing `ANTHROPIC_API_KEY`; the issue is the exit semantics, not a crash.

## Verification

- `python examples/17_runtime_switching.py`
- `python examples/18_custom_runtime.py`
- `python examples/19_cli_runtime.py`
- `python examples/24_deep_research.py`
- `python examples/25_shopping_agent.py`
- `python examples/26_code_project_team.py`
- `python examples/27_nano_claw.py --live` with `ANTHROPIC_API_KEY` removed from env
- Static grep/read-through for `--live`, API key gating, and runtime wiring
