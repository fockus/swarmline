# 2026-03-18 21:15 — Re-audit remediation complete

## Scope closed

- Wave 1 correctness seams:
  - `SessionManager` keeps canonical `final.new_messages`
  - runtime wrappers fail on silent EOF instead of synthesizing success
  - `ClaudeCodeRuntime` stops after terminal `error`
  - DeepAgents portable path keeps tool history
  - builtin `cli` works via registry and legacy fallback
  - workflow executor advertises local tools
- Wave 2 sync:
  - docs/README/runtime narrative updated for `cli`
  - optional exports documented and implemented as fail-fast explicit imports
  - `skills` package root now reflects registry/types as the stable surface
- Wave 3 static debt:
  - repo-wide `ruff` clean
  - repo-wide `mypy src/cognitia/` clean

## Notable implementation details

- `runtime/__all__`, `hooks.__all__`, `runtime.ports.__all__`, `skills.__all__` now expose only stable core exports; optional symbols still resolve via explicit import and raise `ImportError` when extras are absent.
- `GoogleAdapter` now supports both awaitable and synchronous google-genai client methods, which keeps mypy satisfied without breaking async-mock based tests.
- Optional-dependency typing boundaries were normalized with narrow `type: ignore[...]` only at import sites where upstream packages are intentionally optional or untyped.

## Verification

- `ruff check src/ tests/`
- `mypy src/cognitia/`
- `python -m pytest -q`
- `git diff --check`

All four gates are green on the main workspace.
