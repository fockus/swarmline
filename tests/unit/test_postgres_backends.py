"""Smoke tests for Postgres backends.

These tests intentionally stay shallow: importability, schema constants,
and constructor shape only. Real behavior belongs in integration tests that
run against an actual Postgres database.
"""

from __future__ import annotations

import inspect


class TestImports:
    def test_import_postgres_agent_graph(self) -> None:
        from swarmline.multi_agent.graph_store_postgres import PostgresAgentGraph

        assert PostgresAgentGraph is not None

    def test_import_postgres_graph_task_board(self) -> None:
        from swarmline.multi_agent.graph_task_board_postgres import PostgresGraphTaskBoard

        assert PostgresGraphTaskBoard is not None

    def test_import_postgres_graph_communication(self) -> None:
        from swarmline.multi_agent.graph_communication_postgres import PostgresGraphCommunication

        assert PostgresGraphCommunication is not None

    def test_import_postgres_task_queue(self) -> None:
        from swarmline.multi_agent.task_queue_postgres import PostgresTaskQueue

        assert PostgresTaskQueue is not None

    def test_import_postgres_agent_registry(self) -> None:
        from swarmline.multi_agent.agent_registry_postgres import PostgresAgentRegistry

        assert PostgresAgentRegistry is not None

    def test_import_postgres_episodic_memory(self) -> None:
        from swarmline.memory.episodic_postgres import PostgresEpisodicMemory

        assert PostgresEpisodicMemory is not None

    def test_import_postgres_procedural_memory(self) -> None:
        from swarmline.memory.procedural_postgres import PostgresProceduralMemory

        assert PostgresProceduralMemory is not None

    def test_import_postgres_session_backend(self) -> None:
        from swarmline.session.backends_postgres import PostgresSessionBackend

        assert PostgresSessionBackend is not None


class TestSchemas:
    def test_graph_schema_exists(self) -> None:
        from swarmline.multi_agent.graph_store_postgres import POSTGRES_GRAPH_SCHEMA

        assert "agent_nodes" in POSTGRES_GRAPH_SCHEMA

    def test_task_board_schema_exists(self) -> None:
        from swarmline.multi_agent.graph_task_board_postgres import POSTGRES_GRAPH_TASK_SCHEMA

        assert "graph_tasks" in POSTGRES_GRAPH_TASK_SCHEMA

    def test_communication_schema_exists(self) -> None:
        from swarmline.multi_agent.graph_communication_postgres import POSTGRES_GRAPH_COMM_SCHEMA

        assert "graph_messages" in POSTGRES_GRAPH_COMM_SCHEMA

    def test_task_queue_schema_exists(self) -> None:
        from swarmline.multi_agent.task_queue_postgres import POSTGRES_TASK_QUEUE_SCHEMA

        assert "task_queue" in POSTGRES_TASK_QUEUE_SCHEMA

    def test_agent_registry_schema_exists(self) -> None:
        from swarmline.multi_agent.agent_registry_postgres import POSTGRES_AGENT_REGISTRY_SCHEMA

        assert "agent_registry" in POSTGRES_AGENT_REGISTRY_SCHEMA

    def test_episodic_schema_exists(self) -> None:
        from swarmline.memory.episodic_postgres import POSTGRES_EPISODIC_SCHEMA

        assert "episodes" in POSTGRES_EPISODIC_SCHEMA

    def test_procedural_schema_exists(self) -> None:
        from swarmline.memory.procedural_postgres import POSTGRES_PROCEDURAL_SCHEMA

        assert "procedures" in POSTGRES_PROCEDURAL_SCHEMA

    def test_session_schema_exists(self) -> None:
        from swarmline.session.backends_postgres import POSTGRES_SESSION_SCHEMA

        assert "sessions" in POSTGRES_SESSION_SCHEMA


class TestConstructors:
    def test_all_take_session_factory(self) -> None:
        from swarmline.memory.episodic_postgres import PostgresEpisodicMemory
        from swarmline.memory.procedural_postgres import PostgresProceduralMemory
        from swarmline.multi_agent.agent_registry_postgres import PostgresAgentRegistry
        from swarmline.multi_agent.graph_store_postgres import PostgresAgentGraph
        from swarmline.multi_agent.graph_task_board_postgres import PostgresGraphTaskBoard
        from swarmline.multi_agent.task_queue_postgres import PostgresTaskQueue
        from swarmline.session.backends_postgres import PostgresSessionBackend

        for cls in [
            PostgresAgentGraph,
            PostgresGraphTaskBoard,
            PostgresTaskQueue,
            PostgresAgentRegistry,
            PostgresEpisodicMemory,
            PostgresProceduralMemory,
            PostgresSessionBackend,
        ]:
            params = list(inspect.signature(cls.__init__).parameters.keys())
            assert "session_factory" in params, f"{cls.__name__} missing session_factory param"

    def test_communication_takes_graph_query(self) -> None:
        from swarmline.multi_agent.graph_communication_postgres import PostgresGraphCommunication

        params = list(inspect.signature(PostgresGraphCommunication.__init__).parameters.keys())
        assert "session_factory" in params
        assert "graph_query" in params
