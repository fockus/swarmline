# Docs Examples Consistency Remediation

- `docs/examples.md` must track the actual runnable `examples/*.py` surface; stale scenario pages are worse than no examples page because users treat them as copy-pasteable.
- User-facing docs should not mention internal or nonexistent API (`CostTracker.budget_exceeded`, unsupported `SecurityGuard(on_blocked=...)`, wrong middleware ordering/defaults).
- Runtime install tables must match real package extras; a nonexistent extra in `README.md` is a broken installation instruction, not a harmless typo.
- CLI runtime docs need one canonical Claude command shape: `["claude", "--print", "--output", "stream-json", "-"]`.
- Lightweight docs regression tests are cheap and useful here because markdown drift had already escaped the main code/test suite.
