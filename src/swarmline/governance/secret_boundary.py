"""SecretBoundaryManager — secret redaction, trust zones, injection defense.

Implements SecretBoundaryPort. Built-in patterns for API keys, tokens,
passwords, private keys. Detects prompt injection markers.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from swarmline.governance.types import SecretPattern, TrustZone

# ---------------------------------------------------------------------------
# Built-in secret patterns
# ---------------------------------------------------------------------------

_BUILTIN_PATTERNS: tuple[SecretPattern, ...] = (
    SecretPattern(
        pattern=r"sk-[\w\-]{20,}",
        replacement="[REDACTED:api_key]",
        description="API key (sk-..., including sk-ant-, sk-proj-)",
    ),
    SecretPattern(
        pattern=r"Bearer\s+[A-Za-z0-9\-_.]+\.[A-Za-z0-9\-_.]+\.[A-Za-z0-9\-_.]*",
        replacement="[REDACTED:bearer_token]",
        description="Bearer token (JWT-like)",
    ),
    SecretPattern(
        pattern=r"(?i)password\s*[=:]\s*\S+",
        replacement="[REDACTED:password]",
        description="Password assignment (case-insensitive, = or : separator)",
    ),
    SecretPattern(
        pattern=r"-----BEGIN\s+\w*\s*PRIVATE KEY-----[\s\S]*?-----END\s+\w*\s*PRIVATE KEY-----",
        replacement="[REDACTED:private_key]",
        description="PEM private key block",
    ),
    SecretPattern(
        pattern=r"AKIA[0-9A-Z]{16}",
        replacement="[REDACTED:aws_access_key]",
        description="AWS access key ID",
    ),
    SecretPattern(
        pattern=r"gh[pous]_[A-Za-z0-9]{36,}",
        replacement="[REDACTED:github_token]",
        description="GitHub token (ghp_, gho_, ghu_, ghs_)",
    ),
    SecretPattern(
        pattern=r"(?i)(?:token|secret|api_key)\s*[=:]\s*(?!\[REDACTED)\S+",
        replacement="[REDACTED:secret_value]",
        description="Generic token/secret/api_key assignment",
    ),
)

# ---------------------------------------------------------------------------
# Prompt injection patterns
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"(?:^|\n)\s*(?:###\s*)?system\s*:", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"<\|endoftext\|>", re.IGNORECASE),
    re.compile(r"\[SYSTEM\]", re.IGNORECASE),
    re.compile(r"\n\n(?:Human|Assistant)\s*:", re.IGNORECASE),
)

_INJECTION_REPLACEMENT = "[REDACTED:prompt_injection]"


class SecretBoundaryManager:
    """Secret detection, redaction, trust zone checking, and injection defense.

    Satisfies SecretBoundaryPort protocol.
    """

    def __init__(
        self,
        *,
        extra_patterns: Sequence[SecretPattern] | None = None,
    ) -> None:
        self._patterns: list[SecretPattern] = []
        if extra_patterns:
            self._patterns.extend(extra_patterns)
        self._patterns.extend(_BUILTIN_PATTERNS)
        self._compiled: list[tuple[re.Pattern[str], str]] = [
            (re.compile(p.pattern), p.replacement) for p in self._patterns
        ]

    def redact(self, text: str) -> str:
        """Replace matched secret patterns with [REDACTED:description].

        Also detects and replaces prompt injection markers.
        """
        if not text:
            return text

        for compiled, replacement in self._compiled:
            text = compiled.sub(replacement, text)

        for injection_re in _INJECTION_PATTERNS:
            text = injection_re.sub(_INJECTION_REPLACEMENT, text)

        return text

    def is_trusted_zone(self, zone: TrustZone) -> bool:
        """Only TRUSTED zone is considered trusted."""
        return zone == TrustZone.TRUSTED

    def get_patterns(self) -> list[SecretPattern]:
        """Return a defensive copy of all registered patterns."""
        return list(self._patterns)
