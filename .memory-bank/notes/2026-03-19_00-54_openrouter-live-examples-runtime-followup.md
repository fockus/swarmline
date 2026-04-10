# OpenRouter live examples/runtime follow-up

## Scope

Release-focused verification of the remaining live user surface after earlier runtime remediation:

- `examples/24_deep_research.py --live`
- `examples/27_nano_claw.py --live`
- runtime smoke for `thin`, `cli`, `claude_sdk`, and `deepagents`
- docs/examples consistency for supported live credentials

## What was fixed

### 1. Thin mode heuristics were too Russian-specific

`ThinRuntime.detect_mode()` previously defaulted many English tool-oriented requests to `conversational`, which breaks live CLI/tool examples even when tools and runtime wiring are correct.

Concrete repro before the fix:

- prompt: `List the files in /project`
- observed mode: `conversational`
- result: model emitted JSON-ish tool intent text instead of a real tool call path

Fix:

- expanded planner heuristics with `plan`, `strategy`, `step-by-step`, `roadmap`
- expanded react heuristics with `find`, `search`, `compare`, `list`, `read`, `write`, `execute`, `run`

Result:

- the same prompt now selects `react`
- real `tool_call_started` / `tool_call_finished` events are emitted

### 2. Nano Claw live streaming leaked raw JSON envelopes

After the mode fix, `examples/27_nano_claw.py --live` executed tools correctly, but the user still saw raw streamed JSON like:

```text
{"type": "final", "final_message": "..."}
```

This happened because the example printed every `text_delta` chunk immediately, while ThinRuntime streams the model's JSON envelope before the final parsed event is available.

Fix:

- `NanoClaw.run_turn()` now buffers early chunks
- if the stream looks like a JSON envelope, it suppresses those raw chunks
- once the terminal `done/final` event arrives, it prints the parsed final text instead

Result:

- live CLI output is readable again without changing core ThinRuntime streaming semantics

## Live verification matrix

### Examples

- `examples/24_deep_research.py --live` with `OPENROUTER_API_KEY`:
  - success
  - returned a structured `ResearchReport`
- `examples/27_nano_claw.py --live` with `OPENROUTER_API_KEY`:
  - success
  - tool executed: `list_directory`
  - final user-facing output rendered as plain text

### Runtimes

- `thin` with `model='openrouter:anthropic/claude-3.5-haiku'`:
  - success (`OK`)
- `cli` default runtime:
  - success (`OK`)
- `claude_sdk` with `model='sonnet'`:
  - success (`OK`)
- `deepagents`:
  - `model='openrouter:anthropic/claude-3.5-haiku'` failed as expected with provider unsupported
  - supported configuration works:
    - `model='openai:anthropic/claude-3.5-haiku'`
    - `OPENAI_BASE_URL=https://openrouter.ai/api/v1`
    - same OpenRouter key via `OPENAI_API_KEY`
  - under that supported configuration the runtime returned `OK`

## Docs sync

The following public docs were stale and are now aligned with code/tests:

- `examples/README.md`
- `docs/examples.md`

They now explicitly state that examples `24` and `27` accept either:

- `ANTHROPIC_API_KEY`
- `OPENROUTER_API_KEY`

## Verification

- `pytest -q tests/unit/test_thin_modes.py` → `22 passed`
- `pytest -q tests/integration/test_examples_smoke.py -k '27_nano_claw'` → `6 passed`
- `pytest -q tests/integration/test_examples_smoke.py tests/integration/test_docs_examples_consistency.py` → `42 passed`
- `pytest -q tests/unit/test_thin_modes.py tests/integration/test_thin_runtime_tools.py tests/integration/test_examples_smoke.py tests/integration/test_docs_examples_consistency.py` → `65 passed`
- `ruff check src/ tests/ examples/` → green
- `mypy src/cognitia/` → green
- `git diff --check` → green

## Release takeaway

The remaining live/example surface verified cleanly after this follow-up. The only important nuance is that DeepAgents does not treat `openrouter:*` as a first-class provider alias; OpenRouter works there through the OpenAI-compatible configuration path instead.
