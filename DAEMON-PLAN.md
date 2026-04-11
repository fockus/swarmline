# Swarmline Daemon Module — Plan

> Для поддержки 24/7 autonomous mode в Code Factory v2.
> Daemon = отдельный Python процесс, переживает restart Claude Code.

## Контекст

Code Factory v2 имеет 3 уровня heartbeat:
- Level 1: asyncio loop внутри MCP сервера (живёт пока Claude Code открыт)
- Level 2: persist + resume через SQLite state (между сессиями)
- **Level 3: External daemon** (этот план) — 24/7, как systemd service

## Что УЖЕ есть в Swarmline (переиспользуем)

| Компонент | Файл | Что делает |
|-----------|------|------------|
| `CliAgentRuntime` | `runtime/cli/runtime.py` | Запуск claude через subprocess, NDJSON parsing |
| `Pipeline` | `pipeline/pipeline.py` | Phase-based execution с gates и budget |
| `PipelineRunner` | `pipeline/runner.py` | Convenience wrapper для Pipeline |
| `BudgetTracker` | `pipeline/budget.py` | Budget control |
| `EventBus` | `observability/event_bus.py` | Event system |
| `SessionManager` | `session/manager.py` | Session lifecycle с TTL |
| `ExponentialBackoff` | `retry.py` | Retry с backoff и jitter |
| `ModelFallbackChain` | `retry.py` | Fallback на другую модель при rate limit |
| `ToolBudget` | `policy/tool_budget.py` | Per-turn tool call limits |
| `GraphStore/TaskBoard/Comm` | `multi_agent/graph_*` | Вся graph infrastructure |
| `SandboxProvider` | `tools/sandbox_*.py` | 4 sandbox provider'а |

## Что НУЖНО добавить

### Новый модуль: `swarmline/daemon/`

```
src/swarmline/daemon/
├── __init__.py
├── runner.py          # Main daemon loop (asyncio.run + signal handling)
├── scheduler.py       # Cron-like asyncio scheduler (periodic tasks)
├── health.py          # Health check (HTTP endpoint or Unix socket)
├── pid.py             # PID file management (prevent double-start)
├── config.py          # DaemonConfig dataclass
└── cli_entry.py       # CLI entry point: swarmline-daemon command
```

### runner.py — DaemonRunner

```python
class DaemonRunner:
    """Long-running daemon process. Manages lifecycle of factory pipeline.

    Uses:
        - CliAgentRuntime: spawn claude agents
        - Pipeline + PipelineRunner: execute phases
        - EventBus: react to events
        - Scheduler: periodic health checks
        - Graph*: agent/task/comm management

    Responsibilities:
        - Signal handling (SIGTERM → graceful shutdown, SIGINT → immediate)
        - PID file (prevent double-start)
        - Health endpoint (is daemon alive? what's it doing?)
        - Log rotation (structlog to file with rotation)
        - Recovery from crash (read SQLite state, resume)
    """

    def __init__(self, config: DaemonConfig):
        self.config = config
        self.scheduler = Scheduler()
        self.health = HealthCheck(port=config.health_port)
        self.pid = PidFile(config.pid_path)
        self._shutdown = asyncio.Event()

    async def run(self):
        """Main entry point. Blocks until shutdown signal."""
        self.pid.acquire()  # raises if already running
        self._setup_signals()

        try:
            # Init Swarmline components
            graph = SqliteAgentGraph(db_path=self.config.agent_db_path)
            task_board = SqliteGraphTaskBoard(db_path=self.config.agent_db_path)
            comm = SqliteGraphCommunication(graph_query=graph, db_path=self.config.agent_db_path)
            event_bus = InMemoryEventBus()

            # Init factory pipeline (import from swarmline[factory])
            from swarmline.factory.pipeline import SprintPipeline
            pipeline = SprintPipeline(graph=graph, task_board=task_board, ...)

            # Schedule periodic tasks
            self.scheduler.every(self.config.health_check_interval, pipeline.meta_supervisor.system_health_check)
            self.scheduler.every(self.config.sprint_check_interval, self._check_and_start_sprint)

            # Start health endpoint
            await self.health.start()

            # Main loop — runs until SIGTERM/SIGINT
            await self.scheduler.run_until(self._shutdown)

        finally:
            await self._graceful_shutdown()
            self.pid.release()

    def _setup_signals(self):
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: self._shutdown.set())

    async def _graceful_shutdown(self):
        """Save state, cleanup agents, close connections."""
        # 1. Pause current sprint (save step to DB)
        # 2. Cleanup all agents (status=ended)
        # 3. Close health endpoint
        # 4. Flush logs
```

### scheduler.py — Scheduler

```python
class Scheduler:
    """asyncio-based periodic task scheduler.

    Unlike CronCreate: runs IN-PROCESS, no external dependency.
    Unlike crontab: lives with the daemon process, not OS-level.
    """

    def every(self, seconds: int, coro_factory: Callable, name: str = ""):
        """Register a periodic task."""

    def once_at(self, timestamp: float, coro_factory: Callable, name: str = ""):
        """Schedule a one-time task."""

    async def run_until(self, stop_event: asyncio.Event):
        """Run scheduler until stop event is set."""

    def cancel(self, name: str):
        """Cancel a scheduled task by name."""

    def list_tasks(self) -> list[ScheduledTask]:
        """List all registered tasks with next_run times."""
```

### health.py — HealthCheck

```python
class HealthCheck:
    """Simple HTTP health endpoint for monitoring.

    GET /health → {"status": "running", "uptime": 3600, "current_sprint": "s2", ...}
    GET /status → full factory status (same as /factory:status)
    POST /pause → pause scheduler
    POST /resume → resume scheduler
    """

    def __init__(self, port: int = 8471):
        ...

    async def start(self):
        """Start aiohttp server."""

    async def stop(self):
        """Stop server."""
```

### pid.py — PidFile

```python
class PidFile:
    """PID file management. Prevents double-start."""

    def acquire(self) -> None:
        """Write PID. Raises if file exists and process alive."""

    def release(self) -> None:
        """Remove PID file."""

    def is_running(self) -> bool:
        """Check if daemon is already running."""
```

### config.py — DaemonConfig

```python
@dataclass(frozen=True)
class DaemonConfig:
    # Paths
    factory_db_path: str = "factory.db"
    agent_db_path: str = "factory_agents.db"
    pid_path: str = "~/.swarmline/factory-daemon.pid"
    log_path: str = "~/.swarmline/factory-daemon.log"

    # Scheduling
    health_check_interval: int = 900     # 15 min
    sprint_check_interval: int = 300     # 5 min
    pm_analysis_interval: int = 600      # 10 min

    # Health endpoint
    health_port: int = 8471

    # Rate limiting
    max_concurrent_agents: int = 5
    cooldown_after_429: int = 60         # seconds
    max_requests_per_minute: int = 50

    # Budget
    max_budget_usd: float = 100.0
    warn_budget_percent: float = 80.0

    # Mission (for continuous mode)
    mission: str = ""                    # Global goal/mission
    auto_plan_sprints: bool = True       # Auto-create new sprints
```

### cli_entry.py — CLI Entry Point

```python
"""CLI entry point for swarmline-daemon.

Usage:
    swarmline-daemon start --config factory-daemon.yaml
    swarmline-daemon stop
    swarmline-daemon status
    swarmline-daemon pause
    swarmline-daemon resume

Registered as console_script in pyproject.toml:
    [project.scripts]
    swarmline-daemon = "swarmline.daemon.cli_entry:main"
"""

def main():
    parser = argparse.ArgumentParser(description="Swarmline Factory Daemon")
    subparsers = parser.add_subparsers()

    # start: launch daemon (foreground or background with --daemon flag)
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--config", required=True)
    start_parser.add_argument("--daemon", action="store_true", help="Run in background")

    # stop: send SIGTERM to PID
    stop_parser = subparsers.add_parser("stop")

    # status: query health endpoint
    status_parser = subparsers.add_parser("status")

    # pause/resume: POST to health endpoint
    pause_parser = subparsers.add_parser("pause")
    resume_parser = subparsers.add_parser("resume")
```

## pyproject.toml изменения

```toml
[project.optional-dependencies]
factory = ["swarmline[factory]"]
daemon = [
    "swarmline[factory]",
    "aiohttp>=3.9",           # health endpoint
    "structlog>=24.0",        # structured logging
]

[project.scripts]
swarmline-daemon = "swarmline.daemon.cli_entry:main"
```

## Integration с Code Factory v2

```
                    Code Factory v2
                    ══════════════

Level 1 (in-session):
  Claude Code → MCP server → factory pipeline (asyncio loop)
  Живёт пока Claude Code открыт.

Level 2 (between sessions):
  /factory:pause → SQLite state saved
  /factory:resume → read state → continue

Level 3 (daemon):
  swarmline-daemon start --config factory-daemon.yaml
      │
      ├── DaemonRunner.run()
      │   ├── CliAgentRuntime (claude subprocess)
      │   ├── Scheduler (heartbeat, health checks)
      │   ├── HealthCheck (HTTP :8471)
      │   └── Pipeline (SprintPipeline from factory module)
      │
      ├── Живёт как процесс (systemd/launchd/nohup)
      │   Переживает restart Claude Code
      │
      ├── Claude Code подключается к ТОМУ ЖЕ factory.db
      │   /factory:status → reads DB → shows daemon state
      │   /factory:pause → POST :8471/pause
      │
      └── Graceful shutdown:
          SIGTERM → save state → cleanup agents → exit
```

## DoD

- [ ] `daemon/runner.py`: DaemonRunner с signal handling, PID, graceful shutdown
- [ ] `daemon/scheduler.py`: asyncio periodic scheduler (every, once_at, cancel, list)
- [ ] `daemon/health.py`: HTTP health endpoint (aiohttp, /health, /status, /pause, /resume)
- [ ] `daemon/pid.py`: PID file management (acquire, release, is_running)
- [ ] `daemon/config.py`: DaemonConfig dataclass с defaults
- [ ] `daemon/cli_entry.py`: CLI (start, stop, status, pause, resume)
- [ ] pyproject.toml: `swarmline[daemon]` extra, console_script entry point
- [ ] Integration test: start daemon → create sprint → daemon runs it → stop daemon → state preserved
- [ ] Integration test: daemon + Claude Code simultaneous access to same factory.db (WAL)
- [ ] Unit tests: scheduler timing, PID lock, signal handling, health endpoint

## Зависимости от Swarmline (уже есть, НЕ нужно менять)

- CliAgentRuntime → запуск claude агентов
- Pipeline + PipelineRunner → execution
- EventBus → events
- Graph* → agents, tasks, communication
- ExponentialBackoff → retry
- SessionManager → session lifecycle
- SandboxProvider → safe execution (optional)

## Зависимости от Factory (swarmline[factory])

- SprintPipeline → sprint execution
- MetaSupervisor → system health
- Domain repos → SQLite state
- RateLimiter → Anthropic rate limit awareness

## Заметки

1. **Daemon НЕ заменяет Level 1/2** — это дополнительный режим для 24/7
2. **Claude Code может подключаться к работающему daemon** — через shared factory.db + health API
3. **Один daemon per project** — PID file предотвращает double-start
4. **aiohttp = единственная новая зависимость** — для health endpoint (можно заменить на stdlib http.server если не хочется)
5. **launchd/systemd интеграция** — пользователь настраивает сам (мы даём примеры .plist / .service)
