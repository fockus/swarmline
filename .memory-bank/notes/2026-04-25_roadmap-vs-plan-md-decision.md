# roadmap.md vs plan.md — Memory Bank decision
Date: 2026-04-25 (session)

## What was done
- Skill `mb-plan-sync.sh` (v3.1+) ожидает `.memory-bank/roadmap.md`, но в проекте canonical — `.memory-bank/plan.md` (legacy convention).
- Создан симлинк `.memory-bank/roadmap.md → plan.md` (forward-compat alias).
- На macOS APFS file system case-INSENSITIVE — `STATUS.md` доступен и как `status.md`, симлинк не нужен. На Linux/CI (case-sensitive ext4) — может потребоваться `ln -s STATUS.md status.md`.
- ADR-002 фиксирует hybrid migration plan: сейчас симлинк, при следующем `/mb upgrade` — rename + reverse symlink.
- I-001 — запрос на patch skill для автоматической миграции (HIGH priority).

## New knowledge
- **Pattern**: при разногласии skill-canonical и project-canonical имени — forward-compat symlink в направлении skill ожидает (canonical_skill → canonical_project) — обратимо одной командой и не ломает существующие ссылки.
- **macOS APFS gotcha**: `ln -sf STATUS.md status.md` на case-insensitive FS создаёт симлинк-loop ("Too many levels"). Решение: НЕ создавать второй симлинк когда case-folding активен. Проверка: `stat -f "%i %N"` — если inode совпадает, файлы — одно и то же.
- **Skill backwards-compat**: project ADR + idea — корректный путь зафиксировать desired skill behavior без модификации глобального skill в текущей сессии.
- **mb-plan-sync output `added=N`** означает добавление H2 секций (`## Stage N:`); если в checklist уже есть H3 (`### Stage N:`) — будут дубликаты. Решение: либо ручная синхронизация без `mb-plan-sync`, либо принять auto-generated H2 как canonical и удалить ручные H3.
