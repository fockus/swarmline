"""CodingProfileConfig — opt-in coding-agent profile for ThinRuntime.

Frozen dataclass that declares coding profile parameters.
When enabled on AgentConfig, ThinRuntime gains the canonical coding
tool surface (read/write/edit/multi_edit/bash/ls/glob/grep) with
matching policy scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CodingProfileConfig:
    """Opt-in coding-agent profile configuration.

    Attributes:
        enabled: Master switch — when True, coding tools are injected
                 and policy is scoped to the coding tool set.
        allow_host_execution: Whether the coding sandbox permits host
                              commands (bash). Set to False for read-only profiles.
        edit_strategy: Edit-format engine selection. ``"legacy"`` (default) keeps
                       the existing first-occurrence str_replace behaviour unchanged.
                       ``"search_replace"`` enables tolerant cascade matching (adapted
                       from aider/hermes). ``"patch"`` enables V4A transactional patch.
                       ``"auto"`` selects the strategy based on the active model family.
                       ``"anchor"`` enables hash-anchored transactional edits (REQ-RCA-070):
                       each hunk carries a sha256 of its target slice; edits are rejected
                       before any write if the anchor is stale (file changed since last read).
                       All non-legacy values are gated behind Task 1.
        enable_repo_map_ranking: Enable graph-ranked repo-map tool output (Task 3).
                                 When False (default) the repo-map tool output is
                                 byte-identical to the existing ASTRepoMapper output.
        enable_post_edit_verify: Enable pre/post-edit snapshot coordinator that
                                 computes lint-delta after each edit tool call (Task 4).
        enable_lsp_verify: Enable type-aware LSP verify pass after edit (Task 8).
                           Requires ``enable_post_edit_verify`` to also be True.
        enable_edit_guards: Enable anti-flailing pre/post edit guard hooks (Task 6).
        enable_git_checkpoints: Enable git checkpoint after each accepted edit (Task 7).
                                Silently skipped when no git-backed WorkspaceSession.
        max_reflections: Maximum verify-loop reflections per run before feedback is
                         suppressed (Task 5 / RCA-Task 1). Resets on success. Default 3.
        repo_map_max_tokens: Token budget for ranked repo-map truncation (Task 3).
                             Default 4000.
        enable_auto_lint_test: Enable the full-command lint/test auto-verify convergence
                               loop (RCA Task 1). When False (default), the turn loop is
                               byte-identical — no AutoVerifyLoop is constructed and no
                               behaviour changes. When True, after each edit tool call the
                               configured command is run and failures are re-injected as
                               the next agent turn, bounded by ``max_reflections``.
        auto_verify_command: Shell command for the lint/test loop
                             (``enable_auto_lint_test``). When ``None`` (default) the
                             loop fails-open and skips every verify run. Only a single
                             command is supported — shell operators (``&&``, ``;``,
                             ``|``) are rejected by the workspace command validator.
                             Example: ``"pytest"`` or ``"ruff check ."``.
        enable_model_tiering: Enable weak-model routing for auxiliary tasks such as
                              summarization (RCA Task 2). When False (default), ALL
                              LLM calls use the main model exactly as before — the
                              runtime path is byte-identical. When True, callers gate
                              auxiliary calls through ``select_aux_model()`` from
                              ``swarmline.runtime.model_settings``, routing to the
                              ``weak_model`` declared in models.yaml (if any) or
                              falling back to the main model unchanged.
        enable_architect: Enable the two-model architect split (RCA Task 3). When
                          False (default), the runtime path is byte-identical — no
                          ``ArchitectCoordinator`` is constructed or invoked and
                          every coding turn runs via the normal single-model path.
                          When True AND the active main model declares an
                          ``editor_model`` in models.yaml, the coding turn is split
                          into Phase 1 (plan, main model, repo-map OFF) and Phase 2
                          (edit, editor model, editor's edit_format). If
                          ``editor_model`` is absent the coordinator falls back to
                          the normal single-model edit (REQ-RCA-012 fallback) —
                          behaviour is then byte-identical regardless of this flag.
        enable_lazy_skills: Enable lazy skill loading (RCA Task 6 / REQ-RCA-040).
                            When False (default), the system context embeds the full
                            ``instruction_md`` body for each active skill — the
                            context assembly path is byte-identical to all prior
                            phases.  When True, the system context lists skill
                            names + descriptions ONLY; the full body is loaded on
                            demand via the ``read_skill`` local tool which the LLM
                            calls when it needs the complete instruction text.
                            This bounds system-prompt growth to O(N × name+desc)
                            rather than O(N × body) for large skill catalogues.
    """

    enabled: bool = True
    allow_host_execution: bool = True
    edit_strategy: Literal["legacy", "search_replace", "patch", "auto", "anchor"] = (
        "legacy"
    )
    enable_repo_map_ranking: bool = False
    enable_post_edit_verify: bool = False
    enable_lsp_verify: bool = False
    enable_edit_guards: bool = False
    enable_git_checkpoints: bool = False
    max_reflections: int = 3
    repo_map_max_tokens: int = 4000
    enable_auto_lint_test: bool = False
    auto_verify_command: str | None = None
    enable_model_tiering: bool = False
    enable_architect: bool = False
    enable_lazy_skills: bool = False
