"""Golden task suite — built-in reference tasks for coding evaluation."""

from __future__ import annotations

from swarmline.eval.coding_types import GoldenTask, TaskCategory


def _built_in_tasks() -> tuple[GoldenTask, ...]:
    """Create the 5 built-in golden tasks (one per category)."""
    return (
        GoldenTask(
            task_id="golden-bugfix-001",
            category=TaskCategory.BUGFIX,
            name="Fix off-by-one in pagination",
            description=(
                "The pagination helper returns one extra item when the total "
                "is exactly divisible by page_size. Fix the boundary condition."
            ),
            setup_files={
                "paginator.py": (
                    "def paginate(items: list, page: int, page_size: int) -> list:\n"
                    "    start = page * page_size\n"
                    "    end = start + page_size + 1  # BUG: +1\n"
                    "    return items[start:end]\n"
                ),
            },
            expected_outcomes=(
                "off-by-one fixed",
                "tests pass",
                "no extra items returned",
            ),
            tags=("python", "pagination", "boundary"),
        ),
        GoldenTask(
            task_id="golden-refactor-001",
            category=TaskCategory.REFACTOR,
            name="Extract validation logic from handler",
            description=(
                "The request handler has inline validation logic (>50 lines). "
                "Extract it into a dedicated Validator class following SRP."
            ),
            setup_files={
                "handler.py": (
                    "class RequestHandler:\n"
                    "    def handle(self, data: dict) -> dict:\n"
                    "        # 50+ lines of validation mixed with business logic\n"
                    "        if not data.get('name'):\n"
                    "            raise ValueError('name required')\n"
                    "        return {'status': 'ok'}\n"
                ),
            },
            expected_outcomes=(
                "validation extracted to separate class",
                "handler delegates to validator",
                "tests pass",
            ),
            tags=("python", "srp", "refactor"),
        ),
        GoldenTask(
            task_id="golden-test-writing-001",
            category=TaskCategory.TEST_WRITING,
            name="Add tests for token bucket rate limiter",
            description=(
                "The TokenBucket class has no tests. Write comprehensive tests "
                "covering: allow/deny, refill, burst, and edge cases."
            ),
            setup_files={
                "rate_limiter.py": (
                    "import time\n"
                    "class TokenBucket:\n"
                    "    def __init__(self, capacity: int, refill_rate: float):\n"
                    "        self.capacity = capacity\n"
                    "        self.tokens = capacity\n"
                    "        self.refill_rate = refill_rate\n"
                    "        self.last_refill = time.monotonic()\n"
                    "    def allow(self) -> bool:\n"
                    "        self._refill()\n"
                    "        if self.tokens > 0:\n"
                    "            self.tokens -= 1\n"
                    "            return True\n"
                    "        return False\n"
                    "    def _refill(self) -> None:\n"
                    "        now = time.monotonic()\n"
                    "        elapsed = now - self.last_refill\n"
                    "        self.tokens = min(self.capacity, "
                    "self.tokens + elapsed * self.refill_rate)\n"
                    "        self.last_refill = now\n"
                ),
            },
            expected_outcomes=(
                "tests cover allow and deny",
                "tests cover refill behavior",
                "tests cover burst capacity",
                "edge cases tested",
            ),
            tags=("python", "testing", "rate-limiter"),
        ),
        GoldenTask(
            task_id="golden-migration-001",
            category=TaskCategory.MIGRATION,
            name="Migrate config from dict to pydantic Settings",
            description=(
                "Replace the raw dict-based configuration with a pydantic "
                "BaseSettings model. Preserve all existing config keys."
            ),
            setup_files={
                "config.py": (
                    "CONFIG = {\n"
                    "    'db_url': 'sqlite:///app.db',\n"
                    "    'debug': False,\n"
                    "    'max_workers': 4,\n"
                    "}\n"
                ),
            },
            expected_outcomes=(
                "pydantic BaseSettings model created",
                "all config keys preserved",
                "type validation works",
                "tests pass",
            ),
            tags=("python", "pydantic", "migration"),
        ),
        GoldenTask(
            task_id="golden-review-001",
            category=TaskCategory.REVIEW,
            name="Review PR for security issues",
            description=(
                "Review a pull request that adds user input handling. "
                "Identify SQL injection, XSS, and missing input validation."
            ),
            setup_files={
                "user_api.py": (
                    "def get_user(db, user_id: str) -> dict:\n"
                    "    query = f'SELECT * FROM users WHERE id = {user_id}'\n"
                    "    return db.execute(query).fetchone()\n"
                    "def render_profile(name: str) -> str:\n"
                    "    return f'<h1>{name}</h1>'\n"
                ),
            },
            expected_outcomes=(
                "SQL injection identified",
                "XSS vulnerability identified",
                "parameterized query recommended",
                "output escaping recommended",
            ),
            tags=("security", "review", "owasp"),
        ),
    )


class GoldenTaskSuite:
    """In-memory registry of golden reference tasks for coding evaluation.

    Pre-loaded with 5 built-in tasks (one per TaskCategory).
    Supports registration of custom tasks.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, GoldenTask] = {}
        for task in _built_in_tasks():
            self._tasks[task.task_id] = task

    def list_tasks(self) -> tuple[GoldenTask, ...]:
        return tuple(self._tasks.values())

    def get_task(self, task_id: str) -> GoldenTask | None:
        return self._tasks.get(task_id)

    def filter_by_category(self, category: TaskCategory) -> tuple[GoldenTask, ...]:
        return tuple(t for t in self._tasks.values() if t.category == category)

    def register_task(self, task: GoldenTask) -> None:
        self._tasks[task.task_id] = task
