# cli-runtime-taskqueue-review-fixes
Date: 2026-03-18 15:20

## Что сделано
- `SqliteTaskQueue.complete()` / `cancel()` переведены на atomic compare-and-set transition внутри одной SQLite transaction.
- `CliAgentRuntime` теперь определяет Claude CLI по basename и эмитит `bad_model_output`, если subprocess завершился без final NDJSON event.
- `execute_agent_tool()` теперь изолирует любой `Exception`, не только whitelist исключений.

## Проверка
- Targeted regression `pytest`: `150 passed`
- `ruff check` по changed files: green
- Full offline `pytest -q`: `2331 passed, 16 skipped, 5 deselected`

## Примечание
- Эта запись supersedes optimistic note `2026-03-18_14-43_cli-taskqueue-p1-fixes.md`; старую историю не переписываем.
