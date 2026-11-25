"""EditSnapshotCoordinator — in-turn verify-loop (Pre snapshot + Post delta).

B1 fix: ``PostToolUse`` receives only ``tool_name, tool_input, tool_output`` —
it cannot see the *before* content. So the before-snapshot is taken by a
``PreToolUse`` hook (``on_pre_tool``), and ``PostToolUse`` (``on_post_tool``)
only renders the lint delta from that snapshot against the post-edit content.

NEW-ISSUE-1 fix: the dispatcher matches tool names via ``fnmatch(tool_name,
matcher)`` which has **no ``|`` alternation**. Therefore the coordinator is
registered as ONE hook-entry per exact edit/write tool name
(``edit``, ``write``, ``multi_edit``, ``multi_file_edit``) under both
``PreToolUse`` and ``PostToolUse`` — and only when ``enable_post_edit_verify``.

``react_strategy`` / ``ToolExecutor`` are NOT modified. Hooks are fail-open:
any exception inside a hook must NOT break the agent loop (mirrors the
dispatcher's existing fail-open contract).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from swarmline.hooks.dispatcher import HookResult
from swarmline.runtime.thin.reflection import ReflectionState

if TYPE_CHECKING:
    from swarmline.hooks.registry import HookRegistry
    from swarmline.orchestration.lint_delta import DeltaLinter, LintDelta
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig
    from swarmline.tools.protocols import SandboxProvider

logger = logging.getLogger(__name__)

# Exact edit/write tool names this coordinator snapshots. Registered one-per-name
# because fnmatch matchers have no `|` alternation (NEW-ISSUE-1).
EDIT_TOOL_NAMES: tuple[str, ...] = ("edit", "write", "multi_edit", "multi_file_edit")


class EditSnapshotCoordinator:
    """Snapshots before-content on Pre, renders a lint delta on Post.

    Holds a per-run ``{path: before_content}`` map. A snapshot is invalidated
    (popped) after its delta is rendered, so a stale Post without a fresh Pre
    is a no-op.
    """

    def __init__(
        self,
        sandbox: SandboxProvider,
        *,
        delta_linter: DeltaLinter,
        reflection: ReflectionState | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._delta_linter = delta_linter
        self._reflection = reflection
        self._before: dict[str, str] = {}

    def snapshot_for(self, path: str) -> str | None:
        """Return the captured before-content for a path, or None if unsnapshotted."""
        return self._before.get(path)

    async def on_pre_tool(self, *, tool_name: str, tool_input: dict) -> HookResult:
        """Snapshot the before-content of the path(s) the tool will mutate.

        Best-effort: a missing file → empty baseline. ALWAYS allow — blocking is
        Task 6's concern, never this coordinator's. Fail-open on any error.
        """
        try:
            for path in self._paths_for(tool_name, tool_input):
                self._before[path] = await self._read_before(path)
        except Exception:
            logger.warning(
                "EditSnapshotCoordinator.on_pre_tool failed for %r (fail-open)",
                tool_name,
                exc_info=True,
            )
        return HookResult.allow()

    async def on_post_tool(
        self, *, tool_name: str, tool_input: dict, tool_output: str
    ) -> str | None:
        """Render the lint delta for each snapshotted path against the post-state.

        Returns the augmented ``tool_output`` (with a verify-feedback block) when
        there is something to report, else None (no change). The snapshot for each
        rendered path is invalidated afterwards. Fail-open → None.

        Reflection budget (Task 5, NEW-ISSUE-2): a Post hook can only rewrite
        ``tool_output`` — it CANNOT halt the loop, so this method never raises to
        stop it. When a ``reflection`` is wired, the budget governs only WHETHER
        edit-introduced-error feedback keeps being appended:

        * ``reflection is None`` → byte-identical T4 behaviour.
        * failure (new_errors) AND ``should_reflect()`` → append the feedback +
          ``record_failure()``.
        * failure AT/PAST the cap → drop the feedback, append a single TERMINAL
          note so the model finalizes; do NOT increment further.
        * success (no new_errors; still_broken_not_new is informational) →
          ``reset_on_success()`` and render as T4 does.
        """
        try:
            blocks: list[str] = []
            has_failure = False
            checked = False
            for path in self._paths_for(tool_name, tool_input):
                before = self._before.pop(path, None)
                if before is None:
                    continue  # no fresh Pre snapshot → nothing to compare
                after = await self._read_after(path)
                delta = await self._delta_linter.diff(path, before, after)
                checked = True  # a real delta was computed for this post
                if delta.new_errors:
                    has_failure = True
                rendered = self._render_delta(delta)
                if rendered is not None:
                    blocks.append(rendered)

            if self._reflection is None:
                # T4 path: byte-identical to pre-reflection behaviour.
                if not blocks:
                    return None
                return tool_output + "\n\n" + "\n".join(blocks)

            if not checked:
                # No fresh snapshot / no path checked → a no-op post. Do NOT touch
                # the budget: a clean verify never happened, so resetting here would
                # let a stale post bypass the cap (blocks is necessarily empty).
                return None

            if not has_failure:
                # Success (only clean / still-broken-not-new) → reset the budget;
                # surface informational blocks exactly as T4 does.
                self._reflection.reset_on_success()
                if not blocks:
                    return None
                return tool_output + "\n\n" + "\n".join(blocks)

            # Failure with a reflection budget wired.
            if self._reflection.should_reflect():
                self._reflection.record_failure()
                return tool_output + "\n\n" + "\n".join(blocks)
            # At/past cap → stop goading; emit one terminal note instead.
            return tool_output + "\n\n" + self._terminal_note(self._reflection)
        except Exception:
            logger.warning(
                "EditSnapshotCoordinator.on_post_tool failed for %r (fail-open)",
                tool_name,
                exc_info=True,
            )
            return None

    @staticmethod
    def _terminal_note(reflection: ReflectionState) -> str:
        """Single terminal note appended once the reflection budget is exhausted."""
        attempts = reflection.count
        noun = "attempt" if attempts == 1 else "attempts"
        return (
            f"[verify] reflection budget exhausted after {attempts} {noun} — "
            "finalize your answer; no further auto-verify feedback will be added."
        )

    @staticmethod
    def _render_delta(delta: LintDelta) -> str | None:
        """Render a verify-feedback block, or None when nothing is worth surfacing."""
        if not delta.new_errors and not delta.still_broken_not_new:
            return None
        lines = ["[verify] " + delta.summary]
        for err in delta.new_errors:
            lines.append(f"  - {err}")
        return "\n".join(lines)

    @staticmethod
    def _paths_for(tool_name: str, tool_input: dict) -> list[str]:
        """Extract mutated path(s) from a tool's input.

        - edit/write/multi_edit use a single ``path`` key.
        - multi_file_edit carries ``edits: [{path, ...}]`` across files.
        """
        if tool_name == "multi_file_edit":
            edits = tool_input.get("edits") or []
            seen: list[str] = []
            for edit in edits:
                path = edit.get("path") if isinstance(edit, dict) else None
                if isinstance(path, str) and path and path not in seen:
                    seen.append(path)
            return seen
        path = tool_input.get("path")
        return [path] if isinstance(path, str) and path else []

    async def _read_before(self, path: str) -> str:
        """Read before-content; a missing file is an empty baseline (new file)."""
        try:
            return await self._sandbox.read_file(path)
        except FileNotFoundError:
            return ""

    async def _read_after(self, path: str) -> str:
        """Read post-edit content; a vanished file is an empty after-state."""
        try:
            return await self._sandbox.read_file(path)
        except FileNotFoundError:
            return ""


def register_edit_verify_hooks(
    registry: HookRegistry,
    coordinator: EditSnapshotCoordinator,
    config: CodingProfileConfig,
) -> None:
    """Register the coordinator's Pre/Post hooks — one entry per exact tool name.

    Gated on ``config.enable_post_edit_verify``: when False, nothing is
    registered (default path stays byte-identical). One ``PreToolUse`` and one
    ``PostToolUse`` entry per name in :data:`EDIT_TOOL_NAMES`, each with
    ``matcher`` set to the exact name — never an alternation (fnmatch has no
    ``|`` support, NEW-ISSUE-1).
    """
    if not config.enable_post_edit_verify:
        return
    for name in EDIT_TOOL_NAMES:
        registry.on_pre_tool_use(coordinator.on_pre_tool, matcher=name)
        registry.on_post_tool_use(coordinator.on_post_tool, matcher=name)
