"""Contract tests for SecretBoundaryPort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing redact + is_trusted_zone + get_patterns should pass.
"""

from __future__ import annotations

import pytest
from swarmline.governance.protocols import SecretBoundaryPort
from swarmline.governance.types import (
    SecretPattern,
    TrustZone,
)


class _StubSecretBoundary:
    """Minimal valid implementation for contract testing."""

    _patterns: list[SecretPattern] = [
        SecretPattern(
            pattern=r"sk-[a-zA-Z0-9]{20,}",
            replacement="[REDACTED:api_key]",
            description="API key",
        ),
    ]

    def redact(self, text: str) -> str:
        import re

        for p in self._patterns:
            text = re.sub(p.pattern, p.replacement, text)
        return text

    def is_trusted_zone(self, zone: TrustZone) -> bool:
        return zone == TrustZone.TRUSTED

    def get_patterns(self) -> list[SecretPattern]:
        return list(self._patterns)


class _InvalidSecretBoundary:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


class TestSecretBoundaryPortContract:
    """SecretBoundaryPort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubSecretBoundary()
        assert isinstance(impl, SecretBoundaryPort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidSecretBoundary()
        assert not isinstance(invalid, SecretBoundaryPort)

    def test_redact_returns_str(self) -> None:
        impl = _StubSecretBoundary()
        result = impl.redact("key is sk-abcdefghijklmnopqrst")
        assert isinstance(result, str)

    def test_redact_replaces_secret(self) -> None:
        impl = _StubSecretBoundary()
        result = impl.redact("key is sk-abcdefghijklmnopqrst")
        assert "sk-" not in result
        assert "[REDACTED:" in result

    def test_redact_no_secret_unchanged(self) -> None:
        impl = _StubSecretBoundary()
        text = "no secrets here"
        assert impl.redact(text) == text

    def test_is_trusted_zone_returns_bool(self) -> None:
        impl = _StubSecretBoundary()
        assert isinstance(impl.is_trusted_zone(TrustZone.TRUSTED), bool)
        assert isinstance(impl.is_trusted_zone(TrustZone.UNTRUSTED), bool)

    def test_trusted_zone_is_trusted(self) -> None:
        impl = _StubSecretBoundary()
        assert impl.is_trusted_zone(TrustZone.TRUSTED) is True

    def test_untrusted_zone_is_not_trusted(self) -> None:
        impl = _StubSecretBoundary()
        assert impl.is_trusted_zone(TrustZone.UNTRUSTED) is False

    def test_get_patterns_returns_list(self) -> None:
        impl = _StubSecretBoundary()
        result = impl.get_patterns()
        assert isinstance(result, list)
        assert all(isinstance(p, SecretPattern) for p in result)


class TestSecretPatternFrozen:
    """SecretPattern is a frozen dataclass."""

    def test_pattern_is_frozen(self) -> None:
        p = SecretPattern(
            pattern="test",
            replacement="[REDACTED]",
            description="test pattern",
        )
        with pytest.raises(AttributeError):
            p.pattern = "changed"  # type: ignore[misc]

    def test_pattern_fields(self) -> None:
        p = SecretPattern(
            pattern=r"password=\S+",
            replacement="[REDACTED:password]",
            description="Password pattern",
        )
        assert p.pattern == r"password=\S+"
        assert p.replacement == "[REDACTED:password]"
        assert p.description == "Password pattern"


class TestTrustZoneEnum:
    """TrustZone enum has expected members."""

    @pytest.mark.parametrize(
        "zone",
        list(TrustZone),
    )
    def test_all_zones_are_valid(self, zone: TrustZone) -> None:
        assert isinstance(zone, TrustZone)

    def test_three_zones_total(self) -> None:
        assert len(TrustZone) == 3

    def test_zone_values(self) -> None:
        assert TrustZone.TRUSTED.value == "trusted"
        assert TrustZone.UNTRUSTED.value == "untrusted"
        assert TrustZone.SANDBOX.value == "sandbox"
