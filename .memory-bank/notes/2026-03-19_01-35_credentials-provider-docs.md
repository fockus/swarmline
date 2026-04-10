# Credentials & provider docs sync

## Why this was needed

Credential and provider setup information had drifted across multiple public docs:

- `README.md`
- `docs/getting-started.md`
- `docs/configuration.md`
- `docs/runtimes.md`
- `docs/cli-runtime.md`

There was no single canonical place that answered:

- which env vars each runtime/provider path actually uses
- where `base_url` can be configured
- when `AgentConfig.env` is respected
- how OpenRouter differs between `thin` and `deepagents`

## What is now canonical

`docs/credentials.md` is now the single source of truth for:

- runtime-level credential matrix
- provider-specific env vars
- `AgentConfig` vs direct `RuntimeConfig` parameter surface
- `CliConfig.env` usage
- example-specific `OPENROUTER_API_KEY` convenience behavior

## Important rules captured in docs

1. `AgentConfig.env` is primarily a `claude_sdk` runtime facility. Portable runtime facade paths (`thin`, `deepagents`) still read provider credentials from process environment.
2. `RuntimeConfig.base_url` exists on direct runtime construction, but the high-level `AgentConfig` facade does not expose `base_url`.
3. OpenRouter is documented as an OpenAI-compatible path in Cognitia:
   - `thin` can use `openrouter:*`
   - `deepagents` must use the OpenAI provider path, e.g. `openai:anthropic/claude-3.5-haiku`
4. `cli` runtime credentials are always whatever the wrapped CLI expects, passed via inherited env or `CliConfig.env`.

## Verification

- `pytest -q tests/integration/test_docs_examples_consistency.py tests/integration/test_examples_smoke.py` → `44 passed`
- `ruff check tests/integration/test_docs_examples_consistency.py` → green
- `mkdocs build --strict` → green
- `git diff --check` → green
