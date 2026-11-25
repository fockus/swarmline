"""Unit tests: PII detection and redaction (stdlib-only regex core)."""

from __future__ import annotations

import pytest

from swarmline.pii import PiiMatch, detect_pii, redact_pii


# ---------------------------------------------------------------------------
# detect_pii — per-kind positive tests
# ---------------------------------------------------------------------------


class TestDetectPiiEmail:
    def test_detect_pii_email_matches_address(self) -> None:
        text = "Contact us at user+tag@sub.example.com today."
        matches = detect_pii(text, kinds=["email"])
        assert len(matches) == 1
        m = matches[0]
        assert m.kind == "email"
        assert m.value == "user+tag@sub.example.com"

    def test_detect_pii_email_returns_pii_match_dataclass(self) -> None:
        text = "user@example.com"
        matches = detect_pii(text, kinds=["email"])
        assert len(matches) == 1
        m = matches[0]
        assert isinstance(m, PiiMatch)
        assert m.start == 0
        assert m.end == len("user@example.com")

    def test_detect_pii_email_no_match_on_plain_text(self) -> None:
        assert detect_pii("hello world", kinds=["email"]) == []


class TestDetectPiiPhone:
    def test_detect_pii_phone_matches_number(self) -> None:
        text = "Call us at +1 (800) 555-1234 for help."
        matches = detect_pii(text, kinds=["phone"])
        assert len(matches) >= 1
        assert any(m.kind == "phone" for m in matches)

    def test_detect_pii_phone_matched_value_contains_digits(self) -> None:
        text = "Phone: +1 (800) 555-1234"
        matches = detect_pii(text, kinds=["phone"])
        assert matches
        # The matched value must contain digits from the number.
        joined = "".join(m.value for m in matches)
        assert "555" in joined or "1234" in joined


class TestDetectPiiSsn:
    def test_detect_pii_ssn_matches_pattern(self) -> None:
        text = "My SSN is 123-45-6789."
        matches = detect_pii(text, kinds=["ssn"])
        assert len(matches) == 1
        m = matches[0]
        assert m.kind == "ssn"
        assert m.value == "123-45-6789"

    def test_detect_pii_ssn_does_not_match_arbitrary_nine_digit_run(self) -> None:
        # No dashes → must NOT match.
        text = "Code 123456789 is not an SSN."
        matches = detect_pii(text, kinds=["ssn"])
        assert matches == []


class TestDetectPiiIp:
    def test_detect_pii_ip_matches_dotted_quad(self) -> None:
        text = "Server at 192.168.1.100 is up."
        matches = detect_pii(text, kinds=["ip"])
        assert len(matches) == 1
        m = matches[0]
        assert m.kind == "ip"
        assert m.value == "192.168.1.100"

    def test_detect_pii_ip_ignores_out_of_range_octet(self) -> None:
        text = "Address 999.1.1.1 is invalid."
        matches = detect_pii(text, kinds=["ip"])
        assert matches == []


class TestDetectPiiCreditCard:
    def test_detect_pii_credit_card_matches_luhn_valid_number(self) -> None:
        # Classic Visa test number — Luhn-valid.
        text = "Card: 4111 1111 1111 1111"
        matches = detect_pii(text, kinds=["credit_card"])
        assert len(matches) == 1
        m = matches[0]
        assert m.kind == "credit_card"
        assert "4111" in m.value

    def test_detect_pii_credit_card_ignores_luhn_invalid_number(self) -> None:
        # 1234 5678 9012 3456 — Luhn sum = 64 (not divisible by 10).
        text = "Card: 1234 5678 9012 3456"
        matches = detect_pii(text, kinds=["credit_card"])
        assert matches == []


class TestDetectPiiMultiKind:
    def test_detect_pii_without_kinds_finds_all(self) -> None:
        text = (
            "Email user@example.com, card 4111 1111 1111 1111, "
            "ip 10.0.0.1, ssn 123-45-6789"
        )
        matches = detect_pii(text)
        kinds_found = {m.kind for m in matches}
        assert "email" in kinds_found
        assert "credit_card" in kinds_found
        assert "ip" in kinds_found
        assert "ssn" in kinds_found

    def test_detect_pii_empty_text_returns_empty(self) -> None:
        assert detect_pii("") == []

    def test_detect_pii_sorted_by_start_position(self) -> None:
        text = "IP 10.0.0.1 and email user@example.com"
        matches = detect_pii(text)
        starts = [m.start for m in matches]
        assert starts == sorted(starts)


# ---------------------------------------------------------------------------
# redact_pii — strategy tests
# ---------------------------------------------------------------------------


class TestRedactPiiRedactStrategy:
    def test_redact_pii_redact_strategy_replaces_with_token(self) -> None:
        text = "Email me at user@example.com please."
        result = redact_pii(text, strategy="redact", kinds=["email"])
        assert "[REDACTED_EMAIL]" in result
        assert "user@example.com" not in result

    def test_redact_pii_redact_strategy_preserves_surrounding_text(self) -> None:
        text = "Before user@example.com after"
        result = redact_pii(text, strategy="redact", kinds=["email"])
        assert result.startswith("Before ")
        assert result.endswith(" after")


class TestRedactPiiMaskStrategy:
    def test_redact_pii_mask_strategy_keeps_last_four(self) -> None:
        # Card: "4111 1111 1111 1111" — last 4 chars of matched value = "1111"
        # Separators preserved as-is in matched value; last 4 chars = "1111".
        text = "Card: 4111 1111 1111 1111"
        result = redact_pii(text, strategy="mask", kinds=["credit_card"])
        assert "****1111" in result
        assert "4111 1111 1111 1111" not in result

    def test_redact_pii_mask_strategy_uses_four_asterisks_prefix(self) -> None:
        text = "123-45-6789"
        result = redact_pii(text, strategy="mask", kinds=["ssn"])
        # SSN last 4 chars = "6789"
        assert "****6789" in result


class TestRedactPiiHashStrategy:
    def test_redact_pii_hash_strategy_is_deterministic_with_salt(self) -> None:
        text = "user@example.com"
        r1 = redact_pii(text, strategy="hash", kinds=["email"], hash_salt="s3cr3t")
        r2 = redact_pii(text, strategy="hash", kinds=["email"], hash_salt="s3cr3t")
        r3 = redact_pii(text, strategy="hash", kinds=["email"], hash_salt="other")
        assert r1 == r2
        assert r1 != r3

    def test_redact_pii_hash_includes_kind_prefix(self) -> None:
        text = "user@example.com"
        result = redact_pii(text, strategy="hash", kinds=["email"])
        assert "[EMAIL:" in result

    @pytest.mark.parametrize("salt", ["", "abc", "x" * 100])
    def test_redact_pii_hash_token_length_is_fixed(self, salt: str) -> None:
        text = "123-45-6789"
        result = redact_pii(text, strategy="hash", kinds=["ssn"], hash_salt=salt)
        # Format: [SSN:<10-hex-chars>]
        assert "[SSN:" in result
        inner = result[
            result.index("[SSN:") + 5 : result.index("]", result.index("[SSN:"))
        ]
        assert len(inner) == 10


# ---------------------------------------------------------------------------
# redact_pii — behaviour tests
# ---------------------------------------------------------------------------


class TestRedactPiiBehaviour:
    def test_redact_pii_is_idempotent(self) -> None:
        text = "Email: user@example.com, SSN: 123-45-6789"
        once = redact_pii(text)
        twice = redact_pii(once)
        assert once == twice

    def test_redact_pii_handles_multiple_non_overlapping_matches(self) -> None:
        text = "Email user@example.com, card 4111 1111 1111 1111, ip 10.0.0.1"
        result = redact_pii(text)
        assert "[REDACTED_EMAIL]" in result
        assert "[REDACTED_CREDIT_CARD]" in result
        assert "[REDACTED_IP]" in result
        assert "user@example.com" not in result
        assert "4111 1111 1111 1111" not in result
        assert "10.0.0.1" not in result

    def test_redact_pii_empty_text_returns_unchanged(self) -> None:
        assert redact_pii("") == ""

    def test_redact_pii_kind_filter_leaves_other_kinds_intact(self) -> None:
        text = "Email user@example.com, ip 10.0.0.1"
        result = redact_pii(text, kinds=["email"])
        assert "[REDACTED_EMAIL]" in result
        assert "10.0.0.1" in result  # IP not in kinds → untouched

    def test_redact_pii_no_pii_returns_text_unchanged(self) -> None:
        text = "Hello, world! Nothing to see here."
        assert redact_pii(text) == text

    def test_redact_pii_indices_intact_right_to_left_application(self) -> None:
        # Email comes after IP in the string — right-to-left ensures both replaced correctly.
        text = "Server 10.0.0.1 contacted user@example.com"
        result = redact_pii(text)
        assert "10.0.0.1" not in result
        assert "user@example.com" not in result
        assert "[REDACTED_IP]" in result
        assert "[REDACTED_EMAIL]" in result


# ---------------------------------------------------------------------------
# Security regressions (mb-reviewer-security findings, Epic A3)
# ---------------------------------------------------------------------------


class TestPiiSecurityRegressions:
    """Regressions for the A3 security review: leaks, collisions, silent bypass."""

    def test_detect_pii_amex_15_digit_luhn_valid_is_matched(self) -> None:
        # 378282246310005 is a canonical Luhn-valid Amex test number (4-6-5).
        matches = detect_pii("3782 822463 10005")
        assert [m.kind for m in matches] == ["credit_card"]

    def test_detect_pii_amex_unseparated_is_redacted(self) -> None:
        result = redact_pii("pay 378282246310005 now")
        assert "378282246310005" not in result
        assert "[REDACTED_CREDIT_CARD]" in result

    def test_detect_pii_email_matches_long_gtld(self) -> None:
        matches = detect_pii("user@example.international", kinds=["email"])
        assert [m.kind for m in matches] == ["email"]

    def test_detect_pii_returns_single_non_overlapping_match_for_card(self) -> None:
        # The phone pattern also covers a spaced 16-digit card; dedup keeps one.
        matches = detect_pii("Card: 4111 1111 1111 1111")
        assert len(matches) == 1
        assert matches[0].kind == "credit_card"

    def test_detect_pii_classifies_ssn_format_as_ssn_not_phone(self) -> None:
        matches = detect_pii("123-45-6789")
        assert [m.kind for m in matches] == ["ssn"]

    def test_redact_pii_hash_salt_delimiter_prevents_collision(self) -> None:
        # salt+value cancellation must not collide (both salts non-empty → no warning).
        a = redact_pii("foo@bar.com", strategy="hash", hash_salt="user")
        b = redact_pii("userfoo@bar.com", strategy="hash", hash_salt="x")
        assert a.split(":")[1] != b.split(":")[1]

    def test_redact_pii_hash_empty_salt_emits_warning(self) -> None:
        with pytest.warns(UserWarning, match="hash_salt"):
            redact_pii("a@b.com", strategy="hash")

    def test_redact_pii_hash_with_salt_does_not_warn(self) -> None:
        import warnings as _w

        with _w.catch_warnings():
            _w.simplefilter("error")
            redact_pii("a@b.com", strategy="hash", hash_salt="secret")  # must not raise

    def test_detect_pii_presidio_raises_without_extra(self) -> None:
        import importlib.util

        from swarmline.pii import detect_pii_presidio

        if importlib.util.find_spec("presidio_analyzer") is None:
            with pytest.raises(ImportError, match="swarmline\\[pii\\]"):
                detect_pii_presidio("user@example.com")
        else:
            # Installed but stub: must fail loud, never silently return [].
            with pytest.raises(NotImplementedError):
                detect_pii_presidio("user@example.com")
