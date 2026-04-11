"""Tests for ModelPolicy."""

from swarmline.runtime.model_policy import ModelPolicy


class TestModelPolicy:
    """Tests selectiona models."""

    def test_default_is_sonnet(self) -> None:
        """Po umolchaniyu vybiraetsya Sonnet."""
        policy = ModelPolicy()
        assert policy.select("coach") == "sonnet"

    def test_no_default_escalate_roles(self) -> None:
        """Without yavnoy konfiguratsii roli not eskaliruyutsya."""
        policy = ModelPolicy()
        assert policy.select("strategy_planner") == "sonnet"

    def test_escalation_on_failures(self) -> None:
        """Posle N notudach pereklyuchaetsya on Opus."""
        policy = ModelPolicy(escalate_on_tool_failures=3)
        assert policy.select("coach", tool_failure_count=2) == "sonnet"
        assert policy.select("coach", tool_failure_count=3) == "opus"

    def test_custom_escalate_roles(self) -> None:
        """Userskie roli for eskalatsii."""
        policy = ModelPolicy(escalate_roles={"diagnostician", "strategy_planner"})
        assert policy.select("diagnostician") == "opus"
        assert policy.select("coach") == "sonnet"
