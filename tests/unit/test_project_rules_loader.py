"""Tests for swarmline.tools.project_rules — LocalFsProjectRulesLoader.

REQ-OSS-060: generic, product-free filesystem loader for project instruction files.

Covers:
- Precedence: CLAUDE.md > AGENTS.md > .github/AGENTS.md (D-03 semantics)
- Path-traversal guard (ValueError)
- Size cap 1MB (ValueError)
- Not-found (ValueError)
- Happy-path read returns UTF-8 content
"""

from __future__ import annotations

import pytest

from swarmline.tools.project_rules import LocalFsProjectRulesLoader


# ---------------------------------------------------------------------------
# discover_paths — precedence
# ---------------------------------------------------------------------------


async def test_discover_paths_prefers_claude_md_over_agents_md(
    tmp_path: pytest.TempdirFactory,
) -> None:
    """CLAUDE.md wins over AGENTS.md when both exist at project root."""
    claude_md = tmp_path / "CLAUDE.md"  # type: ignore[operator]
    agents_md = tmp_path / "AGENTS.md"  # type: ignore[operator]
    claude_md.write_text("# Claude")
    agents_md.write_text("# Agents")

    loader = LocalFsProjectRulesLoader()
    paths = await loader.discover_paths(str(tmp_path))

    assert len(paths) == 1
    assert paths[0] == str(claude_md.resolve())


async def test_discover_paths_prefers_agents_md_over_github_agents_md(
    tmp_path: pytest.TempdirFactory,
) -> None:
    """AGENTS.md wins over .github/AGENTS.md when CLAUDE.md is absent."""
    agents_md = tmp_path / "AGENTS.md"  # type: ignore[operator]
    github_dir = tmp_path / ".github"  # type: ignore[operator]
    github_dir.mkdir()
    github_agents = github_dir / "AGENTS.md"
    agents_md.write_text("# Root agents")
    github_agents.write_text("# GitHub agents")

    loader = LocalFsProjectRulesLoader()
    paths = await loader.discover_paths(str(tmp_path))

    assert len(paths) == 1
    assert paths[0] == str(agents_md.resolve())


async def test_discover_paths_falls_back_to_github_agents_md(
    tmp_path: pytest.TempdirFactory,
) -> None:
    """.github/AGENTS.md is returned when neither CLAUDE.md nor root AGENTS.md exist."""
    github_dir = tmp_path / ".github"  # type: ignore[operator]
    github_dir.mkdir()
    github_agents = github_dir / "AGENTS.md"
    github_agents.write_text("# GitHub agents")

    loader = LocalFsProjectRulesLoader()
    paths = await loader.discover_paths(str(tmp_path))

    assert len(paths) == 1
    assert paths[0] == str(github_agents.resolve())


async def test_discover_paths_returns_empty_list_when_no_rules_files(
    tmp_path: pytest.TempdirFactory,
) -> None:
    """Returns [] when no candidate file exists."""
    loader = LocalFsProjectRulesLoader()
    paths = await loader.discover_paths(str(tmp_path))
    assert paths == []


# ---------------------------------------------------------------------------
# read — security guards
# ---------------------------------------------------------------------------


async def test_read_rejects_path_traversal_via_double_dots(
    tmp_path: pytest.TempdirFactory,
) -> None:
    """Path traversal via '..' resolves outside project_root and is rejected (ValueError)."""
    outside = tmp_path / "secret.txt"  # type: ignore[operator]
    outside.write_text("secret")
    project_root = tmp_path / "project"  # type: ignore[operator]
    project_root.mkdir()

    traversal_path = str(project_root / ".." / "secret.txt")

    loader = LocalFsProjectRulesLoader()
    with pytest.raises(ValueError, match="[Pp]ath traversal|outside|root"):
        await loader.read(traversal_path, project_root=str(project_root))


async def test_read_rejects_file_over_size_cap(
    tmp_path: pytest.TempdirFactory,
) -> None:
    """Files over 1MB are rejected with ValueError (size cap guard)."""
    project_root = tmp_path  # type: ignore[operator]
    large_file = project_root / "AGENTS.md"
    large_file.write_bytes(b"X" * (2 * 1_048_576))

    loader = LocalFsProjectRulesLoader()
    with pytest.raises(ValueError, match="[Ss]ize|large|1.*MB|1048576"):
        await loader.read(str(large_file), project_root=str(project_root))


async def test_read_raises_value_error_for_not_found_file(
    tmp_path: pytest.TempdirFactory,
) -> None:
    """Reading a non-existent file within project_root raises ValueError."""
    project_root = tmp_path  # type: ignore[operator]
    missing = project_root / "NONEXISTENT.md"

    loader = LocalFsProjectRulesLoader()
    with pytest.raises(ValueError, match="[Nn]ot found|missing|exist"):
        await loader.read(str(missing), project_root=str(project_root))


# ---------------------------------------------------------------------------
# read — happy path
# ---------------------------------------------------------------------------


async def test_read_returns_utf8_content_for_valid_file(
    tmp_path: pytest.TempdirFactory,
) -> None:
    """Valid file within project root returns its UTF-8 content verbatim."""
    project_root = tmp_path  # type: ignore[operator]
    agents_md = project_root / "AGENTS.md"
    content = "# Agent Rules\n- Use TDD\n- Clean Architecture\n"
    agents_md.write_text(content, encoding="utf-8")

    loader = LocalFsProjectRulesLoader()
    result = await loader.read(str(agents_md), project_root=str(project_root))

    assert result == content
