# Re-review: open findings after follow-up audit

- Confirmed open review finding: `SessionManager.stream_reply()` still drops canonical `final.new_messages`, so session-backed portable turns lose tool context between turns.
- Confirmed open review finding: `cli` is registered as a builtin runtime, but `RuntimeFactory.create()` still has no legacy `cli` fallback when registry resolution is unavailable.
- Confirmed open review finding: `cognitia.runtime` now advertises SDK-only symbols in `__all__` while `__getattr__` raises `ImportError`, so package-level `import *` is no longer optional-dep safe.
- Confirmed open review finding: `cognitia.skills` now exports YAML-only helpers in `__all__`, so package-level `import *` requires PyYAML even though core registry/types are dependency-free.
- Follow-up broad audit found adjacent gaps outside strict PR-review scope: cold `import cognitia` still hard-depends on `yaml` through `runtime.model_registry`, docs still describe only three runtimes / `None` optional exports, and the new skills import-isolation test is order-dependent.
- Detailed report: `.memory-bank/reports/2026-03-18_reaudit_public-surface-and-followup-gaps.md`
