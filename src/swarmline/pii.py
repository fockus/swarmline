"""PII detection and redaction — zero-dependency regex core.

Detects and redacts personally identifiable information (PII) from text
using stdlib-only pattern matching.  Optional Presidio integration is
available as a staged stub via the ``swarmline[pii]`` extra.

Supported kinds:  email · phone · credit_card · ssn · ip
Strategies:       redact (token) · mask (keep-last-4) · hash (SHA-256, salted)

Usage::

    from swarmline.pii import detect_pii, redact_pii, PiiInputFilter

    text = "Contact user@example.com or call +1 (800) 555-1234"
    clean = redact_pii(text)
    # "Contact [REDACTED_EMAIL] or call [REDACTED_PHONE]"

The function is idempotent: applying it twice yields the same result because
replacement tokens do not match any of the five PII patterns.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from swarmline.domain_types import Message

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

PiiKind = Literal["email", "phone", "credit_card", "ssn", "ip"]
PiiStrategy = Literal["redact", "mask", "hash"]


@dataclass(frozen=True)
class PiiMatch:
    """A detected PII span within a text string."""

    kind: PiiKind
    start: int
    end: int
    value: str


# ---------------------------------------------------------------------------
# Compiled regex patterns — bounded quantifiers (ReDoS-safe)
# ---------------------------------------------------------------------------

# Email: local-part@domain.tld  (supports subdomains, plus-tags)
_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9.\-]{1,253}\.[a-zA-Z]{2,24}\b"
)

# Phone: international / domestic formats with +, spaces, dashes, parentheses.
# Pattern: optional country code · optional area code · start-segment · 1-3 further segments.
# Bounded quantifiers throughout; no nested repetition → ReDoS-safe.
_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+\d{1,3}[\s\-]?)?"  # optional +country
    r"(?:\(?\d{1,4}\)?[\s\-]?)?"  # optional area code (parens optional)
    r"\d{3,4}"  # main start segment
    r"(?:[\s\-]\d{2,4}){1,3}"  # 1-3 further digit groups via space/dash
    r"(?!\d)"
)

# SSN: xxx-xx-xxxx only — does NOT match arbitrary 9-digit runs.
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# IP: dotted-quad with octet range 0–255 enforced by alternation.
_IP_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d|\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d|\d)\b"
)

# Credit card: 16-digit 4-4-4-4 (Visa/MC/Discover) OR 15-digit 4-6-5 (Amex),
# with optional space/dash separators. Luhn checksum gates every match.
# 16-digit alternative is listed first so it wins when both could apply.
_CARD_RE = re.compile(
    r"(?<!\d)(?:"
    r"\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"  # 16-digit (Visa/MC/Discover)
    r"|"
    r"\d{4}[\s\-]?\d{6}[\s\-]?\d{5}"  # 15-digit Amex (4-6-5)
    r")(?!\d)"
)

_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": _EMAIL_RE,
    "phone": _PHONE_RE,
    "credit_card": _CARD_RE,
    "ssn": _SSN_RE,
    "ip": _IP_RE,
}

_ALL_KINDS: tuple[str, ...] = ("email", "credit_card", "ssn", "ip", "phone")

# Specificity ranking for overlap resolution (lower = more specific, wins).
# A 16-digit card and a 9-digit SSN both also match the looser phone pattern;
# when spans overlap, the more-specific kind is kept and the rest dropped.
_KIND_PRIORITY: dict[str, int] = {
    "credit_card": 0,
    "ssn": 1,
    "ip": 2,
    "email": 3,
    "phone": 4,
}


def _dedup_overlaps(matches: list[PiiMatch]) -> list[PiiMatch]:
    """Return a non-overlapping subset, keeping the most-specific kind per span.

    Most-specific matches are placed first (interval scheduling by priority);
    any later match overlapping an already-kept span is dropped. Deterministic.
    """
    ordered = sorted(
        matches,
        key=lambda m: (_KIND_PRIORITY.get(m.kind, 99), m.start, -(m.end - m.start)),
    )
    kept: list[PiiMatch] = []
    for m in ordered:
        if any(not (m.end <= k.start or m.start >= k.end) for k in kept):
            continue  # overlaps a higher-priority match already kept
        kept.append(m)
    kept.sort(key=lambda m: m.start)
    return kept


# ---------------------------------------------------------------------------
# Luhn checksum
# ---------------------------------------------------------------------------


def _luhn_valid(digits: str) -> bool:
    """Return True if *digits* passes the Luhn (mod-10) checksum.

    Processes right-to-left: odd positions from the right (1-indexed) are
    doubled; if the result exceeds 9, subtract 9.  The check digit itself
    (position 1 from the right) is not doubled.
    """
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------


def detect_pii(text: str, *, kinds: Sequence[str] | None = None) -> list[PiiMatch]:
    """Return non-overlapping PII spans detected in *text*, sorted by start position.

    Parameters
    ----------
    text:
        Input string to scan.
    kinds:
        Restrict detection to these ``PiiKind`` values.
        ``None`` scans all five kinds (email, phone, credit_card, ssn, ip).

    Notes
    -----
    * The returned list is **non-overlapping**: when two patterns cover the same
      (or overlapping) span, the more-specific kind wins
      (credit_card > ssn > ip > email > phone).
    * Credit-card candidates are gated by Luhn checksum.
    * IP address octets are constrained to 0–255.
    * SSN pattern requires the ``xxx-xx-xxxx`` dash format; bare digit runs
      are NOT classified as SSNs.
    * Phone numbers require separators (space or dash) between digit groups;
      unseparated digit runs are NOT classified as phone numbers.
    """
    target: Sequence[str] = kinds if kinds is not None else _ALL_KINDS
    matches: list[PiiMatch] = []

    for kind in target:
        pattern = _PATTERNS.get(kind)
        if pattern is None:
            continue
        for m in pattern.finditer(text):
            value = m.group(0)
            if kind == "credit_card":
                digits = re.sub(r"[\s\-]", "", value)
                if not _luhn_valid(digits):
                    continue
            # kind is a valid PiiKind value at this point (validated by _PATTERNS key).
            matches.append(
                PiiMatch(
                    kind=cast(PiiKind, kind),
                    start=m.start(),
                    end=m.end(),
                    value=value,
                )
            )

    return _dedup_overlaps(matches)


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------


def _make_replacement(match: PiiMatch, strategy: PiiStrategy, hash_salt: str) -> str:
    """Build the replacement string for a single :class:`PiiMatch`."""
    kind_upper = match.kind.upper()
    if strategy == "redact":
        return f"[REDACTED_{kind_upper}]"
    if strategy == "mask":
        # Keep the last 4 characters of the matched value; prefix with ****.
        # For credit cards: "4111 1111 1111 1111"[-4:] == "1111"  (last 4 digits).
        # For SSN "123-45-6789"[-4:] == "6789".  Separators are preserved in
        # the matched value; only the trailing 4 chars are kept.
        return f"****{match.value[-4:]}"
    # hash strategy: deterministic SHA-256 digest (first 10 hex chars), salted.
    # The NUL separator prevents salt/value cancellation collisions
    # (e.g. salt="user"+value="x" vs salt=""+value="userx"); NUL never occurs in PII.
    digest = hashlib.sha256(f"{hash_salt}\x00{match.value}".encode()).hexdigest()[:10]
    return f"[{kind_upper}:{digest}]"


def redact_pii(
    text: str,
    *,
    strategy: PiiStrategy = "redact",
    kinds: Sequence[str] | None = None,
    hash_salt: str = "",
) -> str:
    """Replace PII spans in *text* right-to-left (index-safe for multi-match).

    ``"redact"`` → ``[REDACTED_<KIND>]``;
    ``"mask"`` → ``****<last4>`` (last 4 chars of matched value);
    ``"hash"`` → ``[<KIND>:<sha256(salt+value)[:10]>]`` (deterministic, salted).
    Idempotent: replacement tokens do not re-match any PII pattern.

    Security: the ``"hash"`` strategy is only irreversible when *hash_salt* is a
    long random secret. The default empty salt makes the digest brute-forceable
    for enumerable PII (e.g. phone numbers) and emits a warning.
    """
    if not text:
        return text

    if strategy == "hash" and not hash_salt:
        warnings.warn(
            "redact_pii(strategy='hash') with an empty hash_salt produces an "
            "unsalted, brute-forceable digest. Set hash_salt to a long random "
            "secret in production.",
            stacklevel=2,
        )

    matches = detect_pii(text, kinds=kinds)
    if not matches:
        return text

    # Right-to-left: sort by start descending, then end descending.
    sorted_matches = sorted(matches, key=lambda m: (-m.start, -m.end))

    result = text
    last_processed_start = len(result)

    for match in sorted_matches:
        if match.end > last_processed_start:
            # Overlap with an already-processed region; skip.
            continue
        replacement = _make_replacement(match, strategy, hash_salt)
        result = result[: match.start] + replacement + result[match.end :]
        last_processed_start = match.start

    return result


# ---------------------------------------------------------------------------
# PiiInputFilter
# ---------------------------------------------------------------------------


class PiiInputFilter:
    """InputFilter that redacts PII from messages and system_prompt before each LLM call.

    Implements the ``InputFilter`` protocol (``swarmline.input_filters.InputFilter``).
    Each message's ``content`` field and the system prompt are redacted in
    isolation via ``dataclasses.replace`` — the frozen ``Message`` objects are
    never mutated.

    Note: ``structured_output`` fields are result-side data and are handled
    separately by ``PiiMiddleware.after_result`` (which intentionally leaves
    ``structured_output`` intact).
    """

    def __init__(
        self,
        *,
        strategy: PiiStrategy = "redact",
        kinds: Sequence[str] | None = None,
        hash_salt: str = "",
    ) -> None:
        self._strategy = strategy
        self._kinds: list[str] | None = list(kinds) if kinds is not None else None
        self._hash_salt = hash_salt

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        """Return *(redacted_messages, redacted_system_prompt)*."""
        redacted_messages: list[Message] = [
            dataclasses.replace(
                m,
                content=redact_pii(
                    m.content,
                    strategy=self._strategy,
                    kinds=self._kinds,
                    hash_salt=self._hash_salt,
                ),
            )
            for m in messages
        ]
        redacted_system = redact_pii(
            system_prompt,
            strategy=self._strategy,
            kinds=self._kinds,
            hash_salt=self._hash_salt,
        )
        return redacted_messages, redacted_system


# ---------------------------------------------------------------------------
# Presidio staged stub (requires swarmline[pii] extra)
# ---------------------------------------------------------------------------


def detect_pii_presidio(
    text: str,
    *,
    kinds: Sequence[str] | None = None,
) -> list[PiiMatch]:
    """Presidio-backed PII detection (staged stub; requires ``swarmline[pii]``).

    This function is NOT wired into defaults — the stdlib regex core in
    :func:`detect_pii` is the zero-dependency default.

    Install the extra to enable Presidio support::

        pip install "swarmline[pii]"

    The ``kinds`` mapping to Presidio entity types (``"email"`` →
    ``EMAIL_ADDRESS``, etc.) is not yet implemented in this stub.
    """
    import importlib.util

    if importlib.util.find_spec("presidio_analyzer") is None:
        raise ImportError(
            "Presidio backend requires the optional extra: pip install 'swarmline[pii]'"
        )
    # Presidio IS installed but the integration is not implemented yet. Fail loud
    # instead of silently returning [] (a silent zero-detection guardrail bypass).
    del text, kinds
    raise NotImplementedError(
        "Presidio backend is a staged stub and not yet implemented. "
        "Use detect_pii() (the stdlib regex core, zero-dependency default)."
    )
