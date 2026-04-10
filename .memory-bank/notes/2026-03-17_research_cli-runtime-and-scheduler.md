# Research: CLI Agent Runtime & Scheduled Agents Patterns

## Источники
- **Paperclip** (paperclipai/paperclip) — production heartbeat + CLI adapters
- **OpenClaw** (openclaw) — cron jobs, session targeting, jitter
- **NanoClaw** (qwibitai/nanoclaw) — container-based scheduling
- **claudecron** (phildougherty) — MCP server with 5 trigger types
- **claw0** (shareAI-lab) — educational timer thread pattern

## Ключевые паттерны

### CLI Runtime (для IDEA-003)
1. **Stdin-as-prompt** (Paperclip): CLI получает задачу через stdin, не через args/env — позволяет динамические промпты
2. **Env isolation**: удалять CLAUDE_CODE_* vars перед spawn — защита от nested session rejection
3. **NDJSON parsing**: line-by-line post-hoc, не realtime. Live logs отдельно через onLog callbacks
4. **Session resume**: `--resume <sessionId>` + cwd compatibility check. При ошибке — retry без resume
5. **Session compaction**: авторотация при max_runs / max_tokens / max_age. Handoff markdown → prompt
6. **Process registry**: global Map<runId, child> для orphan detection при restart

### Scheduler (для IDEA-007)
1. **Queue-then-execute** (Paperclip): все runs сначала в БД как `queued`, потом claim через optimistic locking
2. **Coalescing** (Paperclip): concurrent wakeups для same scope → merge context, не создавать новый run
3. **Session targeting** (OpenClaw): isolated / custom-named / main — разные use cases
4. **Deterministic jitter** (OpenClaw, Claude Code): hash(job_id) → offset, не random — предсказуемость
5. **No catch-up** (Claude Code, OpenClaw): пропущенный fire = пропущен. Стандарт де-факто
6. **JSONL history** (OpenClaw, claudecron): append-only run history — аудитируемость без schema migrations
7. **Token sink warning** (OpenClaw #11042): heartbeat с большим контекстом = дорого. Isolated cron jobs дешевле

### Trigger types
- Paperclip: timer / assignment / on_demand / automation (4 типа)
- claudecron: cron / hook / file_watch / dependency / manual (5 типов)
- OpenClaw: cron / interval / one-shot (3 формата schedule)
- **Наш выбор**: timer(cron+interval) / one_shot / event / on_demand (4 типа)
