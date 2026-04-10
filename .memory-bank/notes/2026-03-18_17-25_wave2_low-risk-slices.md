# Wave 2 Low-Risk Slices

Дата: 2026-03-18 17:25

- Первый shared-helper slice в migration cleanup безопаснее держать внутри `agent/`, а не в `session/` или `runtime/`. `SessionManager` всё ещё несёт legacy `RuntimePort` + persisted snapshot semantics, и ранняя унификация там создаёт больше риска, чем пользы.
- Portable runtime wiring удобно сводить к одному плану: `RuntimeConfig`, `tool_executors`, `active_tools`, conditional `mcp_servers` и `deepagents.thread_id`. Это уменьшает расхождение между `Agent` и `Conversation`, не трогая SDK path.
- Package-level optional exports должны быть lazy и fail-fast, но при этом не ломать доступ к реальным submodules. Для package `__getattr__` нужен fallback `import_module(f"{__name__}.{name}")`, иначе ломаются `monkeypatch` и dotted-import tooling.
- `None` placeholder в public API хуже явного `ImportError`: consumer считает символ валидным и ломается позже, дальше от причины.
