# Re-audit: review follow-up + public surface / import isolation gaps

## Scope

Read-only re-audit after the second review pass. Goal:

- not lose the 4 confirmed review findings;
- check whether previous remediation really closed the intended seams;
- expand beyond strict PR-review rules into adjacent public API, import-isolation, registry/factory, docs/examples and test-quality gaps.

## Inputs

- current working tree in `/Users/fockus/Apps/cognitia`
- prior strict review findings
- prior audit report: `.memory-bank/reports/2026-03-18_library-audit.md`
- prior remediation plan: `.memory-bank/plans/2026-03-18_fix_library-audit-remediation.md`

## Verification snapshot

- `python -m pytest -q` → `2357 passed, 16 skipped, 5 deselected`
- `ruff check src/ tests/` → `60 errors`
- `mypy src/cognitia/` → `27 errors in 17 files`
- Manual reproductions executed for:
  - cold import with blocked `yaml`
  - optional `__all__` / `__getattr__` imports with blocked `claude_agent_sdk`
  - `SessionManager.stream_reply()` history persistence with `final.new_messages`
  - legacy registry-unavailable `cli` runtime creation

## Confirmed carry-forward review findings

### 1. `SessionManager.stream_reply()` still loses canonical runtime history

- File: `src/cognitia/session/manager.py:324-327`
- Impact: portable session turns with tool usage persist only synthetic assistant text, not canonical `assistant/tool/assistant` history from `final.new_messages`.
- Proof: reproduced with a fake runtime returning `RuntimeEvent.final(..., new_messages=[assistant, tool, assistant])`; persisted `runtime_messages` became only `['user', 'assistant']`.

### 2. Builtin `cli` registration is still inconsistent with legacy factory fallback

- File: `src/cognitia/runtime/registry.py:141-145`
- Impact: `RuntimeConfig(runtime_name="cli")` is valid, but `RuntimeFactory.create()` still raises `ValueError` when registry resolution falls back to `None`.
- Proof: reproduced by patching `RuntimeFactory._effective_registry` to `None` and calling `factory.create(RuntimeConfig(runtime_name="cli"))`.

### 3. `cognitia.runtime` optional exports are no longer package-level import safe

- File: `src/cognitia/runtime/__init__.py:165-170`
- Impact: `from cognitia.runtime import *` now aborts in SDK-free environments because `__all__` still advertises SDK-only names while `__getattr__` raises `ImportError`.
- Proof: reproduced with blocked `claude_agent_sdk`; star import fails on `ClaudeOptionsBuilder` / `RuntimeAdapter`.

### 4. `cognitia.skills` now exports YAML-only helpers unconditionally

- File: `src/cognitia/skills/__init__.py:15-21`
- Impact: `from cognitia.skills import *` now requires PyYAML even though the core registry/types are dependency-free.
- Proof: reproduced with blocked `yaml`; star import fails on `YamlSkillLoader`.

## Additional audit findings (outside strict PR-review threshold)

### A1. Top-level package import is still not isolated from PyYAML

- Files:
  - `src/cognitia/__init__.py:10-42`
  - `src/cognitia/runtime/model_registry.py:18`
- Severity: P1 audit gap / pre-existing contract violation
- Impact:
  - cold `import cognitia` fails if `yaml` is absent or blocked;
  - cold `from cognitia.skills import YamlSkillLoader` fails before `skills.__getattr__` can produce the new fail-fast message.
- Proof:
  - reproduced `import cognitia` under blocked `yaml` → `ModuleNotFoundError: import of yaml halted; None in sys.modules`
  - reproduced `from cognitia.skills import YamlSkillLoader` under blocked `yaml` from a cold interpreter → same raw `ModuleNotFoundError`
- Interpretation:
  - the new optional export surface for `skills` is only partially integrated because package initialization still pulls `runtime.model_registry`, which hard-imports `yaml`.

### A2. Optional-export docs are stale after the new fail-fast semantics

- Files:
  - `docs/advanced.md:83-85`
  - `docs/api-reference.md:523-527`
- Severity: P2 docs drift
- Impact:
  - docs still state that `registry_to_sdk_hooks` is `None` when the SDK is absent;
  - actual behavior is now `ImportError`, including on `hasattr()`/`getattr()` probes.
- Proof:
  - reproduced `from cognitia.hooks import registry_to_sdk_hooks` under blocked `claude_agent_sdk` → `ImportError`
  - reproduced `hasattr(cognitia.hooks, "registry_to_sdk_hooks")` under blocked `claude_agent_sdk` → `ImportError`

### A3. Runtime docs still advertise only three runtimes although `cli` is public and registered

- Files:
  - `docs/runtimes.md:3-17`
  - `docs/why-cognitia.md:49`
- Severity: P2 docs/public API drift
- Impact:
  - primary runtime overview pages still describe only three runtimes;
  - the codebase now has a public `cli` runtime (`RuntimeConfig(runtime_name="cli")`, `CliAgentRuntime`, registry integration, examples, tests).
- Proof:
  - `docs/runtimes.md` says “поддерживает три runtime”
  - `docs/why-cognitia.md` says “All three runtimes”
  - code and examples expose `cli` via `src/cognitia/runtime/cli/__init__.py`, `src/cognitia/runtime/registry.py`, `examples/19_cli_runtime.py`

### A4. Skills docs and architecture docs still present `YamlSkillLoader` as core

- Files:
  - `docs/tools-and-skills.md:77-80`
  - `docs/architecture.md:58-59`
  - `README.md:301-307`
  - `src/cognitia/skills/__init__.py:1-4`
- Severity: P2 docs/architecture drift
- Impact:
  - docs and README still frame `YamlSkillLoader` as part of the core package surface;
  - module docstring explicitly says it was moved to the application/infrastructure layer and is optional.
- Interpretation:
  - current docs are inconsistent with the package’s own layering story and optional-dependency behavior.

### A5. The new skills import-isolation test is order-dependent and misses the cold-start failure

- File: `tests/unit/test_import_isolation.py:184-195`
- Severity: P2 test gap
- Impact:
  - the test deletes only `cognitia.skills*`, not the top-level `cognitia` package;
  - if earlier tests already imported `cognitia`, the test passes and gives false confidence;
  - from a cold interpreter, the same scenario fails earlier in `runtime.model_registry`.
- Proof:
  - running the scenario from a cold interpreter reproduces raw `ModuleNotFoundError` for `yaml`;
  - the repo-wide suite stays green because import order masks the issue.

## Static-quality snapshot

### Repo-wide `ruff`

- `60` total errors currently block a clean repo-wide lint gate.
- The largest buckets are:
  - `E402` module import ordering in `src/cognitia/runtime/deepagents.py` and several tests
  - `F401` unused imports across e2e/integration/unit tests
  - `F841` unused local variables in tests
- Interpretation:
  - targeted linting around the remediation slices is green, but repo-wide lint is still not an honest quality gate.

### Repo-wide `mypy`

- `27` errors remain in `17` files.
- Main buckets:
  - optional dependency typing/imports: `docker`, `ddgs`, `crawl4ai`, `langgraph`, `deepagents`
  - SQLAlchemy `Result.rowcount` typing in `memory/sqlite.py`
  - provider-specific arg/await typing in `runtime/thin/llm_providers.py`
  - Pydantic v2 method typing in `runtime/structured_output.py`
- Interpretation:
  - mypy is closer than the earlier audit snapshot, but still not yet usable as a repo-wide gate.

## Dead / misleading surface notes

- `src/cognitia/runtime/__init__.py`, `src/cognitia/hooks/__init__.py` and `src/cognitia/skills/__init__.py` now intentionally fail fast, but standard Python capability probing via `hasattr()` is no longer safe for those symbols. This is not necessarily wrong, but it should be treated as an explicit API decision and documented as such.
- `tests/unit/test_skills.py` still imports `YamlSkillLoader` from `cognitia.skills`, which reinforces the old public-surface story and makes it harder to migrate the loader cleanly to an application-only seam.

## Recommended backlog split

### P1 next

1. Close the 4 confirmed open review findings.
2. Decouple cold `import cognitia` from `yaml` so optional import behavior becomes real, not only warm-process behavior.

### P2 next

1. Sync docs for:
   - 4 runtimes (`cli` included)
   - fail-fast optional exports
   - `registry_to_sdk_hooks` import behavior
   - `YamlSkillLoader` layering story
2. Fix `test_import_isolation.py` so it exercises cold-import scenarios honestly.

### P3 after that

1. Decide and document whether `hasattr()` on optional exports is supported behavior.
2. Finish repo-wide `ruff` cleanup.
3. Finish repo-wide `mypy` cleanup / optional-dependency typing policy.

## Bottom line

The previous remediation closed many real runtime contract bugs, but the public import surface is still only partially coherent. The current codebase now has two truths at once:

- runtime/session contracts are much stricter than before;
- package-level import and docs surfaces still reflect older, softer optional-dependency semantics.

That mismatch is now the main source of follow-up debt.
