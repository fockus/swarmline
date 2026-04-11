"""Tests for AgentLogger and configure_logging - pokrytie observability."""

import pytest
from swarmline.observability.logger import AgentLogger, _level_to_int, configure_logging


class TestConfigureLogging:
    """configure_logging nastraivaet structlog."""

    def test_json_format(self) -> None:
        """JSON format - not fails."""
        configure_logging(level="info", fmt="json")

    def test_console_format(self) -> None:
        """Console format - not fails."""
        configure_logging(level="debug", fmt="console")

    def test_default_params(self) -> None:
        """Without parameterov - not fails."""
        configure_logging()


class TestLevelToInt:
    """_level_to_int converts stroku -> chislo."""

    def test_debug(self) -> None:
        assert _level_to_int("debug") == 10

    def test_info(self) -> None:
        assert _level_to_int("info") == 20

    def test_warning(self) -> None:
        assert _level_to_int("warning") == 30

    def test_error(self) -> None:
        assert _level_to_int("error") == 40

    def test_critical(self) -> None:
        assert _level_to_int("critical") == 50

    def test_unknown_defaults_to_info(self) -> None:
        assert _level_to_int("TRACE") == 20

    def test_case_insensitive(self) -> None:
        assert _level_to_int("DEBUG") == 10


class TestAgentLogger:
    """AgentLogger - vse metody vyzyvayut structlog without oshibok."""

    @pytest.fixture
    def logger(self) -> AgentLogger:
        configure_logging(level="debug", fmt="json")
        return AgentLogger(component="test")

    def test_session_created(self, logger: AgentLogger) -> None:
        """session_created not fails."""
        logger.session_created(user_id="u1", topic_id="t1", role_id="coach", is_rehydrated=True)

    def test_turn_start(self, logger: AgentLogger) -> None:
        """turn_start not fails, obrezaet preview do 50 simvolov."""
        logger.turn_start(
            user_id="u1",
            topic_id="t1",
            user_text_preview="A" * 200,
        )

    def test_tool_call(self, logger: AgentLogger) -> None:
        """tool_call logiruet call toola."""
        logger.tool_call(
            tool_name="mcp__iss__get_bonds",
            latency_ms=150,
            status="ok",
            input_preview='{"query": "облигации"}',
        )

    def test_tool_call_long_input(self, logger: AgentLogger) -> None:
        """tool_call obrezaet input_preview do 100 simvolov."""
        logger.tool_call(tool_name="test", input_preview="X" * 500)

    def test_turn_complete(self, logger: AgentLogger) -> None:
        """turn_complete with polnymi parameterami."""
        logger.turn_complete(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            model="sonnet",
            tool_calls=[{"name": "iss", "status": "ok"}],
            context_budget_used=4000,
            context_budget_total=8000,
            truncated_packs=["summary"],
            turn_latency_ms=1500,
        )

    def test_turn_complete_defaults(self, logger: AgentLogger) -> None:
        """turn_complete with defoltnymi parameterami."""
        logger.turn_complete(user_id="u1", topic_id="t1", role_id="coach")

    def test_turn_error(self, logger: AgentLogger) -> None:
        """turn_error logiruet oshibku."""
        logger.turn_error(
            user_id="u1",
            topic_id="t1",
            error_type="MCPTimeout",
            error_message="Connection timeout after 30s",
            recovery_action="circuit_breaker_opened",
        )

    def test_memory_persist(self, logger: AgentLogger) -> None:
        """memory_persist logiruet sohranotnie."""
        logger.memory_persist(
            user_id="u1",
            topic_id="t1",
            facts_saved=3,
            summary_updated=True,
        )

    def test_memory_persist_defaults(self, logger: AgentLogger) -> None:
        """memory_persist with defoltnymi parameterami."""
        logger.memory_persist(user_id="u1", topic_id="t1")

    def test_turn_complete_with_prompt_hash(self, logger: AgentLogger) -> None:
        """turn_complete includes prompt_hash (§12.1)."""
        logger.turn_complete(
            user_id="u1",
            topic_id="t1",
            role_id="coach",
            prompt_hash="abc123def456",
        )

    def test_tool_policy_event_allowed(self, logger: AgentLogger) -> None:
        """tool_policy_event for razreshennogo toola."""
        logger.tool_policy_event(
            tool_name="mcp__iss__get_bonds",
            allowed=True,
            reason="mcp_active_skill",
            server_id="iss",
        )

    def test_tool_policy_event_denied(self, logger: AgentLogger) -> None:
        """tool_policy_event for zapreshchennogo toola."""
        logger.tool_policy_event(
            tool_name="Bash",
            allowed=False,
            reason="always_denied",
        )

    def test_tool_policy_event_with_context(self, logger: AgentLogger) -> None:
        """tool_policy_event with user_id, topic_id, role_id (GAP-4)."""
        logger.tool_policy_event(
            tool_name="mcp__iss__search_bonds",
            allowed=True,
            reason="mcp_active_skill",
            server_id="iss",
            user_id="u1",
            topic_id="t1",
            role_id="coach",
        )

    def test_context_budget_applied(self, logger: AgentLogger) -> None:
        """context_budget_applied event (§10.3)."""
        logger.context_budget_applied(
            user_id="u1",
            topic_id="t1",
            prompt_hash="hash123",
            total_tokens=5000,
            truncated_packs=["summary", "user_profile"],
        )

    def test_settings_loaded(self, logger: AgentLogger) -> None:
        """settings_loaded event (§2.2)."""
        logger.settings_loaded(
            sources=["project", "user"],
            mcp_servers_count=4,
        )
