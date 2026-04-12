## Unified Release-Risk Remediation Complete

- Закрыт unified backlog из `plans/2026-03-18_unified-release-risk-remediation-backlog.md` без расширения public API.
- Критичные persistence fixes: `SessionKey` больше не коллидирует на `:`, `InMemorySessionBackend` и `InMemoryMemoryProvider` хранят snapshot, `SqliteSessionBackend` больше не падает на concurrent `save/load/list/delete`.
- Критичные runtime fixes: `RuntimeAdapter` сохраняет `tool_use_id`/error semantics в stream events, `ClaudeCodeRuntime` больше не маскирует failed tool results как `ok=True`.
- Portable MCP wiring теперь понимает dict-style server specs (`{"type": "http", "url": ...}`) на utility boundary.
- Финальные гейты после закрытия batch'ей: `ruff check src/ tests/`, `mypy src/swarmline/`, `pytest -q`, workflow example smoke и CLI subprocess smoke — все зелёные.
