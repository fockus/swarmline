"""Code project team: multi-agent team that builds a project step by step.

Demonstrates: AgentRegistry, TaskQueue, WorkflowGraph -- full multi-agent orchestration.
No API keys required -- simulates team execution.
"""

from __future__ import annotations

import asyncio
import time

from swarmline.multi_agent.agent_registry import InMemoryAgentRegistry
from swarmline.multi_agent.registry_types import AgentRecord, AgentStatus
from swarmline.multi_agent.task_queue import InMemoryTaskQueue
from swarmline.multi_agent.task_types import TaskFilter, TaskItem, TaskPriority, TaskStatus
from swarmline.orchestration.workflow_graph import END_NODE, WorkflowGraph

# ---------------------------------------------------------------------------
# Team roster — IDs used across registry, tasks, and workflow state
# ---------------------------------------------------------------------------

ARCHITECT_ID = "agent-architect"
ANALYST_ID = "agent-analyst"
LEAD_ID = "agent-lead"
DEV_BACKEND_ID = "agent-dev-backend"
DEV_API_ID = "agent-dev-api"
TESTER_ID = "agent-tester"


async def bootstrap_team(registry: InMemoryAgentRegistry) -> None:
    """Register the full project team with hierarchy and roles."""
    agents = [
        AgentRecord(
            id=ARCHITECT_ID,
            name="Alice (Architect)",
            role="architect",
            runtime_name="thin",
            budget_limit_usd=5.0,
            metadata={"specialty": "system design, API contracts"},
        ),
        AgentRecord(
            id=ANALYST_ID,
            name="Bob (System Analyst)",
            role="analyst",
            runtime_name="thin",
            metadata={"specialty": "requirements, data modelling"},
        ),
        AgentRecord(
            id=LEAD_ID,
            name="Carol (Team Lead)",
            role="lead",
            runtime_name="thin",
            budget_limit_usd=2.0,
            metadata={"manages": [DEV_BACKEND_ID, DEV_API_ID, TESTER_ID]},
        ),
        AgentRecord(
            id=DEV_BACKEND_ID,
            name="Dave (Backend Dev)",
            role="developer",
            parent_id=LEAD_ID,
            runtime_name="thin",
            metadata={"lang": "python", "specialty": "ORM, business logic"},
        ),
        AgentRecord(
            id=DEV_API_ID,
            name="Eve (API Dev)",
            role="developer",
            parent_id=LEAD_ID,
            runtime_name="thin",
            metadata={"lang": "python", "specialty": "FastAPI, routing"},
        ),
        AgentRecord(
            id=TESTER_ID,
            name="Frank (QA Engineer)",
            role="tester",
            parent_id=LEAD_ID,
            runtime_name="thin",
            metadata={"specialty": "pytest, coverage, edge cases"},
        ),
    ]
    for agent in agents:
        await registry.register(agent)

    print("Team registered:")
    all_agents = await registry.list_agents()
    for a in all_agents:
        parent = f"  reports to {a.parent_id}" if a.parent_id else "  (top-level)"
        print(f"  [{a.role:10}] {a.name}{parent}")


async def enqueue_project_tasks(queue: InMemoryTaskQueue) -> list[TaskItem]:
    """Create all project tasks and put them into the queue."""
    now = time.time()
    tasks = [
        TaskItem(
            id="task-requirements",
            title="Clarify & document requirements",
            description="Interview stakeholder, produce a requirements spec for the Todo REST API.",
            priority=TaskPriority.CRITICAL,
            assignee_agent_id=ANALYST_ID,
            created_at=now,
        ),
        TaskItem(
            id="task-architecture",
            title="Design system architecture",
            description="Define layers, DB schema, OpenAPI contract. Produce ADR.",
            priority=TaskPriority.HIGH,
            assignee_agent_id=ARCHITECT_ID,
            created_at=now,
        ),
        TaskItem(
            id="task-backend-models",
            title="Implement domain models & DB layer",
            description="SQLAlchemy models: Todo, User. Migrations via Alembic.",
            priority=TaskPriority.HIGH,
            assignee_agent_id=DEV_BACKEND_ID,
            created_at=now,
        ),
        TaskItem(
            id="task-api-routes",
            title="Implement FastAPI routes",
            description="CRUD endpoints: POST /todos, GET /todos, PATCH /todos/{id}, DELETE /todos/{id}.",
            priority=TaskPriority.HIGH,
            assignee_agent_id=DEV_API_ID,
            created_at=now,
        ),
        TaskItem(
            id="task-testing",
            title="Write and run test suite",
            description="Unit + integration tests, pytest-cov ≥ 85%.",
            priority=TaskPriority.MEDIUM,
            assignee_agent_id=TESTER_ID,
            created_at=now,
        ),
        TaskItem(
            id="task-review",
            title="Team Lead code review & sign-off",
            description="Review PRs, check coverage report, approve merge.",
            priority=TaskPriority.MEDIUM,
            assignee_agent_id=LEAD_ID,
            created_at=now,
        ),
    ]
    for task in tasks:
        await queue.put(task)

    print(f"\n{len(tasks)} tasks enqueued:")
    for t in tasks:
        print(f"  [{t.priority.value:8}] {t.title}  →  {t.assignee_agent_id}")

    return tasks


# ---------------------------------------------------------------------------
# Simulated phase handlers — each accepts/returns workflow State
# ---------------------------------------------------------------------------

async def phase_analyze(state: dict) -> dict:
    """System Analyst: gather requirements."""
    print(f"\n--- PHASE: analyze  [{ANALYST_ID}] ---")
    registry: InMemoryAgentRegistry = state["registry"]
    queue: InMemoryTaskQueue = state["queue"]

    await registry.update_status(ANALYST_ID, AgentStatus.RUNNING)

    task = await queue.get(TaskFilter(assignee_agent_id=ANALYST_ID))
    if task:
        print(f"  Working on: {task.title}")
        print("  Output: Todo API must support CRUD for todo items.")
        print("          Auth via JWT. Pagination on list endpoint.")
        await queue.complete(task.id)
        print(f"  Task '{task.id}' → DONE")

    await registry.update_status(ANALYST_ID, AgentStatus.IDLE)
    state["requirements"] = "CRUD todos, JWT auth, pagination"
    return state


async def phase_design(state: dict) -> dict:
    """Architect: design system."""
    print(f"\n--- PHASE: design  [{ARCHITECT_ID}] ---")
    registry: InMemoryAgentRegistry = state["registry"]
    queue: InMemoryTaskQueue = state["queue"]

    await registry.update_status(ARCHITECT_ID, AgentStatus.RUNNING)

    task = await queue.get(TaskFilter(assignee_agent_id=ARCHITECT_ID))
    if task:
        print(f"  Working on: {task.title}")
        print("  ADR: FastAPI + SQLAlchemy + PostgreSQL.")
        print("  Schema: todos(id, title, done, owner_id), users(id, email, hashed_pw).")
        print("  OpenAPI contract written to openapi.yaml.")
        await queue.complete(task.id)
        print(f"  Task '{task.id}' → DONE")

    await registry.update_status(ARCHITECT_ID, AgentStatus.IDLE)
    state["architecture"] = "FastAPI + SQLAlchemy + PostgreSQL"
    return state


async def phase_implement(state: dict) -> dict:
    """Developers: backend models + API routes in parallel."""
    print(f"\n--- PHASE: implement  [{DEV_BACKEND_ID}, {DEV_API_ID}] ---")
    registry: InMemoryAgentRegistry = state["registry"]
    queue: InMemoryTaskQueue = state["queue"]

    # Both developers go RUNNING simultaneously
    await asyncio.gather(
        registry.update_status(DEV_BACKEND_ID, AgentStatus.RUNNING),
        registry.update_status(DEV_API_ID, AgentStatus.RUNNING),
    )

    async def run_dev(agent_id: str, artifact_key: str, artifact_value: str) -> str:
        task = await queue.get(TaskFilter(assignee_agent_id=agent_id))
        if task:
            print(f"  [{agent_id}] Working on: {task.title}")
            await asyncio.sleep(0)  # yield — simulates concurrent work
            print(f"  [{agent_id}] Committed: {artifact_value}")
            await queue.complete(task.id)
            print(f"  [{agent_id}] Task '{task.id}' → DONE")
        return artifact_value

    results = await asyncio.gather(
        run_dev(DEV_BACKEND_ID, "backend", "models.py, migrations/"),
        run_dev(DEV_API_ID, "api", "routers/todos.py, routers/auth.py"),
    )

    await asyncio.gather(
        registry.update_status(DEV_BACKEND_ID, AgentStatus.IDLE),
        registry.update_status(DEV_API_ID, AgentStatus.IDLE),
    )

    state["implementation"] = {"backend": results[0], "api": results[1]}
    return state


async def phase_test(state: dict) -> dict:
    """QA Engineer: run the test suite."""
    print(f"\n--- PHASE: test  [{TESTER_ID}] ---")
    registry: InMemoryAgentRegistry = state["registry"]
    queue: InMemoryTaskQueue = state["queue"]

    await registry.update_status(TESTER_ID, AgentStatus.RUNNING)

    task = await queue.get(TaskFilter(assignee_agent_id=TESTER_ID))
    if task:
        print(f"  Working on: {task.title}")
        print("  Running: pytest tests/ --cov=app")
        print("  Results: 42 passed, 0 failed — coverage 91%")
        await queue.complete(task.id)
        print(f"  Task '{task.id}' → DONE")

    await registry.update_status(TESTER_ID, AgentStatus.IDLE)
    state["test_coverage"] = 91
    state["tests_passed"] = True
    return state


def review_decision(state: dict) -> str:
    """Route: approve if tests pass and coverage ≥ 85%, else reject."""
    if state.get("tests_passed") and state.get("test_coverage", 0) >= 85:
        return "review_approve"
    return "review_reject"


async def phase_review_approve(state: dict) -> dict:
    """Team Lead: sign off and close the project."""
    print(f"\n--- PHASE: review (APPROVE)  [{LEAD_ID}] ---")
    registry: InMemoryAgentRegistry = state["registry"]
    queue: InMemoryTaskQueue = state["queue"]

    await registry.update_status(LEAD_ID, AgentStatus.RUNNING)

    task = await queue.get(TaskFilter(assignee_agent_id=LEAD_ID))
    if task:
        print(f"  Working on: {task.title}")
        print("  All PRs reviewed. Coverage 91% ≥ 85%. LGTM — merging to main.")
        await queue.complete(task.id)
        print(f"  Task '{task.id}' → DONE")

    await registry.update_status(LEAD_ID, AgentStatus.STOPPED)
    state["project_status"] = "SHIPPED"
    return state


async def phase_review_reject(state: dict) -> dict:
    """Team Lead: reject — send back to testing."""
    print(f"\n--- PHASE: review (REJECT)  [{LEAD_ID}] ---")
    registry: InMemoryAgentRegistry = state["registry"]
    queue: InMemoryTaskQueue = state["queue"]

    await registry.update_status(LEAD_ID, AgentStatus.RUNNING)

    task = await queue.get(TaskFilter(assignee_agent_id=LEAD_ID))
    if task:
        print("  Coverage below threshold or tests failed. Sending back to QA.")
        # Re-enqueue testing task
        retry = TaskItem(
            id="task-testing-retry",
            title="Re-run test suite (retry)",
            description="Fix failing tests, improve coverage.",
            priority=TaskPriority.HIGH,
            assignee_agent_id=TESTER_ID,
            created_at=time.time(),
        )
        await queue.put(retry)

    await registry.update_status(LEAD_ID, AgentStatus.IDLE)
    state["tests_passed"] = True  # force approve on retry
    state["test_coverage"] = 88
    return state


# ---------------------------------------------------------------------------
# Shutdown: mark all agents STOPPED
# ---------------------------------------------------------------------------

async def shutdown_team(registry: InMemoryAgentRegistry) -> None:
    all_agents = await registry.list_agents()
    for agent in all_agents:
        if agent.status != AgentStatus.STOPPED:
            await registry.update_status(agent.id, AgentStatus.STOPPED)


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

async def print_summary(registry: InMemoryAgentRegistry, queue: InMemoryTaskQueue) -> None:
    print("\n" + "=" * 60)
    print("PROJECT SUMMARY")
    print("=" * 60)

    all_agents = await registry.list_agents()
    print("\nAgent statuses:")
    for a in all_agents:
        print(f"  [{a.status.value:7}] {a.name}")

    all_tasks = await queue.list_tasks()
    by_status: dict[str, list[str]] = {}
    for t in all_tasks:
        by_status.setdefault(t.status.value, []).append(t.title)

    print("\nTask statuses:")
    for status_val, titles in sorted(by_status.items()):
        for title in titles:
            print(f"  [{status_val:11}] {title}")

    done_count = len(await queue.list_tasks(TaskFilter(status=TaskStatus.DONE)))
    total_count = len(all_tasks)
    print(f"\nCompleted: {done_count}/{total_count} tasks")


# ---------------------------------------------------------------------------
# Build the project pipeline as a WorkflowGraph
# ---------------------------------------------------------------------------

def build_pipeline(registry: InMemoryAgentRegistry, queue: InMemoryTaskQueue) -> WorkflowGraph:
    graph = WorkflowGraph("todo-api-project")

    graph.add_node("analyze", phase_analyze)
    graph.add_node("design", phase_design)
    graph.add_node("implement", phase_implement)
    graph.add_node("test", phase_test)
    graph.add_node("review_approve", phase_review_approve)
    graph.add_node("review_reject", phase_review_reject)

    graph.add_edge("analyze", "design")
    graph.add_edge("design", "implement")
    graph.add_edge("implement", "test")

    # After test, route conditionally
    graph.add_conditional_edge("test", review_decision)

    graph.add_edge("review_approve", END_NODE)
    graph.add_edge("review_reject", "test")   # retry loop

    graph.set_entry("analyze")
    graph.set_max_loops("test", max_loops=3)  # guard against infinite retry

    return graph


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main() -> None:
    project = "Build a REST API for a todo app"
    print("=" * 60)
    print(f"PROJECT: {project}")
    print("=" * 60)

    registry = InMemoryAgentRegistry()
    queue = InMemoryTaskQueue()

    # 1. Register the team
    print("\n[1] Bootstrapping team...")
    await bootstrap_team(registry)

    # 2. Enqueue all project tasks
    print("\n[2] Creating project backlog...")
    await enqueue_project_tasks(queue)

    # 3. Show pipeline structure
    graph = build_pipeline(registry, queue)
    print(f"\n[3] Pipeline topology:\n{graph.to_mermaid()}")

    # 4. Execute the project pipeline
    print("\n[4] Executing project pipeline...")
    initial_state: dict = {"registry": registry, "queue": queue}
    final_state = await graph.execute(initial_state)

    # 5. Shutdown all agents
    await shutdown_team(registry)

    # 6. Print summary
    await print_summary(registry, queue)

    status = final_state.get("project_status", "UNKNOWN")
    coverage = final_state.get("test_coverage", 0)
    print(f"\nProject status : {status}")
    print(f"Test coverage  : {coverage}%")
    print(f"Architecture   : {final_state.get('architecture', 'n/a')}")


if __name__ == "__main__":
    asyncio.run(main())
