# Live Examples Audit

## Scope

- `examples/README.md`
- `examples/24_deep_research.py`
- `examples/25_shopping_agent.py`
- `examples/26_code_project_team.py`
- `examples/27_nano_claw.py`
- env gating comparison with `examples/01_agent_basics.py`

## Actionable Findings

### 1. `27_nano_claw.py --live` does not fail fast

- File: `examples/27_nano_claw.py:338-342`
- Repro: run `python examples/27_nano_claw.py --live` without `ANTHROPIC_API_KEY`
- Observed: prints `[error] ANTHROPIC_API_KEY not set. Run demo() instead.` and exits `0`
- Impact: explicit live invocation looks successful to shells/CI wrappers even though live mode never started
- Comparison: `examples/01_agent_basics.py --live` exits `1` with a clear error, which is the safer contract

### 2. `27_nano_claw.py` demo path fakes tool execution

- Files:
  - `examples/27_nano_claw.py:33-77` tool handlers
  - `examples/27_nano_claw.py:147-170` mock runtime
  - `examples/27_nano_claw.py:198-235` system prompt + tool wiring
- Repro:
  - run `python examples/27_nano_claw.py`
  - or instantiate `NanoClaw(runtime="mock")` and send `Write a new file /project/utils.py with a helper function`
- Observed:
  - demo prints a successful write message
  - no `[tool]` / `[result]` lines are emitted
  - `_MOCK_FS` stays unchanged; `/project/utils.py` is still absent
- Impact: the default example claims to demonstrate `@tool` integration and file operations, but the offline path only streams canned text and can drift away from real tool behavior unnoticed

### 3. README/live-mode wording overstates the complex examples surface

- Files:
  - `examples/README.md:5`
  - `examples/24_deep_research.py:1-5`
  - `examples/24_deep_research.py:437-457`
- Repro: inspect `24/25/26` for a runnable live entrypoint (`--live`, argparse flag, env-gated main path)
- Observed:
  - README says complex scenarios `24-27` run mock by default and require an API key for full mode
  - `24` says it requires `ANTHROPIC_API_KEY` for full execution
  - in reality, `24/25/26` expose no runnable live mode; `24` only has a commented example snippet
- Impact: users are told there is a full/live path for these scenarios, but three of the four scripts are mock-only demos today

## Checked And Considered Safe

- All `examples/01-27` still run in default/offline mode with `exit=0`, empty `stderr`, and non-empty `stdout`
- `examples/19_cli_runtime.py` is consistent with its contract: it demonstrates parsers and registry wiring and clearly marks the real runtime block as illustrative/commented
- `examples/27_nano_claw.py` demo mode itself launches cleanly and exits cleanly; the problem is semantic accuracy of the demonstration, not startup stability
- `examples/01_agent_basics.py --live` now fail-fast exits non-zero without a key, which is the expected env-gating behavior
