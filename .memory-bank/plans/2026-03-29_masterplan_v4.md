# Master Plan v4: Cognitia Enhancement Roadmap (Phases 11–15)

> **Предшественник:** masterplan_v3.md (Phases 0–10A — все завершены, v1.0.0 released)
> **Базовое состояние:** 2646 tests passed, 199 source files, 4 runtimes, 14 protocols, Clean Architecture
> **Цель:** Сделать Cognitia enterprise-ready, community-friendly и state-of-the-art

---

## Phase 11: Production Trust (делает нас enterprise-ready)

**Цель:** Обеспечить production-grade observability, type-safe structured output и protocol interoperability.

### 11.1 — OpenTelemetry Exporter

**Описание:** Мост из EventBus → OpenTelemetry spans/metrics. OTel GenAI Semantic Conventions (v1.37+) — converging standard. Production-команды хотят видеть agent traces в Datadog, Grafana, Jaeger.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/observability/otel_exporter.py` | **NEW** — OTelExporter (EventBus subscriber → OTel spans) |
| `src/cognitia/observability/__init__.py` | Добавить exports |
| `pyproject.toml` | Добавить optional dep: `otel = ["opentelemetry-api>=1.29", "opentelemetry-sdk>=1.29"]` |
| `tests/unit/test_otel_exporter.py` | **NEW** — unit-тесты с mock TracerProvider |
| `tests/integration/test_otel_integration.py` | **NEW** — EventBus → OTel span lifecycle |
| `docs/observability.md` | Обновить: OTel setup, Datadog/Jaeger примеры |
| `examples/28_opentelemetry_tracing.py` | **NEW** — runnable example |

**Архитектура:**
```python
class OTelExporter:
    """EventBus subscriber that emits OpenTelemetry spans."""
    def __init__(self, tracer_provider=None):  # lazy import opentelemetry
    def subscribe(self, event_bus: EventBus) -> None:
    # Listens: llm_call_start/end, tool_call_start/end
    # Emits: spans with gen_ai.* attributes (OTel GenAI conventions)
```

**OTel GenAI атрибуты:**
- `gen_ai.system` = "cognitia"
- `gen_ai.request.model` = model alias
- `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- `gen_ai.response.finish_reasons`
- `cognitia.runtime` = runtime name
- `cognitia.session_id` = session ID

**DoD:**
- [ ] OTelExporter подписывается на EventBus и создаёт OTel spans для LLM/tool calls
- [ ] Атрибуты соответствуют OTel GenAI Semantic Conventions v1.37+
- [ ] Lazy import — работает без opentelemetry installed (ImportError → warning)
- [ ] Unit-тесты: span creation, attribute mapping, error spans, missing provider graceful
- [ ] Integration-тест: EventBus → OTelExporter → InMemorySpanExporter → verify spans
- [ ] 0 новых required dependencies (optional `otel` extra)
- [ ] Пример запускается: `python examples/28_opentelemetry_tracing.py`
- [ ] docs/observability.md обновлён с OTel setup guide

---

### 11.2 — Structured Output Validation (Pydantic-level)

**Описание:** Агент возвращает `T` (Pydantic model) вместо `str`. Runtime парсит JSON → validates → retry при ошибке. PydanticAI задала стандарт — type-safe structured output со streamed validation.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/agent/structured.py` | **NEW** — StructuredOutput[T], parse/validate/retry logic |
| `src/cognitia/agent/facade.py` | Добавить `query_structured(prompt, output_type: type[T]) -> T` |
| `src/cognitia/runtime/thin/loop.py` | Response format passthrough (JSON mode) |
| `tests/unit/test_structured_output.py` | **NEW** — parsing, validation, retry, edge cases |
| `tests/integration/test_structured_output_integration.py` | **NEW** — Agent.query_structured E2E |
| `docs/structured-output.md` | Расширить: Pydantic models, retry, streaming |
| `examples/29_structured_output_pydantic.py` | **NEW** — runnable example |

**Архитектура:**
```python
class StructuredOutput(Generic[T]):
    """Type-safe structured output from LLM."""
    output_type: type[T]
    max_retries: int = 2

    async def parse_and_validate(self, raw: str) -> T:
        """Parse JSON → Pydantic model. Retry prompt on ValidationError."""

# Agent facade:
async def query_structured(self, prompt: str, output_type: type[T], **kwargs) -> T:
    """Query agent and return validated Pydantic model."""
```

**DoD:**
- [ ] `Agent.query_structured(prompt, MyModel)` возвращает validated Pydantic model
- [ ] При JSON parse error или ValidationError — автоматический retry с error feedback в prompt
- [ ] max_retries=2 по умолчанию, configurable
- [ ] Работает с thin runtime (response_format={"type": "json_object"})
- [ ] Работает с Claude SDK runtime (tool_use для structured output)
- [ ] Unit-тесты: valid parse, invalid JSON retry, validation error retry, max retries exceeded
- [ ] Integration-тест: Agent → query_structured → validated model
- [ ] Обратная совместимость: query() продолжает возвращать str
- [ ] Пример запускается с mock/real LLM

---

### 11.3 — A2A Protocol Support (Agent-to-Agent)

**Описание:** A2A (Google, 50+ enterprise partners) = стандарт для agent-to-agent communication. MCP = vertical (agent→tools), A2A = horizontal (agent↔agent). Позволяет Cognitia-агентам общаться с агентами на CrewAI, LangGraph, Google ADK.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/a2a/__init__.py` | **NEW** — package |
| `src/cognitia/a2a/types.py` | **NEW** — AgentCard, Task, TaskState, Message, Artifact |
| `src/cognitia/a2a/server.py` | **NEW** — A2AServer (HTTP endpoint exposing agent as A2A service) |
| `src/cognitia/a2a/client.py` | **NEW** — A2AClient (call remote A2A agents) |
| `src/cognitia/a2a/adapter.py` | **NEW** — CognitiaA2AAdapter (wraps Agent as A2A-compatible) |
| `pyproject.toml` | Optional dep: `a2a = ["starlette>=0.40", "httpx>=0.28"]` |
| `tests/unit/test_a2a_types.py` | **NEW** — type serialization roundtrip |
| `tests/unit/test_a2a_server.py` | **NEW** — server routing, task lifecycle |
| `tests/unit/test_a2a_client.py` | **NEW** — client request/response |
| `tests/integration/test_a2a_integration.py` | **NEW** — server ↔ client full cycle |
| `docs/a2a-protocol.md` | **NEW** — A2A guide |
| `examples/30_a2a_server.py` | **NEW** — expose agent as A2A service |
| `examples/31_a2a_client.py` | **NEW** — call remote A2A agent |

**Архитектура:**
```
CognitiaAgent
    │
    ▼
CognitiaA2AAdapter → implements A2A Agent interface
    │
    ├── A2AServer (Starlette ASGI app)
    │   ├── GET  /.well-known/agent.json  → AgentCard
    │   ├── POST /tasks/send              → create/resume task
    │   └── POST /tasks/sendSubscribe     → SSE streaming
    │
    └── A2AClient
        ├── discover(url) → AgentCard
        ├── send_task(task) → Task
        └── stream_task(task) → AsyncIterator[TaskEvent]
```

**A2A Core Types (per spec):**
- `AgentCard`: name, description, url, skills[], protocols[]
- `Task`: id, status (submitted/working/completed/failed), messages[], artifacts[]
- `Message`: role, parts[] (TextPart, DataPart, FilePart)
- `Artifact`: name, parts[], metadata

**DoD:**
- [ ] AgentCard JSON schema соответствует A2A spec (/.well-known/agent.json)
- [ ] Task lifecycle: submitted → working → completed/failed
- [ ] A2AServer: HTTP endpoints для send, sendSubscribe (SSE), cancel
- [ ] A2AClient: discover, send_task, stream_task
- [ ] CognitiaA2AAdapter: wraps любой Cognitia Agent как A2A service
- [ ] Streaming через SSE (Server-Sent Events)
- [ ] Unit-тесты: type roundtrip, server routing, client mock
- [ ] Integration-тест: server ↔ client full task lifecycle (in-process)
- [ ] Lazy import — Starlette optional, работает без неё (ImportError → clear message)
- [ ] 0 изменений в core agent/ (adapter pattern)

---

## Phase 12: Ecosystem Growth (делает нас community-friendly)

**Цель:** Снизить time-to-hello-world, дать production-ready templates, профессиональную документацию.

### 12.1 — `cognitia init` CLI Scaffolding

**Описание:** `cognitia init my-agent --runtime thin --memory sqlite` → готовый проект за 10 секунд. "create-react-app" эффект для AI agents.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/cli/__init__.py` | **NEW** — CLI package |
| `src/cognitia/cli/main.py` | **NEW** — Click/Typer CLI entry point |
| `src/cognitia/cli/init_cmd.py` | **NEW** — `cognitia init` command |
| `src/cognitia/cli/templates/` | **NEW** — Jinja2 templates (agent.py, config.yaml, tests/, Dockerfile, .env.example) |
| `pyproject.toml` | Entry point: `[project.scripts] cognitia = "cognitia.cli.main:app"` + dep `click>=8.1` |
| `tests/unit/test_cli_init.py` | **NEW** — template rendering, file creation, flag combinations |
| `docs/getting-started.md` | Обновить: `cognitia init` quick start |

**Шаблоны (5 вариантов):**
```
cognitia init my-agent                    → minimal (thin, inmemory)
cognitia init my-agent --runtime claude   → Claude SDK
cognitia init my-agent --memory sqlite    → with persistence
cognitia init my-agent --full             → all features (memory, tools, web, planning)
cognitia init my-agent --template research → research assistant template
```

**Генерируемая структура:**
```
my-agent/
├── agent.py              ← main entry point
├── config.yaml           ← agent config (runtime, memory, tools)
├── skills/               ← MCP skill definitions
├── tests/
│   └── test_agent.py     ← starter test
├── Dockerfile            ← production-ready
├── docker-compose.yml    ← with memory backend
├── .env.example          ← API keys template
├── pyproject.toml        ← dependencies
└── README.md             ← usage instructions
```

**DoD:**
- [ ] `cognitia init my-agent` создаёт рабочий проект, `cd my-agent && python agent.py` работает
- [ ] Флаги `--runtime`, `--memory`, `--full`, `--template` генерируют правильные конфиги
- [ ] Генерируемый код — clean, lint-clean, с тестом
- [ ] Dockerfile multi-stage, production-ready
- [ ] Unit-тесты: все комбинации флагов, file system assertions
- [ ] `cognitia --help` показывает доступные команды
- [ ] Entry point зарегистрирован в pyproject.toml
- [ ] docs/getting-started.md обновлён

---

### 12.2 — Production Templates (5 штук)

**Описание:** Полноценные production-ready примеры, а не hello-world. Каждый — отдельный мини-проект с тестами, Docker, README.

**Файлы:**
| Файл | Действие |
|------|----------|
| `templates/customer-support/` | **NEW** — customer support agent (memory, tools, escalation) |
| `templates/code-reviewer/` | **NEW** — code review agent (sandbox, git tools, structured output) |
| `templates/research-assistant/` | **NEW** — research agent (web search, RAG, tiered memory) |
| `templates/data-pipeline/` | **NEW** — data processing agent (planning, verification, reporting) |
| `templates/multi-agent-team/` | **NEW** — lead + workers team (orchestration, task queue) |

**Каждый template содержит:**
```
templates/<name>/
├── README.md              ← описание, архитектура, setup
├── agent.py / main.py     ← entry point
├── config.yaml            ← agent configuration
├── skills/                ← MCP skills (если нужны)
├── tools/                 ← custom tools (если нужны)
├── tests/
│   ├── test_agent.py      ← unit tests
│   └── test_e2e.py        ← e2e scenario test
├── Dockerfile             ← production container
├── docker-compose.yml     ← full stack (agent + DB + monitoring)
├── .env.example           ← required API keys
└── pyproject.toml         ← isolated dependencies
```

**DoD:**
- [ ] Каждый template: `pip install -e . && python main.py` работает (с mock LLM или env key)
- [ ] Каждый template: `pytest tests/` — все тесты проходят
- [ ] Каждый template: `docker compose up` — запускается
- [ ] README каждого template: описание, архитектура, setup guide, customization points
- [ ] customer-support: memory persistence, escalation flow, conversation history
- [ ] code-reviewer: sandbox execution, git diff analysis, structured review output
- [ ] research-assistant: web search, RAG retrieval, tiered memory, report generation
- [ ] data-pipeline: planning, step verification, error recovery, final report
- [ ] multi-agent-team: lead delegation, worker execution, task queue, result aggregation

---

### 12.3 — Auto-Generated API Docs + Community Infra

**Описание:** Профессиональный docs site с auto-generated API reference. Contributing guide, issue templates, badges.

**Файлы:**
| Файл | Действие |
|------|----------|
| `docs/conf.py` или `mkdocs.yml` | Обновить: mkdocstrings plugin для API reference |
| `docs/api/` | **NEW** — auto-generated module reference pages |
| `CONTRIBUTING.md` | **NEW** — contribution guide (setup, PR process, code style) |
| `.github/ISSUE_TEMPLATE/` | **NEW** — bug report, feature request templates |
| `.github/PULL_REQUEST_TEMPLATE.md` | **NEW** — PR template |
| `README.md` | Добавить badges (PyPI, tests, coverage, license, docs) |
| `pyproject.toml` | `py.typed` marker |
| `src/cognitia/py.typed` | **NEW** — PEP 561 marker file |

**DoD:**
- [ ] `mkdocs serve` показывает auto-generated API docs для всех public модулей
- [ ] Каждый protocol, class, function имеет rendered docstring
- [ ] CONTRIBUTING.md: setup instructions, coding standards, PR process, release process
- [ ] Issue templates: bug (with repro steps), feature request (with use case)
- [ ] PR template: checklist (tests, lint, docs, changelog)
- [ ] README badges: PyPI version, test status, coverage %, license, docs link
- [ ] `py.typed` marker присутствует — IDE type checking работает для потребителей
- [ ] `pip install cognitia` + IDE показывает type hints

---

## Phase 13: Agent Evaluation (делает нас trustworthy)

**Цель:** Встроенный eval framework для измерения качества агентов.

### 13.1 — Eval Framework Core

**Описание:** `EvalRunner` + `Scorer` protocols + builtin scorers. Позволяет запускать evaluation suites как pytest тесты или standalone.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/eval/__init__.py` | **NEW** — package |
| `src/cognitia/eval/types.py` | **NEW** — EvalCase, EvalResult, EvalSuite, ScorerResult |
| `src/cognitia/eval/runner.py` | **NEW** — EvalRunner (runs suite, collects results) |
| `src/cognitia/eval/scorers.py` | **NEW** — builtin scorers |
| `src/cognitia/eval/reporters.py` | **NEW** — JSON/CSV/console reporters |
| `src/cognitia/eval/pytest_plugin.py` | **NEW** — pytest integration (@pytest.mark.eval) |
| `tests/unit/test_eval_types.py` | **NEW** |
| `tests/unit/test_eval_runner.py` | **NEW** |
| `tests/unit/test_eval_scorers.py` | **NEW** |
| `tests/integration/test_eval_integration.py` | **NEW** |
| `docs/evaluation.md` | **NEW** — eval guide |
| `examples/32_agent_evaluation.py` | **NEW** |

**Архитектура:**
```python
@dataclass(frozen=True)
class EvalCase:
    id: str
    input: str                    # user prompt
    expected: str | None = None   # expected output (for exact/contains match)
    context: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

@dataclass(frozen=True)
class ScorerResult:
    score: float        # 0.0–1.0
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

@runtime_checkable
class Scorer(Protocol):
    async def score(self, case: EvalCase, output: str) -> ScorerResult: ...

class EvalRunner:
    async def run(self, agent: Agent, suite: list[EvalCase], scorers: list[Scorer]) -> EvalReport:
        """Run all cases, apply all scorers, aggregate results."""

# Builtin scorers:
class ExactMatchScorer: ...      # output == expected
class ContainsScorer: ...        # expected in output
class RegexScorer: ...           # pattern match
class LlmJudgeScorer: ...       # LLM-as-judge (quality, relevance, safety)
class ToolAccuracyScorer: ...   # correct tool selection (via event log)
class LatencyScorer: ...         # response time threshold
class CostScorer: ...            # token/cost budget compliance
class HallucinationScorer: ...   # factual grounding check (via RAG context)
```

**DoD:**
- [ ] EvalRunner запускает suite из N cases через agent, применяет M scorers, возвращает EvalReport
- [ ] EvalReport содержит: per-case scores, aggregate metrics (mean, min, p50, p95), pass/fail threshold
- [ ] 8 builtin scorers реализованы и протестированы
- [ ] LlmJudgeScorer: использует отдельный LLM call для оценки (configurable model)
- [ ] ToolAccuracyScorer: проверяет что agent выбрал правильные tools (через EventBus events)
- [ ] JSON/CSV/console reporters для результатов
- [ ] pytest plugin: `@pytest.mark.eval` decorator, `--eval` flag для запуска eval suite
- [ ] Unit-тесты: каждый scorer, runner lifecycle, report generation
- [ ] Integration-тест: Agent + EvalRunner + multiple scorers → report
- [ ] Пример запускается: `python examples/32_agent_evaluation.py`
- [ ] docs/evaluation.md: guide по написанию eval suites

---

### 13.2 — Eval Dashboard & Comparison

**Описание:** Визуализация результатов eval, сравнение между runs (A/B testing моделей/промптов).

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/eval/compare.py` | **NEW** — EvalComparator (diff between runs) |
| `src/cognitia/eval/history.py` | **NEW** — EvalHistory (store/load eval results) |
| `tests/unit/test_eval_compare.py` | **NEW** |
| `docs/evaluation.md` | Расширить: comparison, history, CI integration |
| `examples/33_eval_comparison.py` | **NEW** — A/B model comparison |

**DoD:**
- [ ] EvalComparator: diff двух EvalReport по scorer, case, aggregate
- [ ] Выводит: improved/regressed/unchanged per case
- [ ] EvalHistory: save/load results to JSON file (для tracking over time)
- [ ] CLI: `cognitia eval compare run1.json run2.json` — table diff
- [ ] Unit-тесты: comparison logic, edge cases (missing cases, new scorers)
- [ ] Пример: A/B comparison двух моделей на одном eval suite

---

## Phase 14: Advanced Memory (делает нас state-of-the-art)

**Цель:** Three-layer memory model (episodic/semantic/procedural) + consolidation.

### 14.1 — Episodic Memory

**Описание:** "Что произошло" — агент помнит конкретные эпизоды (сессии, решения, ошибки). Retrieval по similarity/time/tags. Отличие от MessageStore: MessageStore = raw conversation, Episodic = structured episodes с metadata.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/memory/episodic.py` | **NEW** — EpisodicMemory protocol + InMemory implementation |
| `src/cognitia/memory/episodic_types.py` | **NEW** — Episode, EpisodeQuery, EpisodeResult |
| `src/cognitia/memory/episodic_sqlite.py` | **NEW** — SQLite backend |
| `tests/unit/test_episodic_memory.py` | **NEW** — contract tests (parametrized InMemory + SQLite) |
| `tests/integration/test_episodic_integration.py` | **NEW** |
| `docs/memory.md` | Расширить: episodic memory guide |

**Архитектура:**
```python
@dataclass(frozen=True)
class Episode:
    id: str
    summary: str                       # LLM-generated summary of what happened
    key_decisions: tuple[str, ...]     # important decisions made
    tools_used: tuple[str, ...]        # tools invoked
    outcome: str                       # success/failure/partial
    session_id: str
    timestamp: datetime
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

@runtime_checkable
class EpisodicMemory(Protocol):
    async def store(self, episode: Episode) -> None: ...
    async def recall(self, query: str, top_k: int = 5) -> list[Episode]: ...
    async def recall_recent(self, n: int = 10) -> list[Episode]: ...
    async def recall_by_tag(self, tag: str) -> list[Episode]: ...
```

**DoD:**
- [ ] EpisodicMemory protocol: store, recall (by query), recall_recent, recall_by_tag
- [ ] InMemoryEpisodicMemory: word overlap search (как SimpleRetriever)
- [ ] SqliteEpisodicMemory: FTS5 full-text search
- [ ] Episode generation: LLM summarizer создаёт Episode из conversation history
- [ ] Contract-тесты: parametrized для InMemory и SQLite (одинаковое поведение)
- [ ] Integration-тест: session → episodes → recall → context injection

---

### 14.2 — Procedural Memory (Learned Skills)

**Описание:** Агент учится из опыта — запоминает успешные последовательности tool calls как "процедуры". При похожей задаче — предлагает проверенный plan.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/memory/procedural.py` | **NEW** — ProceduralMemory protocol + InMemory impl |
| `src/cognitia/memory/procedural_types.py` | **NEW** — Procedure, ProcedureStep |
| `tests/unit/test_procedural_memory.py` | **NEW** |
| `docs/memory.md` | Расширить: procedural memory |

**Архитектура:**
```python
@dataclass(frozen=True)
class ProcedureStep:
    tool_name: str
    args_template: dict[str, str]  # parameterized args
    expected_outcome: str

@dataclass(frozen=True)
class Procedure:
    id: str
    name: str
    description: str
    trigger: str           # when to suggest this procedure
    steps: tuple[ProcedureStep, ...]
    success_count: int = 0
    failure_count: int = 0

@runtime_checkable
class ProceduralMemory(Protocol):
    async def store(self, procedure: Procedure) -> None: ...
    async def suggest(self, query: str, top_k: int = 3) -> list[Procedure]: ...
    async def record_outcome(self, proc_id: str, success: bool) -> None: ...
```

**DoD:**
- [ ] ProceduralMemory protocol: store, suggest (by query match), record_outcome
- [ ] InMemory implementation с word overlap matching
- [ ] Procedure extraction: из event log (tool_call sequence → Procedure) через LLM
- [ ] success_count/failure_count — reinforcement через record_outcome
- [ ] Unit-тесты: store/suggest roundtrip, outcome tracking, ranking by success rate

---

### 14.3 — Memory Consolidation

**Описание:** Автоматический pipeline: episodic episodes → semantic facts (FactStore). LLM извлекает устойчивые знания из повторяющихся эпизодов.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/memory/consolidation.py` | **NEW** — ConsolidationPipeline |
| `tests/unit/test_consolidation.py` | **NEW** |
| `docs/memory.md` | Расширить: consolidation pipeline |

**Архитектура:**
```python
class ConsolidationPipeline:
    """Extracts semantic facts from episodic memories."""
    def __init__(self, episodic: EpisodicMemory, facts: FactStore, generator: TierGenerator):
        ...
    async def consolidate(self, min_episodes: int = 3) -> list[str]:
        """Find recurring patterns in episodes, extract as facts."""
        # 1. Recall recent episodes
        # 2. Cluster by similarity
        # 3. For clusters with >= min_episodes: LLM extract fact
        # 4. Store in FactStore
        # 5. Return new facts
```

**DoD:**
- [ ] ConsolidationPipeline: episodic → cluster → LLM extract → FactStore
- [ ] min_episodes threshold — не консолидирует единичные эпизоды
- [ ] Duplicate fact detection — не создаёт дубли в FactStore
- [ ] Unit-тесты: clustering logic, fact extraction, dedup
- [ ] Integration-тест: 5 episodes → consolidation → 2 facts in FactStore

---

## Phase 15: Deployment & DX (делает нас production-grade)

**Цель:** Упростить deployment, добавить HITL patterns, улучшить DX.

### 15.1 — `cognitia serve` (HTTP API)

**Описание:** Одна команда — agent доступен по HTTP. REST API + SSE streaming. Для production: FastAPI/Starlette обёртка.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/cli/serve_cmd.py` | **NEW** — `cognitia serve` command |
| `src/cognitia/serve/__init__.py` | **NEW** — package |
| `src/cognitia/serve/app.py` | **NEW** — Starlette ASGI app |
| `src/cognitia/serve/routes.py` | **NEW** — REST endpoints |
| `pyproject.toml` | Optional dep: `serve = ["starlette>=0.40", "uvicorn>=0.30"]` |
| `tests/unit/test_serve_routes.py` | **NEW** |
| `tests/integration/test_serve_integration.py` | **NEW** — HTTP client → agent |
| `docs/deployment.md` | **NEW** — deployment guide |
| `examples/34_serve_http.py` | **NEW** |

**Endpoints:**
```
POST /v1/query           → Agent.query() → JSON response
POST /v1/stream          → Agent.stream() → SSE events
POST /v1/conversation    → Agent.conversation() → SSE events
GET  /v1/health          → health check
GET  /v1/info            → agent info (capabilities, model, version)
```

**DoD:**
- [ ] `cognitia serve --config config.yaml --port 8080` запускает HTTP server
- [ ] POST /v1/query: JSON request → agent response → JSON
- [ ] POST /v1/stream: JSON request → SSE stream (text chunks, tool calls, errors)
- [ ] GET /v1/health: returns 200 + status
- [ ] Authentication: optional Bearer token (via config)
- [ ] CORS: configurable origins
- [ ] Unit-тесты: route handlers, request validation, error responses
- [ ] Integration-тест: httpx client → serve → agent → response
- [ ] Dockerfile: multi-stage, production-ready, healthcheck
- [ ] docs/deployment.md: local, Docker, cloud deployment guides

---

### 15.2 — Human-in-the-Loop Patterns

**Описание:** Ready-made HITL: approval gates для tool execution, plan approval, content review. Обобщение существующего plan approval в generic pattern.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/hitl/__init__.py` | **NEW** — package |
| `src/cognitia/hitl/types.py` | **NEW** — ApprovalRequest, ApprovalResponse, ApprovalPolicy |
| `src/cognitia/hitl/gate.py` | **NEW** — ApprovalGate middleware |
| `src/cognitia/hitl/policies.py` | **NEW** — AlwaysApprove, AlwaysDeny, ToolApproval, CostApproval |
| `src/cognitia/hitl/callback.py` | **NEW** — ApprovalCallback protocol (CLI, HTTP, custom) |
| `tests/unit/test_hitl.py` | **NEW** |
| `tests/integration/test_hitl_integration.py` | **NEW** |
| `docs/hitl.md` | **NEW** — HITL guide |
| `examples/35_human_approval.py` | **NEW** |

**Архитектура:**
```python
@runtime_checkable
class ApprovalCallback(Protocol):
    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse: ...

class ApprovalGate:
    """Middleware that pauses execution for human approval."""
    def __init__(self, policy: ApprovalPolicy, callback: ApprovalCallback): ...

    async def check(self, action: str, context: dict) -> bool:
        """Returns True if approved, False if denied, raises on timeout."""

# Policies:
class ToolApprovalPolicy:      # approve specific tools (e.g., execute, write_file)
class CostApprovalPolicy:      # approve when cost exceeds threshold
class PlanApprovalPolicy:       # approve execution plan before start
class ContentApprovalPolicy:   # approve output content before delivery
```

**DoD:**
- [ ] ApprovalGate middleware: паузит execution, вызывает callback, ждёт response
- [ ] 4 builtin policies: tool, cost, plan, content
- [ ] CLI callback: input() prompt в терминале
- [ ] HTTP callback: webhook POST → wait for response
- [ ] Timeout: configurable, default 5 minutes, raises TimeoutError
- [ ] Integration с hooks: PreToolUse → ApprovalGate → allow/deny
- [ ] Unit-тесты: каждая policy, gate lifecycle, timeout
- [ ] Integration-тест: Agent + ApprovalGate + mock callback → approved/denied flows
- [ ] Пример: agent с tool approval в CLI

---

### 15.3 — Plugin Registry & Discovery

**Описание:** Механизм для community-contributed providers. Entry points + discovery CLI.

**Файлы:**
| Файл | Действие |
|------|----------|
| `src/cognitia/plugins/__init__.py` | **NEW** — package |
| `src/cognitia/plugins/registry.py` | **NEW** — PluginRegistry (entry point discovery) |
| `src/cognitia/plugins/types.py` | **NEW** — PluginInfo, PluginType (runtime, memory, tool, scorer) |
| `src/cognitia/cli/plugins_cmd.py` | **NEW** — `cognitia plugins list/info` |
| `tests/unit/test_plugin_registry.py` | **NEW** |
| `docs/plugins.md` | **NEW** — plugin development guide |

**Архитектура:**
```python
# Third-party package pyproject.toml:
# [project.entry-points."cognitia.plugins"]
# my_runtime = "my_package:MyRuntime"

class PluginRegistry:
    @classmethod
    def discover(cls) -> list[PluginInfo]:
        """Discover installed plugins via entry points."""

    @classmethod
    def get(cls, name: str, plugin_type: PluginType) -> Any:
        """Load a specific plugin by name and type."""
```

**DoD:**
- [ ] PluginRegistry.discover() находит все installed entry points из `cognitia.plugins` namespace
- [ ] PluginInfo: name, version, type (runtime/memory/tool/scorer), module_path
- [ ] `cognitia plugins list` — показывает discovered plugins
- [ ] `cognitia plugins info <name>` — подробная информация
- [ ] Plugin types: runtime, memory_provider, tool_provider, eval_scorer
- [ ] Unit-тесты: discovery mock, type filtering, missing plugin graceful
- [ ] docs/plugins.md: how to create a plugin (entry points, protocol compliance)

---

### 15.4 — Performance Benchmarks

**Описание:** Воспроизводимые бенчмарки: latency, token usage, cost per runtime. Differentiation от конкурентов.

**Файлы:**
| Файл | Действие |
|------|----------|
| `benchmarks/` | **NEW** — directory |
| `benchmarks/bench_latency.py` | **NEW** — response latency per runtime |
| `benchmarks/bench_tokens.py` | **NEW** — token usage efficiency |
| `benchmarks/bench_context.py` | **NEW** — context builder performance |
| `benchmarks/bench_memory.py` | **NEW** — memory provider throughput |
| `benchmarks/conftest.py` | **NEW** — shared fixtures |
| `benchmarks/README.md` | **NEW** — how to run, interpret results |
| `docs/benchmarks.md` | **NEW** — published results |

**DoD:**
- [ ] Latency benchmark: time-to-first-token и total per runtime (thin, claude, deepagents)
- [ ] Token benchmark: overhead per runtime (system prompt, tool definitions, context)
- [ ] Context benchmark: build_context() performance at different budget sizes
- [ ] Memory benchmark: read/write throughput per provider (InMemory, SQLite, Postgres)
- [ ] Reproducible: `pytest benchmarks/ --benchmark-json=results.json`
- [ ] README: methodology, hardware requirements, interpretation guide
- [ ] docs/benchmarks.md: published baseline results

---

## Quick Wins (вне фаз, делать по мере возможности)

### QW-1: py.typed Marker
- [ ] Создать `src/cognitia/py.typed` (пустой файл)
- [ ] Добавить в pyproject.toml: `[tool.hatch.build.targets.wheel] ... include py.typed`
- [ ] Проверить: `pip install -e . && mypy --strict consumer.py` видит типы

### QW-2: README Badges
- [ ] PyPI version badge
- [ ] GitHub Actions CI badge
- [ ] Coverage badge (codecov или shields.io)
- [ ] License badge
- [ ] Python versions badge
- [ ] Docs link badge

### QW-3: Deprecation Warnings Cleanup
- [ ] Устранить 19 DeprecationWarning в тестах (SessionState.adapter → .runtime)
- [ ] Убедиться: 0 warnings при `pytest -W error::DeprecationWarning`

---

## Phase 16: Code Agent Integration (делает нас универсальным инструментом)

**Цель:** Любой код-агент (Claude Code, Codex CLI, OpenCode) использует Cognitia как инструмент. Мозги = код-агент (подписка LLM), руки = Cognitia.

**Юридическая модель:** Cognitia = tool (как Figma MCP, GitHub MCP). Код-агент остаётся продуктом. Стандартное MCP-использование, не нарушает ToS Anthropic/OpenAI.

**Детальный план:** `plans/2026-03-29_feature_code-agent-integration.md`

### Подзадачи:
- **16.1** Cognitia MCP Server (FastMCP STDIO, 15 typed tools + code REPL)
- **16.2** Cognitia CLI Client (cognitia agent/memory/team/run subcommands)
- **16.3** Claude Code Skill (SKILL.md + examples + patterns)
- **16.4** Headless Mode (0 LLM calls — memory/tools/plans only)
- **16.5** Codex & OpenCode Configuration (auto-setup, ready-made configs)

---

## Зависимости между фазами

```
Phase 11 (Production Trust)
    ├── 11.1 OTel          → standalone
    ├── 11.2 Structured    → standalone
    └── 11.3 A2A           → standalone, нужен для 15.1 (serve uses A2A)

Phase 12 (Ecosystem)
    ├── 12.1 CLI init      → standalone
    ├── 12.2 Templates     → после 12.1 (templates use cognitia init structure)
    └── 12.3 API Docs      → standalone

Phase 13 (Evaluation)
    ├── 13.1 Eval Core     → standalone
    └── 13.2 Eval Compare  → после 13.1

Phase 14 (Memory)
    ├── 14.1 Episodic      → standalone
    ├── 14.2 Procedural    → standalone
    └── 14.3 Consolidation → после 14.1 (uses EpisodicMemory)

Phase 15 (Deployment)
    ├── 15.1 Serve         → standalone (может использовать A2A из 11.3)
    ├── 15.2 HITL          → standalone
    ├── 15.3 Plugins       → standalone
    └── 15.4 Benchmarks    → standalone

Phase 16 (Code Agent Integration) ★ HIGH PRIORITY
    ├── 16.1 MCP Server    → standalone (core integration)
    ├── 16.2 CLI Client    → standalone (может делать параллельно с 16.1)
    ├── 16.3 Skill         → после 16.1 или 16.2 (использует один из них)
    ├── 16.4 Headless      → после 16.1 (mode flag для MCP server)
    └── 16.5 Configs       → после 16.1 (настройки для MCP server)
```

## Рекомендуемый порядок реализации

**Iteration 0 (★ game-changer — code agent integration):**
1. **16.1** MCP Server + **16.4** Headless mode (4-5 дней)
2. **16.2** CLI Client (3-4 дня, параллельно с 16.1)
3. **16.3** Claude Code Skill + **16.5** Configs (2-3 дня)

**Iteration 1 (production trust + onboarding):**
4. QW-1, QW-2, QW-3 (quick wins, 1 день)
5. **11.1** OTel Exporter (2-3 дня)
6. **11.2** Structured Output (2-3 дня)
7. **12.3** API Docs + Community infra (1-2 дня)

**Iteration 2 (differentiation — eval + CLI init + templates):**
8. **12.1** CLI init (2-3 дня, расширяет CLI из 16.2)
9. **13.1** Eval Framework Core (3-4 дня)
10. **12.2** Production Templates (3-5 дней)
11. **15.1** Serve HTTP (2-3 дня)

**Iteration 3 (advanced — A2A + HITL + memory):**
12. **11.3** A2A Protocol (4-5 дней)
13. **15.2** HITL Patterns (2-3 дня)
14. **14.1** Episodic Memory (2-3 дня)
15. **14.2** Procedural Memory (2-3 дня)

**Iteration 4 (polish — comparison, consolidation, plugins):**
16. **13.2** Eval Compare (1-2 дня)
17. **14.3** Memory Consolidation (2-3 дня)
18. **15.3** Plugin Registry (2-3 дня)
19. **15.4** Benchmarks (2-3 дня)

---

## Метрики успеха

| Метрика | Текущее | Цель (Phase 15 done) |
|---------|---------|---------------------|
| Tests | 2646 | 3500+ |
| Source files | 199 | 250+ |
| Examples | 27 | 35+ |
| Templates | 0 | 5 |
| Docs pages | 28 | 40+ |
| Runtimes | 4 | 4 (same) |
| Protocols | 14 | 20+ |
| CLI commands | 0 | 6 (agent, memory, team, init, serve, eval) |
| MCP Server | No | Yes (15 tools + code REPL) |
| Code Agent Skills | 0 | 3 (Claude Code, Codex, OpenCode) |
| OTel support | No | Yes |
| A2A support | No | Yes |
| Eval framework | No | Yes |
| Structured output | Partial | Full (Pydantic) |
| Plugin system | No | Yes |
| HITL patterns | Partial | Full |
| Memory layers | 2 (message, fact) | 4 (+ episodic, procedural) |
| Headless mode | No | Yes (0 LLM calls) |
