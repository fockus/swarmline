# Follow-up Hardening Pass

- Локально закрыт остаточный contract gap: `Conversation` и `SessionManager` больше не записывают partial assistant history после terminal error и не пробрасывают portable runtime exceptions наружу.
- `CliAgentRuntime.cancel()` приведён к общей cancellation semantics (`cancelled` вместо `runtime_crash`).
- `InMemoryMemoryProvider` теперь snapshot-store для session state; это было подтверждено уже существующим красным unit test.
- Часть старых audit findings оказалась уже закрыта в текущем дереве и была только переверифицирована: `SessionKey` escaping, `SqliteSessionBackend` concurrent access, workflow resume, parallel export, DeepAgents team aggregate state, SQL fact-source priority.
- Финальные quality gates на workspace после follow-up pass: `ruff check src/ tests/`, `mypy src/swarmline/`, `pytest -q`, `git diff --check` — зелёные.
