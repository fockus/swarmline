"""Tests for RCA Task 9 — hash-anchored edit strategy (REQ-RCA-070).

TDD: tests written before implementation.
Naming: test_<what>_<condition>_<result>.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from swarmline.tools.sandbox_local import LocalSandboxProvider
from swarmline.tools.types import SandboxConfig


def _sha256(text: str) -> str:
    """SHA-256 hexdigest of text encoded as UTF-8."""
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture()
def sandbox(tmp_path: Any) -> LocalSandboxProvider:
    config = SandboxConfig(
        root_path=str(tmp_path),
        user_id="test",
        topic_id="anchor",
        max_file_size_bytes=1024 * 1024,
        timeout_seconds=5,
        allow_host_execution=True,
    )
    return LocalSandboxProvider(config)


# ---------------------------------------------------------------------------
# AnchorEditStrategy — match / reject / transactional
# ---------------------------------------------------------------------------


class TestAnchorEditStrategyApply:
    """AnchorEditStrategy: apply on hash match, reject on stale, transactional."""

    async def test_anchored_edit_applies_when_anchor_matches_file_content(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """AnchoredHunk with correct anchor SHA → edit applied, file updated."""
        from swarmline.tools.edit.anchor import AnchoredHunk, AnchorEditStrategy

        content = "line1\nline2\nline3\n"
        old = "line2"
        # exact matched slice from CascadeFuzzyMatcher on this content is "line2"
        anchor = _sha256(old)
        await sandbox.write_file("f.py", content)

        strategy = AnchorEditStrategy()
        outcome = await strategy.apply(
            (AnchoredHunk(path="f.py", old=old, new="LINE2", anchor=anchor),),
            sandbox,
            transactional=True,
        )
        assert outcome.applied is True
        result = await sandbox.read_file("f.py")
        assert "LINE2" in result
        assert "line2" not in result

    async def test_anchored_edit_rejects_stale_anchor_before_write(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """Stale anchor (sha256 mismatch) → rejected before any write, file unchanged."""
        from swarmline.tools.edit.anchor import AnchoredHunk, AnchorEditStrategy

        content = "line1\nline2\nline3\n"
        await sandbox.write_file("f.py", content)

        stale_anchor = _sha256("STALE_CONTENT_THAT_WAS_HERE_BEFORE")
        strategy = AnchorEditStrategy()
        outcome = await strategy.apply(
            (AnchoredHunk(path="f.py", old="line2", new="LINE2", anchor=stale_anchor),),
            sandbox,
            transactional=True,
        )

        assert outcome.applied is False
        assert len(outcome.results) == 1
        assert outcome.results[0].status == "failed"
        assert outcome.results[0].failure == "stale_anchor"
        # File must be byte-identical to original — no write occurred
        result = await sandbox.read_file("f.py")
        assert result == content

    async def test_anchored_edit_multihunk_one_stale_leaves_all_files_untouched(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """Multi-hunk: one stale anchor → nothing written (transactional all-or-nothing)."""
        from swarmline.tools.edit.anchor import AnchoredHunk, AnchorEditStrategy

        a_content = "alpha\nbeta\ngamma\n"
        b_content = "one\ntwo\nthree\n"
        await sandbox.write_file("a.py", a_content)
        await sandbox.write_file("b.py", b_content)

        # hunk 1 on file a: valid anchor (sha256 of "beta" as it appears in file)
        valid_anchor = _sha256("beta")
        # hunk 2 on file b: stale anchor (sha256 of content that is NOT in file)
        stale_anchor = _sha256("WRONG_CONTENT_NEVER_IN_FILE")

        strategy = AnchorEditStrategy()
        outcome = await strategy.apply(
            (
                AnchoredHunk(path="a.py", old="beta", new="BETA", anchor=valid_anchor),
                AnchoredHunk(path="b.py", old="two", new="TWO", anchor=stale_anchor),
            ),
            sandbox,
            transactional=True,
        )

        assert outcome.applied is False
        stale_result = next(
            (r for r in outcome.results if r.failure == "stale_anchor"), None
        )
        assert stale_result is not None, "Expected a stale_anchor failure result"
        assert stale_result.path == "b.py"
        # Both files must be untouched (transactional)
        assert await sandbox.read_file("a.py") == a_content
        assert await sandbox.read_file("b.py") == b_content

    async def test_plain_hunk_without_anchor_applies_normally(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """A plain Hunk (no anchor field) passes through AnchorEditStrategy without check."""
        from swarmline.tools.edit.anchor import AnchorEditStrategy
        from swarmline.tools.edit.strategy import Hunk

        content = "x = 1\ny = 2\n"
        await sandbox.write_file("p.py", content)

        strategy = AnchorEditStrategy()
        outcome = await strategy.apply(
            (Hunk(path="p.py", old="x = 1", new="x = 99"),),
            sandbox,
            transactional=True,
        )
        assert outcome.applied is True
        result = await sandbox.read_file("p.py")
        assert "x = 99" in result


# ---------------------------------------------------------------------------
# Opt-in isolation — default "legacy" is byte-identical
# ---------------------------------------------------------------------------


class TestAnchorStrategyOptIn:
    """Opt-in: legacy default unchanged; anchor only when edit_strategy='anchor'."""

    def test_legacy_default_multi_file_edit_not_registered(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """edit_strategy='legacy' (config=None) → multi_file_edit absent from specs."""
        from swarmline.tools.builtin import create_sandbox_tools

        specs, executors = create_sandbox_tools(sandbox, config=None)
        assert "multi_file_edit" not in specs
        assert "multi_file_edit" not in executors

    def test_anchor_strategy_literal_accepted_by_coding_profile(self) -> None:
        """CodingProfileConfig accepts edit_strategy='anchor' without validation error."""
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        cfg = CodingProfileConfig(edit_strategy="anchor")
        assert cfg.edit_strategy == "anchor"

    async def test_anchor_strategy_routing_registers_multi_file_edit(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """edit_strategy='anchor' → multi_file_edit registered in specs and executors."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        specs, executors = create_sandbox_tools(
            sandbox, config=CodingProfileConfig(edit_strategy="anchor")
        )
        assert "multi_file_edit" in specs
        assert "multi_file_edit" in executors

    async def test_anchor_strategy_routing_applies_anchored_edit_via_executor(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """Anchor executor applies a correctly-anchored edit end-to-end."""
        import json

        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        content = "alpha\nbeta\ngamma\n"
        await sandbox.write_file("route.py", content)

        _, executors = create_sandbox_tools(
            sandbox, config=CodingProfileConfig(edit_strategy="anchor")
        )

        old = "beta"
        anchor = _sha256(old)
        result = await executors["multi_file_edit"](
            {
                "edits": [
                    {
                        "path": "route.py",
                        "old_string": old,
                        "new_string": "BETA",
                        "anchor": anchor,
                    }
                ]
            }
        )
        data = json.loads(result)
        assert data["status"] == "ok", f"Unexpected failure: {data}"
        new_content = await sandbox.read_file("route.py")
        assert "BETA" in new_content
        assert "beta" not in new_content

    async def test_anchor_strategy_routing_rejects_stale_anchor_via_executor(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """Anchor executor rejects stale anchor; file is untouched."""
        import json

        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        content = "alpha\nbeta\ngamma\n"
        await sandbox.write_file("route.py", content)

        _, executors = create_sandbox_tools(
            sandbox, config=CodingProfileConfig(edit_strategy="anchor")
        )

        stale_anchor = _sha256("STALE")
        result = await executors["multi_file_edit"](
            {
                "edits": [
                    {
                        "path": "route.py",
                        "old_string": "beta",
                        "new_string": "BETA",
                        "anchor": stale_anchor,
                    }
                ]
            }
        )
        data = json.loads(result)
        assert data["status"] == "error"
        assert await sandbox.read_file("route.py") == content


# ---------------------------------------------------------------------------
# Fail-closed: anchor is REQUIRED in anchor mode (missing/empty → rejected)
# ---------------------------------------------------------------------------


class TestAnchorModeRequiresAnchor:
    """edit_strategy='anchor' is fail-closed: omitting or emptying anchor is rejected."""

    async def test_anchor_edit_executor_missing_anchor_rejects_before_write(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """Single-file edit without anchor field → rejected, file byte-identical."""
        import json

        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        content = "x = 1\n"
        await sandbox.write_file("f.py", content)

        _, executors = create_sandbox_tools(
            sandbox, config=CodingProfileConfig(edit_strategy="anchor")
        )
        result = await executors["edit"](
            {"path": "f.py", "old_string": "x = 1", "new_string": "x = 2"}
        )
        data = json.loads(result)
        assert data["status"] == "error", f"Expected error, got: {data}"
        # File must be untouched
        assert await sandbox.read_file("f.py") == content

    async def test_anchor_edit_executor_empty_anchor_rejects_before_write(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """Single-file edit with anchor='' → rejected (empty treated as missing)."""
        import json

        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        content = "x = 1\n"
        await sandbox.write_file("f.py", content)

        _, executors = create_sandbox_tools(
            sandbox, config=CodingProfileConfig(edit_strategy="anchor")
        )
        result = await executors["edit"](
            {"path": "f.py", "old_string": "x = 1", "new_string": "x = 2", "anchor": ""}
        )
        data = json.loads(result)
        assert data["status"] == "error", f"Expected error on empty anchor, got: {data}"
        assert await sandbox.read_file("f.py") == content

    async def test_anchor_multi_file_edit_one_missing_anchor_rejects_all(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """multi_file_edit: one item without anchor → whole call rejected, all files untouched."""
        import json

        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        a_content = "alpha\nbeta\n"
        b_content = "one\ntwo\n"
        await sandbox.write_file("a.py", a_content)
        await sandbox.write_file("b.py", b_content)

        _, executors = create_sandbox_tools(
            sandbox, config=CodingProfileConfig(edit_strategy="anchor")
        )
        # edit a.py has a valid anchor; edit b.py is missing anchor entirely
        valid_anchor = _sha256("beta")
        result = await executors["multi_file_edit"](
            {
                "edits": [
                    {
                        "path": "a.py",
                        "old_string": "beta",
                        "new_string": "BETA",
                        "anchor": valid_anchor,
                    },
                    {
                        "path": "b.py",
                        "old_string": "two",
                        "new_string": "TWO",
                        # anchor intentionally omitted
                    },
                ]
            }
        )
        data = json.loads(result)
        assert data["status"] == "error", (
            f"Expected error when anchor missing, got: {data}"
        )
        # Both files must be untouched
        assert await sandbox.read_file("a.py") == a_content
        assert await sandbox.read_file("b.py") == b_content

    async def test_anchor_edit_executor_whitespace_only_anchor_rejects_before_write(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """Single-file edit with anchor='   ' → rejected by early guard (not stale_anchor)."""
        import json

        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        content = "x = 1\n"
        await sandbox.write_file("f.py", content)

        _, executors = create_sandbox_tools(
            sandbox, config=CodingProfileConfig(edit_strategy="anchor")
        )
        result = await executors["edit"](
            {
                "path": "f.py",
                "old_string": "x = 1",
                "new_string": "x = 2",
                "anchor": "   ",
            }
        )
        data = json.loads(result)
        assert data["status"] == "error", (
            f"Expected error on whitespace-only anchor, got: {data}"
        )
        # Must be the executor-level early rejection, NOT a strategy stale_anchor.
        # _make_json_error returns {"status","message"}; _serialize_edit_outcome adds "results".
        assert "results" not in data, (
            "Whitespace anchor should be rejected by executor guard before reaching "
            f"AnchorEditStrategy, but got strategy-level response: {data}"
        )
        assert "anchor is required" in data.get("message", ""), (
            f"Expected 'anchor is required' in message, got: {data}"
        )
        assert await sandbox.read_file("f.py") == content


# ---------------------------------------------------------------------------
# Schema: anchor mode publishes anchor-aware spec for single-file edit tool
# ---------------------------------------------------------------------------


class TestAnchorModeEditSchema:
    """In anchor mode the published ToolSpec for 'edit' exposes and requires 'anchor'."""

    def test_anchor_mode_edit_spec_requires_anchor_field(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """specs['edit'] in anchor mode has 'anchor' in its required array."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        specs, _ = create_sandbox_tools(
            sandbox, config=CodingProfileConfig(edit_strategy="anchor")
        )
        edit_spec = specs["edit"]
        required = edit_spec.parameters.get("required", [])
        assert "anchor" in required, (
            f"Expected 'anchor' in required, got required={required}"
        )

    def test_anchor_mode_edit_spec_exposes_anchor_property(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """specs['edit'] in anchor mode has 'anchor' in its properties."""
        from swarmline.tools.builtin import create_sandbox_tools
        from swarmline.runtime.thin.coding_profile import CodingProfileConfig

        specs, _ = create_sandbox_tools(
            sandbox, config=CodingProfileConfig(edit_strategy="anchor")
        )
        edit_spec = specs["edit"]
        props = edit_spec.parameters.get("properties", {})
        assert "anchor" in props, (
            f"Expected 'anchor' in properties, got properties={list(props.keys())}"
        )

    def test_legacy_mode_edit_spec_unchanged(
        self, sandbox: LocalSandboxProvider
    ) -> None:
        """specs['edit'] with legacy config has no 'anchor' field (byte-identical)."""
        from swarmline.tools.builtin import create_sandbox_tools

        specs, _ = create_sandbox_tools(sandbox, config=None)
        edit_spec = specs["edit"]
        required = edit_spec.parameters.get("required", [])
        assert "anchor" not in required
        props = edit_spec.parameters.get("properties", {})
        assert "anchor" not in props
