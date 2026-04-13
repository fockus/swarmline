# Releasing

Guide for maintainers: versioning rules, release workflow, and PyPI publication.

## Versioning (Strict SemVer)

Swarmline follows [Semantic Versioning 2.0.0](https://semver.org/). The version lives in `pyproject.toml` (`project.version`).

### What triggers each bump

| Bump | When | Examples |
|------|------|----------|
| **MAJOR** (X.0.0) | Breaking change to public API | Remove/rename exported symbol, change function signature, remove optional dependency group, change Protocol method, incompatible config format |
| **MINOR** (0.X.0) | New user-facing functionality (backward-compatible) | New module/protocol, new runtime/provider, new CLI command, new optional dependency group, new `@tool`, deprecation of existing API |
| **PATCH** (0.0.X) | Bug fix or non-functional improvement | Bug fix, security patch, performance fix, dependency version bump, docs typo in docstrings |

### What does NOT bump the version

These changes are committed to `main` but do **not** trigger a release:

- Internal refactoring (extracting helpers, renaming private symbols, moving code between private modules)
- Test additions, test refactoring, coverage improvements
- CI/CD changes (GitHub Actions, workflows)
- Documentation (docs/, README, CHANGELOG draft)
- Memory Bank, CLAUDE.md, RULES.md, AGENTS.md updates
- Lint/format fixes (ruff, ty)
- Development tooling (scripts/, Makefile, editor configs)

### Batching rule

**Do not release every feature individually.** Accumulate related changes and release them together:

- Aim for **1-2 minor releases per month** maximum, not per feature
- Group related features into a single minor release (e.g., "v1.5.0: new runtime + memory improvements")
- Patch releases can be more frequent (security/bug fixes ship immediately)
- Use CHANGELOG.md to accumulate unreleased changes under `## [Unreleased]` heading

### Version number discipline

| Current | Next patch | Next minor | Next major |
|---------|-----------|------------|------------|
| 1.4.1   | 1.4.2     | 1.5.0      | 2.0.0      |

- After a minor bump, patch resets to 0 (1.4.1 → 1.5.0, not 1.5.1)
- After a major bump, minor and patch reset (1.4.1 → 2.0.0)
- Pre-release suffixes allowed for testing: `1.5.0rc1`, `1.5.0a1`

## Development Model

### Two-repo workflow

```
swarmline-dev (private)     swarmline (public)        PyPI
┌─────────────────┐        ┌─────────────────┐      ┌─────────┐
│ All branches     │──sync──│ main only       │──CI──│ Package │
│ Memory Bank      │  ↑     │ No private files│      │         │
│ CLAUDE.md        │  │     │ AGENTS.public   │      │         │
│ .specs/          │  │     │ as AGENTS.md    │      │         │
│ .planning/       │  │     └─────────────────┘      └─────────┘
│ .factory/        │  │
└─────────────────┘  │
                     └── scripts/sync-public.sh (filters private files)
```

**Private repo** (`origin` = `swarmline-dev`): all branches, all files, daily development.

**Public repo** (`public` = `swarmline`): only `main`, filtered by `sync-public.sh`. Private files excluded:
- `.memory-bank/`, `CLAUDE.md`, `RULES.md`, `AGENTS.md` (replaced with `AGENTS.public.md`), `.specs/`, `.planning/`, `.factory/`

**PyPI**: published automatically by GitHub Actions (`publish.yml`) on public repo when a tag `v*` is pushed.

### Daily development

```bash
# 1. Create feature branch
git checkout -b feat/my-feature

# 2. Develop (TDD: tests first, then implementation)
pytest tests/unit/test_new_feature.py -v   # red
# ... implement ...
pytest tests/unit/test_new_feature.py -v   # green

# 3. Push to private remote
git push origin feat/my-feature

# 4. Merge to main (via PR or direct for solo dev)
git checkout main && git merge feat/my-feature

# 5. Push main to private
git push origin main
```

At this point, changes are on `main` in the private repo but NOT published.

## Release Checklist

### Pre-release

```bash
# 1. Verify all tests pass
pytest -q                              # offline: 4000+ passed
pytest -m integration -v               # integration tests
ruff check src/ tests/                 # lint clean
ty check src/swarmline/                # type check clean

# 2. Check CHANGELOG.md has all changes under [Unreleased]
# Move [Unreleased] → [X.Y.Z] - YYYY-MM-DD
```

### Version bump

```bash
# 3. Create release branch
git checkout -b release/vX.Y.Z

# 4. Bump version in pyproject.toml
#    project.version = "X.Y.Z"

# 5. Finalize CHANGELOG.md
#    [Unreleased] → [X.Y.Z] - YYYY-MM-DD

# 6. Commit
git add pyproject.toml CHANGELOG.md
git commit -m "release: prepare vX.Y.Z"

# 7. Merge to main
git checkout main && git merge release/vX.Y.Z

# 8. Tag
git tag vX.Y.Z

# 9. Push to private
git push origin main --tags
```

### Publish

```bash
# 10. Sync to public (filters private files, runs tests, force-pushes)
./scripts/sync-public.sh --tags

# This triggers:
#   - GitHub Actions publish.yml on public repo
#   - Builds sdist + wheel
#   - Publishes to PyPI via OIDC Trusted Publishing
#   - No API token needed (configured via PyPI project settings)
```

### Post-release

```bash
# 11. Verify on PyPI
pip install swarmline==X.Y.Z
python -c "from swarmline import Agent; print('OK')"

# 12. Add new [Unreleased] section to CHANGELOG.md
# 13. Delete release branch
git branch -d release/vX.Y.Z
```

## Hotfix workflow

For urgent fixes to a published version:

```bash
# 1. Branch from the tag
git checkout -b fix/critical-bug vX.Y.Z

# 2. Fix + test
# 3. Merge to main
git checkout main && git merge fix/critical-bug

# 4. Tag patch version
git tag vX.Y.Z+1   # e.g., v1.4.2

# 5. Publish
git push origin main --tags
./scripts/sync-public.sh --tags
```

## PyPI publishing details

- **Method**: OIDC Trusted Publishing (no API tokens in CI)
- **Configured in**: PyPI project settings → "Trusted Publishers"
- **Workflow**: `.github/workflows/publish.yml`
- **Trigger**: tag push `v*` on public repo
- **Environment**: `pypi` (GitHub Environment with deployment protection)
- **Build**: hatchling (`[build-system]` in pyproject.toml)

### Deprecated cognitia wrapper

The old `cognitia` package on PyPI is a thin wrapper that re-exports `swarmline`. It lives in `deprecated-cognitia/` and should only be updated if:
- The minimum swarmline version it depends on needs bumping
- The wrapper itself has a bug

To publish it (manual, rare):
```bash
cd deprecated-cognitia
pip install build twine
python -m build
twine upload dist/*   # uses cognitia-deprecated-wrapper API token
```

## Decision log

| Date | Version | Rationale |
|------|---------|-----------|
| 2026-04-11 | 1.4.1 | First release as `swarmline` (renamed from `cognitia`). Kept version continuity. |
| 2026-04-11 | cognitia 1.5.0 | Deprecated wrapper pointing to swarmline>=1.4.1 |
