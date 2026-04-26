"""Unit: path_safety — namespace segment validation + path traversal guards.

Stage 1 of plans/2026-04-27_fix_security-audit.md — closes audit finding P1 #1
(cross-tenant filesystem collision via SandboxConfig(user_id=".", topic_id="alice")
resolving to the same workspace as ("alice", ".")).
"""

from __future__ import annotations

import pytest

from swarmline.path_safety import build_isolated_path, validate_namespace_segment


class TestValidateNamespaceSegment:
    """validate_namespace_segment hardens the {user_id, topic_id} → path mapping."""

    def test_validate_namespace_segment_accepts_normal_name(self) -> None:
        assert validate_namespace_segment("alice", "user_id") == "alice"
        assert validate_namespace_segment("topic-42", "topic_id") == "topic-42"
        assert validate_namespace_segment("a_b.c", "label") == "a_b.c"

    def test_validate_namespace_segment_rejects_single_dot(self) -> None:
        """`.` resolves to the parent directory under build_isolated_path → cross-tenant collision."""
        with pytest.raises(ValueError, match="Invalid user_id"):
            validate_namespace_segment(".", "user_id")

    def test_validate_namespace_segment_rejects_double_dot(self) -> None:
        """`..` is a path-traversal segment (regression — already rejected via substring check)."""
        with pytest.raises(ValueError, match="Invalid topic_id"):
            validate_namespace_segment("..", "topic_id")

    def test_validate_namespace_segment_rejects_three_dots(self) -> None:
        """`...` contains `..` substring — must remain rejected (regression guard)."""
        with pytest.raises(ValueError, match="Invalid"):
            validate_namespace_segment("...", "user_id")

    def test_validate_namespace_segment_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            validate_namespace_segment("", "user_id")

    def test_validate_namespace_segment_rejects_slash(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            validate_namespace_segment("a/b", "user_id")

    def test_validate_namespace_segment_rejects_backslash(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            validate_namespace_segment("a\\b", "user_id")

    def test_validate_namespace_segment_rejects_unicode_lookalike_dot(self) -> None:
        """U+2024 (one-dot leader) is not in _SAFE_SEGMENT_CHARS — must be rejected."""
        with pytest.raises(ValueError, match="Invalid characters"):
            validate_namespace_segment("․", "user_id")


class TestPathCollisionPrevention:
    """End-to-end: dot segments must never resolve to the same workspace path."""

    @pytest.mark.parametrize(
        "user_id, topic_id",
        [
            (".", "alice"),
            ("alice", "."),
            ("..", "alice"),
            ("alice", ".."),
        ],
    )
    def test_sandbox_config_rejects_dot_namespace_segments(
        self, tmp_path, user_id: str, topic_id: str
    ) -> None:
        """SandboxConfig.__post_init__ must reject any `.`/`..` segment so two tenants
        cannot collide on the same workspace_path through namespace ambiguity."""
        from swarmline.tools.types import SandboxConfig

        with pytest.raises(ValueError, match="Invalid (user_id|topic_id)"):
            SandboxConfig(
                root_path=str(tmp_path),
                user_id=user_id,
                topic_id=topic_id,
            )


class TestBuildIsolatedPath:
    """build_isolated_path is the second-line guard against traversal."""

    def test_build_isolated_path_resolves_inside_root(self, tmp_path) -> None:
        result = build_isolated_path(tmp_path, "alice", "topic-1", "workspace")
        assert str(result).startswith(str(tmp_path.resolve()))

    def test_build_isolated_path_rejects_traversal_via_resolved_segments(
        self, tmp_path
    ) -> None:
        """Even if a future caller bypasses validate_namespace_segment, the resolve
        check must still flag any ../ that escapes root."""
        with pytest.raises(ValueError, match="Path traversal detected"):
            build_isolated_path(tmp_path, "alice", "..", "..", "etc")
