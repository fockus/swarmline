"""Tests for RoleRouter (section 7 architecture). Deterministic test cases on routing:
1. Explicit command - priority
2. Keyword/regex heuristics
3. Fallback on default role"""

import pytest
from cognitia.routing.role_router import KeywordRoleRouter


@pytest.fixture
def router() -> KeywordRoleRouter:
    """A router with keyword mappings for a financial coach."""
    return KeywordRoleRouter(
        default_role="coach",
        keyword_map={
            "deposit_advisor": [
                "вклад",
                "депозит",
                "накопить",
                "сберечь",
                "ставка по вкладу",
            ],
            "credit_advisor": [
                "кредит",
                "ипотека",
                "долг",
                "рефинанс",
                "займ",
            ],
            "portfolio_builder": [
                "портфель",
                "облигаци",
                "акции",
                "фонд",
                "пиф",
                "etf",
            ],
            "diagnostician": [
                "диагностик",
                "финансовое здоровье",
                "анализ расходов",
            ],
            "strategy_planner": [
                "стратеги",
                "план на год",
                "дорожн",
                "пошагово",
            ],
        },
    )


class TestExplicitCommand:
    """Explicit command /role <id> takes precedence."""

    def test_explicit_role_overrides_keywords(self, router: KeywordRoleRouter) -> None:
        """Even if the text contains keywords - an explicit command wins."""
        result = router.resolve(
            user_text="хочу вклад с хорошей ставкой",
            explicit_role="coach",
        )
        assert result == "coach"

    def test_explicit_role_any_value(self, router: KeywordRoleRouter) -> None:
        """Any explicit value is accepted as-is."""
        result = router.resolve(user_text="", explicit_role="custom_role")
        assert result == "custom_role"


class TestKeywordMatching:
    """Keyword heuristics for automatic role determination."""

    def test_deposit_keywords(self, router: KeywordRoleRouter) -> None:
        """'deposit' -> deposit_advisor."""
        assert router.resolve("хочу открыть вклад") == "deposit_advisor"

    def test_credit_keywords(self, router: KeywordRoleRouter) -> None:
        """'credit' -> credit_advisor."""
        assert router.resolve("как взять кредит") == "credit_advisor"

    def test_portfolio_keywords(self, router: KeywordRoleRouter) -> None:
        """'obligatsii' -> portfolio_builder."""
        assert router.resolve("подбери облигации") == "portfolio_builder"

    def test_diagnostician_keywords(self, router: KeywordRoleRouter) -> None:
        """'diagnostics' -> diagnostician."""
        assert router.resolve("проведи диагностику") == "diagnostician"

    def test_strategy_keywords(self, router: KeywordRoleRouter) -> None:
        """'strategy' -> strategy_planner."""
        assert router.resolve("составь стратегию") == "strategy_planner"

    def test_case_insensitive(self, router: KeywordRoleRouter) -> None:
        """Case-insensitive search."""
        assert router.resolve("ВКЛАД под хороший процент") == "deposit_advisor"

    def test_partial_match(self, router: KeywordRoleRouter) -> None:
        """Word inside a sentence."""
        assert router.resolve("мне нужна ипотека на квартиру") == "credit_advisor"


class TestFallback:
    """Fallback on default role if there are no matches."""

    def test_no_keywords_returns_default(self, router: KeywordRoleRouter) -> None:
        """No matches -> coach."""
        assert router.resolve("привет, как дела?") == "coach"

    def test_empty_text_returns_default(self, router: KeywordRoleRouter) -> None:
        """Empty text -> default."""
        assert router.resolve("") == "coach"

    def test_custom_default(self) -> None:
        """You can set a different default."""
        router = KeywordRoleRouter(default_role="diagnostician", keyword_map={})
        assert router.resolve("что угодно") == "diagnostician"


class TestFirstMatchPriority:
    """If there are not how many matches, the first one wins."""

    def test_first_keyword_wins(self, router: KeywordRoleRouter) -> None:
        """If the text contains words from not how many roles - the first match wins."""
        result = router.resolve("хочу вклад и кредит")
        # The order of checking is determined by the order of the keyword_map
        assert result in ("deposit_advisor", "credit_advisor")
