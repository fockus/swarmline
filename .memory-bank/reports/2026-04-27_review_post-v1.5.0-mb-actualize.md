# Code Review Report
Date: 2026-04-27
Files reviewed: 4 modified (Memory Bank docs) + 1 untracked dir
Lines changed: +109 / -57 (docs-only; zero source code or test changes)

## Scope of this review

Working tree post-`/mb update` actualize: четыре документа Memory Bank (`STATUS.md`, `checklist.md`, `plan.md`, `roadmap.md`) актуализированы под факт v1.5.0 release (tag `v1.5.0` → commit `3fae1b2`, pushed to private `origin` only). Также есть untracked `.memory-bank/codebase/` (51MB output `/mb graph` + `/mb map`).

**Никакого исходного кода / тестов не изменено** — поэтому SOLID/Clean Architecture/TDD/security/perf анализ неприменим. Code-style проверки (mb-rules-enforcer) не запускались — нет .py-файлов в diff.

## Critical
<!-- Merge blockers: bugs, vulnerabilities, broken tests -->

_None._ Всё уже зарелижено (`v1.5.0` tag), 0 source-code изменений, 0 тестов сломано.

## Serious

### 1. `.memory-bank/codebase/` — 51MB untracked, не защищён .gitignore

`.memory-bank/codebase/` (51M) состоит из:
- `.archive/` — 30M (два snapshot-а от 2026-04-25: `2026-04-25_root-scope/`, `2026-04-25_src-scope/`)
- `.cache/` — 14M (~сотни мелких JSON-файлов graph cache)
- `graph.json` — 7.5M (полный code graph, JSON Lines)
- 4 `.md` (`STACK.md`, `ARCHITECTURE.md`, `CONVENTIONS.md`, `CONCERNS.md`) + `god-nodes.md` — суммарно ~24K

**Риск:** одна неосторожная команда `git add .memory-bank/` ИЛИ `git add -A` — и репо распухнет на 51MB бинарного шума, который потом тяжело удалять из истории. На public sync через `./scripts/sync-public.sh` это тоже потенциально просочится (зависит от фильтра).

**Рекомендация (один из вариантов):**
- (a) Добавить в `.gitignore`:
  ```
  .memory-bank/codebase/.archive/
  .memory-bank/codebase/.cache/
  .memory-bank/codebase/graph.json
  ```
  Тогда `*.md`-файлы карты остаются tracked (полезный артефакт `/mb map`), а тяжёлый граф/архив — локально.
- (b) Либо целиком игнорировать `.memory-bank/codebase/`, если контентом ни одна сессия не пользуется — `/mb context` его прочитает повторно через `/mb map` при необходимости.
- (c) Минимум: проверить, что `scripts/sync-public.sh` фильтрует `.memory-bank/` целиком (см. CLAUDE.md "filtered out by sync script") — если так, public-репо защищён, но private всё равно копит мусор.

### 2. Plan-файл `plans/2026-04-25_fix_v150-release-blockers.md` — внутренние DoD не актуализированы

Актуализация перевернула 21 stage-summary в `.memory-bank/checklist.md` (✅ с цитатами commit SHA), но **сам plan-файл оставила нетронутым** — внутри 21 ⬜ DoD-элементов (по 1 на стадию: `- ⬜ <stage description>`) против 10 ✅ (старые pre-release пометки).

Это нарушает workflow `/mb verify` (CLAUDE.md): "Перед `/mb done` если работа по плану — `/mb verify` обязателен". Без перевёртывания DoD внутри plan-файла последующий verify покажет false-negative.

**Рекомендация:** перевернуть 21 ⬜ → ✅ внутри `plans/2026-04-25_fix_v150-release-blockers.md` (с теми же commit-ссылками что в checklist), либо явно пометить plan как `### Status: SHIPPED 2026-04-25 — see checklist for stage-level confirmations` и оставить DoD как историческую ссылку.

## Notes

### N1. Двойной src-count в STATUS.md: "385 .py / 817 total"
Уточнено правильно (817 включает YAML/JSON/MJS-файлы — `runtime/models.yaml`, `runtime/pi_sdk/bridge.mjs`). Но историческая запись в той же секции остаётся `~336 .py files` от 2026-04-13. Это не ошибка, а timeline-маркер — оставлено намеренно. **OK as-is.**

### N2. Stage 18, 20 не цитируют commit SHA в checklist
В `checklist.md` Stage 18 / Stage 20 / Stage 21 имеют `(commit ... Tier ...)` атрибуцию — verified в diff. **OK.**

### N3. plan.md / roadmap.md описывают идентичный "Next Step #1: public sync"
DRY-нарушение мелкое (документация, не код). По convention эти два файла дополняют друг друга (plan = vector/focus; roadmap = milestone-level). Редактор актуализации мог бы сослаться: roadmap → "see plan.md for detail". **Низкий приоритет.**

### N4. KISS / YAGNI
Документы кратки, нет over-engineering, нет планирования "на будущее" в неактуализированных секциях. **OK.**

## Tests

- Unit / Integration / E2E: ⚠️ **N/A — изменены только docs**
- Last verified pytest run (per STATUS.md, не повторял): `5452 passed, 7 skipped, 5 deselected, 0 failed` (2026-04-27, `rtk proxy pytest --tb=no -q`, ~52s)
- ty: `ty check src/swarmline/` → 0 diagnostics (baseline locked)
- ruff: `ruff check src/ tests/` → All checks passed (per STATUS)

**Не запускал тесты заново** — diff документов не может их сломать; release-gate уже зелёный согласно последней зафиксированной выкатке.

## Plan alignment

Активный план: `plans/2026-04-25_fix_v150-release-blockers.md` (v1.5.0 release-blockers, 21 stage). Сам v1.5.0 уже зарелижен и tagged.

- **Implemented в этом diff'e:** актуализация 4 core MB-файлов под факт v1.5.0 release; добавлена таблица "Last release" в STATUS.md; перевёрнуты 21 stage-summary в checklist.md с commit-атрибуцией; обновлён "Next steps" на public sync + Production v2.0 reactivation.
- **Not implemented (gap):** DoD-checkboxes внутри `plans/2026-04-25_fix_v150-release-blockers.md` (Serious #2). `/mb verify` сейчас вернёт inconsistency.
- **Outside the plan:** untracked `.memory-bank/codebase/` (51MB output `/mb graph`/`/mb map`, накопленный во время release prep — не часть release plan'а).

## Summary

Doc-only актуализация чистая по фактам (все 11 commit SHA реальны, метрики совпадают с реальным состоянием репо), безопасна для merge. **Два следящих за вниманием момента:** (1) 51MB untracked `.memory-bank/codebase/` рядом с .git — добавить .gitignore-паттерн или явно решить, что часть его коммитится; (2) plan-файл не синхронизирован со своим rolled-up summary — `/mb verify` поднимет это до commit.

**Рекомендация:** перед `chore(memory-bank): post-v1.5.0 actualize` коммитом — закрыть Serious #1 (gitignore) и Serious #2 (perevernut DoD inside plan-файла). Затем merge безопасен. Содержательная сторона актуализации не блокирует. Public sync — отдельный шаг, по-прежнему ждёт явного user approval.
