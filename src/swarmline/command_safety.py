# Attribution: adapted from hermes-agent (MIT)
# Upstream file: tools/approval.py (_normalize_command_for_detection, classify
#                ordering, sudo-stdin guard) and tools/ansi_strip.py
# Copyright: (c) Nous Research and contributors
# Changes: rewritten as a framework-neutral frozen-dataclass value object;
#          DomainValidationError -> stdlib ValueError; removed all product
#          (taskloom) imports; regex corpus moved to command_safety_patterns.py;
#          added the CommandGuard Protocol for the optional pre-exec seam.
"""Shell-command risk classifier for swarmline code-agents (REQ-OSS-001/002).

A pure, framework-neutral policy: classify a shell command into HARDLINE /
APPROVAL_REQUIRED / SAFE after anti-obfuscation normalization, then map that
level plus session interactivity to an allow/deny/escalate decision. No I/O, no
TTY sensing, no subprocess, no config — the regex corpus lives in
``command_safety_patterns.py`` (split to keep this module <=300 lines).
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from swarmline.command_safety_dangerous import DANGEROUS_PATTERNS
from swarmline.command_safety_patterns import (
    ANSI_ESCAPE_RE,
    HARDLINE_PATTERNS,
    HAS_ESCAPE_RE,
    SUDO_STDIN_RE,
)

# ---------------------------------------------------------------------------
# Risk + decision enums
# ---------------------------------------------------------------------------


class RiskLevel(StrEnum):
    """Risk classification for a shell command.

    HARDLINE          — unconditionally blocked; no bypass path.
    APPROVAL_REQUIRED — dangerous; requires explicit user approval.
    SAFE              — no known risk; proceed without approval.
    """

    HARDLINE = "hardline"
    APPROVAL_REQUIRED = "approval_required"
    SAFE = "safe"


class AccessDecision(StrEnum):
    """Final access decision for a classified command.

    The decision seam maps a :class:`RiskLevel` plus the interactivity of the
    session to a single allow/deny/escalate verdict. TTY detection and
    approval-prompt plumbing are caller concerns: ``interactive`` is passed in,
    never sensed.

    ALLOW            — execute without approval.
    REQUIRE_APPROVAL — execute only after explicit interactive user approval.
    DENY             — refuse unconditionally (no approval path available).
    """

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


# ---------------------------------------------------------------------------
# Anti-evasion consent contract
# ---------------------------------------------------------------------------

_HARDLINE_CONSENT_CONTRACT = (
    "This command is on the unconditional blocklist and cannot be executed via "
    "the agent — do NOT retry, do NOT rephrase to achieve the same outcome. "
    "If you genuinely need to run it, run it yourself in a terminal outside the agent."
)


# ---------------------------------------------------------------------------
# Normalization (anti-obfuscation layer)
# ---------------------------------------------------------------------------


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from *text* (inlined from ansi_strip.py)."""
    if not text or not HAS_ESCAPE_RE.search(text):
        return text
    return ANSI_ESCAPE_RE.sub("", text)


def _rewrite_resolved_user_home(command: str) -> str:
    """Rewrite the current user's absolute home prefix to ``~/``.

    Resolves HOME at detection time so commands targeting absolute home paths
    are checked by the same static patterns as tilde / $HOME forms. No-op when
    HOME is unset or degenerate. Uses only stdlib ``os``.
    """
    try:
        home = os.path.expanduser("~")
        candidates = [home.rstrip("/"), os.path.realpath(home).rstrip("/")]
    except Exception:
        return command
    seen: set[str] = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        normalized = path.rstrip("/")
        if not normalized.startswith("/") or normalized.count("/") < 2:
            continue
        command = command.replace(normalized + "/", "~/")
        command = re.sub(re.escape(normalized) + r"(?![\w/])", "~", command)
    return command


def _normalize_command_for_detection(command: str) -> str:
    """Normalize a command string before risk-pattern matching.

    Anti-obfuscation steps (ported from hermes tools/approval.py):
    1. Strip ANSI escape sequences (inlined regex, no external deps).
    2. Strip null bytes.
    3. NFKC Unicode normalization (fullwidth Latin, etc.).
    4. Strip shell backslash-escapes: ``r\\m`` -> ``rm``.
    5. Strip ALL shell quote characters: ``r'm'`` / ``'r'm`` -> ``rm``.
    6. Rewrite resolved absolute home path to ``~/`` (stdlib os only).

    Step 5 strips *every* single/double quote (not just empty pairs): shells
    treat ``r'm'`` and ``'r'm`` as the single token ``rm``, so non-empty quotes
    are valid word-splitters an attacker can use to slip a hardline command past
    a naive empty-pair strip. Aggressive stripping can over-block a benign
    command that legitimately quotes a dangerous phrase; that tradeoff fails
    *safe* — the agent is told to run such a command itself in a terminal.
    """
    command = _strip_ansi(command)
    command = command.replace("\x00", "")
    command = unicodedata.normalize("NFKC", command)
    command = re.sub(r"\\([^\n])", r"\1", command)
    command = re.sub(r"['\"]", "", command)
    command = _rewrite_resolved_user_home(command)
    return command


# ---------------------------------------------------------------------------
# CommandRiskPolicy value object
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class CommandRiskPolicy:
    """Pure command risk classifier.

    Classifies shell commands into three risk levels by matching against the
    ported hermes corpus. No I/O, no config, no TTY — pure policy.

    Usage::

        policy = CommandRiskPolicy()
        level, reason = policy.classify("rm -rf /")
        # level == RiskLevel.HARDLINE

    ``classify`` is deterministic: the same input always yields the same
    ``(level, reason)`` tuple.
    """

    def classify(self, cmd: str) -> tuple[RiskLevel, str]:
        """Classify *cmd* and return ``(RiskLevel, human-readable reason)``.

        Evaluation order:
        1. Hardline patterns — unconditional block, anti-retry contract appended.
        2. Sudo stdin guard — catches ``sudo -S`` password-guessing.
        3. Dangerous patterns — APPROVAL_REQUIRED.
        4. Default — SAFE.

        ``reason`` is the empty string for SAFE.
        """
        normalized = _normalize_command_for_detection(cmd).lower()

        # 1. Hardline floor
        for pattern, description in HARDLINE_PATTERNS:
            if pattern.search(normalized):
                reason = (
                    f"BLOCKED (hardline): {description}. {_HARDLINE_CONSENT_CONTRACT}"
                )
                return (RiskLevel.HARDLINE, reason)

        # 2. Sudo stdin guard
        if SUDO_STDIN_RE.search(normalized):
            return (
                RiskLevel.APPROVAL_REQUIRED,
                "sudo password guessing via stdin (sudo -S) — do not pipe passwords to sudo -S",
            )

        # 3. Dangerous / approval-required patterns
        for pattern, description in DANGEROUS_PATTERNS:
            if pattern.search(normalized):
                return (RiskLevel.APPROVAL_REQUIRED, description)

        return (RiskLevel.SAFE, "")

    def decide(self, level: RiskLevel, *, interactive: bool) -> AccessDecision:
        """Map a risk *level* + session interactivity to a final access decision.

        Truth table:
            HARDLINE                              -> DENY (no interactive bypass).
            APPROVAL_REQUIRED + not interactive   -> DENY (hosted default-deny).
            APPROVAL_REQUIRED + interactive       -> REQUIRE_APPROVAL.
            SAFE                                  -> ALLOW.
        """
        if level == RiskLevel.HARDLINE:
            return AccessDecision.DENY
        if level == RiskLevel.APPROVAL_REQUIRED:
            return (
                AccessDecision.REQUIRE_APPROVAL if interactive else AccessDecision.DENY
            )
        return AccessDecision.ALLOW

    def __post_init__(self) -> None:
        # Frozen dataclass with no fields — validate the class invariant that
        # the pattern corpora are non-empty (catches accidental truncation).
        if not HARDLINE_PATTERNS:
            raise ValueError("HARDLINE_PATTERNS corpus is empty")
        if not DANGEROUS_PATTERNS:
            raise ValueError("DANGEROUS_PATTERNS corpus is empty")


# ---------------------------------------------------------------------------
# Optional pre-exec guard seam
# ---------------------------------------------------------------------------


@runtime_checkable
class CommandGuard(Protocol):
    """Structural type for the optional pre-exec guard.

    :class:`CommandRiskPolicy` satisfies this protocol. Code paths that want to
    gate shell commands accept a ``CommandGuard | None`` and, when one is
    supplied, classify + decide before executing.
    """

    def classify(self, cmd: str) -> tuple[RiskLevel, str]: ...

    def decide(self, level: RiskLevel, *, interactive: bool) -> AccessDecision: ...


__all__ = [
    "AccessDecision",
    "CommandGuard",
    "CommandRiskPolicy",
    "RiskLevel",
]
