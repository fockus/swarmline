# Testing Patterns

**Analysis Date:** 2026-04-12

## Test Framework

**Runner:**
- `pytest >= 8.0`
- Config: `pyproject.toml` under `[tool.pytest.ini_options]`

**Async:**
- `pytest-asyncio >= 0.24`
- `asyncio_mode = "auto"` — all coroutines auto-wrapped, no `@pytest.mark.asyncio` required on individual tests (though it appears in some older tests)

**Coverage:**
- `pytest-cov >= 5.0`

**Run Commands:**
```bash
pytest                                          # all offline tests (default: -m "not live")
pytest tests/unit/test_foo.py -v                # single file
pytest tests/unit/test_foo.py::TestBar::test_baz -v  # single test
pytest -k "test_name" -v                        # by name pattern
pytest -m integration -v                        # integration tests
pytest -m security -v                           # security tests
pytest -m "requires_claude_sdk" -v              # SDK-specific (needs pip install swarmline[claude])
pytest --cov=swarmline --cov-report=term-missing  # with coverage
```

## Test Markers

Defined in `pyproject.toml`:

| Marker | Purpose |
|--------|---------|
| `security` | Security regression and provider isolation |
| `requires_claude_sdk` | Requires `claude-agent-sdk` (`swarmline[claude]`) |
| `requires_anthropic` | Requires Anthropic SDK (`swarmline[thin]`) |
| `requires_langchain` | Requires LangChain (`swarmline[deepagents]`) |
| `live` | Requires network access (web search, API calls) |
| `integration` | Integration tests with external dependencies |

Default run: `addopts = ["-m", "not live"]` — live tests always excluded unless explicitly requested.

## Test File Organization

**Location:**
```
tests/
├── conftest.py          # Shared fixtures (FakeStreamEvent helper class)
├── unit/                # 235 files — isolated unit tests with mocks
├── integration/         # ~40 files — real components wired together, mock only external
├── e2e/                 # 15 files — full scenarios with mock SDK
├── security/            # 1 file — path isolation, policy parity across providers
└── _stubs.py            # Shared stub types used in tests
```

**Naming:**
- Files: `test_<module_or_feature>.py`
- Contract tests: `test_<entity>_contract.py` (e.g., `test_activity_log_contract.py`, `test_agent_tool_contract.py`)
- Integration: `test_<feature>_integration.py` or `test_<feature>_wiring.py`
- E2E: `test_<feature>_e2e.py`

## Test Structure

**Class-per-behavior** grouping (not one mega-class per module):
```python
class TestAgentQueryBasic:
    """Agent.query() - one-shot queries."""

    async def test_query_returns_result(self) -> None:
        """query() -> Result with text."""
        ...

class TestAgentQueryStructuredOutput:
    """Agent.query() - structured output scenarios."""
    ...
```

**Test naming**: `test_<what>_<condition>_<result>` at the method level:
```python
def test_query_with_messages_forwards_to_stream(self) -> None: ...
def test_query_without_messages_backward_compatible(self) -> None: ...
def test_loop_limit_reached(self) -> None: ...
def test_traversal_blocked_for_all_sandbox_providers(self) -> None: ...
```

**Arrange-Act-Assert** structure, kept explicit:
```python
async def test_middleware_chain_integration(self) -> None:
    # Arrange
    tracker = CostTracker(budget_usd=5.0)
    guard = SecurityGuard(block_patterns=["DROP TABLE"])
    config = AgentConfig(system_prompt="test", middleware=(tracker, guard))
    agent = Agent(config)

    # Act
    async def fake_stream(prompt, **_kwargs):
        yield FakeStreamEvent("done", text="result", is_final=True, total_cost_usd=0.5)

    with patch.object(agent, "_execute_stream", side_effect=fake_stream):
        result = await agent.query("hello")

    # Assert
    assert result.ok is True
    assert tracker.total_cost_usd == pytest.approx(0.5)
```

**Return types**: always `-> None` on test methods.

## Shared Fixtures

**`tests/conftest.py`** provides `FakeStreamEvent` — minimal mock for streaming events:
```python
class FakeStreamEvent:
    """Minimal StreamEvent-like mock for unit/integration/e2e tests."""
    def __init__(self, type: str = "done", text: str = "", **kwargs: Any) -> None:
        self.type = type
        self.text = text
        self.is_final = kwargs.get("is_final", False)
        self.session_id = kwargs.get("session_id")
        self.total_cost_usd = kwargs.get("total_cost_usd")
        # ... and other StreamEvent fields
```

Used across unit, integration, and e2e tests via `from conftest import FakeStreamEvent`.

**pytest fixtures** with `params` for contract tests:
```python
@pytest.fixture(params=["inmemory", "sqlite"])
def log(request, tmp_path):
    if request.param == "inmemory":
        from swarmline.observability.activity_log import InMemoryActivityLog
        return InMemoryActivityLog()
    else:
        from swarmline.observability.activity_log import SqliteActivityLog
        return SqliteActivityLog(str(tmp_path / "test.db"))
```

## Mocking

**Framework:** `unittest.mock` — `MagicMock`, `AsyncMock`, `patch`

**Primary pattern — `patch.object` on the seam:**
```python
with patch.object(agent, "_execute_stream", side_effect=fake_stream):
    result = await agent.query("Hi")
```

**Fake async generators** (standard pattern for streaming):
```python
async def fake_stream(prompt, **_kwargs):
    yield FakeStreamEvent("text_delta", text="Hello ")
    yield FakeStreamEvent("text_delta", text="World")
    yield FakeStreamEvent("done", text="Hello World", is_final=True, session_id="s1")
```

**Fake callable LLM** for ThinRuntime tests:
```python
class MockLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def __call__(self, messages: list[dict], system_prompt: str) -> str:
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp
```

**`AsyncMock`** for external service dependencies:
```python
mock_e2b = AsyncMock()
e2b = E2BSandboxProvider(config, _sandbox=mock_e2b)
```

**`pytest.importorskip`** for optional-dependency tests:
```python
aiosqlite = pytest.importorskip("aiosqlite", reason="aiosqlite not installed")
pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk not installed")
```

**What to mock:**
- External LLM calls (`llm_call` param in `ThinRuntime`)
- Stream execution seam (`_execute_stream` on `Agent`)
- External service SDK clients (e2b, docker, openshell sandboxes)
- Subprocess-based runtimes (Claude SDK subprocess)

**What NOT to mock:**
- Internal domain logic (`TurnContext`, `ContextPack`, `SkillSet`)
- In-memory implementations (`InMemoryMemoryProvider`, `InMemoryActivityLog`)
- Protocol compliance checks
- Tool decorator schema generation

## Contract Tests

Protocol compliance is verified via parametrized contract tests:

```python
# tests/unit/test_activity_log_contract.py
@pytest.fixture(params=["inmemory", "sqlite"])
def log(request, tmp_path): ...

class TestProtocolShape:
    def test_protocol_shape(self, log) -> None:
        from swarmline.observability.activity_log import ActivityLog
        assert isinstance(log, ActivityLog)

class TestBasicCRUD:
    async def test_log_and_query_all(self, log) -> None: ...
```

ISP compliance is tested directly:
```python
# tests/unit/test_protocol_contracts.py
@pytest.mark.parametrize(
    "protocol_cls,max_methods",
    [
        (RuntimePort, 5),
        (RoleSkillsProvider, 5),
        (SummaryGenerator, 5),
        (ModelSelector, 5),
    ],
)
def test_protocol_method_count(self, protocol_cls: type, max_methods: int) -> None:
    """Protocol has <= max_methods public methods/properties."""
    public = [name for name in dir(protocol_cls) if not name.startswith("_")]
    assert len(public) <= max_methods
```

## Parametrize

Use `@pytest.mark.parametrize` over copy-paste — 15 files use it:
```python
@pytest.mark.parametrize(
    ("member", "value"),
    [
        (LifecycleMode.EPHEMERAL, "ephemeral"),
        (LifecycleMode.SUPERVISED, "supervised"),
        (LifecycleMode.PERSISTENT, "persistent"),
    ],
)
def test_lifecycle_mode_values(self, member: LifecycleMode, value: str) -> None:
    assert member.value == value
```

## Test Helpers and Factories

Each test file defines local `_make_*` factory functions for test data:
```python
def _make_config(**overrides: Any) -> AgentConfig:
    defaults = {"system_prompt": "test prompt"}
    defaults.update(overrides)
    return AgentConfig(**defaults)

def _make_agent(config: AgentConfig | None = None, **overrides: Any) -> Agent:
    cfg = config or _make_config(**overrides)
    factory = MagicMock(spec=RuntimeFactoryPort)
    factory.validate_agent_config.return_value = None
    return Agent(cfg, runtime_factory=factory)
```

`tmp_path` (pytest built-in) used extensively for SQLite file databases and filesystem-based tests.

## Fixtures and Factories

**Location:** Local to each test file (no separate `fixtures/` directory).

**Pattern for integration setup:**
```python
@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """Create directory with prompts for tests."""
    (tmp_path / "identity.md").write_text("...", encoding="utf-8")
    (tmp_path / "guardrails.md").write_text("...", encoding="utf-8")
    return tmp_path

@pytest.fixture
def builder(prompts_dir: Path) -> DefaultContextBuilder:
    return DefaultContextBuilder(prompts_dir)
```

## Coverage

**Requirements:** Not enforced via `--cov-fail-under` in `pyproject.toml`. 4263 tests passing. Target per global RULES: 85%+ overall, 95%+ core/business, 70%+ infrastructure.

**View Coverage:**
```bash
pytest --cov=swarmline --cov-report=term-missing
pytest --cov=swarmline --cov-report=html  # HTML report
```

## Test Types

**Unit Tests** (`tests/unit/`, 235 files):
- Scope: single class or function in isolation
- Mock: external calls (LLM, SDK subprocess, DB)
- Use real domain objects (`AgentConfig`, `Result`, `TurnContext`)
- No network, no filesystem (except `tmp_path` for SQLite)

**Integration Tests** (`tests/integration/`, ~40 files):
- Scope: real components assembled together
- Mock: only truly external (LLM API, network)
- Use `ThinRuntime` with `MockLLM`/fake `llm_call` — real internal pipeline
- Verify full wiring: config → agent → middleware → result

**E2E Tests** (`tests/e2e/`, 15 files):
- Scope: full user-facing scenarios
- Mock: `_execute_stream` seam on `Agent` (replaces real SDK subprocess)
- Verify: `@tool` → `AgentConfig` → `Agent.query()` → `Result` with metrics

**Security Tests** (`tests/security/`, 1 file):
- Scope: path isolation parity across all sandbox providers
- `pytestmark = pytest.mark.security` at module level
- Tests same invariant across `LocalSandboxProvider`, `E2BSandboxProvider`, `DockerSandboxProvider`, `OpenShellSandboxProvider`

## Smoke/Import Tests

**`tests/unit/test_package_imports_smoke.py`** — subprocess-isolated import verification:
```python
@pytest.mark.parametrize(
    ("module_name", "expected_symbols"),
    [
        ("swarmline.daemon", ["DaemonRunner", "Scheduler", ...]),
        ("swarmline.multi_agent", ["AgentToolResult", ...]),
    ],
)
def test_module_imports_and_exports(module_name, expected_symbols): ...
```

Runs imports in clean subprocess via `subprocess.run` with explicit `PYTHONPATH` to catch circular imports and missing `__all__` entries.

## Common Patterns

**Async event collection** (used in ThinRuntime tests):
```python
async def collect(runtime: ThinRuntime, text: str = "test", ...) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="Test system prompt",
        active_tools=tools or [],
    ):
        events.append(ev)
    return events
```

**Frozen dataclass mutation test:**
```python
def test_frozen(self) -> None:
    ctx = TurnContext(user_id="u1", ...)
    with pytest.raises(AttributeError):
        ctx.user_id = "u2"  # type: ignore[misc]
```

**pytest.approx for floats:**
```python
assert tracker.total_cost_usd == pytest.approx(0.5)
```

**Security test — parity check across providers:**
```python
with pytest.raises(SandboxViolation):
    await local.read_file("../secret.txt")
with pytest.raises(SandboxViolation):
    await e2b.read_file("../secret.txt")
with pytest.raises(SandboxViolation):
    await docker.read_file("../secret.txt")
```

---

*Testing analysis: 2026-04-12*
