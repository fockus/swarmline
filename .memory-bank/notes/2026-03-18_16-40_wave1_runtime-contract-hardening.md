# Wave 1 Runtime Contract Hardening

Дата: 2026-03-18 16:40

- `final.new_messages` является каноническим delta-представлением истории turn'а. Facade и `Conversation` должны брать историю из него, а не восстанавливать её эвристически из `text_delta`.
- Portable runtime wiring должно отличаться от native/CLI: `mcp_servers` пробрасываются только туда, где runtime реально поддерживает этот seam. Facade-only kwargs нельзя без фильтра прокидывать в registry factories.
- Любой runtime helper, который завершился без terminal `final`/`error` или без final `ResultMessage`, обязан fail-fast'иться typed error'ом. Пустой success опаснее явной ошибки.
- Wrappers (`BaseRuntimePort`, `SessionManager`) должны переносить final metadata в свои `done` events. Иначе facade-level метрики и structured output теряются на compatibility path.
- Для tool-видимости недостаточно зарегистрировать executor. LLM-facing surface должна отдельно advertises `ToolSpec` (`send_message`, local tools), иначе execution path и planning surface расходятся.
- Retry ownership в thin runtime должен жить в одном месте. Для buffered post-processing authoritative слой — strategy-level buffered call path, а не constructor-level wrapper.
