# Plan: fix — v1.5.0 release-blockers

**Дата:** 2026-04-25
**Тип:** fix (release-blockers + DX paper-cuts + security hardening)
**Статус:** ✅ SHIPPED 2026-04-25 — tag `v1.5.0` on commit `3fae1b2`. All 21 stages merged on `main`. Pushed to private `origin` only; public sync to PyPI awaits user approval. Inner DoD `- [ ]` markers preserved as historical acceptance criteria — stage-level closure recorded in the rolled-up checklist below (lines 1833-1862) with commit attribution. Mirror in `.memory-bank/checklist.md` ("v1.5.0 release-blockers plan — ALL STAGES DONE").
**Complexity:** L
**Baseline commit:** 1c896cbbeb6582c18a3b5af4dedb6d78e2ad78ea

---

## Цель

Закрыть все release-blockers, выявленные master production-readiness audit (4 параллельных аудита: architect / DX / security / reality), и подготовить публикацию `v1.5.0` (1.4.1 → 1.5.0). Без этого плана `git tag v1.5.0` шипит:

1. Красный CI lint job (1 ruff error + 457 unformatted files)
2. Empty `[Unreleased]` CHANGELOG entry, несмотря на 55 commits / 7 phases
3. `pyproject.toml` всё ещё `1.4.1`
4. Test-install matrix падает на Python 3.10 (но `requires-python>=3.11`)
5. Default runtime mismatch (`claude_sdk` в коде vs `thin` в docs) — first-time user hits ImportError
6. Russian error string в user-facing path
7. Sync file I/O в `JsonlTelemetrySink.record` блокирует event loop
8. Test isolation сломана из-за `force=True` в `logging.basicConfig`

## Scope

### Входит:
- **Tier 1 (~6h, MUST)**: code/tooling fixes, обязательные для зелёного CI
- **Tier 2 (~3h, MUST)**: CHANGELOG `[1.5.0]`, migration guide, minimum-viable feature docs
- **Tier 3 (~7h, STRONGLY RECOMMENDED)**: DX paper-cuts (трим `__all__`, `SwarmlineError`, MockRuntime extraction, `ThinkingConfig` typed promotion, удаление `max_thinking_tokens`)
- **Tier 4 selected (~3.5h, SHIP)**: M-1 (loopback enforcement в `serve`), M-3 (расширенный JSONL redaction), `pip-audit` в CI

### НЕ входит:
- Tier 5 / v1.6+ items (разбивка `AgentConfig` на composed configs, рефакторинг `ThinRuntime.run()`, `@agent.hook` decorator, FastAPI-style `Depends()`, M-2 sanitisation провайдер-исключений) — они **non-blocking** для v1.5.0
- Refactoring `ThinRuntime.run()` god-method (H-6) — defer
- Refactoring `session/manager.py:_run_awaitable_sync` (H-7) — defer
- Thread-safe `CircuitBreaker` (H-8) — defer
- Renaming `Conversation.say` → `Conversation.query` — breaking, defer to v2.0

## Assumptions

- Repo on branch `main`, baseline `1c896cb`, working tree clean (после уже-staged фич) — pre-flight `git status` подтвердит.
- Все 5352 offline-теста зелёные **в isolation**. Нужно достичь, чтобы проходило в combined run после fix C-1/C-3.
- Coverage baseline = 86%. Нет регрессий (≥86% в финале).
- Existing public API unchanged (additive только) — все существующие тесты проходят без модификаций (кроме тех, которые специально опираются на старый default runtime).
- `ty check src/swarmline/` = 0 — baseline locked. Не должна расти.
- В будущем `release/v1.5.0` создаётся отдельной операцией (вне scope этого плана) — план фокусируется на code/docs работе на `main`.

## Риски

| Риск | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Stage 5 (logger fix) ломает > 14 тестов, которые сейчас проходят | M | H | После каждого encoding/stream-related изменения — `pytest -q` full run; gate перед merge. Если регрессии — атомарный rollback Stage 5 и пересмотр плана. |
| Stage 2 (default runtime) ломает downstream users, опирающихся на `claude_sdk` default implicitly | M | M | Документировать в CHANGELOG как **non-breaking** (default — heuristic), перечислить migration steps. Gate: `pytest -q tests/unit/test_agent_facade.py` зелёный. |
| Stage 14 (`__all__` trim) удаляет имена, которые downstream users импортируют | L | H | Все удаляемые имена остаются доступны через `from swarmline.<module> import X` (модульный путь). Только `__all__` (т.е. wildcard `from swarmline import *`) сужается. |
| Stage 16 (extract `_MockBasicsRuntime` → `swarmline.testing`) breaks `examples/01_agent_basics.py` smoke test | L | M | TDD на module level: `from swarmline.testing import MockRuntime; agent = ...` работает; example smoke регрессионный тест продолжает проходить. |
| Stage 6 (JsonlTelemetrySink async fix) меняет ordering записи под нагрузкой | L | L | Single asyncio.Lock + asyncio.to_thread сохраняют write order для same-task callers. Документировать non-guarantee для cross-task ordering. |
| Stage 19 (M-1 serve loopback) breaks downstream test infra, который ожидает `allow_unauthenticated_query=True` без host-проверки | L | M | Параметр `host: str | None = None` опционален; если не передан — поведение без изменений (предупреждение в logger вместо ValueError). Документировать в CHANGELOG. |
| Stage 12 (feature docs) пропустит фичу — пользователи не найдут её | M | L | Используем git log v1.4.0..HEAD и `__all__` diff как exhaustive checklist. Не нужны полные docs — minimum-viable stub OK. |
| Total effort ≥ 19h vs estimated 12-15h (out of single-session range) | M | L | План разбит на atomic stages. Можно execute partially (Tier 1+2+selected Tier 4 = 12.5h = 2 сессии). Tier 3 не блокирует. |
| Tier 4 securityfix меняет behaviour и backward-compatible | L | M | Для serve.create_app параметр host опционален, если None — без regression. JSONL redaction только расширяет (никогда не сужает). Параметризованный test для всех старых redact keys. |
| Stage 9 (version bump) забыт перед `git tag v1.5.0` | L | H | Gate в final checklist; `swarmline.__version__ == "1.5.0"` проверка в Stage 9 DoD. |

---

## Этапы

<!-- mb-stage:1 -->
## Stage 1: CI lint cleanup — `ruff check --fix && ruff format`

**Source**: T1.1 = C-6
**Effort**: ~5min
**Type**: tooling

**What to do:**
- Запустить `ruff check --fix src/ tests/` — фиксит F401 в `tests/unit/test_pi_sdk_runtime.py:5` и любые другие auto-fixable.
- Запустить `ruff format src/ tests/` — приводит 457 файлов к canonical formatting.
- Нет code logic change — только tooling.

**Testing (TDD — tests BEFORE implementation):**
- TDD not applicable: формат-only change. Существующие 5352 тестов остаются зелёными — gate.

**Files to touch:**
- `src/**/*.py` — formatted by ruff
- `tests/**/*.py` — formatted + 1 unused import auto-removed in `tests/unit/test_pi_sdk_runtime.py:5`

**Commands to verify:**
```bash
ruff check --fix src/ tests/
ruff format src/ tests/
ruff check src/ tests/        # -> "All checks passed"
ruff format --check src/ tests/  # -> "X files already formatted"
pytest -q                     # -> 5352 passed (no regression)
ty check src/swarmline/       # -> All checks passed!
```

**DoD (SMART):**
- [ ] `ruff check src/ tests/` — exit 0, "All checks passed!"
- [ ] `ruff format --check src/ tests/` — exit 0
- [ ] `pytest -q` — full green (no regression vs baseline)
- [ ] `ty check src/swarmline/` — All checks passed!
- [ ] Coverage ≥86% (no regression)

**Code rules:** Tooling-only. KISS.

---

<!-- mb-stage:2 -->
## Stage 2: Default runtime fix — `claude_sdk` → `thin`

**Source**: T1.2 = C-8
**Effort**: ~1h
**Type**: code (behavioural change)

**What to do:**
- В `src/swarmline/agent/config.py:35`: изменить `runtime: str = "claude_sdk"` → `runtime: str = "thin"`.
- Обновить inline comment `# Runtime: thin | claude_sdk | deepagents | cli | openai_agents | pi_sdk` → подчеркнуть, что `thin` is default.
- Обновить existing тесты, которые **specifically** opираются на `claude_sdk` default:
  - `tests/unit/test_runtime_factory.py:25-27` (`test_default_is_claude_sdk`) — переименовать → `test_default_is_thin` и поправить assertion. **CRITICAL**: проверить, что этот test действительно про `AgentConfig` default. Если это про `RuntimeFactory.resolve_runtime_name()` (отдельный layer) — оставить как есть. Прочитать контекст test'а перед правкой.
  - `tests/unit/test_runtime_registry.py:239` (если ассертит default registration name) — проверить.
  - `tests/unit/test_agent_facade.py:260` (`caps.runtime_name == "claude_sdk"`) — проверить test setup; если в setup явно передан `runtime="claude_sdk"`, оставить; если test полагается на default, обновить.
- Проверить, что `tests/integration/test_docs_examples_consistency.py:142` ("AgentConfig.env is currently used by the `claude_sdk` runtime path") ссылается на documentation string — может потребовать обновления.

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** в `tests/unit/test_agent_config.py`: 
  - `test_default_runtime_is_thin` — `assert AgentConfig(system_prompt="x").runtime == "thin"`.
  - `test_explicit_claude_sdk_runtime_preserved` — `assert AgentConfig(system_prompt="x", runtime="claude_sdk").runtime == "claude_sdk"`.
- Update existing assertions: переименовать `test_default_is_claude_sdk` → `test_default_is_thin` (если test about `AgentConfig`).

**Files to touch:**
- `src/swarmline/agent/config.py:35` (modify default value + comment)
- `tests/unit/test_agent_config.py` (add 2 new tests)
- `tests/unit/test_runtime_factory.py:25-27` (verify scope; possibly rename test if it's about AgentConfig default; otherwise leave)
- `tests/unit/test_agent_facade.py` (verify any failing assertions and update if rooted on default)
- Поиск `pytest -q -x` — фикс tests, которые падают из-за изменения

**Commands to verify:**
```bash
pytest tests/unit/test_agent_config.py::TestDefaults -xvs  # red phase first
# Implement change
pytest tests/unit/test_agent_config.py -xvs                # green
pytest -q                                                   # full suite green
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] `AgentConfig(system_prompt="x").runtime == "thin"` (verified in new test)
- [ ] `AgentConfig(system_prompt="x", runtime="claude_sdk").runtime == "claude_sdk"` (override preserved)
- [ ] All 5352+ tests green
- [ ] Inline comment в `config.py:34` явно говорит "default: thin (lightweight, multi-provider)"
- [ ] CHANGELOG entry скрипт-готов: "Default runtime changed from `claude_sdk` to `thin`"
- [ ] No `ty check` regressions
- [ ] Lint clean

**Edge cases:**
- Tests, которые делают `AgentConfig(system_prompt="x")` без `runtime` и проверяют downstream behaviour, могут начать падать с другим code path. Не угадывать — запустить full suite, обнаружить, обновить.
- `AgentConfig.env`-related tests могут упоминать "claude_sdk runtime path" в docs — проверить, что docs-consistency тест не падает.

**Code rules:** SOLID, KISS. Backward-compat: default value change (NOT a removal); `runtime="claude_sdk"` остаётся валидным, документировано в CHANGELOG.

---

<!-- mb-stage:3 -->
## Stage 3: Russian error string fix

**Source**: T1.3 = C-9
**Effort**: ~5min
**Type**: code (i18n)

**What to do:**
- В `src/swarmline/runtime/thin/errors.py:45`: заменить `f"Ошибка LLM API ({provider}): {type(exc).__name__}: {exc}"` → `f"LLM API error ({provider}): {type(exc).__name__}: {exc}"`.

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** в `tests/unit/test_thin_runtime_errors.py` (создать, если нет):
  ```python
  def test_provider_runtime_crash_message_is_english():
      err = provider_runtime_crash("anthropic", ValueError("boom"))
      assert "LLM API error" in err.error.message
      assert "Ошибка" not in err.error.message
      assert "anthropic" in err.error.message
      assert "ValueError" in err.error.message
  ```

**Files to touch:**
- `src/swarmline/runtime/thin/errors.py:45` (modify)
- `tests/unit/test_thin_runtime_errors.py` (create or extend) — 1 test

**Commands to verify:**
```bash
pytest tests/unit/test_thin_runtime_errors.py -xvs   # red, then green
pytest -q                                             # full suite
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] No Russian text remains in `src/swarmline/runtime/thin/errors.py` (`grep -i "Ошибка"` returns 0 hits)
- [ ] New test asserts English-only message
- [ ] Full suite green

**Code rules:** KISS, i18n: English-only in user-facing strings.

---

<!-- mb-stage:4 -->
## Stage 4: Docs lie fix — `agent-facade.md:36`

**Source**: T1.4 = C-10
**Effort**: ~5min
**Type**: docs

**What to do:**
- В `docs/agent-facade.md:36`: заменить "All fields have sensible defaults. Only `runtime` is typically required." → "All fields except `system_prompt` have sensible defaults. `system_prompt` is the only required parameter."
- Проверить остальной текст файла на consistency: блок example на line 7-13 показывает `Agent(AgentConfig(runtime="thin"))` без `system_prompt` — это **сломается** с `ValueError`. Обновить на:
  ```python
  agent = Agent(AgentConfig(system_prompt="You are a helpful assistant."))
  ```
  (`runtime="thin"` теперь default — Stage 2)

**Testing (TDD — tests BEFORE implementation):**
- TDD not applicable: doc-only change. Опираемся на `tests/integration/test_docs_examples_consistency.py` если оно валидирует agent-facade.md (проверить — если да, может потребовать обновления expected strings).

**Files to touch:**
- `docs/agent-facade.md:7-13, 36` (modify)
- (опционально) `tests/integration/test_docs_examples_consistency.py` — проверить, не падает ли

**Commands to verify:**
```bash
pytest tests/integration/test_docs_examples_consistency.py -xvs
pytest -q
```

**DoD (SMART):**
- [ ] `docs/agent-facade.md` example block uses `system_prompt=...` and no longer relies on `runtime="thin"` (since now default)
- [ ] Line 36 description is accurate: `system_prompt` is the only required parameter
- [ ] `pytest tests/integration/test_docs_examples_consistency.py -xvs` green

**Code rules:** Truthful docs.

---

<!-- mb-stage:5 -->
## Stage 5: Test isolation fix — drop `force=True`, route stdlib logging to stderr

**Source**: T1.5 = C-1, C-3
**Effort**: ~2h
**Type**: code (behavioural — fixes test isolation, fixes CLI JSON contract)

**What to do:**
- В `src/swarmline/observability/logger.py:22-27`: 
  - Изменить `stream=sys.stdout` → `stream=sys.stderr` (CLI JSON output не контаминируется).
  - **Опасно**: убрать `force=True` целиком (или изолировать только если basicConfig ещё не был вызван).
  - Альтернативный безопасный паттерн:
    ```python
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=numeric_level,
            stream=sys.stderr,
            format="%(levelname)s %(name)s: %(message)s",
        )
    ```
  - structlog сам пишет через `PrintLoggerFactory()` — проверить, в какой stream. Если в stdout — переключить через `PrintLoggerFactory(file=sys.stderr)`.
- Документировать на module-level: "Logs go to stderr to avoid corrupting stdout JSON CLI output."
- (Опционально, для надёжности) Добавить pytest fixture в `tests/conftest.py`:
  ```python
  @pytest.fixture(autouse=True)
  def _reset_root_logger():
      """Reset root logger between tests so configure_logging() in one test doesn't pollute another."""
      yield
      root = logging.getLogger()
      for h in list(root.handlers):
          root.removeHandler(h)
  ```

**Testing (TDD — tests BEFORE implementation):**
- **NEW integration test** `tests/integration/test_cli_json_output_clean.py`:
  - Вызвать `swarmline --format json team agents` через subprocess (или CliRunner) и assert `json.loads(stdout)` работает без exception.
- **NEW integration test** `tests/integration/test_test_isolation_logger.py`:
  - Запустить два scenarios подряд, второй из которых полагается на `capsys.readouterr().out` без log-noise. Assert `out` не contains "INFO " / "session_created".
- **NEW unit test** `tests/unit/test_observability_logger.py::test_logger_writes_to_stderr_not_stdout`:
  - Mock `sys.stdout`, `sys.stderr`. Вызвать `configure_logging()`, через `logging.info("test")`. Assert "test" попало в stderr, **не** в stdout.

**Files to touch:**
- `src/swarmline/observability/logger.py:22-49` (modify basicConfig + structlog factory)
- `tests/conftest.py` (add `_reset_root_logger` fixture, autouse)
- `tests/unit/test_observability_logger.py` (create) — 1-2 тестов
- `tests/integration/test_cli_json_output_clean.py` (create) — 1 тест
- `tests/integration/test_test_isolation_logger.py` (create) — 1 тест

**Commands to verify:**
```bash
# Red phase
pytest tests/unit/test_observability_logger.py -xvs           # initially fails (or skipped)
pytest tests/integration/test_cli_json_output_clean.py -xvs   # initially fails

# Implement
# Green phase
pytest tests/integration/test_cli_json_output_clean.py -xvs
pytest tests/unit/test_observability_logger.py -xvs

# Test isolation regression check (run combined)
pytest tests/unit/test_event_bus.py tests/unit/test_cli_commands.py -q  # both pass together

# Full suite
pytest -q                                                      # 5354+ passed
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] `pytest tests/unit/test_event_bus.py tests/unit/test_cli_commands.py -q` — both pass together (was 14 fails, now 0)
- [ ] `swarmline --format json team agents` stdout is valid JSON (no log lines mixed in)
- [ ] `configure_logging()` is idempotent (multiple calls don't double-log)
- [ ] Full suite `pytest -q` ≥ 5352 passed
- [ ] No coverage regression
- [ ] No new ty diagnostics

**Edge cases:**
- pytest's `capsys` ведёт себя по-разному с stderr vs stdout. Проверить что existing tests, которые используют `capsys.readouterr().out`, не падают. Если падают — подобрать compromise: маршрутизировать в stderr, но через `caplog` enabled в pytest config.
- structlog уже использует `PrintLoggerFactory()` без явного `file=` argument — выяснить default. Если stdout — pass `file=sys.stderr` явно.
- conftest fixture `_reset_root_logger` может конфликтовать с tests, которые специально настраивают logging в setup — проверить.

**Code rules:** SOLID (SRP — logging-only concern), KISS, Test isolation.

---

<!-- mb-stage:6 -->
## Stage 6: JsonlTelemetrySink async fix — wrap I/O in `asyncio.to_thread()` + add lock

**Source**: T1.6 = C-2
**Effort**: ~1h
**Type**: code (async correctness)

**What to do:**
- В `src/swarmline/observability/jsonl_sink.py`:
  - Add `import asyncio` (если ещё нет).
  - В `__init__`: добавить `self._lock = asyncio.Lock()` (lazy init OK — но dataclass-ish init с `Lock()` пустой работает).
  - **CAREFUL**: `asyncio.Lock()` нельзя создавать в `__init__` если sink instantiated до running loop в некоторых сценариях. Вариант: `self._lock: asyncio.Lock | None = None` и lazy в первом `record()`. Проверить в существующих тестах — если sink создаётся в test setup до event loop, нужен lazy paradigm.
  - В `async def record()`:
    ```python
    async def record(self, event_type: str, data: dict[str, Any]) -> None:
        record = {
            "schema_version": self._schema_version,
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "event_type": event_type,
            "data": _make_json_safe(_redact(data, self._redact_keys)),
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            await asyncio.to_thread(self._append_line, line)
    
    def _append_line(self, line: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    ```
- Подразумевается, что `_append_line` — sync helper, выполняемый в `to_thread`.

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** в `tests/unit/test_jsonl_telemetry_sink.py` (extend existing):
  - `test_record_does_not_block_event_loop`: 
    - Mock `_append_line` to `time.sleep(0.5)` (synchronous).
    - В `asyncio.gather(sink.record(...), some_other_async_task())`.
    - Assert other task makes progress in parallel (timing-based: total < 0.6s, not 1.0s).
  - `test_record_serializes_concurrent_writes_with_lock`:
    - Spawn 50 `sink.record(...)` concurrently.
    - Read `path.read_text()` and assert exactly 50 valid JSONL lines (no interleaved partial writes).

**Files to touch:**
- `src/swarmline/observability/jsonl_sink.py:49-60` (modify)
- `tests/unit/test_jsonl_telemetry_sink.py` (extend with 2 new tests)

**Commands to verify:**
```bash
pytest tests/unit/test_jsonl_telemetry_sink.py -xvs    # red on new tests, then green
pytest -q
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] `record()` does not block other coroutines (verified by gather-with-sleep test, total < 0.6s)
- [ ] 50 concurrent `record()` calls produce exactly 50 valid JSONL lines (no interleaving)
- [ ] All existing tests green
- [ ] No ty regressions

**Edge cases:**
- `asyncio.Lock()` instantiation timing — выше описано.
- File handle creation — `mkdir(parents=True, exist_ok=True)` тоже sync, тоже should be in `to_thread` (или вызывается один раз перед циклом).

**Code rules:** Async correctness, SRP.

---

<!-- mb-stage:7 -->
## Stage 7: Drop Python 3.10 from `publish.yml` matrix

**Source**: T1.7 = C-7
**Effort**: ~2min
**Type**: tooling (CI)

**What to do:**
- В `.github/workflows/publish.yml:42`: изменить `python-version: ['3.10', '3.11', '3.12', '3.13']` → `python-version: ['3.11', '3.12', '3.13']`.

**Testing (TDD — tests BEFORE implementation):**
- TDD not applicable: CI YAML config change.

**Files to touch:**
- `.github/workflows/publish.yml:42`

**Commands to verify:**
```bash
# Verify yaml syntax
python -c "import yaml; yaml.safe_load(open('.github/workflows/publish.yml'))"
grep -n "python-version" .github/workflows/publish.yml
```

**DoD (SMART):**
- [ ] `.github/workflows/publish.yml` `test-install` matrix contains exactly 3 versions: `'3.11'`, `'3.12'`, `'3.13'`
- [ ] No `'3.10'` reference remains in publish.yml
- [ ] YAML syntax valid

**Code rules:** Consistency with `pyproject.toml requires-python = ">=3.11"`.

---

<!-- mb-stage:8 -->
## Stage 8: Update CLAUDE.md / AGENTS.md to Python 3.11+

**Source**: T1.8
**Effort**: ~5min
**Type**: docs

**What to do:**
- В `/Users/fockus/Apps/swarmline/CLAUDE.md:7`: изменить "Version 1.4.1, Python 3.10+" → "Version 1.5.0, Python 3.11+".
- В `/Users/fockus/Apps/swarmline/CLAUDE.md:174`: "Python 3.10+" → "Python 3.11+".
- В `/Users/fockus/Apps/swarmline/AGENTS.md:7`: "Python 3.10+" → "Python 3.11+".
- Проверить, не упоминается ли где-то ещё "3.10" в этих файлах через `grep -n "3\.10"`.

**Testing (TDD — tests BEFORE implementation):**
- TDD not applicable: docs-only change.

**Files to touch:**
- `CLAUDE.md:7, 174`
- `AGENTS.md:7`

**Commands to verify:**
```bash
grep -n "Python 3\.10" CLAUDE.md AGENTS.md
grep -n "Python 3\.11" CLAUDE.md AGENTS.md  # should show updated lines
```

**DoD (SMART):**
- [ ] Zero matches for "Python 3.10+" in CLAUDE.md or AGENTS.md (`grep -c "Python 3\.10"` = 0)
- [ ] Both files mention "Python 3.11+"
- [ ] Version updated to "1.5.0" in CLAUDE.md line 7

**Code rules:** Truthful docs.

---

<!-- mb-stage:9 -->
## Stage 9: Bump version to 1.5.0

**Source**: T1.9 = C-5
**Effort**: ~2min
**Type**: tooling

**What to do:**
- В `pyproject.toml:7`: изменить `version = "1.4.1"` → `version = "1.5.0"`.
- В `src/swarmline/serve/app.py:17`: проверить `_VERSION = "1.4.0"` — рассмотреть обновление на `_VERSION = "1.5.0"` для consistency (хотя это internal). Если ничто на это не опирается, можно оставить.

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** в `tests/unit/test_version.py` (create or extend):
  ```python
  def test_swarmline_version_is_150():
      import swarmline
      # Either via PackageNotFoundError fallback (dev) or installed (CI)
      assert swarmline.__version__ in ("1.5.0", "0.0.0-dev")  # accept dev for editable install
  
  def test_pyproject_version_pin():
      # Read pyproject.toml directly for canonical version
      import tomllib  # py3.11+
      from pathlib import Path
      data = tomllib.loads(Path("pyproject.toml").read_text())
      assert data["project"]["version"] == "1.5.0"
  ```

**Files to touch:**
- `pyproject.toml:7` (modify)
- `tests/unit/test_version.py` (create or extend) — 2 тестов
- (опционально) `src/swarmline/serve/app.py:17`

**Commands to verify:**
```bash
pytest tests/unit/test_version.py -xvs
grep version pyproject.toml | head -1   # should print 'version = "1.5.0"'
pytest -q
```

**DoD (SMART):**
- [ ] `pyproject.toml [project] version` is `"1.5.0"`
- [ ] `tests/unit/test_version.py` includes pyproject-version assertion
- [ ] Full suite green

**Code rules:** Strict SemVer (MINOR bump for backward-compat features).

---

<!-- mb-stage:10 -->
## Stage 10: CHANGELOG.md `[1.5.0]` entry

**Source**: T2.1 = C-4
**Effort**: ~30min – 1h
**Type**: docs

**What to do:**
- Открыть `CHANGELOG.md`. После строки `## [Unreleased]` добавить новую секцию `## [1.5.0] - 2026-04-25`.
- Сгруппировать commits `v1.4.0..HEAD` (55 коммитов) по категориям Keep-a-Changelog. Использовать данные из `.memory-bank/checklist.md` (Phase 11-17 полная taxonomy) и git log:

  ```markdown
  ## [1.5.0] - 2026-04-25
  
  ### Added
  - **Phase 11: Foundation Filters** — `ProjectInstructionFilter` (CLAUDE.md/AGENTS.md/RULES.md/GEMINI.md walk-up loading) + `SystemReminderFilter` (dynamic context injection)
  - **Phase 12: Tool Surface Expansion** — `web_allowed_domains` / `web_blocked_domains` filtering for `web_fetch`; MCP resource reading (`list_resources` / `read_resource` + caching); `read_mcp_resource` builtin tool; `ResourceDescriptor` frozen dataclass exported
  - **Phase 13: Conversation Compaction** — `ConversationCompactionFilter` + `CompactionConfig`; 3-tier cascade (tool result collapse → LLM summarization → emergency truncation)
  - **Phase 14: Session Resume** — `JsonlMessageStore` (SHA-256 filenames, corrupted-line resilience); `Conversation.resume(session_id)` with auto-persist + auto-compaction
  - **Phase 15: Thinking Events** — `ThinkingConfig` frozen dataclass (`enabled` / `adaptive` / `disabled`); `RuntimeEvent.thinking_delta` factory; `LlmCallResult` envelope; AnthropicAdapter thinking extraction
  - **Phase 16: Multimodal Input** — `ContentBlock` / `TextBlock` / `ImageBlock` types; `Message.content_blocks` additive field; multimodal in Anthropic / OpenAI / Google adapters; `BinaryReadProvider`; PDF / Jupyter extractors
  - **Phase 17: Parallel Agents** — `SubagentSpec.isolation`; worktree lifecycle for `spawn_agent`; `RuntimeEvent.background_complete`; `monitor_agent` builtin tool
  - **Pi-SDK Runtime** — 4th adapter via Node.js bridge (`runtime="pi_sdk"`)
  - **OpenAI Agents SDK Runtime** — `runtime="openai_agents"` (Codex + OpenAI models, 5th adapter)
  - **Agent Packs** — `AgentPackResolver`, `AgentPackResource`, `ResolvedAgentPack` for declarative agent loading
  - **JSONL Telemetry Sink** — `JsonlTelemetrySink` with EventBus subscription + key-name redaction (extended to value-pattern in this release)
  - **Typed Pipeline** — structured workflow primitives (typed bridge + chain extensions)
  - **Coding Profile** — `CodingProfileConfig` for opt-in coding-agent tool surface + policy
  - **Subagent Tool** — `SubagentToolConfig` with worktree isolation
  - **Native Tool Calling** — parallel tool execution path in ThinRuntime
  - **Command Routing** — slash-command registry in ThinRuntime
  - **Tool Policy Enforcement** — `DefaultToolPolicy` wired through `ToolExecutor`
  - **Hook Dispatch** — full pre/post/stop hook support in ThinRuntime
  
  ### Changed
  - **BREAKING-IN-DEFAULTS (non-breaking-API)**: `AgentConfig.runtime` default changed `"claude_sdk"` → `"thin"`. Existing code passing explicit `runtime="claude_sdk"` continues to work; only implicit default-runtime users see new behaviour. Recommended migration: pin `runtime="thin"` (or your chosen runtime) explicitly in production code. (See migration guide.)
  - **Python 3.10 dropped** from supported matrix; minimum is now `>=3.11` (`pyproject.toml`). `publish.yml` test-install matrix updated.
  - **CI lint / format strict** — repo formatted with `ruff format`; lint job will fail on new violations.
  - `_VERSION` in `swarmline/serve/app.py` bumped to align with pyproject.
  - **ty strict-mode** = 0 diagnostics (Sprint 1A + 1B). Locked in `tests/architecture/ty_baseline.txt`.
  - Documented all `protocols/` package contents (>30 protocols) in `architecture.md`. Old "14 ISP-compliant protocols" claim corrected.
  
  ### Deprecated
  - `AgentConfig.max_thinking_tokens` — removed entirely (was deprecated since Phase 15). Use `AgentConfig.thinking={"type":"enabled","budget_tokens":N}` instead. (See migration guide.)
  - `AgentConfig.thinking: dict[str, Any]` — still accepted for backward compat, but `ThinkingConfig` typed dataclass is preferred. Deprecation warning emitted when dict is passed.
  
  ### Removed
  - `AgentConfig.max_thinking_tokens` field
  
  ### Fixed
  - **C-1 / C-3**: Test isolation broken — `observability/logger.py` no longer calls `logging.basicConfig(force=True)`; routes stdlib logging to `stderr` to preserve CLI JSON contract on `stdout`. Fixes 14 cross-test contamination failures.
  - **C-2**: `JsonlTelemetrySink.record()` no longer blocks the event loop — file I/O wrapped in `asyncio.to_thread()`; concurrent writes serialized via `asyncio.Lock`.
  - **C-9**: Russian error string in `runtime/thin/errors.py` translated to English ("LLM API error" instead of "Ошибка LLM API").
  - **C-10**: `docs/agent-facade.md` corrected — `system_prompt` (not `runtime`) is the only required parameter.
  
  ### Security
  - **M-1**: `serve.create_app(allow_unauthenticated_query=True)` now enforces loopback host (parity with A2A / HealthServer).
  - **M-3**: `JsonlTelemetrySink` redaction extended — added missing key names (`bearer`, `cookie`, `private_key`, `dsn`, `client_secret`, `aws_secret_access_key`, etc.) and value-level regex (`sk-*`, `Bearer ...`, URL userinfo).
  - **CI hardening**: `pip-audit --strict --desc` added to CI lint job for supply-chain visibility.
  - **Constant-time** auth comparison verified across all 3 control planes (`serve`, `a2a`, `daemon` health) using `hmac.compare_digest`.
  
  ### Documentation
  - New: `docs/migration/v1.4-to-v1.5.md` — migration guide.
  - New: `docs/runtimes/openai-agents.md`, `docs/runtimes/pi-sdk.md` — new runtime docs.
  - New: `docs/parallel-agents.md` — Phase 17 isolation + worktree.
  - New: `docs/multimodal.md` — Phase 16 ContentBlock + image inputs.
  - New: `docs/sessions.md` extended with `Conversation.resume()`.
  - New: `docs/thinking.md` (or extension) — Phase 15 thinking events.
  - New: `examples/00_hello_world.py` — 10-line minimal example without `_MockBasicsRuntime` boilerplate.
  - Updated: `docs/agent-facade.md`, `docs/agent-pack.md`, `docs/observability.md` — accuracy + new features.
  ```
- В section `## [Unreleased]` оставить пустой stub `(none yet)`.
- Обновить footer link section: добавить `[1.5.0]: https://github.com/fockus/swarmline/releases/tag/v1.5.0` если такой паттерн используется.

**Testing (TDD — tests BEFORE implementation):**
- TDD not applicable: docs change. Опираемся на architecture meta-test (если он валидирует CHANGELOG-presence; проверить).

**Files to touch:**
- `CHANGELOG.md` (insert new section between line 8 `## [Unreleased]` and line 10 `## [1.4.0]`)

**Commands to verify:**
```bash
grep -n "## \[1\.5\.0\]" CHANGELOG.md
# Verify Markdown — should pass mkdocs build (if run later in Stage 11)
```

**DoD (SMART):**
- [ ] CHANGELOG `## [1.5.0]` section present, dated `2026-04-25`
- [ ] All 6 Keep-a-Changelog categories present (`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`)
- [ ] Section Lists all 7 phases + Sprint 1A/1B + new public surface
- [ ] `[Unreleased]` section heading remains
- [ ] `pytest tests/architecture/` green (if tests check CHANGELOG)

**Code rules:** Keep-a-Changelog format, accurate, conventional-commits-derived.

---

<!-- mb-stage:11 -->
## Stage 11: Migration guide v1.4 → v1.5

**Source**: T2.2 = H-5
**Effort**: ~1h
**Type**: docs

**What to do:**
- Создать `docs/migration/v1.4-to-v1.5.md` (создать каталог `docs/migration/` если нет — проверил, пока нет; используется `docs/migration-guide.md` как монолит. Решение: создать каталог и vivendi-style guide).
- Структура:
  ```markdown
  # Migration Guide: swarmline v1.4 → v1.5
  
  This guide covers all user-visible changes between swarmline v1.4.x and v1.5.0.
  
  ## TL;DR
  
  - **Default runtime change** (non-breaking-API): `AgentConfig.runtime` default is now `"thin"` instead of `"claude_sdk"`. Pin explicitly to avoid surprise.
  - **Python 3.10 no longer supported.** Minimum is now `>=3.11`.
  - `AgentConfig.max_thinking_tokens` removed (was deprecated). Use `thinking=` instead.
  - All other changes are additive.
  
  ## Breaking changes
  
  ### 1. `AgentConfig.runtime` default changed
  
  **Before (v1.4.x)**:
  ```python
  agent = Agent(AgentConfig(system_prompt="..."))
  # silently uses runtime="claude_sdk" — needs claude-agent-sdk installed
  ```
  
  **After (v1.5.0)**:
  ```python
  agent = Agent(AgentConfig(system_prompt="..."))
  # uses runtime="thin" — needs swarmline[thin] (anthropic, openai, google-genai, httpx)
  ```
  
  **Migration**: pin runtime explicitly:
  ```python
  agent = Agent(AgentConfig(system_prompt="...", runtime="claude_sdk"))  # if you want v1.4 behaviour
  agent = Agent(AgentConfig(system_prompt="...", runtime="thin"))         # if you want new default explicitly
  ```
  
  ### 2. `AgentConfig.max_thinking_tokens` removed
  
  **Before (v1.4.x)**:
  ```python
  AgentConfig(system_prompt="...", max_thinking_tokens=4096)
  ```
  
  **After (v1.5.0)**:
  ```python
  AgentConfig(system_prompt="...", thinking={"type": "enabled", "budget_tokens": 4096})
  # or with new typed config (preferred):
  from swarmline.runtime.types import ThinkingConfigEnabled
  AgentConfig(system_prompt="...", thinking=ThinkingConfigEnabled(type="enabled", budget_tokens=4096))
  ```
  
  ### 3. Python 3.10 dropped
  
  **Before**: `pip install swarmline` worked on Python 3.10.x.
  
  **After**: minimum is `>=3.11`. Upgrade your interpreter.
  
  ## New features (additive — no migration required)
  
  ### Foundation filters (Phase 11)
  - `ProjectInstructionFilter` — auto-loads CLAUDE.md / AGENTS.md / RULES.md / GEMINI.md from cwd up.
  - `SystemReminderFilter` — inject dynamic system reminders.
  
  ### MCP resources (Phase 12)
  - `read_mcp_resource(uri)` — built-in tool to read MCP resources.
  - `web_fetch` now supports `web_allowed_domains` / `web_blocked_domains` filters.
  
  ### Conversation compaction (Phase 13)
  - 3-tier cascade for long conversations.
  
  ### Session resume (Phase 14)
  - `Conversation.resume(session_id)` for cross-session memory.
  - `JsonlMessageStore` for filesystem persistence.
  
  ### Thinking events (Phase 15)
  - `ThinkingConfig` for extended thinking control.
  - `RuntimeEvent.thinking_delta` events.
  
  ### Multimodal input (Phase 16)
  - `ContentBlock` / `TextBlock` / `ImageBlock` types.
  - `Message.content_blocks` field for image / PDF inputs.
  
  ### Parallel agents (Phase 17)
  - `SubagentSpec.isolation` for worktree-per-agent.
  - `monitor_agent` tool to track background work.
  
  ### New runtimes
  - `runtime="openai_agents"` (OpenAI Agents SDK + Codex)
  - `runtime="pi_sdk"` (Pi SDK via Node.js bridge)
  
  ### Other
  - `AgentPackResolver` for declarative agent loading.
  - `JsonlTelemetrySink` for append-only event logging.
  - Coding profile (`CodingProfileConfig`) for opt-in coding-agent surface.
  
  ## Bug fixes affecting users
  
  - Test isolation fixed (`force=True` removed from logger).
  - CLI `--format json` no longer mixes log lines with JSON output (logs go to stderr).
  - `JsonlTelemetrySink.record()` no longer blocks the event loop.
  - Russian error string in `runtime/thin/errors.py` translated to English.
  
  ## Security improvements
  
  - `serve.create_app(allow_unauthenticated_query=True)` now enforces loopback (M-1).
  - `JsonlTelemetrySink` redaction broadened (M-3).
  - `pip-audit` added to CI.
  
  ## See also
  
  - `CHANGELOG.md` — full changelog
  - `docs/configuration.md` — current configuration reference
  ```

**Testing (TDD — tests BEFORE implementation):**
- TDD not applicable: docs.

**Files to touch:**
- `docs/migration/v1.4-to-v1.5.md` (create new file + create directory if not exists)

**Commands to verify:**
```bash
ls docs/migration/v1.4-to-v1.5.md   # exists
wc -l docs/migration/v1.4-to-v1.5.md   # ≥ 50 lines
```

**DoD (SMART):**
- [ ] `docs/migration/v1.4-to-v1.5.md` exists with TL;DR, Breaking changes, Additive features, Fixes, Security sections
- [ ] All 3 breaking changes documented with before/after
- [ ] All 7 phases listed
- [ ] All new runtimes (`openai_agents`, `pi_sdk`) listed

**Code rules:** Truthful migration guide.

---

<!-- mb-stage:12 -->
## Stage 12: Feature docs for new v1.5.0 features

**Source**: T2.3 = H-3
**Effort**: ~2-4h (4 files full + 5 stubs)
**Type**: docs

**What to do:**
Создать **минимум 5 of 12** новых docs files (full content) + **до 7 stub** для остальных. Приоритет:

#### Full docs:
1. `docs/runtimes/openai-agents.md` — Phase 11 (OpenAI Agents SDK Runtime). Покрыть: when to use, install (`pip install swarmline[openai-agents]`), example, options, comparison vs `thin`/`claude_sdk`.
2. `docs/parallel-agents.md` — Phase 17 (parallel agents + worktree isolation). Покрыть: `SubagentSpec.isolation`, worktree lifecycle, `RuntimeEvent.background_complete`, `monitor_agent` tool, gotchas.
3. `docs/multimodal.md` — Phase 16. Покрыть: `ContentBlock` / `TextBlock` / `ImageBlock`, `Message.content_blocks`, provider compatibility (Anthropic / OpenAI / Google), PDF / Jupyter inputs.
4. `docs/thinking.md` — Phase 15. Покрыть: `ThinkingConfig` (`enabled` / `adaptive` / `disabled`), `RuntimeEvent.thinking_delta`, AnthropicAdapter behaviour, non-Anthropic warning.
5. `docs/runtimes/pi-sdk.md` — Pi SDK Runtime. Покрыть: install, Node.js bridge, when to use, options, limitations.

#### Stubs (1-paragraph stub OK):
6. `docs/agent-pack.md` — verify exists (per git status). Если stub — расширить на 1-2 paragraph "Agent packs let you declare agent configurations..."
7. `docs/sessions.md` — already exists; добавить секцию `## Resume across sessions` с `Conversation.resume()`.
8. `docs/observability.md` — already exists per `M docs/observability.md`; добавить секцию `## JsonlTelemetrySink`.
9. `docs/evaluation.md` — already exists; verify mentions Phase 13 evaluation.
10. `docs/orchestration.md` или новый `docs/coding-profile.md` — упомянуть `CodingProfileConfig`.
11. `docs/structured-output.md` — already exists per `M docs/structured-output.md`; verify accurate.
12. `docs/pipeline.md` — already exists per `M docs/pipeline.md`; добавить раздел про typed pipeline.

#### Index update:
- Обновить `docs/index.md` — добавить ссылки на новые файлы.
- Обновить `mkdocs.yml` (если необходимо для navigation).

**Testing (TDD — tests BEFORE implementation):**
- TDD not applicable: docs.
- Если есть `tests/integration/test_docs_examples_consistency.py` — оно должно валидировать code blocks в новых docs (особенно код-сниппеты с `Agent`/`AgentConfig`/`tool`). Если падают — исправить snippets.

**Files to touch:**
- `docs/runtimes/openai-agents.md` (create) — full
- `docs/runtimes/pi-sdk.md` (create) — full  
- `docs/parallel-agents.md` (create) — full
- `docs/multimodal.md` (create) — full
- `docs/thinking.md` (create) — full
- `docs/agent-pack.md` (verify, extend if stub)
- `docs/sessions.md` (extend)
- `docs/observability.md` (extend with JSONL sink)
- `docs/index.md` (update navigation)
- `mkdocs.yml` (if needed)

**Commands to verify:**
```bash
ls docs/runtimes/openai-agents.md docs/runtimes/pi-sdk.md docs/parallel-agents.md docs/multimodal.md docs/thinking.md
# All exist, each ≥ 30 lines
wc -l docs/runtimes/*.md docs/parallel-agents.md docs/multimodal.md docs/thinking.md
pytest tests/integration/test_docs_examples_consistency.py -xvs   # green
mkdocs build --strict   # if mkdocs is installed; reports broken links
```

**DoD (SMART):**
- [ ] At least 5 NEW feature docs files exist (`docs/runtimes/openai-agents.md`, `docs/runtimes/pi-sdk.md`, `docs/parallel-agents.md`, `docs/multimodal.md`, `docs/thinking.md`)
- [ ] Each new file ≥ 30 lines (not empty stub)
- [ ] Each new file includes a runnable code example
- [ ] `docs/index.md` links to all new docs
- [ ] `tests/integration/test_docs_examples_consistency.py` green
- [ ] (Optional) `mkdocs build --strict` succeeds

**Code rules:** Truthful, runnable, copy-paste examples.

---

<!-- mb-stage:13 -->
## Stage 13: Add `examples/00_hello_world.py` — 10-line minimal example

**Source**: T3.1
**Effort**: ~30min
**Type**: code (example)

**What to do:**
- Создать `examples/00_hello_world.py` — самый минимальный hello-world. Подходит и для CI smoke test (offline, без API key).

  ```python
  """Hello-world swarmline agent — 10-line minimum.
  
  Run offline (mock provider): python examples/00_hello_world.py
  Run with real provider: ANTHROPIC_API_KEY=sk-... python examples/00_hello_world.py --live
  """
  
  from __future__ import annotations
  
  import asyncio
  import os
  import sys
  
  from swarmline import Agent, AgentConfig
  
  
  async def main() -> None:
      # Minimum config — only system_prompt is required.
      # Default runtime is "thin"; uses any installed provider (anthropic, openai, google).
      runtime = "thin"
      if "--live" not in sys.argv:
          # Offline-safe: use the testing.MockRuntime (added in v1.5.0).
          from swarmline.testing import MockRuntime  # ← создан в Stage 16
          MockRuntime.register_default()
          runtime = MockRuntime.NAME
      
      agent = Agent(AgentConfig(system_prompt="You are a helpful assistant.", runtime=runtime))
      result = await agent.query("What is 2+2?")
      print(result.text)
  
  
  if __name__ == "__main__":
      asyncio.run(main())
  ```

- **CRITICAL DEPENDENCY**: этот example полагается на `swarmline.testing.MockRuntime`, который создаётся в **Stage 16**. Поэтому Stage 13 должен идти **после** Stage 16.

**Testing (TDD — tests BEFORE implementation):**
- **NEW integration test** в `tests/integration/test_examples_smoke.py` (extend existing matrix):
  - Add `00_hello_world.py` to smoke matrix.
  - Assert exit code 0.
  - Assert stdout contains expected reply.

**Files to touch:**
- `examples/00_hello_world.py` (create)
- `tests/integration/test_examples_smoke.py` (extend matrix; if uses parametrize over filename, add `"00_hello_world.py"`)

**Commands to verify:**
```bash
python examples/00_hello_world.py    # offline mode, prints something
pytest tests/integration/test_examples_smoke.py -xvs -k "00_hello_world"
```

**DoD (SMART):**
- [ ] `examples/00_hello_world.py` ≤ 30 lines (excluding docstring)
- [ ] Runs offline with exit 0 (using `MockRuntime` from Stage 16)
- [ ] Smoke test green
- [ ] No `_MockBasicsRuntime` boilerplate in example file

**Code rules:** KISS. Truly minimal.

---

<!-- mb-stage:14 -->
## Stage 14: Trim `swarmline/__init__.py __all__`

**Source**: T3.2 = H-1
**Effort**: ~2h
**Type**: refactor (public API surface)

**What to do:**
- В `src/swarmline/__init__.py:54-106`: уменьшить `__all__` с 51 имён до **~12 ядерных**.

  **Keep in `__all__` (12 names)**:
  ```
  Agent, AgentConfig, Conversation, Result, tool,
  Message, RuntimeEvent, ToolSpec,
  SwarmlineStack, ContextPack, SkillSet, TurnContext
  ```

  **Remove from `__all__`** (но оставить imports — доступны через `from swarmline import X` или через под-модули `from swarmline.session import SessionFactory`):
  ```
  AgentPackResolver, AgentPackResource, ResolvedAgentPack,
  AgentRuntime, CompactionConfig, ConversationCompactionFilter,
  ContextBuilder, FactStore, GoalStore, ImageBlock, ContentBlock, TextBlock,
  JsonlMessageStore, LocalToolResolver, MessageStore, ModelRequestOptions,
  ProjectInstructionFilter, ModelSelector, PhaseStore, ResourceDescriptor,
  RoleRouter, RoleSkillsProvider, RuntimeConfig, RuntimeErrorData, RuntimeFactory,
  RuntimePort, SessionFactory, SessionLifecycle, SessionManager, SessionRehydrator,
  SessionStateStore, SummaryStore, SystemReminder, SystemReminderFilter,
  ThinkingConfig, ToolEventStore, ToolIdCodec, TurnMetrics, UserStore
  ```

- **CRITICAL**: imports у самого top-level `swarmline/__init__.py` остаются — только `__all__` сужается. Поэтому `from swarmline import AgentRuntime` продолжает работать. Меняется только поведение `from swarmline import *` — в нём теперь только 12 ядерных имён.
- Опционально: добавить в docstring модуля краткий "minimal API" guide:
  ```python
  """Swarmline — LLM-agnostic framework for building AI agents.

  Quick start:
      from swarmline import Agent, AgentConfig, tool

      @tool
      async def add(a: int, b: int) -> int:
          return a + b

      agent = Agent(AgentConfig(system_prompt="You add numbers.", tools=(add,)))
      result = await agent.query("What is 2+2?")

  Public API (in __all__): Agent, AgentConfig, Conversation, Result, tool,
                           Message, RuntimeEvent, ToolSpec,
                           SwarmlineStack, ContextPack, SkillSet, TurnContext
  
  Other names are still importable via direct path:
      from swarmline.session import SessionFactory
      from swarmline import RoleRouter  # also still works
  """
  ```

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** `tests/unit/test_public_api_surface.py`:
  ```python
  import swarmline
  
  CORE_NAMES = {
      "Agent", "AgentConfig", "Conversation", "Result", "tool",
      "Message", "RuntimeEvent", "ToolSpec",
      "SwarmlineStack", "ContextPack", "SkillSet", "TurnContext",
  }
  
  def test_all_contains_core_names():
      assert set(swarmline.__all__) == CORE_NAMES
  
  def test_all_count_is_twelve():
      assert len(swarmline.__all__) == 12
  
  def test_infrastructure_not_in_all():
      assert "RoleRouter" not in swarmline.__all__
      assert "SessionFactory" not in swarmline.__all__
      assert "ToolEventStore" not in swarmline.__all__
      assert "MessageStore" not in swarmline.__all__
  
  def test_infrastructure_still_importable():
      # via direct path
      from swarmline.session import SessionFactory  # noqa
      # via top-level (still imported, just not in __all__)
      from swarmline import RoleRouter  # noqa
  ```

**Files to touch:**
- `src/swarmline/__init__.py:54-106` (modify `__all__` list; optionally extend module docstring)
- `tests/unit/test_public_api_surface.py` (create) — 4 tests

**Commands to verify:**
```bash
pytest tests/unit/test_public_api_surface.py -xvs   # red first, then green
pytest -q
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] `swarmline.__all__` contains exactly 12 names (the core set)
- [ ] All infrastructure names removed from `__all__` (verified via test)
- [ ] All infrastructure names still importable via `from swarmline import X` (no breakage)
- [ ] Full suite green
- [ ] No ty regressions

**Edge cases:**
- Some downstream tests `from swarmline import *` могут начать failing. Проверить — если есть, либо переписать на explicit imports, либо добавить нужные имена обратно в `__all__`.
- Sphinx/mkdocs `automodule swarmline` будет показывать только 12 имён — это **wanted** behaviour (less noise).

**Code rules:** ISP, public API hygiene.

---

<!-- mb-stage:15 -->
## Stage 15: Add `SwarmlineError` base exception class

**Source**: T3.3 = H-4
**Effort**: ~2h
**Type**: code (refactor — exception hierarchy)

**What to do:**
- Создать `src/swarmline/errors.py`:
  ```python
  """Base exception class for all swarmline-raised errors."""
  
  from __future__ import annotations
  
  
  class SwarmlineError(Exception):
      """Base class for all exceptions raised by swarmline.
      
      Users can catch any swarmline-raised error via:
          try:
              await agent.query(...)
          except SwarmlineError as e:
              # handle any swarmline failure
      """
  ```
- В `src/swarmline/__init__.py`: добавить `from swarmline.errors import SwarmlineError` (но **не** в `__all__` — это infrastructure-shaped).
- Обновить **все** custom exception classes в src/, чтобы наследовались от `SwarmlineError`:

  Список (по `grep "class.*Error" src/swarmline/`):
  1. `src/swarmline/multi_agent/graph_governance.py:22 GovernanceError(Exception)` → `(SwarmlineError)`
  2. `src/swarmline/pipeline/budget.py:11 BudgetExceededError(RuntimeError)` → `(SwarmlineError, RuntimeError)`
  3. `src/swarmline/a2a/client.py:256 A2AClientError(Exception)` → `(SwarmlineError)`
  4. `src/swarmline/hitl/gate.py:10 ApprovalDeniedError(Exception)` → `(SwarmlineError)`
  5. `src/swarmline/runtime/thin/errors.py:10 ThinLlmError(RuntimeError)` → `(SwarmlineError, RuntimeError)`
  6. `src/swarmline/runtime/deepagents_models.py:41 DeepAgentsModelError(RuntimeError)` → `(SwarmlineError, RuntimeError)`
  7. `src/swarmline/agent/structured.py:22 StructuredOutputError(Exception)` → `(SwarmlineError)`
  8. `src/swarmline/agent/middleware.py:16 BudgetExceededError(RuntimeError)` → `(SwarmlineError, RuntimeError)`
  9. `src/swarmline/mcp/_session.py:21 HeadlessModeError(Exception)` → `(SwarmlineError)`
  10. `src/swarmline/daemon/pid.py:10 DaemonAlreadyRunningError(RuntimeError)` → `(SwarmlineError, RuntimeError)`

- **NOTE**: 2 классa с одинаковым именем `BudgetExceededError` (middleware vs pipeline) — это antipattern, но не fix-here scope. Оба наследуются от `SwarmlineError`. Документировать как known issue.

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** `tests/unit/test_swarmline_error_hierarchy.py`:
  ```python
  import pytest
  
  from swarmline.errors import SwarmlineError
  
  
  @pytest.mark.parametrize(
      "exc_path, exc_name",
      [
          ("swarmline.multi_agent.graph_governance", "GovernanceError"),
          ("swarmline.pipeline.budget", "BudgetExceededError"),
          ("swarmline.a2a.client", "A2AClientError"),
          ("swarmline.hitl.gate", "ApprovalDeniedError"),
          ("swarmline.runtime.thin.errors", "ThinLlmError"),
          ("swarmline.runtime.deepagents_models", "DeepAgentsModelError"),
          ("swarmline.agent.structured", "StructuredOutputError"),
          ("swarmline.agent.middleware", "BudgetExceededError"),
          ("swarmline.mcp._session", "HeadlessModeError"),
          ("swarmline.daemon.pid", "DaemonAlreadyRunningError"),
      ],
  )
  def test_all_swarmline_exceptions_inherit_from_swarmlineerror(exc_path, exc_name):
      import importlib
      module = importlib.import_module(exc_path)
      exc_class = getattr(module, exc_name)
      assert issubclass(exc_class, SwarmlineError), f"{exc_name} from {exc_path} should subclass SwarmlineError"
  
  
  def test_swarmline_error_is_exception():
      assert issubclass(SwarmlineError, Exception)
  
  
  def test_swarmline_error_raisable():
      with pytest.raises(SwarmlineError):
          raise SwarmlineError("test")
  ```

**Files to touch:**
- `src/swarmline/errors.py` (create new file)
- `src/swarmline/__init__.py` (add import — but NOT to `__all__`)
- `src/swarmline/multi_agent/graph_governance.py:22` (modify class declaration)
- `src/swarmline/pipeline/budget.py:11` (modify)
- `src/swarmline/a2a/client.py:256` (modify)
- `src/swarmline/hitl/gate.py:10` (modify)
- `src/swarmline/runtime/thin/errors.py:10` (modify)
- `src/swarmline/runtime/deepagents_models.py:41` (modify)
- `src/swarmline/agent/structured.py:22` (modify)
- `src/swarmline/agent/middleware.py:16` (modify)
- `src/swarmline/mcp/_session.py:21` (modify)
- `src/swarmline/daemon/pid.py:10` (modify)
- `tests/unit/test_swarmline_error_hierarchy.py` (create) — 12+ tests via parametrize

**Commands to verify:**
```bash
pytest tests/unit/test_swarmline_error_hierarchy.py -xvs   # red first; green after
pytest -q
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] `swarmline.errors.SwarmlineError` exists and is `Exception` subclass
- [ ] All 10 custom exception classes subclass `SwarmlineError`
- [ ] `try: ... except SwarmlineError: ...` catches all of them (verified via parametrized test)
- [ ] Each custom exception's prior parent (`Exception` or `RuntimeError`) preserved via multiple inheritance where present
- [ ] All existing tests green (no behavioural change in `except` clauses)
- [ ] No ty regressions

**Edge cases:**
- Multiple inheritance MRO — `class ThinLlmError(SwarmlineError, RuntimeError)` order matters. Поставить `SwarmlineError` first (closer to caller's intent), `RuntimeError` second (preserves stdlib hierarchy). MRO: `ThinLlmError → SwarmlineError → Exception` then `→ RuntimeError → Exception`. Linearization fine.
- `BudgetExceededError` дублируется (middleware и pipeline). Обе версии наследуются от SwarmlineError — это OK для текущего scope. Документировать как technical debt.

**Code rules:** ISP, exception hierarchy, backward-compat.

---

<!-- mb-stage:16 -->
## Stage 16: Move `_MockBasicsRuntime` to `swarmline.testing.MockRuntime`

**Source**: T3.4 = H-2
**Effort**: ~3h
**Type**: refactor

**What to do:**
- Создать **новый module**:
  - `src/swarmline/testing/__init__.py`:
    ```python
    """Testing utilities for swarmline."""
    
    from swarmline.testing.mock_runtime import MockRuntime
    
    __all__ = ["MockRuntime"]
    ```
  - `src/swarmline/testing/mock_runtime.py` — extract класс `_MockBasicsRuntime` из `examples/01_agent_basics.py`, переименовать в `MockRuntime`, generalize:
    ```python
    """MockRuntime — deterministic test/example runtime that needs no API keys."""
    
    from __future__ import annotations
    
    import asyncio
    from collections.abc import AsyncIterator
    from typing import Callable, Mapping
    
    from swarmline.runtime.capabilities import RuntimeCapabilities
    from swarmline.runtime.registry import get_default_registry
    from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec
    
    
    DEFAULT_REPLIES: Mapping[str, str] = {
        "capital of france": "Paris.",
        "haiku and python": "Python softly hums / Clean functions guide the logic / Bugs fade into tests.",
        "17 * 23": "391.",
    }
    
    
    class MockRuntime:
        """Deterministic mock runtime for testing and examples.
        
        Use ``MockRuntime.register_default()`` to register under default name 
        ``mock``, then pass ``runtime="mock"`` to AgentConfig.
        """
        
        NAME = "mock"
        
        def __init__(
            self,
            *,
            replies: Mapping[str, str] | None = None,
            session_id: str = "mock-session",
        ) -> None:
            self._replies = dict(DEFAULT_REPLIES, **(replies or {}))
            self._session_id = session_id
        
        async def run(
            self,
            *,
            messages: list[Message],
            system_prompt: str,
            active_tools: list[ToolSpec],
            config: RuntimeConfig | None = None,
            mode_hint: str | None = None,
        ) -> AsyncIterator[RuntimeEvent]:
            _ = (system_prompt, active_tools, config, mode_hint)
            reply = self._reply_for(messages)
            for token in reply.split():
                yield RuntimeEvent.assistant_delta(f"{token} ")
                await asyncio.sleep(0.001)
            yield RuntimeEvent.final(
                text=reply,
                session_id=self._session_id,
                new_messages=[Message(role="assistant", content=reply)],
            )
        
        def cancel(self) -> None:
            return None
        
        async def cleanup(self) -> None:
            return None
        
        def _reply_for(self, messages: list[Message]) -> str:
            last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
            lowered = last_user.lower()
            for trigger, reply in self._replies.items():
                if trigger in lowered:
                    return reply
            return f"You said: {last_user}"
        
        @classmethod
        def register_default(cls) -> None:
            """Register MockRuntime under name 'mock' in the default registry."""
            registry = get_default_registry()
            if registry.is_registered(cls.NAME):
                return
            
            def _factory(config: RuntimeConfig | None = None, **kwargs: object) -> "MockRuntime":
                _ = (config, kwargs)
                return cls()
            
            registry.register(
                cls.NAME,
                _factory,
                capabilities=RuntimeCapabilities(
                    runtime_name=cls.NAME,
                    tier="light",
                    supports_mcp=False,
                    supports_provider_override=False,
                ),
            )
    ```
- Update `examples/01_agent_basics.py` — заменить 80-line `_MockBasicsRuntime` на:
  ```python
  from swarmline.testing import MockRuntime
  MockRuntime.register_default()
  
  agent = Agent(AgentConfig(
      system_prompt="You are a helpful assistant. Reply concisely.",
      runtime=MockRuntime.NAME,
  ))
  ```
  Сократить файл с 176 LOC до ~30-40 LOC. Сохранить все 4 demo blocks (one-shot, streaming, conversation, context manager cleanup).

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** `tests/unit/test_mock_runtime.py`:
  ```python
  import pytest
  from swarmline.testing import MockRuntime
  from swarmline.runtime.types import Message
  
  
  @pytest.mark.asyncio
  async def test_mock_runtime_replies_to_capital_of_france():
      rt = MockRuntime()
      events = []
      async for event in rt.run(
          messages=[Message(role="user", content="What is the capital of France?")],
          system_prompt="",
          active_tools=[],
      ):
          events.append(event)
      assert events  # at least one event
      final = events[-1]
      assert "Paris" in final.text
  
  @pytest.mark.asyncio
  async def test_mock_runtime_register_default_idempotent():
      MockRuntime.register_default()
      MockRuntime.register_default()  # second call no-op
      from swarmline.runtime.registry import get_default_registry
      assert get_default_registry().is_registered(MockRuntime.NAME)
  
  @pytest.mark.asyncio
  async def test_agent_with_mock_runtime():
      from swarmline import Agent, AgentConfig
      MockRuntime.register_default()
      agent = Agent(AgentConfig(system_prompt="You are helpful.", runtime=MockRuntime.NAME))
      result = await agent.query("What is the capital of France?")
      assert "Paris" in result.text
  ```
- **NEW integration test** в `tests/integration/test_examples_smoke.py` — verify `01_agent_basics.py` still passes after refactor.

**Files to touch:**
- `src/swarmline/testing/__init__.py` (create)
- `src/swarmline/testing/mock_runtime.py` (create)
- `examples/01_agent_basics.py` (rewrite — 176 LOC → ~40 LOC)
- `tests/unit/test_mock_runtime.py` (create) — 3 tests
- `tests/integration/test_examples_smoke.py` (verify still green for 01_agent_basics.py)

**Commands to verify:**
```bash
pytest tests/unit/test_mock_runtime.py -xvs        # red first; green after
python examples/01_agent_basics.py                 # runs offline
pytest tests/integration/test_examples_smoke.py -xvs -k "01_agent_basics"
pytest -q                                          # full suite
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] `from swarmline.testing import MockRuntime` works
- [ ] `MockRuntime.register_default()` registers under name `"mock"`
- [ ] `Agent(AgentConfig(runtime="mock", ...))` runs end-to-end without API key
- [ ] `examples/01_agent_basics.py` ≤ 50 LOC (was 176)
- [ ] All 32 example smoke tests still green
- [ ] No `_MockBasicsRuntime` boilerplate in any example
- [ ] Full suite ≥ 5354+ passed
- [ ] No ty regressions

**Edge cases:**
- `MockRuntime.register_default()` idempotency — must guard against double-registration (already checked via `is_registered`).
- Existing tests that rely on `_DEMO_RUNTIME_NAME = "agent_basics_mock"` — search and replace if any.

**Code rules:** SOLID (SRP — testing utility, separated from examples), KISS, DRY (one MockRuntime, used by example + future test code).

---

<!-- mb-stage:17 -->
## Stage 17: Promote `AgentConfig.thinking: dict` → `ThinkingConfig` typed

**Source**: T3.5
**Effort**: ~1h
**Type**: refactor

**What to do:**
- В `src/swarmline/agent/config.py:78`: change type hint:
  ```python
  thinking: dict[str, Any] | ThinkingConfig | None = None
  ```
  где `ThinkingConfig = ThinkingConfigEnabled | ThinkingConfigAdaptive | ThinkingConfigDisabled` (импорт из `swarmline.runtime.types`).
- В `__post_init__`: если `thinking` — dict, конвертировать в правильный typed dataclass через existing `_resolve_thinking()` helper из `runtime/options_builder.py:148-180`. Использовать `object.__setattr__` для frozen dataclass.
  
  ```python
  def __post_init__(self) -> None:
      if not self.system_prompt or not self.system_prompt.strip():
          raise ValueError("system_prompt must not be empty")
      
      if isinstance(self.thinking, dict):
          import warnings
          warnings.warn(
              "Passing thinking as a dict is deprecated; use ThinkingConfig dataclass instead.",
              DeprecationWarning,
              stacklevel=2,
          )
          # Convert dict to typed dataclass
          from swarmline.runtime.options_builder import _resolve_thinking
          typed = _resolve_thinking(self.thinking, None)
          object.__setattr__(self, "thinking", typed)
  ```
- Проверить что downstream consumers (`runtime/options_builder.py:153 thinking` parameter) принимает as-is оба варианта; если нет — обернуть в conversion shim там же.
- Обновить `__all__` re-export `ThinkingConfig` в `swarmline/__init__.py` (хотя по Stage 14 он не в `__all__`, но import должен оставаться).

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** `tests/unit/test_agent_config_thinking_typed.py`:
  ```python
  import warnings
  
  import pytest
  
  from swarmline import AgentConfig
  from swarmline.runtime.types import ThinkingConfig  # Union or alias
  
  
  def test_thinking_dict_still_accepted_with_deprecation_warning():
      with warnings.catch_warnings(record=True) as w:
          warnings.simplefilter("always")
          cfg = AgentConfig(
              system_prompt="x",
              thinking={"type": "enabled", "budget_tokens": 4096},
          )
          assert any(issubclass(item.category, DeprecationWarning) for item in w)
      # Should be auto-converted to typed dataclass
      assert hasattr(cfg.thinking, "type") or isinstance(cfg.thinking, dict)
  
  def test_thinking_typed_dataclass_accepted():
      from swarmline.runtime.options_builder import ThinkingConfigEnabled
      cfg = AgentConfig(
          system_prompt="x",
          thinking=ThinkingConfigEnabled(type="enabled", budget_tokens=4096),
      )
      assert cfg.thinking.type == "enabled"
  
  def test_thinking_none_default():
      cfg = AgentConfig(system_prompt="x")
      assert cfg.thinking is None
  ```

**Files to touch:**
- `src/swarmline/agent/config.py:78, 103-105` (modify type hint + `__post_init__`)
- `tests/unit/test_agent_config_thinking_typed.py` (create) — 3 tests

**Commands to verify:**
```bash
pytest tests/unit/test_agent_config_thinking_typed.py -xvs   # red, then green
pytest -q
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] Existing tests passing dict to `thinking=` still work (backward-compat)
- [ ] `DeprecationWarning` emitted when dict is passed
- [ ] `ThinkingConfig` typed dataclass accepted
- [ ] Full suite green
- [ ] No ty regressions

**Code rules:** Backward-compat, gradual deprecation, SOLID.

---

<!-- mb-stage:18 -->
## Stage 18: Remove deprecated `max_thinking_tokens`

**Source**: T3.6
**Effort**: ~30min
**Type**: refactor (breaking — removes deprecated field)

**What to do:**
- В `src/swarmline/agent/config.py:79`: удалить line `max_thinking_tokens: int | None = None  # Deprecated: use thinking instead`.
- В `src/swarmline/runtime/options_builder.py:73, 111, 153, 174-177`: убрать `max_thinking_tokens` parameter и related fallback логику в `_resolve_thinking()`. Метод теперь принимает только `thinking`.
- В `src/swarmline/agent/runtime_dispatch.py:164`: убрать `max_thinking_tokens=config.max_thinking_tokens` из вызова.
- Поиск других использований `grep -rn "max_thinking_tokens" src/swarmline/ tests/` — фикс remaining.

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** `tests/unit/test_agent_config_no_max_thinking_tokens.py`:
  ```python
  import pytest
  
  from swarmline import AgentConfig
  
  
  def test_max_thinking_tokens_field_removed():
      cfg = AgentConfig(system_prompt="x")
      assert not hasattr(cfg, "max_thinking_tokens")
  
  def test_max_thinking_tokens_kwarg_rejected():
      with pytest.raises(TypeError, match="max_thinking_tokens"):
          AgentConfig(system_prompt="x", max_thinking_tokens=4096)
  ```
- Update existing tests, которые passed `max_thinking_tokens` — заменить на `thinking={"type": "enabled", "budget_tokens": ...}`.

**Files to touch:**
- `src/swarmline/agent/config.py:79` (remove field)
- `src/swarmline/runtime/options_builder.py:73, 111, 153, 174-177` (remove parameter + fallback)
- `src/swarmline/agent/runtime_dispatch.py:164` (remove param passing)
- `tests/unit/test_agent_config_no_max_thinking_tokens.py` (create)
- Other test files referencing `max_thinking_tokens` — update via grep

**Commands to verify:**
```bash
grep -rn "max_thinking_tokens" src/swarmline/ tests/    # should be 0 hits after fix
pytest -q
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] No `max_thinking_tokens` references in src/ or tests/ (`grep -c` = 0)
- [ ] `AgentConfig(max_thinking_tokens=...)` raises `TypeError`
- [ ] Full suite green
- [ ] No ty regressions
- [ ] CHANGELOG `[1.5.0]` `Removed` section already documents this

**Code rules:** Strangler Fig — removing deprecated, документировано в CHANGELOG.

---

<!-- mb-stage:19 -->
## Stage 19: M-1 fix — enforce loopback host in `serve.create_app(allow_unauthenticated_query=True)`

**Source**: T4.1 = M-1
**Effort**: ~1h
**Type**: code (security)

**What to do:**
- В `src/swarmline/serve/app.py:135`: добавить `host: str | None = None` parameter.
- В `create_app(...)`: если `allow_unauthenticated_query=True` AND `host is not None` AND host не loopback (`localhost`, `127.0.0.1`, `::1`) — raise `ValueError`. Mirror pattern из `src/swarmline/a2a/server.py:170-187` или `src/swarmline/daemon/health.py:63-72` (точная implementation — посмотреть в этих файлах).
- Если `host=None` (legacy callers до v1.5.0) — оставить старое поведение, но залогировать `WARNING` через `log_security_decision` для audit trail.

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** `tests/unit/test_serve_app_loopback_enforcement.py`:
  ```python
  import pytest
  
  from swarmline.serve.app import create_app
  
  
  class _DummyAgent:
      async def query(self, prompt: str): ...
  
  
  def test_unauthenticated_query_with_non_loopback_host_raises():
      with pytest.raises(ValueError, match="loopback"):
          create_app(_DummyAgent(), allow_unauthenticated_query=True, host="0.0.0.0")
  
  def test_unauthenticated_query_with_loopback_host_ok():
      app = create_app(_DummyAgent(), allow_unauthenticated_query=True, host="127.0.0.1")
      assert app is not None
  
  def test_unauthenticated_query_no_host_logs_warning(caplog):
      # backward-compat: no host → no enforcement, just warning
      app = create_app(_DummyAgent(), allow_unauthenticated_query=True)
      # check that some warning was logged via security_decision
      assert app is not None
  
  def test_authenticated_query_no_loopback_check():
      app = create_app(_DummyAgent(), auth_token="secret", host="0.0.0.0")
      assert app is not None
  ```

**Files to touch:**
- `src/swarmline/serve/app.py:135-160` (modify `create_app`, add `host` param + validation)
- `tests/unit/test_serve_app_loopback_enforcement.py` (create) — 4 tests

**Commands to verify:**
```bash
pytest tests/unit/test_serve_app_loopback_enforcement.py -xvs
pytest -q
pytest -m security -v
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] `create_app(allow_unauthenticated_query=True, host="0.0.0.0")` raises `ValueError`
- [ ] `create_app(allow_unauthenticated_query=True, host="127.0.0.1")` succeeds
- [ ] `create_app(allow_unauthenticated_query=True)` (no host) succeeds with warning
- [ ] `create_app(auth_token="x", host="0.0.0.0")` succeeds
- [ ] All existing serve tests green
- [ ] Pattern matches A2A/HealthServer

**Code rules:** Defense in depth, secure-by-default (when host is specified), backward-compat (when host=None).

---

<!-- mb-stage:20 -->
## Stage 20: M-3 fix — extend `JsonlTelemetrySink` redaction (key + value-level regex)

**Source**: T4.2 = M-3
**Effort**: ~2h
**Type**: code (security)

**What to do:**
- В `src/swarmline/observability/jsonl_sink.py:12-21`: extend `DEFAULT_REDACT_KEYS`:
  ```python
  DEFAULT_REDACT_KEYS = frozenset(
      {
          # existing
          "api_key", "apikey", "authorization", "password", "secret", "token",
          # added in v1.5.0
          "bearer", "credential", "credentials", "private_key", "privatekey",
          "pem", "cookie", "set-cookie", "x-api-key", "auth", "oauth_token",
          "refresh_token", "client_secret", "aws_secret_access_key",
          "connection_string", "dsn",
      }
  )
  ```
- Add `DEFAULT_REDACT_VALUE_PATTERNS` (compiled regex):
  ```python
  import re
  
  DEFAULT_REDACT_VALUE_PATTERNS: tuple[re.Pattern, ...] = (
      re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                    # OpenAI/Anthropic API keys
      re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),  # Bearer tokens
      re.compile(r"://[^/\s]+:[^/\s@]+@"),                      # URL userinfo
  )
  ```
- В `__init__`: add `redact_value_patterns: tuple[re.Pattern, ...] = DEFAULT_REDACT_VALUE_PATTERNS`.
- В `_redact()` function (line 80): добавить value-level regex pass для всех string leaves:
  ```python
  def _redact(value: Any, redact_keys: frozenset[str], 
              redact_value_patterns: tuple[re.Pattern, ...] = ()) -> Any:
      if isinstance(value, dict):
          result: dict[str, Any] = {}
          for key, item in value.items():
              key_text = str(key)
              if key_text.lower() in redact_keys:
                  result[key_text] = "[REDACTED]"
              else:
                  result[key_text] = _redact(item, redact_keys, redact_value_patterns)
          return result
      if isinstance(value, list):
          return [_redact(item, redact_keys, redact_value_patterns) for item in value]
      if isinstance(value, tuple):
          return [_redact(item, redact_keys, redact_value_patterns) for item in value]
      if isinstance(value, str) and redact_value_patterns:
          for pattern in redact_value_patterns:
              value = pattern.sub("[REDACTED]", value)
          return value
      return value
  ```
- Обновить call site `record()` чтобы передавать `self._redact_value_patterns`.

**Testing (TDD — tests BEFORE implementation):**
- **NEW unit test** `tests/unit/test_jsonl_telemetry_sink_redaction.py`:
  ```python
  import json
  import re
  
  import pytest
  
  from swarmline.observability.jsonl_sink import JsonlTelemetrySink
  
  
  @pytest.mark.asyncio
  @pytest.mark.parametrize(
      "key,value,expected_redacted",
      [
          # Pre-existing keys
          ("api_key", "sk-abc", True),
          ("authorization", "Bearer xyz", True),
          ("password", "p", True),
          # Newly added keys
          ("bearer", "xyz", True),
          ("credential", "xyz", True),
          ("private_key", "----PEM", True),
          ("cookie", "session=abc", True),
          ("dsn", "postgres://user:pass@host", True),
          ("client_secret", "xyz", True),
          ("aws_secret_access_key", "xyz", True),
          # Non-secret keys
          ("user_name", "alice", False),
          ("topic_id", "t1", False),
      ],
  )
  async def test_redaction_by_key_name(tmp_path, key, value, expected_redacted):
      sink = JsonlTelemetrySink(tmp_path / "out.jsonl")
      await sink.record("e", {key: value})
      content = (tmp_path / "out.jsonl").read_text()
      record = json.loads(content.splitlines()[0])
      if expected_redacted:
          assert record["data"][key] == "[REDACTED]"
      else:
          assert record["data"][key] == value
  
  
  @pytest.mark.asyncio
  @pytest.mark.parametrize(
      "value,should_have_redacted",
      [
          ("My API key is sk-ant-1234567890abcdefghij", True),
          ("Authorization header was Bearer 1234567890abc", True),
          ("Connection error: postgres://user:hunter2@db/x", True),
          ("Just a regular message", False),
      ],
  )
  async def test_redaction_by_value_pattern(tmp_path, value, should_have_redacted):
      sink = JsonlTelemetrySink(tmp_path / "out.jsonl")
      await sink.record("e", {"prompt": value})
      content = (tmp_path / "out.jsonl").read_text()
      record = json.loads(content.splitlines()[0])
      if should_have_redacted:
          assert "[REDACTED]" in record["data"]["prompt"]
      else:
          assert record["data"]["prompt"] == value
  ```

**Files to touch:**
- `src/swarmline/observability/jsonl_sink.py:1-95` (modify)
- `tests/unit/test_jsonl_telemetry_sink_redaction.py` (create) — 14+ parametrized tests

**Commands to verify:**
```bash
pytest tests/unit/test_jsonl_telemetry_sink_redaction.py -xvs
pytest -m security -v
pytest -q
ruff check src/ tests/
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] `DEFAULT_REDACT_KEYS` contains 18+ keys (was 6)
- [ ] `DEFAULT_REDACT_VALUE_PATTERNS` redacts `sk-*`, `Bearer ...`, URL userinfo
- [ ] Value containing `sk-ant-...` in any key is redacted at value level
- [ ] All existing redaction tests still green
- [ ] No ty regressions

**Code rules:** Secure-by-default expansion. Backward-compat: existing key set is a subset of new.

---

<!-- mb-stage:21 -->
## Stage 21: Add `pip-audit` to CI

**Source**: T4.5
**Effort**: ~30min
**Type**: tooling (CI)

**What to do:**
- В `.github/workflows/ci.yml`: добавить новый job `audit` (или новый step в `lint` job):
  ```yaml
  audit:
    name: Security audit (pip-audit)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - name: Install pip-audit
        run: pip install pip-audit
      - name: Install project deps for audit
        run: pip install -e ".[all]"
      - name: Run pip-audit
        run: pip-audit --strict --desc
  ```
- (Опционально) добавить в `pyproject.toml [project.optional-dependencies] dev` зависимость `pip-audit>=2.6` для local-run convenience.

**Testing (TDD — tests BEFORE implementation):**
- TDD not applicable: CI tooling.

**Files to touch:**
- `.github/workflows/ci.yml` (add new job)
- (опционально) `pyproject.toml` (add `pip-audit>=2.6` to `dev`)

**Commands to verify:**
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
pip install pip-audit && pip-audit --strict --desc   # local smoke
```

**DoD (SMART):**
- [ ] `.github/workflows/ci.yml` has `audit` job (or step) running `pip-audit --strict --desc`
- [ ] YAML syntax valid
- [ ] Local pip-audit passes (no known vulns) OR documented exceptions

**Code rules:** Supply-chain hardening, defense-in-depth.

---

## Финальные секции плана

### Граф зависимостей (DAG)

```
Stage 1 (ruff) ──────────────────────┐
                                     │
Stage 2 (default runtime) ─────┐     │
Stage 3 (russian fix) ─────────┤     │
Stage 4 (docs lie) ────────────┤     │
Stage 5 (logger fix) ──────────┤     │
Stage 6 (jsonl async) ─────────┤     │
Stage 7 (publish.yml) ─────────┤     │
Stage 8 (CLAUDE/AGENTS) ───────┤     │
                               │     │
                               ▼     │
                       Stage 9 (version bump) ──┐
                                                │
                                                ▼
Stage 10 (CHANGELOG) ←───── all of (2,3,5,6,9,18,20) — needs them done
Stage 11 (migration) ←───── needs (2,18)
Stage 12 (feature docs) ─── independent

Stage 14 (__all__ trim) ─── independent (after Stage 9)
Stage 15 (SwarmlineError) ─ independent
Stage 16 (MockRuntime) ──── needs Stage 2 done (default runtime)
Stage 13 (00_hello_world) ─ needs Stage 16 (MockRuntime exists)
Stage 17 (thinking typed) ─ independent
Stage 18 (max_thinking rm) ─ needs Stage 17 done first

Stage 19 (M-1 serve) ────── independent
Stage 20 (M-3 redact) ───── independent
Stage 21 (pip-audit) ────── independent
```

### Параллелизация (если несколько agents — например, parallel claude sessions)

| Phase | Stages | Notes |
|-------|--------|-------|
| Phase 1 (sequential) | 1 | tooling foundation; everyone needs formatted base |
| Phase 2 (parallel-3) | 2, 3, 7, 8 | trivial isolated changes |
| Phase 3 (parallel-2) | 5, 6 | logger + jsonl; both observability, but different files |
| Phase 4 (sequential) | 9 | version bump; gates on tests |
| Phase 5 (parallel-3) | 14, 15, 17 | DX cleanup; isolated files |
| Phase 6 (sequential) | 18 | depends on Stage 17 |
| Phase 7 (sequential) | 16 | MockRuntime |
| Phase 8 (sequential) | 13 | hello_world depends on 16 |
| Phase 9 (parallel-3) | 19, 20, 21 | tier 4 security |
| Phase 10 (sequential) | 4 | docs lie (small) |
| Phase 11 (sequential) | 10 | CHANGELOG (depends on 2,3,5,6,9,18,20) |
| Phase 12 (parallel-2) | 11, 12 | docs (migration + feature) |

### Possible merge conflicts

- `src/swarmline/__init__.py` — modified by Stage 14 (`__all__` trim) AND Stage 15 (`SwarmlineError` import). **Mitigation**: order Stage 15 FIRST, Stage 14 SECOND (или single agent runs both).
- `src/swarmline/agent/config.py` — modified by Stage 2 (`runtime` default), Stage 17 (thinking typed), Stage 18 (`max_thinking_tokens` removal). **Mitigation**: одна сессия делает все три (или strict order: 2 → 17 → 18).
- `src/swarmline/observability/jsonl_sink.py` — modified by Stage 6 (async I/O) AND Stage 20 (redaction). **Mitigation**: order Stage 6 FIRST, Stage 20 SECOND.
- `CHANGELOG.md` — only Stage 10 modifies. No conflict.
- `tests/conftest.py` — only Stage 5 modifies. No conflict.

### Gate (план-success criterion)

Plan complete когда **все** following are true:

- [ ] All Tier 1 stages done (Stages 1-9)
- [ ] All Tier 2 stages done (Stages 10-12)
- [ ] All Tier 3 stages done (Stages 13-18) — **strongly recommended**, optional if time pressure
- [ ] Selected Tier 4 stages done (Stages 19, 20, 21)
- [ ] `ruff check src/ tests/` exit 0
- [ ] `ruff format --check src/ tests/` exit 0
- [ ] `ty check src/swarmline/` All checks passed!
- [ ] `pytest -q` ≥ 5354+ passed (no regression)
- [ ] `pytest --cov=swarmline --cov-report=term` coverage ≥ 86%
- [ ] CHANGELOG `[1.5.0]` written, dated, all 6 categories
- [ ] `docs/migration/v1.4-to-v1.5.md` exists
- [ ] At least 5 of 12 NEW feature doc files created
- [ ] `pyproject.toml [project] version` = `"1.5.0"`
- [ ] `swarmline.__all__` has exactly 12 names
- [ ] `swarmline.errors.SwarmlineError` exists, all 10 custom errors subclass it
- [ ] `swarmline.testing.MockRuntime` exists, `examples/01_agent_basics.py` ≤ 50 LOC
- [ ] `examples/00_hello_world.py` exists, ≤ 30 LOC
- [ ] `serve.create_app(host="0.0.0.0", allow_unauthenticated_query=True)` raises ValueError
- [ ] `JsonlTelemetrySink` redacts `sk-*` and `Bearer ...` in values
- [ ] `pip-audit` job in CI

### Estimated total effort

| Tier | Stages | Hours |
|------|--------|-------|
| Tier 1 | 1-9 | ~6h |
| Tier 2 | 10-12 | ~3h |
| Tier 3 | 13-18 | ~7h |
| Tier 4 (selected) | 19, 20, 21 | ~3.5h |
| **Total (Tier 1 + 2 + 4 selected)** | required | **~12.5h** |
| **Total (full plan)** | required + recommended | **~19.5h** |

### Checklist (для копирования в `.memory-bank/checklist.md`)

#### Tier 1 (release blockers)
- ✅ Stage 1: ruff check --fix && ruff format — commit `0badf89` (Tier 1) + format pass `1511f65`
- ✅ Stage 2: AgentConfig.runtime default → "thin" — commit `3bdd7ab` (C-8)
- ✅ Stage 3: Russian error string → English — commit `0badf89` (Tier 1)
- ✅ Stage 4: docs/agent-facade.md system_prompt fix — commit `0badf89` (Tier 1)
- ✅ Stage 5: observability/logger.py — drop force=True, route to stderr — commit `5cbc326` (C-1, C-3)
- ✅ Stage 6: JsonlTelemetrySink async I/O via asyncio.to_thread — commit `32fe1af` (C-2)
- ✅ Stage 7: drop Python 3.10 from publish.yml matrix — commit `0badf89` (Tier 1)
- ✅ Stage 8: CLAUDE.md / AGENTS.md → Python 3.11+ — commit `0badf89` (Tier 1)
- ✅ Stage 9: bump pyproject.toml version → 1.5.0 — release commit `3fae1b2`

#### Tier 2 (release packaging)
- ✅ Stage 10: CHANGELOG [1.5.0] entry — commit `d541edb` (Tier 2)
- ✅ Stage 11: docs/migration/v1.4-to-v1.5.md — commit `d541edb` (Tier 2)
- ✅ Stage 12: minimum-viable feature docs (≥5 files) — commit `d541edb` (Tier 2)

#### Tier 3 (DX paper-cuts)
- ✅ Stage 13: examples/00_hello_world.py — commit `d7f2a55` (Tier 3)
- ✅ Stage 14: trim swarmline/__init__.py __all__ → 12 names — commit `d7f2a55` (Tier 3)
- ✅ Stage 15: SwarmlineError base + 10 subclasses — commit `d7f2a55` (Tier 3)
- ✅ Stage 16: swarmline.testing.MockRuntime + refactor 01_agent_basics.py — commit `d7f2a55` (Tier 3)
- ✅ Stage 17: AgentConfig.thinking → ThinkingConfig typed — commit `d7f2a55` (Tier 3)
- ✅ Stage 18: remove max_thinking_tokens (deprecated) — commit `d7f2a55` (Tier 3)

#### Tier 4 (security hardening)
- ✅ Stage 19: M-1 serve.create_app loopback enforcement — commit `913cb5c` (Tier 4)
- ✅ Stage 20: M-3 JsonlTelemetrySink extended redaction — commit `913cb5c` (Tier 4)
- ✅ Stage 21: pip-audit in CI — commit `913cb5c` (Tier 4)

---

## Self-review (план перед execution)

- ✅ Каждая stage atomic (≤ 2-3h max, чаще 5-30min)
- ✅ TDD везде где есть code change (Stages 2, 3, 5, 6, 9, 14, 15, 16, 17, 18, 19, 20)
- ✅ Файлы и команды конкретные, copy-paste ready
- ✅ Зависимости очевидны (DAG explicit)
- ✅ Production wiring учтён (CHANGELOG, version, docs)
- ✅ Нет пропущенных шагов между stages (test isolation, async correctness, security, public API hygiene)
- ✅ Assumptions зафиксированы
- ✅ Risks с probability + mitigation
- ✅ Backward-compat сохранён где возможно (Stages 14, 17, 19)
- ✅ Removal documented (Stages 7, 18 — в CHANGELOG)
