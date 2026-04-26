---
type: hygiene
tags: [release-housekeeping, v1.5.0, code-review, memory-bank]
related_features: []
sprint: null
importance: medium
created: 2026-04-27
---

# post-v1.5.0-mb-actualize-and-review
Date: 2026-04-27 00:57

## What was done
- Committed `b335090` — `chore(memory-bank): post-v1.5.0 actualize` (4 files, +109/-57: STATUS, checklist, plan, roadmap reflect v1.5.0 SHIPPED + 2026-04-27 metrics).
- `/review` produced `.memory-bank/reports/2026-04-27_review_post-v1.5.0-mb-actualize.md` (untracked). Critical: none. Serious: 2 open.
- Two open decisions deferred to user: (a) `.gitignore` for `.memory-bank/codebase/` 51MB untracked dir, (b) inner ⬜ DoD checkboxes in `plans/2026-04-25_fix_v150-release-blockers.md`.

## New knowledge
- **MB-wide gap:** `.memory-bank/codebase/` (51MB: `.archive/` 30M pre-release snapshots + `.cache/` 14M graph cache + `graph.json` 7.5M) is untracked but **not protected by `.gitignore`** — single `git add -A` can accidentally inflate repo. Project-wide remediation candidate: add `.memory-bank/codebase/{.archive,.cache,graph.json}` to `.gitignore`, optionally keep the 4 small `.md` maps tracked.
- **Workflow gap:** `/mb update` only rolls up stage status into `checklist.md`; it does **not** flip the inner `- ⬜ <stage description>` lines inside the plan file itself. `/mb verify` is the mechanism that catches this drift — running it before `/mb done` for plan-driven sessions is the missing step. Either teach `/mb update` to walk plan-file DoD checkboxes, or treat closed plan files as immutable historical documents with a `SHIPPED <date> — see checklist for stage-level confirmations` header.

## Followups
- **Serious #1:** decide `.gitignore` policy for `.memory-bank/codebase/` (gitignore subdirs vs delete entirely — `/mb map` regenerates).
- **Serious #2:** flip plan-file inner DoD ⬜→✅ as follow-up commit, or add SHIPPED header and treat as historical.
- **Public sync:** `./scripts/sync-public.sh --tags` → PyPI auto-publish via OIDC — awaiting user approval before destructive remote write.
