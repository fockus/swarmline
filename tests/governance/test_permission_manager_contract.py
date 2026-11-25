"""Contract tests for PermissionManagerPort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing check_permission + get_profile + list_profiles should pass.
"""

from __future__ import annotations

import pytest
from swarmline.governance.protocols import PermissionManagerPort
from swarmline.governance.types import (
    PermissionLevel,
    PermissionProfile,
)


class _StubPermissionManager:
    """Minimal valid implementation for contract testing."""

    _profiles: dict[str, PermissionProfile] = {
        "read-only": PermissionProfile(
            name="read-only",
            level=PermissionLevel.READ_ONLY,
            allowed_tools=frozenset({"read_file", "list_files"}),
            denied_patterns=("write_*", "delete_*"),
        ),
        "editor": PermissionProfile(
            name="editor",
            level=PermissionLevel.EDIT,
            allowed_tools=frozenset({"read_file", "write_file"}),
            denied_patterns=("delete_*",),
        ),
    }

    def check_permission(
        self, profile_name: str, action: str, tool_name: str | None = None
    ) -> bool:
        profile = self._profiles.get(profile_name)
        if profile is None:
            return False
        if tool_name and tool_name not in profile.allowed_tools:
            return False
        return True

    def get_profile(self, name: str) -> PermissionProfile | None:
        return self._profiles.get(name)

    def list_profiles(self) -> list[PermissionProfile]:
        return list(self._profiles.values())


class _InvalidPermissionManager:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


class TestPermissionManagerPortContract:
    """PermissionManagerPort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubPermissionManager()
        assert isinstance(impl, PermissionManagerPort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidPermissionManager()
        assert not isinstance(invalid, PermissionManagerPort)

    def test_check_permission_returns_bool(self) -> None:
        impl = _StubPermissionManager()
        result = impl.check_permission("read-only", "view")
        assert isinstance(result, bool)

    def test_check_permission_with_tool_name(self) -> None:
        impl = _StubPermissionManager()
        assert impl.check_permission("read-only", "view", tool_name="read_file") is True
        assert impl.check_permission("read-only", "view", tool_name="unknown") is False

    def test_check_permission_unknown_profile_returns_false(self) -> None:
        impl = _StubPermissionManager()
        assert impl.check_permission("nonexistent", "view") is False

    def test_get_profile_returns_permission_profile(self) -> None:
        impl = _StubPermissionManager()
        result = impl.get_profile("read-only")
        assert isinstance(result, PermissionProfile)

    def test_get_profile_unknown_returns_none(self) -> None:
        impl = _StubPermissionManager()
        result = impl.get_profile("nonexistent")
        assert result is None

    def test_list_profiles_returns_list(self) -> None:
        impl = _StubPermissionManager()
        result = impl.list_profiles()
        assert isinstance(result, list)
        assert all(isinstance(p, PermissionProfile) for p in result)

    def test_list_profiles_not_empty(self) -> None:
        impl = _StubPermissionManager()
        assert len(impl.list_profiles()) > 0


class TestPermissionProfileFrozen:
    """PermissionProfile is a frozen dataclass."""

    def test_profile_is_frozen(self) -> None:
        p = PermissionProfile(
            name="test",
            level=PermissionLevel.READ_ONLY,
            allowed_tools=frozenset(),
            denied_patterns=(),
        )
        with pytest.raises(AttributeError):
            p.name = "changed"  # type: ignore[misc]

    def test_profile_fields(self) -> None:
        p = PermissionProfile(
            name="test",
            level=PermissionLevel.EDIT,
            allowed_tools=frozenset({"read"}),
            denied_patterns=("write_*",),
        )
        assert p.name == "test"
        assert p.level == PermissionLevel.EDIT
        assert isinstance(p.allowed_tools, frozenset)
        assert isinstance(p.denied_patterns, tuple)


class TestPermissionLevelHierarchy:
    """PermissionLevel enum has correct ordering."""

    def test_levels_ordered(self) -> None:
        assert PermissionLevel.READ_ONLY < PermissionLevel.EDIT
        assert PermissionLevel.EDIT < PermissionLevel.GIT_WRITE
        assert PermissionLevel.GIT_WRITE < PermissionLevel.NETWORK_ENABLED
        assert PermissionLevel.NETWORK_ENABLED < PermissionLevel.DEPLOY_CAPABLE

    @pytest.mark.parametrize(
        "level",
        list(PermissionLevel),
    )
    def test_all_levels_are_valid(self, level: PermissionLevel) -> None:
        assert isinstance(level, PermissionLevel)

    def test_five_levels_total(self) -> None:
        assert len(PermissionLevel) == 5
