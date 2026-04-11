"""Tests for mode detection ThinRuntime."""

import re

from swarmline.runtime.thin.modes import VALID_MODES, detect_mode


class TestDetectModeHint:
    """mode_hint takes precedence."""

    def test_hint_planner(self) -> None:
        assert detect_mode("привет", mode_hint="planner") == "planner"

    def test_hint_react(self) -> None:
        assert detect_mode("привет", mode_hint="react") == "react"

    def test_hint_conversational(self) -> None:
        assert detect_mode("план на год", mode_hint="conversational") == "conversational"

    def test_invalid_hint_ignored(self) -> None:
        """Invalid hint -> uses heuristic."""
        assert detect_mode("привет", mode_hint="invalid") == "conversational"


class TestDetectModePlanner:
    """Keyword heuristics → planner."""

    def test_plan_keyword(self) -> None:
        assert detect_mode("Составь план на год") == "planner"

    def test_strategy_keyword(self) -> None:
        assert detect_mode("Разработай стратегию") == "planner"

    def test_step_by_step_keyword(self) -> None:
        assert detect_mode("Объясни пошагово") == "planner"

    def test_road_keyword(self) -> None:
        assert detect_mode("Составь дорожную карту") == "planner"

    def test_plan_keyword_in_english(self) -> None:
        assert detect_mode("Create a step-by-step plan for deployment") == "planner"


class TestDetectModeReact:
    """Keyword heuristics → react."""

    def test_find_keyword(self) -> None:
        assert detect_mode("Подбери вклад под мои параметры") == "react"

    def test_search_keyword(self) -> None:
        assert detect_mode("Найди лучший вклад") == "react"

    def test_compare_keyword(self) -> None:
        assert detect_mode("Сравни условия") == "react"

    def test_list_files_keyword_in_english(self) -> None:
        assert detect_mode("List the files in /project") == "react"

    def test_read_file_keyword_in_english(self) -> None:
        assert detect_mode("Read the file /project/main.py") == "react"

    def test_write_file_keyword_in_english(self) -> None:
        assert detect_mode("Write a new file /project/utils.py") == "react"


class TestDetectModeConversational:
    """Default → conversational."""

    def test_greeting(self) -> None:
        assert detect_mode("Привет!") == "conversational"

    def test_question(self) -> None:
        assert detect_mode("Что такое диверсификация?") == "conversational"

    def test_empty_string(self) -> None:
        assert detect_mode("") == "conversational"

    def test_pf5_without_custom_patterns(self) -> None:
        assert detect_mode("Сделай PF5-диагностику") == "conversational"


class TestDetectModeCustomPatterns:
    """Custom domain patterns are passed from not."""

    def test_custom_planner_pattern(self) -> None:
        planner_patterns = [re.compile(r"\bpf5\b", re.IGNORECASE)]
        assert (
            detect_mode(
                "Сделай PF5-диагностику",
                planner_patterns=planner_patterns,
            )
            == "planner"
        )

    def test_custom_react_patterns(self) -> None:
        react_patterns = [
            re.compile(r"\bставк", re.IGNORECASE),
            re.compile(r"\bвклад", re.IGNORECASE),
        ]
        assert (
            detect_mode(
                "Какая ставка по вкладу?",
                react_patterns=react_patterns,
            )
            == "react"
        )


class TestValidModes:
    """Many acceptable modes."""

    def test_all_modes(self) -> None:
        assert {"conversational", "react", "planner"} == VALID_MODES
