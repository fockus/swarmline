# Attribution: adapted from hermes-agent (MIT)
# Upstream file: tools/approval.py (DANGEROUS_PATTERNS)
# Copyright: (c) Nous Research and contributors
# Changes: extracted the APPROVAL_REQUIRED corpus into its own data module so
#          every command_safety file stays <=300 lines; reuses the shared regex
#          building blocks from command_safety_patterns.py; removed taskloom
#          REQ-ID references; hardened dynamic-execution detection beyond the
#          verbatim upstream corpus: added generalized pipe-to-shell (any source,
#          not only curl/wget) and eval-at-command-position patterns (OSS-BL-01).
"""APPROVAL_REQUIRED (dangerous) shell-command pattern corpus.

Split from ``command_safety_patterns.py`` purely to honour the <=300-line file
invariant — this module holds only the dangerous-command regex DATA and reuses
the shared building blocks (``_RE_FLAGS`` + sensitive-path fragments) from the
patterns module.
"""

from __future__ import annotations

import re

from swarmline.command_safety_patterns import (
    _COMMAND_TAIL,
    _PROJECT_SENSITIVE_WRITE_TARGET,
    _RE_FLAGS,
    _SENSITIVE_WRITE_TARGET,
    _SYSTEM_CONFIG_PATH,
    _USER_SENSITIVE_WRITE_TARGET,
)

# ---------------------------------------------------------------------------
# Dangerous / APPROVAL_REQUIRED patterns corpus.
# Ported verbatim from tools/approval.py DANGEROUS_PATTERNS.
# ---------------------------------------------------------------------------

DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[^\s]*\s+)*/", _RE_FLAGS), "delete in root path"),
    (re.compile(r"\brm\s+-[^\s]*r", _RE_FLAGS), "recursive delete"),
    (re.compile(r"\brm\s+--recursive\b", _RE_FLAGS), "recursive delete (long flag)"),
    (
        re.compile(
            r"\bchmod\s+(-[^\s]*\s+)*(777|666|o\+[rwx]*w|a\+[rwx]*w)\b", _RE_FLAGS
        ),
        "world/other-writable permissions",
    ),
    (
        re.compile(
            r"\bchmod\s+--recursive\b.*(777|666|o\+[rwx]*w|a\+[rwx]*w)", _RE_FLAGS
        ),
        "recursive world/other-writable (long flag)",
    ),
    (re.compile(r"\bchown\s+(-[^\s]*)?R\s+root", _RE_FLAGS), "recursive chown to root"),
    (
        re.compile(r"\bchown\s+--recursive\b.*root", _RE_FLAGS),
        "recursive chown to root (long flag)",
    ),
    (re.compile(r"\bmkfs\b", _RE_FLAGS), "format filesystem"),
    (re.compile(r"\bdd\s+.*if=", _RE_FLAGS), "disk copy"),
    (re.compile(r">\s*/dev/sd", _RE_FLAGS), "write to block device"),
    (re.compile(r"\bDROP\s+(TABLE|DATABASE)\b", _RE_FLAGS), "SQL DROP"),
    (
        re.compile(r"\bDELETE\s+FROM\b(?![^\n]*\bWHERE\b)", _RE_FLAGS),
        "SQL DELETE without WHERE",
    ),
    (re.compile(r"\bTRUNCATE\s+(TABLE)?\s*\w", _RE_FLAGS), "SQL TRUNCATE"),
    (re.compile(rf">\s*{_SYSTEM_CONFIG_PATH}", _RE_FLAGS), "overwrite system config"),
    (
        re.compile(
            r"\bsystemctl\s+(-[^\s]+\s+)*(stop|restart|disable|mask)\b", _RE_FLAGS
        ),
        "stop/restart system service",
    ),
    (re.compile(r"\bkill\s+-9\s+-1\b", _RE_FLAGS), "kill all processes"),
    (re.compile(r"\bpkill\s+-9\b", _RE_FLAGS), "force kill processes"),
    (
        re.compile(r"\bkillall\s+(-[^\s]*\s+)*-(9|KILL|SIGKILL)\b", _RE_FLAGS),
        "force kill processes (killall -KILL)",
    ),
    (
        re.compile(r"\bkillall\s+(-[^\s]*\s+)*-s\s+(KILL|SIGKILL|9)\b", _RE_FLAGS),
        "force kill processes (killall -s KILL)",
    ),
    (
        re.compile(r"\bkillall\s+(-[^\s]*\s+)*-r\b", _RE_FLAGS),
        "kill processes by regex (killall -r)",
    ),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", _RE_FLAGS), "fork bomb"),
    (
        re.compile(r"\b(bash|sh|zsh|ksh)\s+-[^\s]*c(\s+|$)", _RE_FLAGS),
        "shell command via -c/-lc flag",
    ),
    (
        re.compile(r"\b(python[23]?|perl|ruby|node)\s+-[ec]\s+", _RE_FLAGS),
        "script execution via -e/-c flag",
    ),
    (
        re.compile(
            r"\b(curl|wget)\b.*\|\s*(?:[/\w]*/)?(?:ba)?sh(?:\s|$|-c)", _RE_FLAGS
        ),
        "pipe remote content to shell",
    ),
    (
        re.compile(r"\b(bash|sh|zsh|ksh)\s+<\s*<?\s*\(\s*(curl|wget)\b", _RE_FLAGS),
        "execute remote script via process substitution",
    ),
    (
        re.compile(rf'\btee\b.*["\']?{_SENSITIVE_WRITE_TARGET}', _RE_FLAGS),
        "overwrite system file via tee",
    ),
    (
        re.compile(rf'>>?\s*["\']?{_SENSITIVE_WRITE_TARGET}', _RE_FLAGS),
        "overwrite system file via redirection",
    ),
    (
        re.compile(
            rf'\btee\b.*["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_COMMAND_TAIL}',
            _RE_FLAGS,
        ),
        "overwrite project env/config via tee",
    ),
    (
        re.compile(
            rf'>>?\s*["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_COMMAND_TAIL}',
            _RE_FLAGS,
        ),
        "overwrite project env/config via redirection",
    ),
    (re.compile(r"\bxargs\s+.*\brm\b", _RE_FLAGS), "xargs with rm"),
    (
        re.compile(r"\bfind\b.*-exec(?:dir)?\s+(/\S*/)?rm\b", _RE_FLAGS),
        "find -exec/-execdir rm",
    ),
    (re.compile(r"\bfind\b.*-delete\b", _RE_FLAGS), "find -delete"),
    (
        re.compile(r"\bgit\s+reset\s+--hard\b", _RE_FLAGS),
        "git reset --hard (destroys uncommitted changes)",
    ),
    (
        re.compile(r"\bgit\s+push\b.*--force\b", _RE_FLAGS),
        "git force push (rewrites remote history)",
    ),
    (
        re.compile(r"\bgit\s+push\b.*-f\b", _RE_FLAGS),
        "git force push short flag (rewrites remote history)",
    ),
    (
        re.compile(r"\bgit\s+clean\s+-[^\s]*f", _RE_FLAGS),
        "git clean with force (deletes untracked files)",
    ),
    (re.compile(r"\bgit\s+branch\s+-D\b", _RE_FLAGS), "git branch force delete"),
    (
        re.compile(r"\bchmod\s+\+x\b.*[;&|]+\s*\./", _RE_FLAGS),
        "chmod +x followed by immediate execution",
    ),
    (
        re.compile(
            r"\bsudo\b[^;|&\n]*?\s+(?:-s\b|--stdin\b|-a\b|--askpass\b)", _RE_FLAGS
        ),
        "sudo with privilege flag (stdin/askpass/shell/list)",
    ),
    (
        re.compile(r"\bsudo\b[^;|&\n]*?\s+-[a-z]*[sa][a-z]*\b", _RE_FLAGS),
        "sudo with combined-flag privilege escalation",
    ),
    # Sensitive file writes.
    (
        re.compile(rf"\b(cp|mv|install)\b.*\s{_SYSTEM_CONFIG_PATH}", _RE_FLAGS),
        "copy/move file into system config path",
    ),
    (
        re.compile(
            rf'\b(cp|mv|install)\b.*\s["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_COMMAND_TAIL}',
            _RE_FLAGS,
        ),
        "overwrite project env/config file",
    ),
    (
        re.compile(
            rf'\b(cp|mv|install)\b.*\s["\']?{_SENSITIVE_WRITE_TARGET}[^\s"\']*["\']?{_COMMAND_TAIL}',
            _RE_FLAGS,
        ),
        "copy/move file into sensitive credential/SSH/shell-rc path",
    ),
    (
        re.compile(
            rf'\bsed\s+-[^\s]*i.*(?:{_USER_SENSITIVE_WRITE_TARGET})[^\s"\']*', _RE_FLAGS
        ),
        "in-place edit of sensitive credential/SSH/shell-rc path",
    ),
    (
        re.compile(
            rf'\bsed\s+--in-place\b.*(?:{_USER_SENSITIVE_WRITE_TARGET})[^\s"\']*',
            _RE_FLAGS,
        ),
        "in-place edit of sensitive credential/SSH/shell-rc path (long flag)",
    ),
    (
        re.compile(
            rf'\b(?:perl|ruby)\b.*(?:^|\s)-[^\s]*i\b.*(?:{_USER_SENSITIVE_WRITE_TARGET})[^\s"\']*',
            _RE_FLAGS,
        ),
        "in-place edit of sensitive credential/SSH/shell-rc path (perl/ruby)",
    ),
    (
        re.compile(rf"\bsed\s+-[^\s]*i.*\s{_SYSTEM_CONFIG_PATH}", _RE_FLAGS),
        "in-place edit of system config",
    ),
    (
        re.compile(rf"\bsed\s+--in-place\b.*\s{_SYSTEM_CONFIG_PATH}", _RE_FLAGS),
        "in-place edit of system config (long flag)",
    ),
    # In-place edits of PROJECT env/config (.env, config.yaml). Quotes are
    # stripped during normalization, so the target follows whitespace bare.
    (
        re.compile(
            rf"\bsed\s+-[^\s]*i.*\s{_PROJECT_SENSITIVE_WRITE_TARGET}{_COMMAND_TAIL}",
            _RE_FLAGS,
        ),
        "in-place edit of project env/config",
    ),
    (
        re.compile(
            rf"\bsed\s+--in-place\b.*\s{_PROJECT_SENSITIVE_WRITE_TARGET}{_COMMAND_TAIL}",
            _RE_FLAGS,
        ),
        "in-place edit of project env/config (long flag)",
    ),
    (
        re.compile(
            rf"\b(?:perl|ruby)\b.*(?:^|\s)-[^\s]*i\b.*\s{_PROJECT_SENSITIVE_WRITE_TARGET}{_COMMAND_TAIL}",
            _RE_FLAGS,
        ),
        "in-place edit of project env/config (perl/ruby)",
    ),
    (
        re.compile(r"\b(python[23]?|perl|ruby|node)\s+<<", _RE_FLAGS),
        "script execution via heredoc",
    ),
    # OSS-BL-01: generalized pipe-to-shell — any source, not only curl/wget.
    # The upstream pattern only gates `(curl|wget) ... | (ba)?sh`; this closes
    # the gap for `echo ... | base64 -d | sh`, `cat payload | sh`, etc. where
    # the decoded/dynamic payload cannot be statically analyzed.
    # Negative guards verified: `| ssh host` fails (sh at wrong offset in ssh),
    # `| sha256sum` fails (\b after sh fails inside sha256sum), `| tee` is plain.
    (
        re.compile(r"\|\s*(?:[/\w.]+/)?(?:ba|z|k|da)?sh\b", _RE_FLAGS),
        "pipe content to shell interpreter (dynamic execution)",
    ),
    # OSS-BL-01: eval at a command position (start, after ;/&/|/backtick/newline/
    # subshell $(…)/subshell (…)/brace-group { …).
    # Matches `eval "$X"`, `eval $(curl ...)`, `; eval $CMD`,
    # `(eval "$CMD")` (subshell — bare `(` added to position char class),
    # `{ eval "$CMD"; }` (brace-group — `\{\s` alternative; the mandatory
    # whitespace after `{` is the deliberate distinguisher: brace GROUPS require
    # `{ ` (space) whereas `${eval}` parameter expansions have NO space — so
    # `\{\s` matches `{ eval` but NOT `${eval}`, avoiding false-positives on
    # variables named `eval`).
    # OSS-BL-01 cycle-4: also matches shell reserved words that introduce eval
    # at a command position: `if eval $cmd; then :; fi`, `then eval`,
    # `do eval`, `else eval`, `elif eval`, `while eval`, `until eval`,
    # `time eval`, `! eval`.
    # The reserved-word chain `(?:\b(?:if|then|…)\b\s+|!\s+)*` is placed AFTER
    # the existing command-position anchor, so a reserved word is only consumed
    # when it itself sits at a real command position (start / after a separator /
    # opener).  This is the key FP guard:
    #   - `if eval $cmd; then :; fi`  → `^` anchors `if`, chain matches → CATCH.
    #   - `git commit -m if eval works` → `^` anchors `git`; `git` is neither
    #     a reserved word nor an assignment, so the eval token inside `-m`'s
    #     argument is unreachable via the chain → NO match → stays SAFE.
    #   - `echo if eval` → same logic: `^` anchors `echo`; `if` appears only
    #     as echo's argument, not at a command position → NO match → stays SAFE.
    # Also matches inline env-assignment prefixes: `X=1 eval $CMD`,
    # `X=1 Y=2 eval $CMD` — `(?:\w+=\S*\s+)*` consumes each `VAR=VAL ` token.
    # The reserved-word chain comes BEFORE the assignment chain (shell order:
    # `if X=1 eval` is valid; `X=1 if` is not).
    # Does NOT match `FOO=eval ls` (eval is the value, not the command: the
    # quantifier consumes `FOO=eval ` and then `eval\b` fails on `ls`).
    # Does NOT match `do_something eval` — `\bdo\b` fails on `do_` because `_`
    # is a word char, so the reserved-word chain cannot fire.
    # Does NOT match `eval_helper foo` — `_` is a word char so `eval\b` fails.
    (
        re.compile(
            r"(?:^|[;&|`\n(]|\$\(|\{\s)\s*"
            r"(?:\b(?:if|then|elif|else|do|while|until|time)\b\s+|!\s+)*"
            r"(?:\w+=\S*\s+)*eval\b",
            _RE_FLAGS,
        ),
        "eval of dynamically-constructed command",
    ),
]

__all__ = ["DANGEROUS_PATTERNS"]
