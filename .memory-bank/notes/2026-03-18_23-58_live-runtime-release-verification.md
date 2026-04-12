[MEMORY BANK: ACTIVE]

# Live Runtime Release Verification

Date: 2026-03-18

## Scope

Release-oriented live verification of all four runtimes with the currently available credentials and local CLI environment:

- `thin`
- `claude_sdk`
- `cli`
- `deepagents`

The work included code fixes discovered during the verification itself, followed by full repo gates.

## What Was Fixed

### 1. Explicit provider-prefixed models now survive facade resolution

Problem:
- `resolve_model_name("openrouter:anthropic/claude-3.5-haiku")` collapsed to the registry default model.
- This silently routed `thin` requests to Anthropic instead of the intended OpenRouter-compatible provider.

Fix:
- `src/swarmline/runtime/types.py` now preserves recognized `provider:model` strings.
- Added regression coverage in:
  - `tests/unit/test_runtime_types.py`
  - `tests/unit/test_agent_config.py`

### 2. Claude CLI runtime now matches the installed CLI contract

Problem:
- The installed `claude` CLI requires `--verbose --output-format stream-json` for NDJSON streaming.
- The runtime/examples/docs had drifted to a stale `--output stream-json` form.
- `CliConfig.output_format` existed but runtime execution ignored it.

Fix:
- `src/swarmline/runtime/cli/runtime.py` now normalizes Claude commands:
  - upgrades legacy `--output` to `--output-format`
  - injects `--output-format <fmt>` when absent
  - injects `--verbose` for `stream-json`
  - uses an explicit NDJSON-capable default Claude command
- Synced:
  - `src/swarmline/runtime/cli/types.py`
  - `examples/19_cli_runtime.py`
  - `docs/cli-runtime.md`
  - CLI-related tests

### 3. Optional-deps testability after installing deepagents extras

Problem:
- Once `deepagents` extras were installed, hidden failures appeared:
  - `tests/unit/test_deepagents_native.py` patched symbols that did not exist at module scope
  - `mypy` started type-checking the real `langgraph` integration and failed in `workflow_langgraph.py`

Fix:
- `src/swarmline/runtime/deepagents_native.py`
  - added lazy wrapper exports for `build_deepagents_chat_model()` and `create_langchain_tool()`
  - preserves lazy import behavior while remaining patchable in tests
- `src/swarmline/orchestration/workflow_langgraph.py`
  - type-erased the concrete `StateGraph(dict)` construction point
  - prevents optional-dependency mypy breakage without changing runtime behavior

## Live Verification Results

### Thin runtime

Verified path:
- `Agent(runtime="thin", model="openrouter:anthropic/claude-3.5-haiku")`
- env: OpenRouter key provided via OpenAI-compatible credentials

Result:
- returned `OK`

Negative check:
- using the same key as `ANTHROPIC_API_KEY` on the direct Anthropic path returned `401 invalid x-api-key`

Conclusion:
- OpenRouter works for the OpenAI-compatible path
- it does not substitute for native Anthropic credentials

### Claude SDK runtime

Verified path:
- `Agent(runtime="claude_sdk", model="sonnet")`

Result:
- returned `OK`

Conclusion:
- `claude_sdk` runtime is live-functional in the current local Claude environment

### CLI runtime

Verified paths:
- raw `claude` CLI behavior
- `CliAgentRuntime()` with the normalized default command

Observed local CLI behavior:
- installed CLI uses `--output-format`, not `--output`
- `stream-json` also requires `--verbose`

Result:
- `CliAgentRuntime()` returned:
  - `assistant_delta("OK")`
  - `final("OK")`

Conclusion:
- runtime is now compatible with the installed local Claude CLI

### DeepAgents runtime

Installed for verification:
- `deepagents>=0.4.11`
- `langchain>=1.0`
- `langgraph>=1.0`
- `langchain-openai>=1.0`

Verified paths:
- direct runtime:
  - `DeepAgentsRuntime(RuntimeConfig(runtime_name="deepagents", feature_mode="portable", model="openai:anthropic/claude-3.5-haiku", base_url="https://openrouter.ai/api/v1"))`
- facade path:
  - `Agent(runtime="deepagents", model="openai:anthropic/claude-3.5-haiku")`
  - env: `OPENAI_BASE_URL=https://openrouter.ai/api/v1`

Result:
- both returned `OK`

Conclusion:
- `deepagents` portable path is live-functional with an OpenAI-compatible backend when deps and base URL are present

## Environment Side Effect

Installing `deepagents` extras upgraded shared packages, including:
- `openai`
- `anthropic`
- `google-auth`

`pip` reported dependency conflicts with external `aider-chat`.

This did not break Swarmline:
- repo tests passed afterward
- live runtime verification succeeded afterward

But the environment impact is real and should be considered separately from repo correctness.

## Final Gates

- `ruff check src/ tests/` -> green
- `mypy src/swarmline/` -> green
- `pytest -q` -> `2517 passed, 11 skipped, 5 deselected`
- `git diff --check` -> green

## Release Verdict

With the current workspace state:
- all four runtimes have a verified working path
- source/docs/examples are consistent on the CLI surface
- static and test gates are green

Known limit:
- examples `24` and `27` still require real Anthropic credentials for their built-in `--live` path; the provided OpenRouter key does not replace that native Anthropic requirement.
