"""Secret-pattern redaction for log/error/HTTP-response strings.

Stage 6 of plans/2026-04-27_fix_security-audit.md — closes audit finding P2 #6:
provider exceptions, CLI subprocess stderr, and HTTP 500 responses previously
included Bearer tokens, sk-* API keys, URL userinfo, and ``KEY=value`` env-style
strings verbatim. ``redact_secrets()`` applies a conservative pattern set so a
leaky exception or stderr buffer does not transit through error events.

The same patterns also back ``JsonlTelemetrySink``'s default value-level
redaction (DRY).
"""

from __future__ import annotations

import re

# Each entry: (compiled_regex, replacement_template).
# Patterns are intentionally conservative — they require distinctive prefixes
# (sk-, Bearer, scheme://userinfo@) or 20+ char tails so benign user content
# (e.g. variable names, short identifiers) is not stripped.
DEFAULT_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Bearer / bearer tokens (>=8 chars distinctive token).
    # 8-char threshold catches short test-fixture tokens like "abc.def-ghi"
    # while still rejecting bare words. Real-world tokens are 16+ anyway.
    (
        re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._\-]{8,}"),
        "Bearer [REDACTED]",
    ),
    # OpenAI / OpenRouter style sk-... (incl. sk-proj-, sk-or-)
    (
        re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
        "sk-[REDACTED]",
    ),
    # Anthropic specifically
    (
        re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
        "sk-ant-[REDACTED]",
    ),
    # GitHub tokens — ghp_ / gho_ / ghu_ / ghs_ / ghr_ + 20+ chars
    (
        re.compile(r"\b(gh[poursr])_[A-Za-z0-9]{20,}"),
        r"\1_[REDACTED]",
    ),
    # URL userinfo: scheme://user:password@host
    (
        re.compile(r"(\w+://)([^:/@\s]+):([^@/\s]+)@"),
        r"\1[REDACTED]:[REDACTED]@",
    ),
    # Common env-style assignments where the key ends in _KEY/_TOKEN/_SECRET/_PASSWORD
    (
        re.compile(r"\b([A-Z][A-Z0-9_]*(?:_KEY|_TOKEN|_SECRET|_PASSWORD))=([^\s'\"]+)"),
        r"\1=[REDACTED]",
    ),
)


def redact_secrets(
    text: str | None,
    *,
    patterns: tuple[tuple[re.Pattern[str], str], ...] = DEFAULT_SECRET_PATTERNS,
) -> str:
    """Return ``text`` with known secret patterns replaced by tokenized placeholders.

    Conservative — only patterns with distinctive prefixes / minimum lengths are
    matched, so plain prose passes through unchanged. Idempotent: applying the
    function twice yields the same result.

    Non-string inputs are coerced via ``str()`` so callers can pass exception
    messages directly without ``isinstance`` boilerplate.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return text
    redacted = text
    for pattern, replacement in patterns:
        redacted = pattern.sub(replacement, redacted)
    return redacted
