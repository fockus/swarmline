# Research: Paperclip Tasks/Hierarchy + NanoClaw + RTK + DeepAgents CLI

## Paperclip Task System
- **Status machine**: backlog → todo → in_progress → in_review → done/cancelled/blocked
- **Checkout**: атомарный UPDATE с stale adoption — если run мёртв, новый забирает задачу
- **Task session**: persistent per task (не per agent), переживает переназначение
- **Priority**: critical(0) > high(1) > medium(2) > low(3), SQL CASE ORDER
- **Identifier**: auto-increment per company, формат "PAP-42"
- **Parent tasks**: self-referencing parentId для иерархии задач

## Paperclip Agent Hierarchy
- **Org chart**: `reportsTo` self-reference, cycle detection (обход до 50 levels)
- **Lifecycle**: pending_approval → idle ↔ running → paused → terminated
- **Permissions**: canCreateAgents, per-agent, наследуются budget constraints
- **Config versioning**: snapshot before/after каждого изменения, rollback
- **Budget**: monthly cents, auto-pause при превышении

## NanoClaw — уникальные идеи для cognitia
1. **Credential Proxy** → IDEA-020: секреты не в runtime, placeholder → injection
2. **Memory Scopes** → IDEA-021: global/agent/shared три уровня
3. **CallerPolicy** → IDEA-022: sender allowlist, первая линия до guardrails
4. **ConcurrencyGroup** → встроено в 9D delegation: max_concurrent per group
5. **Context since last run** → встроено в 9E scheduler: events_since_last_run

## RTK (Rust Token Killer)
- CLI proxy на Rust, перехватывает bash → фильтрует boilerplate (не LLM)
- 60-90% экономия: git diff 94%, pytest 96%, git log 86%
- **Нет API/SDK** — только CLI. Интеграция: subprocess wrapper + `shutil.which("rtk")`
- Для ClaudeCodeRuntime: работает автоматически через hook, ничего не нужно
- Для ThinRuntime/CLI: toggleable wrapper → IDEA-017

## DeepAgents CLI (замена Cline в presets)
- `deepagents -n "<task>" -q [--no-stream]` — non-interactive, quiet, buffered
- `deepagents --agent <name> --model provider:model` — named agent + model
- `-S recommended` — разрешить shell commands
- `--json` только для management (list, threads, skills), не для inference
- Max piped input: 10 MiB
- Session: `--resume [ID]`, `/offload` для компрессии
