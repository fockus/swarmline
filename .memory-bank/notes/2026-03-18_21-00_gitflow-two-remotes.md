# Git Workflow: Two Remotes + GitHub Flow

Настроено 2026-03-18. Две удалённые репы для разделения разработки и публикации.

**Remotes:**
- `origin` → github.com/fockus/swarmline-dev (private) — все ветки, WIP
- `public` → github.com/fockus/swarmline (public) — только стабильный main

**Branching:** GitHub Flow — feat/, fix/, release/ ветки → PR → main
**Sync:** `./scripts/sync-public.sh` — проверяет тесты и пушит main в public
**Private content:** .memory-bank/, .claude/, RULES.md, CLAUDE.md — gitignored, никогда не в git

Подробности: секция "Git Workflow" в CLAUDE.md
