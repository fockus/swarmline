# Re-review findings follow-up

- Подтверждены 4 дополнительных findings после remediation Wave 2; их нельзя считать закрытыми.
- `SessionManager.stream_reply()` теряет canonical `final.new_messages` и сохраняет только synthetic assistant text, поэтому session-based multi-turn path всё ещё теряет tool context.
- builtin `cli` добавлен в registry/valid runtime names, но legacy fallback в `RuntimeFactory.create()` не знает про `cli`; при недоступном registry runtime становится valid-but-unconstructable.
- lazy fail-fast optional exports создали новый public-surface regression: `from cognitia.runtime import *` падает без SDK extras, потому что SDK-only names остаются в `__all__`.
- аналогичный public-surface regression есть в `cognitia.skills`: YAML-only helpers попали в `__all__`, и star import теперь требует PyYAML даже для core registry/types.
- Уточнение после broader audit: `PyYAML` объявлен core dependency в `pyproject.toml`, поэтому `skills` finding нужно трактовать как low-confidence public-surface consistency gap, а не как unsupported-install blocker.
- Эти findings нужно перенести в следующий remediation backlog отдельно от broader audit debt, чтобы не потерять среди pre-existing проблем.
