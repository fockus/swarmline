# Plan: v1.0.0-core Release Pipeline

Создан 2026-03-18. 10 этапов от tech debt до PyPI release.

**Три блока:**
1. **Tech debt** (этапы 1-5): ruff 60 errors → 0, mypy 27 → 0, session/runtime migration cleanup, factory/registry hardening
2. **Docs** (этапы 6-8): CHANGELOG finalization, Getting Started update, mkdocs site audit
3. **Release** (этапы 9-10): version bump 0.5.0 → 1.0.0, PyPI upload, final gate check

**Параллелизация:** этапы 1-3 параллельны, 4-5 параллельны, 6-8 параллельны.
**Оценка:** ~10-13 часов.
**Файл плана:** `plans/2026-03-18_feature_v1-release-pipeline.md`
