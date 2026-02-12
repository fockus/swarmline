"""Тесты для mode detection ThinRuntime."""

import re

from cognitia.runtime.thin.modes import VALID_MODES, detect_mode


class TestDetectModeHint:
    """mode_hint имеет приоритет."""

    def test_hint_planner(self) -> None:
        assert detect_mode("привет", mode_hint="planner") == "planner"

    def test_hint_react(self) -> None:
        assert detect_mode("привет", mode_hint="react") == "react"

    def test_hint_conversational(self) -> None:
        assert detect_mode("план на год", mode_hint="conversational") == "conversational"

    def test_invalid_hint_ignored(self) -> None:
        """Невалидный hint → используется эвристика."""
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


class TestDetectModeReact:
    """Keyword heuristics → react."""

    def test_find_keyword(self) -> None:
        assert detect_mode("Подбери вклад под мои параметры") == "react"

    def test_search_keyword(self) -> None:
        assert detect_mode("Найди лучший вклад") == "react"

    def test_compare_keyword(self) -> None:
        assert detect_mode("Сравни условия") == "react"

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
    """Кастомные domain-паттерны передаются извне."""

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
    """Множество допустимых режимов."""

    def test_all_modes(self) -> None:
        assert {"conversational", "react", "planner"} == VALID_MODES
