"""Tests for PermissionManager implementation.

TDD: these tests written BEFORE the implementation.
Tests 5 built-in profiles, hierarchical permission checking, tool allowlist.
"""

from __future__ import annotations

import pytest
from swarmline.governance.protocols import PermissionManagerPort
from swarmline.governance.types import PermissionLevel, PermissionProfile


def _make_manager() -> PermissionManagerPort:
    from swarmline.governance.permission_manager import PermissionManager

    return PermissionManager()


class TestPermissionManagerSatisfiesProtocol:
    """PermissionManager implements PermissionManagerPort."""

    def test_isinstance_check(self) -> None:
        mgr = _make_manager()
        assert isinstance(mgr, PermissionManagerPort)


class TestBuiltInProfiles:
    """5 built-in profiles matching permission levels."""

    def test_five_builtin_profiles(self) -> None:
        mgr = _make_manager()
        profiles = mgr.list_profiles()
        assert len(profiles) == 5

    @pytest.mark.parametrize(
        ("name", "expected_level"),
        [
            ("read-only", PermissionLevel.READ_ONLY),
            ("editor", PermissionLevel.EDIT),
            ("git-writer", PermissionLevel.GIT_WRITE),
            ("network-enabled", PermissionLevel.NETWORK_ENABLED),
            ("deploy-capable", PermissionLevel.DEPLOY_CAPABLE),
        ],
    )
    def test_builtin_profile_level(
        self, name: str, expected_level: PermissionLevel
    ) -> None:
        mgr = _make_manager()
        profile = mgr.get_profile(name)
        assert profile is not None
        assert profile.level == expected_level

    def test_all_profiles_are_permission_profile(self) -> None:
        mgr = _make_manager()
        for p in mgr.list_profiles():
            assert isinstance(p, PermissionProfile)

    def test_get_profile_unknown_returns_none(self) -> None:
        mgr = _make_manager()
        assert mgr.get_profile("nonexistent") is None

    def test_profiles_have_allowed_tools(self) -> None:
        mgr = _make_manager()
        for p in mgr.list_profiles():
            assert isinstance(p.allowed_tools, frozenset)

    def test_profiles_have_denied_patterns(self) -> None:
        mgr = _make_manager()
        for p in mgr.list_profiles():
            assert isinstance(p.denied_patterns, tuple)


class TestPermissionHierarchy:
    """Higher level inherits lower level permissions."""

    def test_read_only_allows_read(self) -> None:
        mgr = _make_manager()
        assert mgr.check_permission("read-only", "read_file") is True

    def test_read_only_denies_write(self) -> None:
        mgr = _make_manager()
        assert mgr.check_permission("read-only", "write_file") is False

    def test_editor_allows_read_and_write(self) -> None:
        mgr = _make_manager()
        assert mgr.check_permission("editor", "read_file") is True
        assert mgr.check_permission("editor", "write_file") is True

    def test_editor_denies_git(self) -> None:
        mgr = _make_manager()
        assert mgr.check_permission("editor", "git_push") is False

    def test_git_writer_allows_git(self) -> None:
        mgr = _make_manager()
        assert mgr.check_permission("git-writer", "git_push") is True

    def test_deploy_capable_allows_deploy(self) -> None:
        mgr = _make_manager()
        assert mgr.check_permission("deploy-capable", "deploy_production") is True

    def test_unknown_profile_denies_all(self) -> None:
        mgr = _make_manager()
        assert mgr.check_permission("nonexistent", "read_file") is False


class TestToolAllowlist:
    """Tool name checking against allowed_tools in profile."""

    def test_tool_in_allowlist_permitted(self) -> None:
        mgr = _make_manager()
        profile = mgr.get_profile("read-only")
        assert profile is not None
        tool = next(iter(profile.allowed_tools))
        assert mgr.check_permission("read-only", "read_file", tool_name=tool) is True

    def test_tool_not_in_allowlist_denied(self) -> None:
        mgr = _make_manager()
        assert (
            mgr.check_permission("read-only", "read_file", tool_name="deploy_tool")
            is False
        )

    def test_no_tool_name_checks_action_only(self) -> None:
        mgr = _make_manager()
        result = mgr.check_permission("editor", "write_file")
        assert isinstance(result, bool)


class TestDeniedPatterns:
    """Actions matching denied_patterns are blocked."""

    def test_denied_pattern_blocks_action(self) -> None:
        mgr = _make_manager()
        assert mgr.check_permission("read-only", "delete_file") is False

    def test_denied_pattern_with_glob(self) -> None:
        mgr = _make_manager()
        assert mgr.check_permission("read-only", "force_push") is False
