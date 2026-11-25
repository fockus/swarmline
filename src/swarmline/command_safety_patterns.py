# Attribution: adapted from hermes-agent (MIT)
# Upstream file: tools/approval.py (HARDLINE_PATTERNS, DANGEROUS_PATTERNS,
#                _SUDO_STDIN_RE) and tools/ansi_strip.py (ANSI escape regex)
# Copyright: (c) Nous Research and contributors
# Changes: extracted the regex corpus into a standalone data module so the
#          classifier in command_safety.py stays <=300 lines; inlined the ANSI
#          strip regex (no external deps); removed taskloom REQ-ID references.
#          Hardline rm corpus hardened beyond upstream to close hardline-deny
#          bypasses: braced ${HOME} expansion added, and the trailing target
#          anchor widened (_RM_TARGET_END) so a shell separator attached to a
#          protected target (e.g. `rm -rf /;true`) no longer downgrades to
#          approval-required.
"""Shell-command risk-pattern corpus for :mod:`swarmline.command_safety`.

Split out from the classifier purely to honour the <=300-line file invariant:
this module is the regex DATA (HARDLINE + dangerous corpora, building blocks,
ANSI/sudo guards) while ``command_safety.py`` holds the policy logic.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# ANSI stripping (inlined from hermes tools/ansi_strip.py — MIT License)
# ---------------------------------------------------------------------------

ANSI_ESCAPE_RE = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"  # CSI sequence
    r"|\][\s\S]*?(?:\x07|\x1b\\)"  # OSC (BEL or ST terminator)
    r"|[PX^_][\s\S]*?(?:\x1b\\)"  # DCS/SOS/PM/APC strings
    r"|[\x20-\x2f]+[\x30-\x7e]"  # nF escape sequences
    r"|[\x30-\x7e]"  # Fp/Fe/Fs single-byte
    r")"
    r"|\x9b[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"  # 8-bit CSI
    r"|\x9d[\s\S]*?(?:\x07|\x9c)"  # 8-bit OSC
    r"|[\x80-\x9f]",  # Other 8-bit C1 controls
    re.DOTALL,
)
HAS_ESCAPE_RE = re.compile(r"[\x1b\x80-\x9f]")

# ---------------------------------------------------------------------------
# Regex building blocks (ported from tools/approval.py)
# ---------------------------------------------------------------------------

_RE_FLAGS = re.IGNORECASE | re.DOTALL

# Trailing boundary for rm-target patterns: whitespace, end-of-string, or any
# shell separator/terminator (`;` `&` `|` backtick `)` `<` `>`).
# Quotes are already stripped by normalization so they never appear here.
_RM_TARGET_END = r"(?:\s|$|[;&|`)<>])"

_CMDPOS = (
    r"(?:^|[;&|\n`]|\$\()"  # start position
    r"\s*"  # optional whitespace
    r"(?:sudo\s+(?:-[^\s]+\s+)*)?"  # optional sudo with flags
    r"(?:env\s+(?:\w+=\S*\s+)*)?"  # optional env with VAR=VAL pairs
    r"(?:(?:exec|nohup|setsid|time)\s+)*"  # optional wrapper commands
    r"\s*"
)

# Sensitive-write path fragments (ported from tools/approval.py)
_SSH_SENSITIVE_PATH = r"(?:~|\$home|\$\{home\})/\.ssh(?:/|$)"
_SHELL_RC_FILES = (
    r"(?:~|\$home|\$\{home\})/\.(?:bashrc|zshrc|profile|bash_profile|zprofile)\b"
)
_CREDENTIAL_FILES = r"(?:~|\$home|\$\{home\})/\.(?:netrc|pgpass|npmrc|pypirc)\b"
_MACOS_PRIVATE_SYSTEM_PATH = r"/private/(?:etc|var|tmp|home)/"
_SYSTEM_CONFIG_PATH = rf"(?:/etc/|{_MACOS_PRIVATE_SYSTEM_PATH})"
_PROJECT_ENV_PATH = r"(?:(?:/|\.{1,2}/)?(?:[^\s/\"'`]+/)*\.env(?:\.[^/\s\"'`]+)*)"
_PROJECT_CONFIG_PATH = r"(?:(?:/|\.{1,2}/)?(?:[^\s/\"'`]+/)*config\.yaml)"
_COMMAND_TAIL = r"(?:\s*(?:&&|\|\||;).*)?$"
_SENSITIVE_WRITE_TARGET = (
    rf"(?:{_SYSTEM_CONFIG_PATH}|/dev/sd|"
    rf"{_SSH_SENSITIVE_PATH}|"
    rf"{_SHELL_RC_FILES}|"
    rf"{_CREDENTIAL_FILES})"
)
_USER_SENSITIVE_WRITE_TARGET = (
    rf"(?:{_SSH_SENSITIVE_PATH}|" rf"{_SHELL_RC_FILES}|" rf"{_CREDENTIAL_FILES})"
)
_PROJECT_SENSITIVE_WRITE_TARGET = rf"(?:{_PROJECT_ENV_PATH}|{_PROJECT_CONFIG_PATH})"

# ---------------------------------------------------------------------------
# Hardline patterns corpus — unconditional block.
# Adapted from tools/approval.py HARDLINE_PATTERNS, with the rm-target corpus
# hardened (braced ${HOME}; separator-aware _RM_TARGET_END boundary).
# ---------------------------------------------------------------------------

HARDLINE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\brm\s+(-[^\s]*\s+)*(/|/\*|/ \*)" + _RM_TARGET_END, _RE_FLAGS),
        "recursive delete of root filesystem",
    ),
    (
        re.compile(
            r"\brm\s+(-[^\s]*\s+)*(/home|/home/\*|/root|/root/\*|/etc|/etc/\*"
            r"|/usr|/usr/\*|/var|/var/\*|/bin|/bin/\*|/sbin|/sbin/\*"
            r"|/boot|/boot/\*|/lib|/lib/\*)" + _RM_TARGET_END,
            _RE_FLAGS,
        ),
        "recursive delete of system directory",
    ),
    (
        re.compile(
            r"\brm\s+(-[^\s]*\s+)*(~|\$HOME|\$\{HOME\})(/?|/\*)?" + _RM_TARGET_END,
            _RE_FLAGS,
        ),
        "recursive delete of home directory",
    ),
    (re.compile(r"\bmkfs(\.[a-z0-9]+)?\b", _RE_FLAGS), "format filesystem (mkfs)"),
    (
        re.compile(
            r"\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*", _RE_FLAGS
        ),
        "dd to raw block device",
    ),
    (
        re.compile(r">\s*/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*\b", _RE_FLAGS),
        "redirect to raw block device",
    ),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", _RE_FLAGS), "fork bomb"),
    (re.compile(r"\bkill\s+(-[^\s]+\s+)*-1\b", _RE_FLAGS), "kill all processes"),
    (
        re.compile(_CMDPOS + r"(shutdown|reboot|halt|poweroff)\b", _RE_FLAGS),
        "system shutdown/reboot",
    ),
    (re.compile(_CMDPOS + r"init\s+[06]\b", _RE_FLAGS), "init 0/6 (shutdown/reboot)"),
    (
        re.compile(_CMDPOS + r"systemctl\s+(poweroff|reboot|halt|kexec)\b", _RE_FLAGS),
        "systemctl poweroff/reboot",
    ),
    (
        re.compile(_CMDPOS + r"telinit\s+[06]\b", _RE_FLAGS),
        "telinit 0/6 (shutdown/reboot)",
    ),
]

# ---------------------------------------------------------------------------
# Sudo stdin guard
# ---------------------------------------------------------------------------

SUDO_STDIN_RE = re.compile(
    r"(?:^|[;&|`\n]|&&|\|\||\$\()\s*sudo\s+-S\b",
    re.IGNORECASE,
)

# The APPROVAL_REQUIRED (dangerous) corpus lives in command_safety_dangerous.py
# (split out to keep every command_safety file <=300 lines). It reuses the
# shared regex building blocks defined above (_RE_FLAGS + sensitive-path
# fragments), so those fragments stay module-level here for cross-import.

__all__ = [
    "ANSI_ESCAPE_RE",
    "HARDLINE_PATTERNS",
    "HAS_ESCAPE_RE",
    "SUDO_STDIN_RE",
]
