"""Stage 3 (Sprint 1A): lock typed access to CursorResult.rowcount in
PostgresAgentRegistry.delete.

Background: SQLAlchemy 2.x `session.execute()` returns abstract `Result[Any]`,
which does not expose `.rowcount`. Only the concrete `CursorResult` (returned
for DML statements) has it. Original code used `result.rowcount  # type: ignore[attr-defined]`
to silence ty — Stage 3 replaces the silencing with an explicit `cast()` to
`CursorResult` and removes the ignore.

These tests run only when a Postgres DSN is provided (env var `PG_DSN` or
`SWARMLINE_TEST_PG_DSN`). Without it, the entire module is skipped — keeps
local dev runs frictionless while CI can wire up a service container.
"""

from __future__ import annotations

import inspect
import os

import pytest

pytestmark = pytest.mark.integration

# Skip module entirely if asyncpg / sqlalchemy / Postgres DSN unavailable
asyncpg = pytest.importorskip("asyncpg")
sqlalchemy_asyncio = pytest.importorskip("sqlalchemy.ext.asyncio")

PG_DSN = os.environ.get("PG_DSN") or os.environ.get("SWARMLINE_TEST_PG_DSN")

requires_pg_dsn = pytest.mark.skipif(
    PG_DSN is None,
    reason="Postgres DSN not set (set PG_DSN or SWARMLINE_TEST_PG_DSN to run)",
)


from swarmline.multi_agent.agent_registry_postgres import (  # noqa: E402
    PostgresAgentRegistry,
)
from swarmline.multi_agent.registry_types import AgentRecord, AgentStatus  # noqa: E402


def test_remove_method_uses_cursor_result_cast_not_type_ignore() -> None:
    """Source-level invariant: remove() casts to CursorResult, no type:ignore.

    Locks the Stage 3 fix — without this guard, future refactors could re-add
    `# type: ignore[attr-defined]` and silently regress ty count.
    """
    source = inspect.getsource(PostgresAgentRegistry.remove)
    assert "CursorResult" in source, (
        "remove() should cast to CursorResult to access rowcount typed-correctly"
    )
    assert "type: ignore[attr-defined]" not in source, (
        "remove() must not silence ty via type:ignore — use cast(CursorResult, ...) instead"
    )


@pytest.fixture
async def registry():
    """Real PostgresAgentRegistry with a fresh schema."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(PG_DSN, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    reg = PostgresAgentRegistry(session_maker, namespace="test_stage3")
    await reg.initialize()
    yield reg
    # Teardown: drop the agents created
    async with session_maker() as session:
        from sqlalchemy import text

        await session.execute(
            text("DELETE FROM agent_registry WHERE namespace = :ns"),
            {"ns": "test_stage3"},
        )
        await session.commit()
    await engine.dispose()


@pytest.mark.integration
@requires_pg_dsn
async def test_remove_returns_true_when_agent_exists(
    registry: PostgresAgentRegistry,
) -> None:
    """remove() returns True for existing agent (rowcount > 0)."""
    agent = AgentRecord(
        id="agent-stage3-existing",
        role="researcher",
        capabilities=("research",),
        status=AgentStatus.IDLE,
        metadata={},
    )
    await registry.register(agent)

    deleted = await registry.remove("agent-stage3-existing")
    assert deleted is True


@pytest.mark.integration
@requires_pg_dsn
async def test_remove_returns_false_when_agent_missing(
    registry: PostgresAgentRegistry,
) -> None:
    """remove() returns False for non-existent agent (rowcount == 0)."""
    deleted = await registry.remove("agent-stage3-nonexistent")
    assert deleted is False
