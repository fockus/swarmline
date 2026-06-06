# Plan: feature — minimal-code-agent-sdk

**Baseline commit:** fbc2f44508a6a26bb7293b6dfc00a6e92449703e
**Source idea:** `BACKLOG.md#IDEA-081` (P0 = 19 пунктов, 4 группы: A–H, AA–AE, AF–AH, K1–K3)
**Target release:** v1.5.0 (single minor bump для всей умбреллы)
**Methodology:** TDD red-green-refactor + Contract-First (Stage 1 gate) + Strangler Fig (для P0-D AgentMessage). Тесты ПЕРВЫМИ на каждом шаге.

## Context

**Problem:** ThinRuntime сейчас — низкоуровневый движок (12 коллабораторов в `__init__`, нет публичного фасада, нет session lifecycle, нет safety guards, нет self-verification feedback loop). Build a minimal code-agent в 3 строки невозможен. Конкуренты (`badlogic/pi-mono` 44.6K⭐, `anomalyco/opencode` форк 155K⭐, `HarnessLab/claw-code-agent`) показывают канонический минимум: фасад + safety + self-verification + sessions.

**Expected result:** Разработчик пишет
```python
from swarmline import CodeAgent
agent = CodeAgent(model="sonnet", cwd="/repo")
async for ev in agent.run("fix typo in README"):
    print(ev)
```
— получает агента, который:
- сам себя проверяет (`diagnostics` after edit),
- переживает > 50 turns без падения (truncation continuation + reactive compact + preflight check),
- не сжигает workspace (file/bash safety guards),
- спрашивает в неоднозначных ситуациях (`question` tool),
- сохраняется автоматически после каждого turn и резюмится после крэша.

**Related files:**
- `src/swarmline/runtime/thin/runtime.py` — `ThinRuntime` (25.1K, главный entrypoint, 12 deps)
- `src/swarmline/runtime/thin/coding_toolpack.py` — текущий tool set (read/write/edit/glob/bash/grep — `apply_patch` и `todo` отсутствуют)
- `src/swarmline/bootstrap/__init__.py` — `SwarmlineStack` factory (база для дефолтов)
- `src/swarmline/memory/sqlite.py` — `SqliteMessageStore` / `SqliteSessionStateStore` (база для P0-K1)
- `src/swarmline/protocols/__init__.py` — 14 ISP-protocols (≤ 5 методов)
- `src/swarmline/policy/` — `DefaultToolPolicy` (для P0-E надстройки)
- `src/swarmline/hooks/` — `HookRegistry` (база для P0-F mid-run hooks)
- `src/swarmline/__init__.py` — public API (нужно добавить `CodeAgent` в `__all__`)
- `src/swarmline/runtime/thin/stream_parser.py` — частично готово для tool_output_chunk (P1-R, не в этом плане)
- `tests/integration/`, `tests/unit/runtime/thin/` — миррор для новых тестов
- `reports/2026-05-05_analysis_thin-vs-pi-mono-opencode-code-agent-sdk.md` — конкурентный анализ

**Constraints:**
- Backward compat: 4263+ существующих тестов зелёные на каждом шаге. Все новые поля в `RuntimeConfig` — `Optional[X] = None`.
- Test markers: `integration`, `security`, `live`. Default `pytest -m "not live"`.
- Lint: `ruff check src/ tests/`. Format: `ruff format`. Type: `ty check src/swarmline/` (не mypy).
- Coverage: общий 85%+, новый `code_agent/` модуль 95%+ (core SDK).
- Никаких новых deps в `pyproject.toml`. Используем только stdlib + уже подключённые.
- Защищённые файлы (`.env`, `ci/**`, Docker/K8s/Terraform) — не трогаем.

---

## Stages

<!-- mb-stage:1 -->
### Stage 1: Foundation — Contracts & ADRs (Contract-First gate)

**Goal:** До любой реализации зафиксировать архитектурные решения как ADR + определить Protocols + написать contract-тесты, которые должны проходить для ЛЮБОЙ корректной реализации (Contract-First per RULES.md).

**Why first:** RULES.md `CRITICAL`: «Contract-First: интерфейс → contract-тесты → реализация». План вводит несколько новых абстракций (`PermissionDecision`, `DiagnosticsProvider`, mid-run hooks, `SessionMetadata`) — все требуют Protocol + contract test до конкретной реализации.

**What to do:**

- [ ] **Step 1.1: ADR — Strangler Fig migration для AgentMessage**
  - Команда: `bash ~/.claude/skills/memory-bank/scripts/mb-adr.sh "Strangler Fig migration for AgentMessage in CodeAgent"`
  - Заполнить в `.memory-bank/BACKLOG.md` секции: Context (legacy `Message` существует, новый CodeAgent нужен `AgentMessage` с UI-ролями), Options (A: replace inline / B: parallel types via Strangler / C: subclass), Decision (B), Rationale (4263+ tests, no break), Consequences (двойная поддержка пока migration).

- [ ] **Step 1.2: ADR — Sessions storage location**
  - `mb-adr.sh "CodeAgent sessions storage in ~/.swarmline/sessions/<id>/"`.
  - Options: A: project-local `.swarmline/`, B: XDG `~/.local/share/swarmline/`, C: user home `~/.swarmline/`.
  - Decision: C (user-scoped, cross-project, не засоряет git workspace).
  - Consequences: `XDG_DATA_HOME` override, документировать.

- [ ] **Step 1.3: ADR — `convert_to_llm` callback signature**
  - `mb-adr.sh "convert_to_llm callback shape (pi-agent-core pattern)"`.
  - Options: A: pi-pattern `(list[AgentMessage]) -> list[Message]`, B: per-message converter, C: subclass override.
  - Decision: A (matches pi-mono ergonomics, single seam).

- [ ] **Step 1.4: ADR — Default `tool_execution="sequential"`**
  - `mb-adr.sh "Default tool_execution=sequential, parallel opt-in"`.
  - Options: A: sequential default (safety), B: parallel default (perf), C: heuristic per-tool.
  - Decision: A. Rationale: P1-I file-mutation queue ещё не реализован → race conditions.

- [ ] **Step 1.5: Define new Protocols в `src/swarmline/code_agent/protocols.py`**
  ```python
  # src/swarmline/code_agent/protocols.py
  from typing import Protocol, runtime_checkable, Awaitable
  from dataclasses import dataclass

  @dataclass(frozen=True)
  class Allow: ...
  @dataclass(frozen=True)
  class Deny:
      reason: str
  @dataclass(frozen=True)
  class AskUser:
      prompt: str

  PermissionDecision = Allow | Deny | AskUser

  @runtime_checkable
  class PermissionProvider(Protocol):
      async def decide(self, tool: str, args: dict) -> PermissionDecision: ...

  @dataclass(frozen=True)
  class DiagnosticIssue:
      file: str
      line: int
      col: int
      severity: str
      message: str

  @runtime_checkable
  class DiagnosticsProvider(Protocol):
      async def check(self, cwd: str, files: list[str] | None = None) -> list[DiagnosticIssue]: ...

  @dataclass(frozen=True)
  class LifecycleHooks:
      """ISP-safe grouping of mid-run hooks (≤5 publicly-relevant fields)."""
      should_stop_after_turn: object | None = None  # Callable[[int, list], Awaitable[bool]]
      get_steering_messages: object | None = None
      get_followup_messages: object | None = None
      transform_context: object | None = None
      convert_to_llm: object | None = None
  ```
  - Все Protocols ≤ 5 методов (ISP). `LifecycleHooks` группирует 5 callbacks в один параметр `CodeAgent` чтобы не раздувать конструктор.

- [ ] **Step 1.6: Write contract test `PermissionProvider`**
  ```python
  # tests/contract/code_agent/test_permission_provider_contract.py
  import pytest
  from swarmline.code_agent.protocols import PermissionProvider, Allow, Deny, AskUser

  class _AlwaysAllow:
      async def decide(self, tool, args):
          return Allow()

  class _AlwaysDeny:
      async def decide(self, tool, args):
          return Deny(reason="blocked")

  @pytest.mark.parametrize("impl", [_AlwaysAllow(), _AlwaysDeny()])
  @pytest.mark.asyncio
  async def test_permission_provider_returns_one_of_three_decision_types(impl):
      assert isinstance(impl, PermissionProvider)
      result = await impl.decide("write", {"path": "/tmp/x"})
      assert isinstance(result, (Allow, Deny, AskUser))
  ```
  Команда: `pytest tests/contract/code_agent/test_permission_provider_contract.py -v`
  Expected: `FAIL — ImportError`.

- [ ] **Step 1.7: Write contract test `DiagnosticsProvider`**
  ```python
  # tests/contract/code_agent/test_diagnostics_provider_contract.py
  import pytest
  from swarmline.code_agent.protocols import DiagnosticsProvider, DiagnosticIssue

  class _NoIssues:
      async def check(self, cwd, files=None):
          return []

  class _OneIssue:
      async def check(self, cwd, files=None):
          return [DiagnosticIssue(file="x.py", line=1, col=1, severity="error", message="bad")]

  @pytest.mark.parametrize("impl", [_NoIssues(), _OneIssue()])
  @pytest.mark.asyncio
  async def test_diagnostics_provider_returns_list_of_issues(impl, tmp_path):
      assert isinstance(impl, DiagnosticsProvider)
      issues = await impl.check(str(tmp_path))
      assert isinstance(issues, list)
      for i in issues:
          assert isinstance(i, DiagnosticIssue)
  ```
  Expected: `FAIL — ImportError`.

- [ ] **Step 1.8: Реализация Protocols (минимально достаточная для contract tests)**
  - Создать `src/swarmline/code_agent/protocols.py` с кодом из 1.5.
  - Добавить в `src/swarmline/code_agent/__init__.py` экспорт типов.
  - Запустить contract tests 1.6, 1.7 → `PASS`.

- [ ] **Step 1.9: Verify ADR & Protocols gate**
  - `grep -c "^### ADR-" .memory-bank/BACKLOG.md` ≥ предыдущее значение + 4.
  - `pytest tests/contract/code_agent/ -v` exit 0.
  - `ty check src/swarmline/code_agent/protocols.py` clean.

- [ ] **Step 1.10: Commit**
  - `git commit -m "feat(code_agent): foundation Protocols + 4 ADRs (Stage 1 contract-first gate)"`

**Testing (TDD — Contract-First):**
- Contract: `PermissionProvider`, `DiagnosticsProvider` — параметризованные тесты, должны проходить для любой корректной реализации.
- Unit: dataclass invariants (frozen, equality).

**DoD (SMART):**
- [ ] 4 ADR созданы в `BACKLOG.md ## ADR` секции (S: явные ID, M: grep count, A: mb-adr.sh, R: блокирует Stage 2+, T: 0.5 дня).
- [ ] `src/swarmline/code_agent/protocols.py` содержит ≥3 Protocols (`PermissionProvider`, `DiagnosticsProvider`, `LifecycleHooks` dataclass).
- [ ] Все Protocols ≤5 методов (ISP).
- [ ] 2 contract test файла зелёные (>=4 параметризованных тестов).
- [ ] Backward compat: 4263+ зелёные.
- [ ] `ruff` + `ty` clean.

**Code rules:** Contract-First (Protocols → contract tests → impl). ISP (≤5 методов на Protocol). DIP (новые абстракции через Protocol, не конкретные классы). YAGNI (не определяем Protocols, которые не нужны для P0).

---

<!-- mb-stage:2 -->
### Stage 2: Spike — `CodeAgent` фасад (single-file прототип, выявить choke-points)

**Goal:** За 1 день собрать минимально работающий `CodeAgent` фасад в **одном файле** `src/swarmline/code_agent.py` (без подмодуля). Пробрасывает в `bootstrap.SwarmlineStack`. **Не финальная архитектура** — exploratory prototype, чтобы найти места, где `ThinRuntime.__init__` требует не-Optional аргументы (Stage 2 сделает их Optional).

**What to do:**
- [ ] **Step 1.1: Inventory `ThinRuntime.__init__` коллабораторов**
  - Прочитать `src/swarmline/runtime/thin/runtime.py:1-200`, выписать все required параметры конструктора в `notes/2026-05-05_thin-runtime-collaborators.md`.
  - Команда: `grep -n "def __init__" src/swarmline/runtime/thin/runtime.py`.
  - Expected: список из 12 параметров с типами и текущими defaults.
- [ ] **Step 1.2: Inventory `SwarmlineStack` factory**
  - Прочитать `src/swarmline/bootstrap/__init__.py`, понять, какие дефолты он уже даёт.
  - Команда: `grep -rn "class SwarmlineStack\|def from_" src/swarmline/bootstrap/`.
  - Expected: задокументирован минимальный happy-path для построения stack из 1-2 параметров.
- [ ] **Step 1.3: Write failing smoke test для spike фасада**
  ```python
  # tests/integration/code_agent/test_spike_facade.py
  import pytest
  from swarmline import CodeAgent

  @pytest.mark.asyncio
  async def test_code_agent_three_lines_constructs(tmp_path):
      agent = CodeAgent(model="claude-3-5-haiku-20241022", cwd=str(tmp_path))
      assert agent.cwd == str(tmp_path)
      assert agent.model == "claude-3-5-haiku-20241022"
  ```
  Команда: `pytest tests/integration/code_agent/test_spike_facade.py::test_code_agent_three_lines_constructs -v`
  Expected: `FAIL — ImportError: cannot import name 'CodeAgent' from 'swarmline'`.
- [ ] **Step 1.4: Minimal implementation `swarmline/code_agent.py`**
  - Создать `src/swarmline/code_agent.py` (single file). Класс `CodeAgent(model, cwd, tools=None)` хранит атрибуты, ничего не запускает.
  - Добавить экспорт в `src/swarmline/__init__.py`: `from swarmline.code_agent import CodeAgent` + добавить в `__all__`.
  - Команда: `pytest tests/integration/code_agent/test_spike_facade.py::test_code_agent_three_lines_constructs -v`
  - Expected: `PASS`.
- [ ] **Step 1.5: Spike `.run(prompt)` через `SwarmlineStack`**
  - Реализовать `async def run(self, prompt: str) -> AsyncIterator[RuntimeEvent]` — собирает stack через `SwarmlineStack.from_defaults(model=...)` (если такого метода нет — использовать существующий `SwarmlineStack(...)` с минимумом параметров).
  - Записать в spike-notes какие параметры потребовали неочевидных значений (`hook_registry`, `tool_policy`, `workspace`, `command_registry` — кандидаты для Optional default в Stage 2).
- [ ] **Step 1.6: Spike-level integration test (offline, fake LLM)**
  ```python
  # tests/integration/code_agent/test_spike_run.py
  @pytest.mark.asyncio
  async def test_code_agent_run_yields_events_with_fake_llm(tmp_path, fake_llm):
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm)
      events = [ev async for ev in agent.run("hello")]
      event_types = {type(ev).__name__ for ev in events}
      # Бизнес-факт: spike run должен эмитировать как минимум start, assistant_message, end
      assert "RunStartEvent" in event_types or any(getattr(ev, "type", None) == "run_start" for ev in events)
      assert any(getattr(ev, "type", None) == "assistant_message" or "Assistant" in type(ev).__name__ for ev in events)
  ```
  Использовать существующий `fake_llm` fixture (см. `tests/conftest.py` или `tests/unit/runtime/thin/conftest.py`).
- [ ] **Step 1.7: Записать findings в `notes/2026-05-05_code-agent-spike-findings.md`**
  - Список: какие поля в `RuntimeConfig` сейчас non-Optional, какие нужно перевести в Optional, какие дефолты добавить в `SwarmlineStack`.
- [ ] **Step 1.8: Commit**
  - `git add src/swarmline/code_agent.py src/swarmline/__init__.py tests/integration/code_agent/ .memory-bank/notes/2026-05-05_*.md`
  - `git commit -m "spike(code_agent): single-file CodeAgent facade prototype to find Optional choke-points"`

**Testing (TDD):**
- Unit: smoke test «фасад конструируется в 3 строки» (Step 1.3).
- Integration: spike run yields events с fake LLM (Step 1.6).

**DoD (SMART):**
- [ ] `from swarmline import CodeAgent` успешно (S: импорт, M: pytest pass, A: 1 строка экспорта, R: первый шаг роадмапа, T: 1 день).
- [ ] 2 теста зелёные (1 unit + 1 integration).
- [ ] `notes/2026-05-05_code-agent-spike-findings.md` содержит список ≥5 choke-points для Stage 2.
- [ ] `ruff check src/swarmline/code_agent.py tests/integration/code_agent/` — clean.
- [ ] `ty check src/swarmline/code_agent.py` — clean.
- [ ] Все 4263+ существующих тестов проходят: `pytest -m "not live"` exit 0.

**Code rules:** SOLID (CodeAgent — фасад, делегирует stack), KISS (single file для spike, без подмодуля), YAGNI (не реализуем session/safety на этом этапе).

---

<!-- mb-stage:3 -->
### Stage 3: P0-A + P0-B + P0-H — Публичный фасад + slim `ThinRuntime.__init__` + CLI

**Goal:** Превратить spike в production-grade модуль `src/swarmline/code_agent/` (теперь подмодуль). `ThinRuntime` принимает только обязательные deps; остальные имеют sensible defaults через `from_config()` builder. CLI `python -m swarmline.code_agent "<prompt>"` работает поверх фасада.

**What to do:**
- [ ] **Step 2.1: Промоут single-file → subpackage**
  - `mkdir src/swarmline/code_agent/` → `mv src/swarmline/code_agent.py src/swarmline/code_agent/_facade.py` → `src/swarmline/code_agent/__init__.py` реэкспортирует `CodeAgent`.
  - Команда: `pytest tests/integration/code_agent/ -v` — должно остаться зелёным.
- [ ] **Step 2.2: Write failing test для Optional defaults в `RuntimeConfig`**
  ```python
  # tests/unit/runtime/thin/test_runtime_config_optional_defaults.py
  from swarmline.runtime.types import RuntimeConfig
  def test_runtime_config_minimal_construction_only_model_required():
      cfg = RuntimeConfig(model="sonnet")
      assert cfg.hook_registry is None  # auto-default at runtime
      assert cfg.tool_policy is None
      assert cfg.workspace is None
      assert cfg.command_registry is None
      assert cfg.subagent_config is None
      assert cfg.tool_execution is None  # P0-G placeholder
  ```
  Команда: `pytest tests/unit/runtime/thin/test_runtime_config_optional_defaults.py -v` — Expected `FAIL`.
- [ ] **Step 2.3: Сделать поля `RuntimeConfig` Optional с `None` default**
  - Прочитать `src/swarmline/runtime/types.py`, найти `RuntimeConfig` dataclass.
  - Изменить `hook_registry: HookRegistry` → `hook_registry: HookRegistry | None = None`. Аналогично для остальных 5 полей. Strangler Fig: НЕ меняем существующих публичных контрактов.
  - Запустить full suite: `pytest -m "not live" -x` — Expected все 4263+ зелёные.
- [ ] **Step 2.4: Write failing test для `ThinRuntime.from_config()` builder**
  ```python
  # tests/integration/runtime/thin/test_runtime_from_config.py
  @pytest.mark.asyncio
  async def test_thin_runtime_from_config_with_defaults_constructs(fake_llm):
      from swarmline.runtime.thin.runtime import ThinRuntime
      from swarmline.runtime.types import RuntimeConfig
      cfg = RuntimeConfig(model="fake")
      rt = ThinRuntime.from_config(cfg, llm_client=fake_llm)
      assert rt.hook_registry is not None  # auto-defaulted
      assert rt.tool_policy is not None
      assert rt.workspace is not None
      assert rt.command_registry is not None
  ```
  Expected: `FAIL — AttributeError: type object 'ThinRuntime' has no attribute 'from_config'`.
- [ ] **Step 2.5: Реализовать `ThinRuntime.from_config()` classmethod**
  - В `src/swarmline/runtime/thin/runtime.py` добавить classmethod `from_config(cls, cfg: RuntimeConfig, **deps) -> ThinRuntime`.
  - Внутри: для каждого `None`-поля cfg создаётся sensible default (`HookRegistry()`, `DefaultToolPolicy()`, `ExecutionWorkspace(cwd=cfg.cwd)`, `CommandRegistry()`, `SubagentConfig.disabled()`).
  - Запустить тест из 2.4 → `PASS`.
- [ ] **Step 2.6: Refactor `CodeAgent` в подмодуле**
  - `src/swarmline/code_agent/_facade.py` — `CodeAgent` использует `ThinRuntime.from_config()`.
  - `src/swarmline/code_agent/__init__.py` — экспорт `CodeAgent` + `__all__ = ("CodeAgent",)`.
  - Все методы публичного API: `__init__(model, cwd, tools=None, on_permission=None, on_question=None)`, `run(prompt) -> AsyncIterator[RuntimeEvent]`, `stream(prompt)`, `close()`.
  - `on_permission`/`on_question` пока accepted, но не wired (Stage 5 / Stage 9).
- [ ] **Step 2.7: Write failing test для CLI runner**
  ```python
  # tests/integration/code_agent/test_cli.py
  import subprocess, sys
  def test_python_m_swarmline_code_agent_runs_with_help():
      r = subprocess.run([sys.executable, "-m", "swarmline.code_agent", "--help"],
                         capture_output=True, text=True, timeout=10)
      assert r.returncode == 0
      assert "prompt" in r.stdout.lower()
  ```
  Expected: `FAIL — No module named swarmline.code_agent.__main__`.
- [ ] **Step 2.8: Реализовать `src/swarmline/code_agent/__main__.py`**
  - Использовать `argparse`: позиционный `prompt`, `--model` (default `"sonnet"`), `--cwd` (default `os.getcwd()`), `--json` (stream events as JSONL).
  - Запускает `asyncio.run(main(...))` который инстанцирует `CodeAgent` и стримит события.
  - Тесты:
    - 2.7 (help) → `PASS`.
    - Дополнительный smoke: `python -m swarmline.code_agent "hi" --model fake --cwd /tmp/x` (с моком LLM через env-var) → exit 0.
- [ ] **Step 2.9: Update `swarmline.__init__` exports**
  - `from swarmline.code_agent import CodeAgent`
  - Добавить в `__all__` рядом с `Agent`, `Conversation`, `Result`.
- [ ] **Step 2.10: Backward-compat regression run**
  - `pytest -m "not live" --tb=short` — Expected: все 4263+ зелёные.
  - `ruff check src/ tests/` — clean.
  - `ty check src/swarmline/` — no new errors против baseline в `tests/architecture/ty_baseline.txt`.
- [ ] **Step 2.11: Commit**
  - `git commit -m "feat(code_agent): public CodeAgent facade + ThinRuntime.from_config + CLI runner (P0-A, P0-B, P0-H)"`

**Testing (TDD):**
- Unit: `RuntimeConfig` Optional defaults (5 полей) (2.2).
- Integration: `ThinRuntime.from_config()` builds with defaults (2.4); `CodeAgent` 3-line construction smoke; `CodeAgent.run()` yields events with fake LLM.
- E2E (CLI): `python -m swarmline.code_agent --help` exit 0; `python -m swarmline.code_agent "hi" --model fake` exit 0.

**DoD (SMART):**
- [ ] `from swarmline import CodeAgent` (S: 1 строка), `CodeAgent(model="sonnet", cwd="/tmp")` (M: tests pass), без явной сборки stack (A: from_config выполняет).
- [ ] `python -m swarmline.code_agent --help` exit 0 (M: subprocess test).
- [ ] 6 новых тестов зелёные (2 unit + 3 integration + 1 CLI E2E).
- [ ] Coverage `src/swarmline/code_agent/` ≥ 95% (core SDK — RULES.md: «core/business 95%+») (T: `pytest --cov=swarmline.code_agent --cov-fail-under=95`).
- [ ] Все 4263+ старых тестов зелёные.
- [ ] `ruff check` + `ty check` clean.

**Code rules:** SOLID (CodeAgent — фасад/SRP, ThinRuntime — двигатель/SRP). DRY (defaults в одном месте — `from_config`). ISP (RuntimeConfig поля Optional не нарушает существующие интерфейсы). YAGNI (на permission/question — только signature, реализация в Stage 4/8).

---

<!-- mb-stage:4 -->
### Stage 4: P0-C — Аудит coding_toolpack + `apply_patch` + `todo` tools

**Goal:** Привести `coding_toolpack.py` к каноническому набору: `read`, `write`, `edit`, `glob`, **`apply_patch`** (новый), **`todo`** (новый), `bash`, `grep`. Каждый tool — async, ISP-friendly, с docstring для LLM.

**What to do:**
- [ ] **Step 3.0: Pre-flight — наличие `swarmline.todo` модуля**
  - Команда: `ls src/swarmline/todo/ 2>/dev/null && grep -rn "def add\|def list\|def complete" src/swarmline/todo/ | head`.
  - Если модуль существует с CRUD API → todo tool делегирует туда (зафиксировать в notes).
  - Если модуля нет → добавить minimal in-process store как **staged stub** (RULES.md разрешает: «Stub = полная реализация Protocol + docstring»). Создать `swarmline.todo.InMemoryTodoStore` за feature flag `enable_todo=True` в config.
  - Документировать решение в `notes/2026-05-05_todo-tool-decision.md`.
- [ ] **Step 3.1: Аудит существующих tools**
  - Прочитать `src/swarmline/runtime/thin/coding_toolpack.py:1-200`, составить таблицу: `{tool_name: signature, has_dry_run, has_max_size}`.
  - Записать в `notes/2026-05-05_coding-toolpack-audit.md`.
  - Команда: `grep -n "@tool\|def " src/swarmline/runtime/thin/coding_toolpack.py`.
- [ ] **Step 3.2: Write failing test для `apply_patch` dry-run**
  ```python
  # tests/unit/runtime/thin/test_apply_patch.py
  import pytest
  from swarmline.runtime.thin.coding_toolpack import apply_patch

  @pytest.mark.asyncio
  async def test_apply_patch_dry_run_does_not_write(tmp_path):
      target = tmp_path / "x.py"
      target.write_text("hello\n")
      diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-hello\n+world\n"
      result = await apply_patch(path=str(target), diff=diff, dry_run=True)
      assert target.read_text() == "hello\n"
      assert result["would_apply"] is True
  ```
  Expected: `FAIL — ImportError: cannot import name 'apply_patch'`.
- [ ] **Step 3.3: Write failing test для `apply_patch` real apply**
  ```python
  @pytest.mark.asyncio
  async def test_apply_patch_real_apply_modifies_file(tmp_path):
      target = tmp_path / "x.py"
      target.write_text("hello\n")
      diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-hello\n+world\n"
      result = await apply_patch(path=str(target), diff=diff, dry_run=False)
      assert target.read_text() == "world\n"
      assert result["applied"] is True
  ```
- [ ] **Step 3.4: Write failing test edge cases для `apply_patch`**
  - `test_apply_patch_invalid_diff_returns_error`: invalid hunk → `{"error": "..."}`, файл не меняется.
  - `test_apply_patch_target_does_not_exist`: файла нет → ошибка.
  - `test_apply_patch_offset_mismatch`: hunk не совпадает по контексту → ошибка с подсказкой.
- [ ] **Step 3.5: Реализация `apply_patch`**
  - В `coding_toolpack.py` добавить `@tool async def apply_patch(path: str, diff: str, dry_run: bool = False) -> dict`.
  - Использовать `difflib.unified_diff` обратно через парсер (или мини-парсер unified diff). Для dry-run — только верификация, что hunks применяются.
  - Atomic write: писать в `path.tmp`, потом `os.replace`.
  - Запустить тесты 3.2-3.4 → `PASS`.
- [ ] **Step 3.6: Write failing tests для `todo` tool (CRUD)**
  ```python
  # tests/unit/runtime/thin/test_todo_tool.py
  @pytest.mark.asyncio
  async def test_todo_add_returns_id_and_persists():
      from swarmline.runtime.thin.coding_toolpack import todo
      r = await todo(action="add", text="fix typo")
      assert r["id"]
      lst = await todo(action="list")
      assert any(t["text"] == "fix typo" for t in lst["items"])

  @pytest.mark.asyncio
  async def test_todo_complete_marks_done():
      from swarmline.runtime.thin.coding_toolpack import todo
      a = await todo(action="add", text="x")
      await todo(action="complete", id=a["id"])
      lst = await todo(action="list", status="done")
      assert any(t["id"] == a["id"] and t["status"] == "done" for t in lst["items"])
  ```
  Expected: `FAIL`.
- [ ] **Step 3.7: Реализация `todo` tool**
  - `@tool async def todo(action: Literal["add","list","complete","remove","clear"], text: str | None = None, id: str | None = None, status: str | None = None) -> dict`.
  - Persistence per-session: использовать существующий `swarmline.todo` модуль (см. `src/swarmline/todo/`); если нет API — добавить minimal in-process store с docstring «session-local TODO list».
  - Запустить тесты 3.6 → `PASS`.
- [ ] **Step 3.8: Регистрация новых tools в default toolset**
  - `coding_toolpack.py` экспортирует список `CODING_TOOLS = (read, write, edit, glob, apply_patch, todo, bash, grep)`.
  - `CodeAgent` использует `CODING_TOOLS` если `tools=None`.
- [ ] **Step 3.9: Integration test «edit through apply_patch via CodeAgent»**
  ```python
  # tests/integration/code_agent/test_apply_patch_via_facade.py
  @pytest.mark.asyncio
  async def test_code_agent_uses_apply_patch_tool(tmp_path, fake_llm_with_apply_patch_call):
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_with_apply_patch_call)
      target = tmp_path / "f.txt"
      target.write_text("a\n")
      events = [ev async for ev in agent.run("change a to b in f.txt")]
      assert target.read_text() == "b\n"
  ```
- [ ] **Step 3.10: Commit**
  - `git commit -m "feat(coding_toolpack): apply_patch + todo tools (P0-C)"`

**Testing (TDD):**
- Unit: 4 тестов на `apply_patch` (dry-run, apply, invalid diff, missing file, offset mismatch); 4 на `todo` (add/list/complete/remove).
- Integration: `CodeAgent` использует `apply_patch` end-to-end с fake LLM.
- Edge cases: пустой diff, multi-hunk diff, бинарный файл (должен отказаться).

**DoD (SMART):**
- [ ] `apply_patch` tool работает (dry-run + apply) (S: signature defined, M: 5 tests pass).
- [ ] `todo` tool — full CRUD (M: 4 tests pass).
- [ ] `CODING_TOOLS` экспорт содержит 8 tools (S: explicit list).
- [ ] Coverage `coding_toolpack.py` ≥ 90%.
- [ ] Backward compat: 4263+ зелёные.
- [ ] `ruff` + `ty` clean.

**Code rules:** ISP (каждый tool — одна функция, одна ответственность). KISS (todo — minimal CRUD, не отдельный backend). DRY (atomic write helper переиспользовать с существующим `write` tool).

---

<!-- mb-stage:5 -->
### Stage 5: P0-E — `on_permission_request` async callback

**Goal:** В `CodeAgent` добавить `on_permission_request: Callable[[tool, args], Awaitable[Allow | Deny | AskUser]]`. Отдельно от существующего `DefaultToolPolicy` — это user-facing async hook, который запускается **до** policy enforcement.

**What to do:**
- [ ] **Step 4.1: Импорт Permission types из Stage 1 protocols**
  - Удалить локальный `src/swarmline/code_agent/_permissions.py` (если был создан).
  - В `_facade.py`: `from swarmline.code_agent.protocols import Allow, Deny, AskUser, PermissionDecision`.
  - Это переиспользование Contract-First типов из Stage 1, не дубль (DRY).
- [ ] **Step 4.2: Write failing test «callback Allow → tool runs»**
  ```python
  # tests/integration/code_agent/test_permission_callback.py
  @pytest.mark.asyncio
  async def test_permission_callback_allow_lets_tool_execute(tmp_path, fake_llm_calls_write):
      called = []
      async def cb(tool, args):
          called.append((tool, args))
          return Allow()
      agent = CodeAgent(model="fake", cwd=str(tmp_path),
                        llm_client=fake_llm_calls_write,
                        on_permission_request=cb)
      events = [ev async for ev in agent.run("write hi to a.txt")]
      assert (tmp_path / "a.txt").exists()
      assert len(called) == 1 and called[0][0] == "write"
  ```
  Expected: `FAIL — TypeError: unexpected keyword argument 'on_permission_request'`.
- [ ] **Step 4.3: Write failing test «callback Deny → tool blocked, event emitted»**
  ```python
  @pytest.mark.asyncio
  async def test_permission_callback_deny_blocks_tool(tmp_path, fake_llm_calls_write):
      async def cb(tool, args):
          return Deny(reason="not allowed in test")
      agent = CodeAgent(model="fake", cwd=str(tmp_path),
                        llm_client=fake_llm_calls_write,
                        on_permission_request=cb)
      events = [ev async for ev in agent.run("write hi to a.txt")]
      assert not (tmp_path / "a.txt").exists()
      assert any(getattr(ev, "type", None) == "tool_denied" for ev in events)
  ```
- [ ] **Step 4.4: Write failing test «callback AskUser → SDK gets prompt»**
  ```python
  @pytest.mark.asyncio
  async def test_permission_callback_ask_user_yields_prompt_event(tmp_path, fake_llm_calls_write):
      async def cb(tool, args):
          return AskUser(prompt=f"Run {tool}?")
      agent = CodeAgent(model="fake", cwd=str(tmp_path),
                        llm_client=fake_llm_calls_write,
                        on_permission_request=cb)
      events = [ev async for ev in agent.run("write hi")]
      assert any(getattr(ev, "type", None) == "permission_ask" for ev in events)
  ```
- [ ] **Step 4.5: Реализация callback wiring**
  - `src/swarmline/code_agent/_facade.py`: добавить параметр `on_permission_request` в `__init__`.
  - В `_facade._run_tool_with_permission(tool_call)`: вызвать callback **перед** `DefaultToolPolicy.check`. На `Deny` — emit `ToolDenied` event, skip exec. На `AskUser` — emit `PermissionAsk` event, ждать `agent.respond_to_permission(...)` (для синхронного теста — ввести Future).
  - Добавить новые event types в `swarmline/runtime/types.py`: `ToolDeniedEvent`, `PermissionAskEvent` (frozen dataclass).
  - Тесты 4.2–4.4 → `PASS`.
- [ ] **Step 4.6: Composition с `DefaultToolPolicy`**
  - Если callback вернул `Allow` — далее всё равно проходит `DefaultToolPolicy` (default-deny). Это второй уровень защиты.
  - Test: `test_permission_callback_allow_but_policy_denies_blocks_tool` — callback Allow, policy deny → tool не запускается.
- [ ] **Step 4.7: Type-check**
  - `ty check src/swarmline/code_agent/`.
- [ ] **Step 4.8: Commit**
  - `git commit -m "feat(code_agent): on_permission_request async callback (P0-E)"`

**Testing (TDD):**
- Unit: callback signature вызывается с `(tool_name, args_dict)`.
- Integration: 4 теста — Allow, Deny, AskUser, Allow+PolicyDeny.
- Edge cases: callback throws → wrapped в `PermissionCallbackError`, tool blocked.

**DoD (SMART):**
- [ ] Callback вызывается перед каждым tool exec (M: assertion в test).
- [ ] 3 решения (Allow/Deny/AskUser) работают (M: 4 tests pass).
- [ ] Callback композиция с `DefaultToolPolicy` корректна (M: composition test).
- [ ] Coverage `_permissions.py` = 100% (T).
- [ ] Backward compat: 4263+ + Stage 2-4 тесты зелёные.

**Code rules:** ISP (`PermissionDecision` — sealed union, 3 варианта). DIP (callback — абстракция, реализация в SDK consumer). YAGNI (не добавляем cache/persist решений в этом этапе).

---

<!-- mb-stage:6 -->
### Stage 6: P0-K1 + K2 + K3 — Session lifecycle (auto-save/resume/reset/metadata)

**Goal:** Каждый `CodeAgent` имеет `session_id` (auto UUID4), автосохраняется после каждого turn в `~/.swarmline/sessions/<id>/` поверх `swarmline.memory.sqlite`. `CodeAgent.resume(id)` восстанавливает state. `agent.reset()` / `agent.clear_history(keep=...)` чистят. Метаданные: title (из первого prompt — 60 chars), cwd, git branch (auto-detect), created_at, last_used_at, status, turn_count.

**What to do:**
- [ ] **Step 5.1: Schema sessions metadata**
  ```python
  # src/swarmline/code_agent/_session.py
  from dataclasses import dataclass, field
  from datetime import datetime, timezone
  import uuid

  @dataclass(frozen=True)
  class SessionMetadata:
      session_id: str
      title: str
      cwd: str
      git_branch: str | None
      created_at: datetime
      last_used_at: datetime
      status: Literal["active", "paused", "done"]
      turn_count: int
  ```
- [ ] **Step 5.2: Write failing test «agent has auto session_id»**
  ```python
  # tests/integration/code_agent/test_session_lifecycle.py
  @pytest.mark.asyncio
  async def test_code_agent_has_auto_session_id(tmp_path):
      agent = CodeAgent(model="fake", cwd=str(tmp_path))
      assert agent.session_id
      uuid.UUID(agent.session_id)  # validates UUID4
  ```
- [ ] **Step 5.3: Write failing test «auto-save после turn»**
  ```python
  @pytest.mark.asyncio
  async def test_auto_save_persists_after_each_turn(tmp_path, fake_llm_simple, monkeypatch):
      monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple)
      _ = [ev async for ev in agent.run("hi")]
      session_dir = tmp_path / "sessions" / agent.session_id
      assert session_dir.exists()
      assert (session_dir / "messages.sqlite").exists()
      assert (session_dir / "meta.json").exists()
  ```
- [ ] **Step 5.4: Write failing test «resume сохраняет history»**
  ```python
  @pytest.mark.asyncio
  async def test_resume_restores_message_history(tmp_path, fake_llm_simple, monkeypatch):
      monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))
      a = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple)
      _ = [ev async for ev in a.run("hi")]
      sid = a.session_id
      await a.close()

      b = CodeAgent.resume(sid, llm_client=fake_llm_simple)
      assert b.session_id == sid
      assert b.cwd == str(tmp_path)
      assert b.turn_count == 1
      assert len(b.messages) >= 2  # user + assistant
  ```
- [ ] **Step 5.5: Реализация storage layer**
  - `src/swarmline/code_agent/_session.py` — `SessionStore` ISP-protocol (≤ 5 methods): `save_meta`, `load_meta`, `list_metas`, `delete`, `archive`.
  - Implementation `SqliteSessionStore`: использует существующий `swarmline.memory.sqlite.SqliteMessageStore` для messages + новый `meta.json` (или `meta.sqlite` table) для metadata.
  - Default location: `~/.swarmline/sessions/<id>/` (override через `SWARMLINE_SESSIONS_DIR` env).
- [ ] **Step 5.6: Auto-save hook**
  - `CodeAgent._on_turn_complete()` вызывается после каждого turn → `SessionStore.save_meta` + `MessageStore.append_messages` + bump `turn_count` + update `last_used_at`.
- [ ] **Step 5.7: Реализация `CodeAgent.resume(session_id)`**
  - Classmethod: `cls.resume(session_id: str, **deps) -> CodeAgent`.
  - Загружает meta + messages, реконструирует `CodeAgent` с тем же `cwd`/`session_id`.
- [ ] **Step 5.8: Write failing test для `agent.reset()`**
  ```python
  @pytest.mark.asyncio
  async def test_reset_clears_history_keeps_session_id_and_cwd(tmp_path, fake_llm_simple):
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple)
      _ = [ev async for ev in agent.run("hi")]
      sid_before = agent.session_id
      cwd_before = agent.cwd
      agent.reset()
      assert agent.session_id == sid_before
      assert agent.cwd == cwd_before
      assert len(agent.messages) == 0
      assert agent.turn_count == 0
  ```
- [ ] **Step 5.9: Write failing test для `agent.clear_history(keep=["system","agents_md"])`**
  ```python
  @pytest.mark.asyncio
  async def test_clear_history_keeps_specified_categories(tmp_path, fake_llm_simple):
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple,
                        system_prompt="You are coder", agents_md="# Project rules\n...")
      _ = [ev async for ev in agent.run("hi")]
      agent.clear_history(keep=["system", "agents_md"])
      kinds = {m.role for m in agent.messages}
      assert "system" in kinds
      assert "user" not in kinds
      assert "assistant" not in kinds
  ```
- [ ] **Step 5.10: Реализация `reset` / `clear_history`**
  - `reset()` — clears `self._messages`, `self._turn_count`, persists empty session.
  - `clear_history(keep: list[str])` — фильтрует `self._messages` сохраняя `role in keep` или сообщения с meta.kind in keep.
- [ ] **Step 5.11: Write test «metadata: title auto-generated from first prompt»**
  ```python
  @pytest.mark.asyncio
  async def test_session_title_auto_from_first_prompt(tmp_path, fake_llm_simple):
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple)
      _ = [ev async for ev in agent.run("Implement OAuth2 login flow with refresh tokens please")]
      meta = agent.session_meta()
      assert meta.title.startswith("Implement OAuth2 login flow")
      assert len(meta.title) <= 60
  ```
- [ ] **Step 5.12: Write test «metadata: git branch auto-detected»**
  ```python
  @pytest.mark.asyncio
  async def test_session_git_branch_auto_detected(tmp_path, fake_llm_simple):
      import subprocess
      subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
      subprocess.run(["git", "checkout", "-b", "feat/x", "-q"], cwd=tmp_path, check=True)
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple)
      _ = [ev async for ev in agent.run("hi")]
      assert agent.session_meta().git_branch == "feat/x"
  ```
- [ ] **Step 5.13: Реализация title/branch detection**
  - Title: первые 60 chars первого user prompt, strip, без переносов.
  - Branch: `subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, capture_output=True)`. Если `returncode != 0` → `None`.
- [ ] **Step 5.14: Crash-resume scenario test (E2E)**
  ```python
  @pytest.mark.asyncio
  async def test_kill_then_resume_continues_from_last_turn(tmp_path, fake_llm_simple, monkeypatch):
      monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path / "sessions"))
      a = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple)
      _ = [ev async for ev in a.run("turn 1")]
      _ = [ev async for ev in a.run("turn 2")]
      sid = a.session_id
      del a  # simulate crash, no .close()

      b = CodeAgent.resume(sid, llm_client=fake_llm_simple)
      assert b.turn_count == 2
      _ = [ev async for ev in b.run("turn 3")]
      assert b.turn_count == 3
  ```
- [ ] **Step 5.15: Commit**
  - `git commit -m "feat(code_agent): session lifecycle — auto-save, resume, reset, metadata (P0-K1, K2, K3)"`

**Testing (TDD):**
- Unit: `SessionMetadata` dataclass, title truncation, branch detect (mock subprocess).
- Integration: 8 тестов — auto session_id, auto-save, resume, reset, clear_history, title auto, branch auto, kill+resume.
- Edge cases: cwd без git → branch=None; пустой prompt → title="(empty)"; concurrent agents в одной cwd → разные session_ids.

**DoD (SMART):**
- [ ] `agent.session_id` авто-UUID (S).
- [ ] После каждого turn — persisted state в `~/.swarmline/sessions/<id>/` (M: file exists).
- [ ] `CodeAgent.resume(id)` возвращает agent с теми же messages/cwd/turn_count (M: 1 test).
- [ ] `agent.reset()` + `clear_history(keep=...)` работают (M: 2 tests).
- [ ] Все 4 поля metadata авто (title, cwd, branch, status) (M: 2 tests).
- [ ] Crash-resume scenario работает (M: E2E test).
- [ ] Backward compat: 4263+ зелёные.
- [ ] Coverage `_session.py` ≥ 95%.

**Code rules:** ISP (`SessionStore` ≤ 5 methods). DIP (`SessionStore` — protocol, sqlite — реализация). DRY (переиспользуем `SqliteMessageStore`). KISS (meta.json вместо отдельной таблицы).

---

<!-- mb-stage:7 -->
### Stage 7: P0-AA + AB + AC — Truncation continuation + reactive compaction + preflight check

**Goal:** Агент **переживает длинную сессию**:
- AA: при `finish_reason == "length"` агент авто-делает continuation (повторный API call с history + last partial assistant).
- AB: при `prompt_too_long` ошибке провайдера — авто-compact старых turns и retry.
- AC: преflight char/4 эвристика для prompt-length, soft-warn / hard-block с экономией денег.

**What to do:**
- [ ] **Step 6.1: Write failing test для truncation continuation**
  ```python
  # tests/integration/code_agent/test_truncation_continuation.py
  @pytest.mark.asyncio
  async def test_finish_reason_length_triggers_continuation(tmp_path, fake_llm_truncated_first_call):
      # fake_llm_truncated_first_call: 1й call returns finish_reason="length" with partial text "abc",
      # 2й call returns finish_reason="stop" with continuation "def"
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_truncated_first_call)
      events = [ev async for ev in agent.run("write a story")]
      texts = [e.text for e in events if hasattr(e, "text")]
      assert "abcdef" in "".join(texts)
  ```
  Expected: `FAIL` (continuation не реализован).
- [ ] **Step 6.2: Реализация continuation в `runtime/thin/runtime.py`**
  - В цикле обработки assistant message: после получения response проверять `finish_reason`. Если `"length"` — append assistant partial в history, повторный API call. Loop с max retries (default 3).
  - Лимит retries в `RuntimeConfig.max_continuation_retries: int = 3`.
  - Тест 6.1 → `PASS`.
- [ ] **Step 6.3: Write failing test для reactive compaction**
  ```python
  # tests/integration/code_agent/test_reactive_compaction.py
  @pytest.mark.asyncio
  async def test_prompt_too_long_error_triggers_compaction_and_retry(tmp_path, fake_llm_overflow_then_ok):
      # fake_llm_overflow_then_ok: 1й call raises PromptTooLongError, 2й call (post-compact) returns "ok"
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_overflow_then_ok)
      # fill history с 30 turns
      for i in range(30):
          _ = [ev async for ev in agent.run(f"turn {i}")]
      events = [ev async for ev in agent.run("trigger overflow")]
      assert any(getattr(ev, "type", None) == "compaction_triggered" for ev in events)
      assert any(hasattr(ev, "text") and "ok" in ev.text for ev in events)
  ```
- [ ] **Step 6.4: Реализация reactive compaction**
  - Поймать `PromptTooLongError` (или эквивалент по провайдеру) в `runtime.py`.
  - Использовать существующий `swarmline.compaction.Compactor` (см. `src/swarmline/compaction.py`). Сжимаем старые messages (keep last 5 + summary).
  - Emit `CompactionTriggeredEvent`.
  - Retry 1 раз. Если снова overflow → fail с понятной ошибкой.
- [ ] **Step 6.5: Write failing test для preflight check**
  ```python
  # tests/unit/code_agent/test_preflight_check.py
  def test_preflight_estimates_tokens_chars_div_4():
      from swarmline.code_agent._preflight import estimate_tokens
      assert estimate_tokens("a" * 4000) == 1000

  @pytest.mark.asyncio
  async def test_preflight_soft_warn_emits_event_when_above_80pct(tmp_path, fake_llm_simple):
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple,
                        context_window=1000, preflight_soft_warn_pct=80)
      huge = "x" * 3500  # ~875 tokens, 87.5%
      events = [ev async for ev in agent.run(huge)]
      assert any(getattr(ev, "type", None) == "preflight_warn" for ev in events)

  @pytest.mark.asyncio
  async def test_preflight_hard_block_when_above_100pct(tmp_path, fake_llm_simple):
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple,
                        context_window=1000)
      huge = "x" * 5000  # ~1250 tokens, 125%
      with pytest.raises(PromptTooLongError):
          _ = [ev async for ev in agent.run(huge)]
  ```
- [ ] **Step 6.6: Реализация `_preflight.py`**
  - Функция `estimate_tokens(text: str) -> int = len(text) // 4`.
  - В `CodeAgent.run()`: до API call считаем total tokens (history + new prompt). Soft-warn (default 80%) → emit `PreflightWarnEvent`. Hard-block (≥100%) → raise `PromptTooLongError` без API call.
  - Поля в `RuntimeConfig`: `context_window: int | None = None`, `preflight_soft_warn_pct: int = 80`, `preflight_hard_block: bool = True`.
- [ ] **Step 6.7: Long-session integration test (50+ turns)**
  ```python
  # tests/integration/code_agent/test_long_session_survival.py
  @pytest.mark.slow
  @pytest.mark.asyncio
  async def test_50_turns_no_crash(tmp_path, fake_llm_simple):
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple,
                        context_window=8000)
      for i in range(55):
          events = [ev async for ev in agent.run(f"turn {i}: " + "x" * 100)]
          assert not any(getattr(ev, "type", None) == "error" for ev in events)
      assert agent.turn_count == 55
  ```
- [ ] **Step 6.8: Commit**
  - `git commit -m "feat(code_agent): truncation continuation + reactive compaction + preflight check (P0-AA, AB, AC)"`

**Testing (TDD):**
- Unit: `estimate_tokens` (3 тестов: empty, ascii, multibyte).
- Integration: 5 тестов — continuation, reactive compact, preflight soft warn, preflight hard block, 50-turn survival.
- Edge cases: continuation бесконечный loop (clamp на `max_continuation_retries`); compaction после которой всё равно overflow → user-friendly error; soft-warn при `context_window=None` → no-op.

**DoD (SMART):**
- [ ] `finish_reason="length"` → continuation, итоговый текст полный (M: 1 test).
- [ ] `PromptTooLongError` → compaction + retry, событие emitted (M: 1 test).
- [ ] Preflight soft/hard работает (M: 2 tests).
- [ ] 50-turn long-session test зелёный (T: integration, slow marker).
- [ ] Coverage `_preflight.py` = 100%.
- [ ] Backward compat: 4263+ зелёные.

**Code rules:** SOLID (continuation/compaction/preflight — 3 разных модуля). DRY (переиспользуем `swarmline.compaction.Compactor`). KISS (preflight через char/4, не tokenizer). Strangler Fig: новые поля Optional, никаких breaking changes.

---

<!-- mb-stage:8 -->
### Stage 8: P0-AD + AE — File-tool safety guards + bash destructive warning

**Goal:** Агент **не сжигает workspace и не читает системные файлы**.
- AD: file safety — binary detection (NUL byte heuristic), max read/write size (default 5MB), workspace boundary, symlink escape detection (`os.path.realpath` outside cwd).
- AE: bash destructive — regex для `rm -rf`, `git push --force`, `drop database`, `dd of=`.

**What to do:**
- [ ] **Step 7.1: Write failing tests для file safety**
  ```python
  # tests/security/test_file_safety.py
  import pytest
  from swarmline.runtime.thin.coding_toolpack import read

  @pytest.mark.security
  @pytest.mark.asyncio
  async def test_read_blocks_binary_file(tmp_path):
      f = tmp_path / "bin.dat"
      f.write_bytes(b"abc\x00def")
      r = await read(path=str(f), workspace_cwd=str(tmp_path))
      assert r["error"] == "binary_file_detected"

  @pytest.mark.security
  @pytest.mark.asyncio
  async def test_read_blocks_outside_workspace(tmp_path):
      outside = tmp_path.parent / "outside.txt"
      outside.write_text("secret")
      r = await read(path=str(outside), workspace_cwd=str(tmp_path))
      assert r["error"] == "outside_workspace"

  @pytest.mark.security
  @pytest.mark.asyncio
  async def test_read_blocks_symlink_escape(tmp_path):
      target = tmp_path.parent / "secret.txt"
      target.write_text("X")
      link = tmp_path / "link.txt"
      link.symlink_to(target)
      r = await read(path=str(link), workspace_cwd=str(tmp_path))
      assert r["error"] == "symlink_escape"

  @pytest.mark.security
  @pytest.mark.asyncio
  async def test_read_blocks_oversized_file(tmp_path):
      big = tmp_path / "big.txt"
      big.write_bytes(b"x" * (6 * 1024 * 1024))  # 6 MB
      r = await read(path=str(big), workspace_cwd=str(tmp_path), max_size=5 * 1024 * 1024)
      assert r["error"] == "file_too_large"
  ```
- [ ] **Step 7.2: Реализация safety helpers**
  - `src/swarmline/runtime/thin/_file_safety.py`:
    ```python
    def is_binary(path: Path, sniff_bytes: int = 8192) -> bool:
        with path.open("rb") as f:
            return b"\x00" in f.read(sniff_bytes)

    def is_inside_workspace(path: Path, cwd: Path) -> bool:
        real = path.resolve()
        return real == cwd.resolve() or cwd.resolve() in real.parents

    def check_read_safety(path: str, workspace_cwd: str, max_size: int = 5*1024*1024) -> str | None:
        # returns error code or None
        ...
    ```
- [ ] **Step 7.3: Wire safety в `read` / `write` / `edit` / `apply_patch` tools**
  - В `coding_toolpack.py` каждая mutating операция получает `workspace_cwd` (через context-var или explicit param).
  - На каждом call → `check_read_safety(...)` / `check_write_safety(...)` → если error → return `{"error": ...}`.
  - `CodeAgent` пробрасывает `cwd` как `workspace_cwd` через context-var (`contextvars.ContextVar("swarmline_workspace_cwd")`).
- [ ] **Step 7.4: Write failing tests для bash safety**
  ```python
  # tests/security/test_bash_safety.py
  import pytest
  from swarmline.runtime.thin.coding_toolpack import bash

  @pytest.mark.security
  @pytest.mark.parametrize("cmd", [
      "rm -rf /",
      "rm -rf $HOME",
      "rm -rf ~",
      "git push --force",
      "git push -f origin main",
      "drop database production",
      "DROP DATABASE foo",
      "dd if=/dev/zero of=/dev/sda",
  ])
  @pytest.mark.asyncio
  async def test_bash_blocks_destructive_commands(cmd, tmp_path):
      r = await bash(command=cmd, workspace_cwd=str(tmp_path))
      assert r["error"] == "destructive_command_blocked"
      assert r.get("matched_pattern")

  @pytest.mark.security
  @pytest.mark.parametrize("cmd", [
      "rm -rf node_modules",  # local cleanup ok
      "git push origin main",  # non-force
      "ls -la",
  ])
  @pytest.mark.asyncio
  async def test_bash_allows_safe_commands(cmd, tmp_path):
      r = await bash(command=cmd, workspace_cwd=str(tmp_path))
      assert r.get("error") != "destructive_command_blocked"
  ```
- [ ] **Step 7.5: Реализация bash safety**
  - `src/swarmline/runtime/thin/_bash_safety.py`:
    ```python
    DESTRUCTIVE_PATTERNS = [
        r"\brm\s+-[rRf]+\s+(/|~|\$HOME|/?\*)",
        r"\bgit\s+push\s+(-[fF]|--force)",
        r"\bdrop\s+database\b",
        r"\bdd\s+.*of=/dev/",
    ]
    ```
  - Функция `check_destructive(cmd: str) -> tuple[bool, str | None]`.
  - Поведение: default block. Override через `RuntimeConfig.bash_allow_destructive: bool = False`.
- [ ] **Step 7.6: Wire bash safety в bash tool**
  - На входе → `check_destructive`. Если match и `bash_allow_destructive=False` → return error.
- [ ] **Step 7.7: E2E security test через CodeAgent**
  ```python
  # tests/security/test_code_agent_safety_e2e.py
  @pytest.mark.security
  @pytest.mark.asyncio
  async def test_agent_blocks_rm_rf_home(tmp_path, fake_llm_calls_rm_rf):
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_calls_rm_rf)
      events = [ev async for ev in agent.run("clean up everything")]
      assert any(getattr(ev, "type", None) == "tool_blocked" for ev in events)
      assert tmp_path.exists()  # workspace untouched
  ```
- [ ] **Step 7.8: Commit**
  - `git commit -m "feat(code_agent): file/bash safety guards (P0-AD, P0-AE)"`

**Testing (TDD):**
- Security tests (`@pytest.mark.security`): 4 file safety + 8 bash patterns (parametrize) + 3 safe-bash + 1 E2E.
- Edge cases: symlink на саму cwd → ok; relative path traversal `../../etc/passwd` → blocked; пустая команда → ok.

**DoD (SMART):**
- [ ] 4 file safety errors (binary, outside, symlink, oversized) (M: 4 tests).
- [ ] ≥ 4 destructive bash patterns blocked (M: parametrize).
- [ ] E2E: agent с злонамеренным prompt не сносит workspace (M: 1 test).
- [ ] Coverage `_file_safety.py` + `_bash_safety.py` ≥ 95%.
- [ ] Backward compat: 4263+ зелёные.
- [ ] `pytest -m security` exit 0.

**Code rules:** YAGNI (4 паттерна — не Claude-Code-style 18-submodule матрица). KISS (regex, не AST parser). Defence-in-depth: tool-level + policy-level.

---

<!-- mb-stage:9 -->
### Stage 9: P0-AF + AG + AH — diagnostics tool + question tool + smart truncation

**Goal:**
- AF: `diagnostics` tool — auto-detect project type (`pyproject.toml`/`package.json`/`Cargo.toml`/`go.mod`), shell-out к `ruff`/`tsc`/`cargo check`/`go vet`. Output: `[{file, line, col, severity, message}]`.
- AG: `question` tool + `on_question` callback. Default — «no answer, use best judgment».
- AH: smart tool-output truncation — head/tail с маркером `[N more lines truncated, use offset=X to see more]`, configurable per-tool.

**What to do:**
- [ ] **Step 8.1: Write failing test для project type detection**
  ```python
  # tests/unit/runtime/thin/test_diagnostics.py
  from swarmline.runtime.thin._diagnostics import detect_project_type

  @pytest.mark.parametrize("marker,expected", [
      ("pyproject.toml", "python"),
      ("package.json", "node"),
      ("Cargo.toml", "rust"),
      ("go.mod", "go"),
  ])
  def test_detect_project_type(tmp_path, marker, expected):
      (tmp_path / marker).write_text("")
      assert detect_project_type(tmp_path) == expected

  def test_detect_project_type_unknown(tmp_path):
      assert detect_project_type(tmp_path) is None
  ```
- [ ] **Step 8.2: Write failing test для diagnostics shell-out (Python project)**
  ```python
  @pytest.mark.asyncio
  async def test_diagnostics_python_runs_ruff(tmp_path):
      from swarmline.runtime.thin.coding_toolpack import diagnostics
      (tmp_path / "pyproject.toml").write_text("")
      (tmp_path / "bad.py").write_text("import os\n")  # unused import, F401
      r = await diagnostics(cwd=str(tmp_path))
      assert any(d["file"].endswith("bad.py") and d["severity"] in ("warning","error")
                 for d in r["diagnostics"])
  ```
  Marker: `@pytest.mark.integration` (требует ruff в PATH — он уже dev-dep).
- [ ] **Step 8.3: Реализация `_diagnostics.py`**
  - `detect_project_type(cwd: Path) -> Literal["python","node","rust","go"] | None`.
  - `async def run_diagnostics(cwd: Path) -> list[dict]`:
    - Для python: `subprocess.run(["ruff", "check", "--output-format=json", "."], cwd=cwd)`. Парсим JSON в `[{file,line,col,severity,message}]`.
    - Для node: `tsc --noEmit --pretty=false` (regex parse).
    - Для rust: `cargo check --message-format=json`.
    - Для go: `go vet ./...`.
  - Каждая ветвь: try/except, missing tool → `{"diagnostics": [], "error": "tool_not_installed", "tool": "ruff"}`.
- [ ] **Step 8.4: `diagnostics` tool в `coding_toolpack.py`**
  - `@tool async def diagnostics(cwd: str | None = None) -> dict`. Если cwd None — current workspace_cwd.
  - Добавить в `CODING_TOOLS`.
- [ ] **Step 8.5: Self-verification E2E test**
  ```python
  # tests/integration/code_agent/test_self_verification.py
  @pytest.mark.integration
  @pytest.mark.asyncio
  async def test_agent_edits_then_runs_diagnostics_then_fixes(tmp_path, fake_llm_self_verify_loop):
      # fake LLM: turn1 = edit(bad.py), turn2 = diagnostics, turn3 = edit again to fix, turn4 = diagnostics clean
      (tmp_path / "pyproject.toml").write_text("")
      (tmp_path / "bad.py").write_text("import os\n")
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_self_verify_loop)
      events = [ev async for ev in agent.run("fix lint in bad.py")]
      # final diagnostics call returns []
      assert "import os" not in (tmp_path / "bad.py").read_text()
  ```
- [ ] **Step 8.6: Write failing test для `question` tool**
  ```python
  # tests/integration/code_agent/test_question_tool.py
  @pytest.mark.asyncio
  async def test_question_tool_invokes_on_question_callback(tmp_path, fake_llm_calls_question):
      answers = []
      async def on_q(prompt):
          answers.append(prompt)
          return "use python 3.11"
      agent = CodeAgent(model="fake", cwd=str(tmp_path),
                        llm_client=fake_llm_calls_question, on_question=on_q)
      _ = [ev async for ev in agent.run("which python version?")]
      assert answers == ["which python version?"]

  @pytest.mark.asyncio
  async def test_question_tool_default_returns_no_answer(tmp_path, fake_llm_calls_question):
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_calls_question)
      events = [ev async for ev in agent.run("ambiguous prompt")]
      # tool result back to LLM = "no answer; use best judgment"
      assert any("best judgment" in str(getattr(e, "result", "")) for e in events)
  ```
- [ ] **Step 8.7: Реализация `question` tool**
  - `@tool async def question(prompt: str) -> dict`. Доступ к callback через context-var, установленный `CodeAgent`.
  - Default callback: `async def _default_on_question(p): return None` → tool returns `{"answer": None, "guidance": "no answer; use best judgment"}`.
- [ ] **Step 8.8: Write failing test для smart truncation**
  ```python
  # tests/unit/runtime/thin/test_smart_truncation.py
  from swarmline.runtime.thin._truncation import smart_truncate

  def test_smart_truncate_keeps_head_and_tail():
      lines = [f"line {i}" for i in range(1000)]
      out = smart_truncate("\n".join(lines), max_lines=20)
      assert out.startswith("line 0")
      assert "line 999" in out
      assert "[980 more lines truncated" in out

  def test_smart_truncate_short_input_unchanged():
      out = smart_truncate("a\nb\nc", max_lines=20)
      assert out == "a\nb\nc"

  def test_smart_truncate_offset_marker_format():
      out = smart_truncate("\n".join(str(i) for i in range(100)), max_lines=10)
      assert "use offset=" in out
  ```
- [ ] **Step 8.9: Реализация `_truncation.py`**
  - `smart_truncate(text: str, max_lines: int = 100, head: int = 50, tail: int = 50, offset_token: str = "use offset={n} to see more") -> str`.
  - Wire в `bash`/`grep`/`read` tools (per-tool max_lines override).
- [ ] **Step 8.10: Commit**
  - `git commit -m "feat(code_agent): diagnostics tool + question tool + smart truncation (P0-AF, AG, AH)"`

**Testing (TDD):**
- Unit: `detect_project_type` parametrize (5 cases); `smart_truncate` (3 tests).
- Integration: ruff shell-out (Python project); fake LLM self-verify loop; question callback invoked / default fallback.
- Edge cases: ruff не установлен → `error: tool_not_installed`; multi-language project (python + node) → берём первый match по приоритету.

**DoD (SMART):**
- [ ] `diagnostics` tool работает на Python project (M: ruff parse).
- [ ] Self-verification E2E loop: edit → diagnostics → fix → diagnostics clean (M: 1 integration test).
- [ ] `question` tool + callback (M: 2 tests).
- [ ] Smart truncation сохраняет head+tail+marker (M: 3 unit tests).
- [ ] Coverage `_diagnostics.py` ≥ 90%, `_truncation.py` = 100%.
- [ ] Backward compat: 4263+ зелёные.

**Code rules:** ISP (`question`/`diagnostics` — отдельные tools, разные ответственности). KISS (4 ветки project-type, без plugin system). DIP (`on_question` — абстрактный callback, default = no-op).

---

<!-- mb-stage:10 -->
### Stage 10: P0-D + F + G — AgentMessage + convertToLlm seam (Strangler Fig) + mid-run hooks + tool_execution mode

**Goal:** Самое инвазивное P0. Strangler Fig migration:
- D: `AgentMessage` — новый тип параллельно со старым `Message`. Поддерживает `user`/`assistant`/`tool_result` + UI `notification`/`status`. `convert_to_llm` callback решает, какие AgentMessage уходят в LLM-историю.
- F: mid-run hooks в `RuntimeConfig`: `should_stop_after_turn`, `get_steering_messages`, `get_followup_messages`, `transform_context`.
- G: `tool_execution: Literal["sequential","parallel"]` — sequential по умолчанию, parallel опционально.

**What to do:**
- [ ] **Step 10.0: Verify Stage 1 contracts применимы**
  - Проверить, что `LifecycleHooks` Protocol из `src/swarmline/code_agent/protocols.py` совпадает по форме с тем, что нужно в этой стадии.
  - Если расхождения — обновить Stage 1 protocols **через ADR** (не silently). Если совпадает — продолжать.
  - Команда: `pytest tests/contract/code_agent/ -v` — должно остаться зелёным.
- [ ] **Step 9.1: Define `AgentMessage` параллельно с `Message`**
  - **Примечание:** `LifecycleHooks` уже определён в Stage 1 protocols (`src/swarmline/code_agent/protocols.py`); переиспользуем его, не дублируем (DRY).
  ```python
  # src/swarmline/code_agent/_messages.py
  @dataclass(frozen=True)
  class AgentMessage:
      kind: Literal["user", "assistant", "tool_result", "notification", "status"]
      content: str
      meta: dict[str, Any] = field(default_factory=dict)
      timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
  ```
- [ ] **Step 9.2: Write failing test «AgentMessage не ломает старый Message API»**
  ```python
  # tests/unit/code_agent/test_agent_message.py
  def test_agent_message_to_llm_default_skips_ui_kinds():
      from swarmline.code_agent._messages import AgentMessage, default_convert_to_llm
      msgs = [
          AgentMessage(kind="user", content="hi"),
          AgentMessage(kind="assistant", content="hello"),
          AgentMessage(kind="notification", content="ui ping"),
          AgentMessage(kind="status", content="working..."),
          AgentMessage(kind="tool_result", content="{}", meta={"tool":"read"}),
      ]
      llm_msgs = default_convert_to_llm(msgs)
      kinds = {m.role for m in llm_msgs}
      assert "user" in kinds and "assistant" in kinds
      assert "notification" not in kinds
      assert "status" not in kinds
  ```
- [ ] **Step 9.3: Реализация `default_convert_to_llm`**
  - Функция: фильтрует `notification`/`status`, конвертирует остальные в legacy `Message`.
  - Кастомный callback: `convert_to_llm: Callable[[list[AgentMessage]], list[Message]]` в `RuntimeConfig`.
- [ ] **Step 9.4: Strangler integration — параллельные пути**
  - В `CodeAgent`: внутренний state — `list[AgentMessage]`. На API call → `convert_to_llm(self._agent_messages)` → `list[Message]` → `runtime.run(messages=...)`.
  - Старый `Agent`/`Conversation` API не трогаем — продолжает работать с `Message`.
  - Backward compat: 4263+ зелёные.
- [ ] **Step 9.5: Write failing test для `should_stop_after_turn` hook**
  ```python
  # tests/integration/code_agent/test_mid_run_hooks.py
  @pytest.mark.asyncio
  async def test_should_stop_after_turn_terminates_loop(tmp_path, fake_llm_multi_turn):
      stop_calls = []
      async def stop_hook(turn_idx, messages):
          stop_calls.append(turn_idx)
          return turn_idx >= 2
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_multi_turn,
                        hooks=LifecycleHooks(should_stop_after_turn=stop_hook))
      _ = [ev async for ev in agent.run("multi-step task")]
      assert max(stop_calls) == 2
  ```
- [ ] **Step 9.6: Write failing test для `get_steering_messages`**
  ```python
  @pytest.mark.asyncio
  async def test_get_steering_messages_injected_before_each_call(tmp_path, fake_llm_simple):
      async def steer(turn_idx, messages):
          return [AgentMessage(kind="user", content=f"REMEMBER: be concise (turn {turn_idx})")]
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple,
                        hooks=LifecycleHooks(get_steering_messages=steer))
      _ = [ev async for ev in agent.run("hi")]
      assert any("REMEMBER" in m.content for m in agent.messages if m.kind == "user")
  ```
- [ ] **Step 9.7: Write failing test для `get_followup_messages`**
  - Аналогично 9.6, но messages добавляются **после** assistant response (для self-prompting).
- [ ] **Step 9.8: Write failing test для `transform_context`**
  ```python
  @pytest.mark.asyncio
  async def test_transform_context_can_filter_messages(tmp_path, fake_llm_simple):
      def shrink(messages):
          return messages[-2:]  # last 2 only
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_simple,
                        hooks=LifecycleHooks(transform_context=shrink))
      for i in range(5):
          _ = [ev async for ev in agent.run(f"turn {i}")]
      # последний LLM call видел только 2 msgs
      assert agent._last_llm_call_msg_count == 2
  ```
- [ ] **Step 9.9: Реализация всех 4 mid-run hooks через `LifecycleHooks`**
  - Все hooks принимаются через **один** параметр `CodeAgent.__init__(..., hooks: LifecycleHooks | None = None)` (ISP — группировка ≤5 callbacks в один dataclass из Stage 1, не 4 отдельных kwargs).
  - В `RuntimeConfig`: `hooks: LifecycleHooks | None = None`.
  - Wired в `runtime.py` main loop: `cfg.hooks.should_stop_after_turn`, `cfg.hooks.get_steering_messages`, и т.д.
  - Тесты 9.5–9.8 обновить: вместо `should_stop_after_turn=stop_hook` использовать `hooks=LifecycleHooks(should_stop_after_turn=stop_hook)`.
- [ ] **Step 9.10: Write failing test для `tool_execution`**
  ```python
  # tests/integration/code_agent/test_tool_execution_mode.py
  @pytest.mark.asyncio
  async def test_tool_execution_sequential_default(tmp_path, fake_llm_calls_3_tools_in_order):
      timings = []
      # ... captures order
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_calls_3_tools_in_order,
                        tool_execution="sequential")
      _ = [ev async for ev in agent.run("do 3 things")]
      # assert tools ran one after another, not overlapping

  @pytest.mark.asyncio
  async def test_tool_execution_parallel_runs_concurrently(tmp_path, fake_llm_calls_3_slow_tools):
      import time
      agent = CodeAgent(model="fake", cwd=str(tmp_path), llm_client=fake_llm_calls_3_slow_tools,
                        tool_execution="parallel")
      t0 = time.perf_counter()
      _ = [ev async for ev in agent.run("do 3 things")]
      elapsed = time.perf_counter() - t0
      # 3 tools × 100ms each: parallel ≈ 100ms, sequential = 300ms
      assert elapsed < 0.25
  ```
- [ ] **Step 9.11: Реализация parallel tool execution**
  - В `runtime.py` executor: при `tool_execution="parallel"` использовать `asyncio.gather(*tool_calls)`. Default `"sequential"` (текущее поведение).
- [ ] **Step 9.12: Full regression run**
  - `pytest -m "not live" --tb=short` — Expected: все 4263+ + новые stage 1-10 тесты зелёные.
  - `ty check src/swarmline/` — no new errors.
- [ ] **Step 9.13: Commit**
  - `git commit -m "feat(code_agent): AgentMessage + mid-run hooks + tool_execution (P0-D, F, G) — strangler fig"`

**Testing (TDD):**
- Unit: `default_convert_to_llm` filters UI kinds (1 test); `AgentMessage` immutability (1 test).
- Integration: 4 mid-run hooks (4 tests); 2 tool_execution modes (sequential vs parallel).
- Edge cases: hook returns invalid type → typed error; circular hook (stop=True at turn 0) → 0 LLM calls.

**DoD (SMART):**
- [ ] `AgentMessage` сосуществует с `Message`, не ломает старое API (M: 4263+ зелёные).
- [ ] 4 mid-run hooks работают (M: 4 tests).
- [ ] `tool_execution="parallel"` ускоряет (M: timing test).
- [ ] Coverage `_messages.py` ≥ 95%.
- [ ] Backward compat: 4263+ + Stage 2-9 зелёные.

**Code rules:** Strangler Fig (новый тип параллельно). DIP (hooks — абстрактные callbacks). YAGNI (parallel — opt-in, не default). ISP — все 5 hooks сгруппированы в `LifecycleHooks` (≤ 5 fields), не на CodeAgent напрямую.

---

<!-- mb-stage:11 -->
### Stage 11: Documentation + example + final E2E + release-prep

**Goal:** Production-ready release. `docs/code_agent_sdk.md`, `examples/code_agent_quickstart.py` прогоняется в CI, integration test «long-session survival > 50 turns» зелёный, safety tests зелёные, self-verification E2E зелёный, session resume E2E зелёный. Bump version v1.5.0, CHANGELOG.

**What to do:**
- [ ] **Step 10.1: Write `docs/code_agent_sdk.md`**
  - Sections: Quick Start (3 lines), Concepts (CodeAgent / sessions / tools / safety / self-verification), API Reference (CodeAgent class + parameters + methods), Examples (5+), Migration Guide (от `Agent` к `CodeAgent`), FAQ.
  - 800-1500 lines.
- [ ] **Step 10.2: Write `examples/code_agent_quickstart.py`**
  ```python
  """Minimal CodeAgent example. Runs in CI with fake LLM."""
  import asyncio
  import os
  from swarmline import CodeAgent

  async def main():
      cwd = os.environ.get("WORKSPACE", os.getcwd())
      agent = CodeAgent(model="claude-3-5-haiku-20241022", cwd=cwd)
      async for event in agent.run("list all .py files and count lines in each"):
          print(event)

  if __name__ == "__main__":
      asyncio.run(main())
  ```
- [ ] **Step 10.3: CI smoke для example**
  - `tests/e2e/test_quickstart_example.py`:
    ```python
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_quickstart_example_runs_with_fake_llm(tmp_path, monkeypatch, fake_llm_simple):
        monkeypatch.setenv("WORKSPACE", str(tmp_path))
        monkeypatch.setenv("SWARMLINE_FAKE_LLM", "1")
        # spawn subprocess: python examples/code_agent_quickstart.py
        r = subprocess.run([sys.executable, "examples/code_agent_quickstart.py"],
                           capture_output=True, text=True, timeout=30,
                           env={**os.environ})
        assert r.returncode == 0
    ```
  - Альтернативно: import как module и run main() inproc.
- [ ] **Step 10.4: Acceptance test «long-session survival > 50 turns» (final)**
  - Уже написан в Stage 7. Перезапустить в Stage 11 как gate, mark `@pytest.mark.acceptance`.
- [ ] **Step 10.5: Acceptance test «safety: rm -rf $HOME blocked»**
  - Уже в Stage 8. Mark `@pytest.mark.acceptance`.
- [ ] **Step 10.6: Acceptance test «self-verification E2E (edit→diagnostics→fix без вмешательства)»**
  - Уже в Stage 9. Mark `@pytest.mark.acceptance`.
- [ ] **Step 10.7: Acceptance test «session resume E2E»**
  - Уже в Stage 6. Mark `@pytest.mark.acceptance`.
- [ ] **Step 10.8: Coverage gate**
  - `pytest --cov=swarmline.code_agent --cov-report=term-missing --cov-fail-under=95`.
  - Если < 95 — добавить точечные тесты на пропущенные branches.
- [ ] **Step 10.9: Full final regression**
  - `pytest -m "not live" --tb=short` exit 0.
  - `pytest -m security` exit 0.
  - `pytest -m acceptance` exit 0.
  - `ruff check src/ tests/` clean.
  - `ruff format --check src/ tests/` clean.
  - `ty check src/swarmline/` no new errors against `tests/architecture/ty_baseline.txt`.
- [ ] **Step 10.10: Bump version + CHANGELOG**
  - `pyproject.toml`: version `1.4.1` → `1.5.0`.
  - `CHANGELOG.md`: добавить секцию `## [1.5.0] - 2026-05-XX` с подсекциями `Added` (CodeAgent, sessions, safety, self-verification), `Changed` (RuntimeConfig поля Optional, Strangler AgentMessage), `Fixed` (если будут).
- [ ] **Step 10.11: Update Memory Bank**
  - `STATUS.md` — release notes ссылка на v1.5.0.
  - `progress.md` — append-only запись «code_agent SDK v1.5.0 shipped».
  - `notes/2026-05-XX_code-agent-v1.5.0-release.md` — release post-mortem.
- [ ] **Step 10.12: Commit + tag (separate release branch per CLAUDE.md)**
  - `git checkout -b release/v1.5.0`
  - `git commit -am "release: v1.5.0 — Minimal Code Agent SDK (P0 complete)"`
  - Merge to `main` после approval.
  - Tag `v1.5.0` после merge — следуя `docs/releasing.md`.

**Testing (TDD):**
- Acceptance: 4 acceptance tests из gate (long-session, safety, self-verify, resume).
- E2E: example smoke test.
- Coverage: gate ≥ 90% на `code_agent/`.

**DoD (SMART):**
- [ ] `docs/code_agent_sdk.md` написан, ≥ 800 lines (S).
- [ ] `examples/code_agent_quickstart.py` exit 0 в CI (M).
- [ ] 4 acceptance tests зелёные (M).
- [ ] Coverage `code_agent/` ≥ 95% (core SDK per RULES.md) (T).
- [ ] All 4263+ + новые тесты зелёные (M).
- [ ] `ruff` + `ty` clean (M).
- [ ] CHANGELOG секция v1.5.0 (S).
- [ ] Version bumped 1.4.1 → 1.5.0 (S).

**Code rules:** Документация-as-tests (примеры в docs прогоняются). KISS (5 примеров, не 50). DRY (acceptance tests = переиспользование Stage 6/7/8/9 тестов с marker).

---

## Risks and mitigation

| # | Risk | Probability | Impact | Mitigation |
|---|------|-------------|--------|------------|
| 1 | **Backward compat break** в 4263+ существующих тестах после Optional defaults в `RuntimeConfig` | M | H | Strict TDD: запускать full suite после каждого Step. Все новые поля `Optional[X] = None`. Регресс-gate в Stage 3 + Stage 10 + Stage 11. CI fails on red. |
| 2 | **AgentMessage Strangler Fig сложность** — параллельные пути legacy `Message` vs новый `AgentMessage` могут привести к двойной поддержке, drift | H | H | Чётко разграничить: `Agent` (legacy) использует `Message`, `CodeAgent` (новый) использует `AgentMessage` + `convert_to_llm`. ADR в `BACKLOG.md` с решением миграции. Не трогать `Agent` API в этом плане. |
| 3 | **Session storage corruption** при concurrent agents в одной cwd / прерванном write | M | H | Atomic write через `os.replace`. SQLite WAL mode (default в `swarmline.memory.sqlite`). Тест `test_concurrent_agents_different_session_ids`. На corrupted resume — fail-fast с понятной ошибкой, не silent. |
| 4 | **Performance regression** от safety guards (regex на каждый bash call, realpath на каждый file op) | M | M | Benchmark в Stage 8: `pytest tests/perf/test_file_safety_overhead.py` — overhead < 1ms на 1000 calls. Pre-compile regex (`re.compile`). Cache `cwd.resolve()` per-agent. |
| 5 | **Lint/type churn** — `ty` baseline `tests/architecture/ty_baseline.txt` ломается на новом коде | M | L | После каждого Stage запускать `ty check src/swarmline/` и сравнивать с baseline. Если baseline растёт > 0 → fix перед commit. Канонические паттерны (см. `notes/2026-04-25_ty-strict-decisions.md`). |
| 6 | **Parallel tool execution race conditions** (P0-G) — два tool concurrent edit одного файла | L | H | Default `tool_execution="sequential"`. Parallel — opt-in. Документировать caveat в `docs/code_agent_sdk.md`. P1-I `Atomic file-mutation queue` — следующий релиз. |
| 7 | **Diagnostics tool dependency на ruff/tsc/cargo/go** — не у всех есть в PATH | M | M | Graceful fallback: `tool_not_installed` error в результате, агент продолжает работу. Документировать в FAQ. Тесты с `which ruff` skip если не установлен. |
| 8 | **Spike под Stage 2 даёт неполный список choke-points** → Stage 3 буксует | M | M | Stage 2 имеет explicit DoD «≥5 choke-points в notes». Если меньше — extend Stage 2 на полдня. Не stопит Stage 3 если 5+ собрано. |
| 9 | **Длительность 3.5 недели нереалистична** при исследовательской работе | M | L | Roadmap имеет batches: `A,B,H` параллельны; `AA,AB,AC` параллельны; `AD,AE` параллельны; `AF,AG,AH` параллельны. После Stage 6 можно делать 3 stages параллельно командой. |

---

## Gate (plan success criterion)

План считается выполненным когда **все 4 acceptance criteria зелёные одновременно** на main, на v1.5.0 tag:

1. **DX-test «3 строки кода работает»**
   ```python
   from swarmline import CodeAgent
   agent = CodeAgent(model="sonnet", cwd="/repo")
   async for ev in agent.run("fix typo in README"):
       print(ev)
   ```
   — без явного построения `RuntimeConfig`/`HookRegistry`/`DefaultToolPolicy`/`ExecutionWorkspace`/`CommandRegistry`/`SwarmlineStack`. Тест `tests/acceptance/test_three_line_dx.py`.

2. **Long-session survival > 50 turns**
   — `tests/integration/code_agent/test_long_session_survival.py::test_50_turns_no_crash` зелёный с `@pytest.mark.acceptance`. Включает truncation continuation + reactive compaction + preflight. Финальный `agent.turn_count == 55`, ни одного `error` event.

3. **Safety: `rm -rf $HOME` блокируется + symlink-escape блокируется**
   — `tests/security/test_code_agent_safety_e2e.py::test_agent_blocks_rm_rf_home` + `test_read_blocks_symlink_escape` зелёные. Workspace `tmp_path` остаётся untouched после злонамеренного prompt.

4. **Все 4263+ старых тестов зелёные** + новый `code_agent/` модуль coverage ≥ 95% (core SDK per RULES.md).
   — `pytest -m "not live"` exit 0; `pytest --cov=swarmline.code_agent --cov-fail-under=95` exit 0.

Дополнительные secondary gates (не блокирующие, но required):
- Self-verification E2E (edit→diagnostics→fix без вмешательства) зелёный.
- Session resume E2E (kill agent → resume → продолжает с того же turn) зелёный.
- `examples/code_agent_quickstart.py` exit 0 в CI.
- `docs/code_agent_sdk.md` опубликован.
- `ruff` + `ty` clean.
- Version bumped → 1.5.0, CHANGELOG обновлён.

---

## Stage dependency graph

```
Stage 1 (foundation: ADRs + Protocols + contract tests, 0.5d) — Contract-First gate
  └─→ Stage 2 (spike, 1d)
        └─→ Stage 3 (P0-A,B,H, 2-3d)
              ├─→ Stage 4 (P0-C, 2d)         ┐
              ├─→ Stage 5 (P0-E, 1d)          ├─→ Stage 10 (P0-D,F,G, 3-4d) ─→ Stage 11 (docs+release, 1-2d)
              ├─→ Stage 6 (P0-K1,K2,K3, 2-3d) │     (Strangler Fig, инвазивный — последний перед docs)
              ├─→ Stage 7 (P0-AA,AB,AC, 2-3d) │
              ├─→ Stage 8 (P0-AD,AE, 1-2d)    │
              └─→ Stage 9 (P0-AF,AG,AH, 2-3d) ┘
```

Stage 1 — обязательный foundation gate (ADRs + Protocols + contract tests) перед любой реализацией (Contract-First per RULES.md). После Stage 3 — Stages 4,5,6,7,8,9 могут идти параллельно командой (разные файлы, минимальные конфликты). Stage 10 (AgentMessage) — последний перед docs, потому что трогает базовые типы.

---

## Checklist sync

После сохранения плана запустить:
```bash
bash ~/.claude/skills/memory-bank/scripts/mb-plan-sync.sh
```
для апдейта `roadmap.md` (через симлинк → `plan.md`) и `checklist.md` с 11 stages.
