"""Unit: Verify all Postgres backends are importable and match their protocols.

These tests do NOT require a running Postgres instance — they only
verify that classes import correctly, have the expected methods,
and match protocol shapes.
"""

from __future__ import annotations

import inspect



# ---------------------------------------------------------------------------
# Import tests — all backends importable
# ---------------------------------------------------------------------------


class TestImports:

    def test_import_postgres_agent_graph(self) -> None:
        from cognitia.multi_agent.graph_store_postgres import PostgresAgentGraph
        assert PostgresAgentGraph is not None

    def test_import_postgres_graph_task_board(self) -> None:
        from cognitia.multi_agent.graph_task_board_postgres import PostgresGraphTaskBoard
        assert PostgresGraphTaskBoard is not None

    def test_import_postgres_graph_communication(self) -> None:
        from cognitia.multi_agent.graph_communication_postgres import PostgresGraphCommunication
        assert PostgresGraphCommunication is not None

    def test_import_postgres_task_queue(self) -> None:
        from cognitia.multi_agent.task_queue_postgres import PostgresTaskQueue
        assert PostgresTaskQueue is not None

    def test_import_postgres_agent_registry(self) -> None:
        from cognitia.multi_agent.agent_registry_postgres import PostgresAgentRegistry
        assert PostgresAgentRegistry is not None

    def test_import_postgres_episodic_memory(self) -> None:
        from cognitia.memory.episodic_postgres import PostgresEpisodicMemory
        assert PostgresEpisodicMemory is not None

    def test_import_postgres_procedural_memory(self) -> None:
        from cognitia.memory.procedural_postgres import PostgresProceduralMemory
        assert PostgresProceduralMemory is not None

    def test_import_postgres_session_backend(self) -> None:
        from cognitia.session.backends_postgres import PostgresSessionBackend
        assert PostgresSessionBackend is not None


# ---------------------------------------------------------------------------
# Schema constants exist
# ---------------------------------------------------------------------------


class TestSchemas:

    def test_graph_schema_exists(self) -> None:
        from cognitia.multi_agent.graph_store_postgres import POSTGRES_GRAPH_SCHEMA
        assert "agent_nodes" in POSTGRES_GRAPH_SCHEMA

    def test_task_board_schema_exists(self) -> None:
        from cognitia.multi_agent.graph_task_board_postgres import POSTGRES_GRAPH_TASK_SCHEMA
        assert "graph_tasks" in POSTGRES_GRAPH_TASK_SCHEMA

    def test_communication_schema_exists(self) -> None:
        from cognitia.multi_agent.graph_communication_postgres import POSTGRES_GRAPH_COMM_SCHEMA
        assert "graph_messages" in POSTGRES_GRAPH_COMM_SCHEMA

    def test_task_queue_schema_exists(self) -> None:
        from cognitia.multi_agent.task_queue_postgres import POSTGRES_TASK_QUEUE_SCHEMA
        assert "task_queue" in POSTGRES_TASK_QUEUE_SCHEMA

    def test_agent_registry_schema_exists(self) -> None:
        from cognitia.multi_agent.agent_registry_postgres import POSTGRES_AGENT_REGISTRY_SCHEMA
        assert "agent_registry" in POSTGRES_AGENT_REGISTRY_SCHEMA

    def test_episodic_schema_exists(self) -> None:
        from cognitia.memory.episodic_postgres import POSTGRES_EPISODIC_SCHEMA
        assert "episodes" in POSTGRES_EPISODIC_SCHEMA
        assert "tsvector" in POSTGRES_EPISODIC_SCHEMA

    def test_procedural_schema_exists(self) -> None:
        from cognitia.memory.procedural_postgres import POSTGRES_PROCEDURAL_SCHEMA
        assert "procedures" in POSTGRES_PROCEDURAL_SCHEMA
        assert "tsvector" in POSTGRES_PROCEDURAL_SCHEMA

    def test_session_schema_exists(self) -> None:
        from cognitia.session.backends_postgres import POSTGRES_SESSION_SCHEMA
        assert "sessions" in POSTGRES_SESSION_SCHEMA


# ---------------------------------------------------------------------------
# Protocol method coverage
# ---------------------------------------------------------------------------


class TestProtocolCoverage:

    def test_graph_store_methods(self) -> None:
        from cognitia.multi_agent.graph_store_postgres import PostgresAgentGraph
        required = {"add_node", "remove_node", "get_node", "get_children", "snapshot",
                     "get_chain_of_command", "get_subtree", "get_root", "find_by_role",
                     "update_node"}
        actual = {m for m in dir(PostgresAgentGraph) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_task_board_methods(self) -> None:
        from cognitia.multi_agent.graph_task_board_postgres import PostgresGraphTaskBoard
        required = {"create_task", "checkout_task", "complete_task", "get_subtasks",
                     "list_tasks", "add_comment", "get_comments", "get_thread",
                     "get_goal_ancestry", "get_ready_tasks", "get_blocked_by"}
        actual = {m for m in dir(PostgresGraphTaskBoard) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_communication_methods(self) -> None:
        from cognitia.multi_agent.graph_communication_postgres import PostgresGraphCommunication
        required = {"send_direct", "broadcast_subtree", "escalate", "get_inbox", "get_thread"}
        actual = {m for m in dir(PostgresGraphCommunication) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_task_queue_methods(self) -> None:
        from cognitia.multi_agent.task_queue_postgres import PostgresTaskQueue
        required = {"put", "get", "complete", "cancel", "list_tasks"}
        actual = {m for m in dir(PostgresTaskQueue) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_agent_registry_methods(self) -> None:
        from cognitia.multi_agent.agent_registry_postgres import PostgresAgentRegistry
        required = {"register", "get", "list_agents", "update_status", "remove"}
        actual = {m for m in dir(PostgresAgentRegistry) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_episodic_memory_methods(self) -> None:
        from cognitia.memory.episodic_postgres import PostgresEpisodicMemory
        required = {"store", "recall", "recall_recent", "recall_by_tag", "count"}
        actual = {m for m in dir(PostgresEpisodicMemory) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_procedural_memory_methods(self) -> None:
        from cognitia.memory.procedural_postgres import PostgresProceduralMemory
        required = {"store", "suggest", "record_outcome", "get", "count"}
        actual = {m for m in dir(PostgresProceduralMemory) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_session_backend_methods(self) -> None:
        from cognitia.session.backends_postgres import PostgresSessionBackend
        required = {"save", "load", "delete", "list_keys"}
        actual = {m for m in dir(PostgresSessionBackend) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"


# ---------------------------------------------------------------------------
# Constructor takes session_factory
# ---------------------------------------------------------------------------


class TestConstructors:

    def test_all_take_session_factory(self) -> None:
        from cognitia.memory.episodic_postgres import PostgresEpisodicMemory
        from cognitia.memory.procedural_postgres import PostgresProceduralMemory
        from cognitia.multi_agent.agent_registry_postgres import PostgresAgentRegistry
        from cognitia.multi_agent.graph_store_postgres import PostgresAgentGraph
        from cognitia.multi_agent.graph_task_board_postgres import PostgresGraphTaskBoard
        from cognitia.multi_agent.task_queue_postgres import PostgresTaskQueue
        from cognitia.session.backends_postgres import PostgresSessionBackend

        for cls in [
            PostgresAgentGraph, PostgresGraphTaskBoard,
            PostgresTaskQueue, PostgresAgentRegistry,
            PostgresEpisodicMemory, PostgresProceduralMemory,
            PostgresSessionBackend,
        ]:
            sig = inspect.signature(cls.__init__)
            params = list(sig.parameters.keys())
            assert "session_factory" in params, f"{cls.__name__} missing session_factory param"

    def test_communication_takes_graph_query(self) -> None:
        from cognitia.multi_agent.graph_communication_postgres import PostgresGraphCommunication
        sig = inspect.signature(PostgresGraphCommunication.__init__)
        params = list(sig.parameters.keys())
        assert "session_factory" in params
        assert "graph_query" in params


# ---------------------------------------------------------------------------
# All methods are async
# ---------------------------------------------------------------------------


class TestAllAsync:

    def test_all_protocol_methods_are_async(self) -> None:
        from cognitia.memory.episodic_postgres import PostgresEpisodicMemory
        from cognitia.memory.procedural_postgres import PostgresProceduralMemory
        from cognitia.multi_agent.agent_registry_postgres import PostgresAgentRegistry
        from cognitia.multi_agent.graph_communication_postgres import PostgresGraphCommunication
        from cognitia.multi_agent.graph_store_postgres import PostgresAgentGraph
        from cognitia.multi_agent.graph_task_board_postgres import PostgresGraphTaskBoard
        from cognitia.multi_agent.task_queue_postgres import PostgresTaskQueue
        from cognitia.session.backends_postgres import PostgresSessionBackend

        classes = [
            PostgresAgentGraph, PostgresGraphTaskBoard,
            PostgresGraphCommunication, PostgresTaskQueue,
            PostgresAgentRegistry, PostgresEpisodicMemory,
            PostgresProceduralMemory, PostgresSessionBackend,
        ]
        for cls in classes:
            for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
                if name.startswith("_"):
                    continue
                assert inspect.iscoroutinefunction(method), (
                    f"{cls.__name__}.{name} is not async"
                )
