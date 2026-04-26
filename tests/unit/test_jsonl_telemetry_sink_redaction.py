"""Stage 20 (M-3) — JsonlTelemetrySink redaction extension.

Verifies:
1. The DEFAULT_REDACT_KEYS frozenset covers the expanded v1.5.0 secret-name list.
2. The DEFAULT_REDACT_VALUE_PATTERNS regex set redacts secret-shaped values
   (sk-* keys, Bearer tokens, URL userinfo) regardless of the surrounding key.
3. Existing v1.4 redaction behaviour is preserved (no regression).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarmline.observability.jsonl_sink import (
    DEFAULT_REDACT_KEYS,
    DEFAULT_REDACT_VALUE_PATTERNS,
    JsonlTelemetrySink,
)


def _read_first_record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])


# -----------------------------------------------------------------------------
# Default key set — coverage and back-compat
# -----------------------------------------------------------------------------


def test_default_redact_keys_covers_v14_baseline() -> None:
    """The v1.4 baseline keys must remain redacted (no regression)."""
    baseline = {"api_key", "apikey", "authorization", "password", "secret", "token"}
    assert baseline.issubset(DEFAULT_REDACT_KEYS)


def test_default_redact_keys_extended_in_v15() -> None:
    """v1.5 must add at least 12 new common-secret key names."""
    new_keys = {
        "bearer",
        "credential",
        "credentials",
        "private_key",
        "privatekey",
        "pem",
        "cookie",
        "set-cookie",
        "x-api-key",
        "auth",
        "oauth_token",
        "refresh_token",
        "client_secret",
        "aws_secret_access_key",
        "connection_string",
        "dsn",
    }
    missing = new_keys - DEFAULT_REDACT_KEYS
    assert not missing, f"Missing v1.5 redact keys: {sorted(missing)}"


# -----------------------------------------------------------------------------
# Per-key redaction (key-name match)
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, value, expected_redacted",
    [
        # v1.4 baseline (regression guard)
        ("api_key", "sk-abc123", True),
        ("authorization", "Bearer xyz", True),
        ("password", "p@ss", True),
        ("secret", "shhh", True),
        ("token", "tok-1", True),
        # v1.5 extensions
        ("bearer", "xyz", True),
        ("credential", "x", True),
        ("credentials", "x", True),
        ("private_key", "-----BEGIN PRIVATE KEY-----", True),
        ("privatekey", "x", True),
        ("pem", "-----BEGIN", True),
        ("cookie", "session=abc; user=alice", True),
        ("set-cookie", "session=abc", True),
        ("x-api-key", "key", True),
        ("auth", "x", True),
        ("oauth_token", "x", True),
        ("refresh_token", "x", True),
        ("client_secret", "x", True),
        ("aws_secret_access_key", "wJalrXUtn", True),
        ("connection_string", "postgres://u:p@h/db", True),
        ("dsn", "postgres://u:p@h/db", True),
        # Non-secrets — stay verbatim
        ("user_name", "alice", False),
        ("topic_id", "t1", False),
        ("description", "an authorized device", False),
    ],
)
async def test_redaction_by_key_name(
    tmp_path: Path, key: str, value: str, expected_redacted: bool
) -> None:
    sink = JsonlTelemetrySink(tmp_path / "events.jsonl")
    await sink.record("e", {key: value})
    record = _read_first_record(tmp_path / "events.jsonl")
    if expected_redacted:
        assert record["data"][key] == "[REDACTED]"
    else:
        assert record["data"][key] == value


async def test_redaction_case_insensitive_keys(tmp_path: Path) -> None:
    """Key matching must be case-insensitive."""
    sink = JsonlTelemetrySink(tmp_path / "events.jsonl")
    await sink.record(
        "e",
        {
            "API_KEY": "sk-abc",
            "Authorization": "Bearer xyz",
            "X-Api-Key": "k",
        },
    )
    record = _read_first_record(tmp_path / "events.jsonl")
    assert record["data"]["API_KEY"] == "[REDACTED]"
    assert record["data"]["Authorization"] == "[REDACTED]"
    assert record["data"]["X-Api-Key"] == "[REDACTED]"


# -----------------------------------------------------------------------------
# Value-level pattern redaction (regex match on free-text values)
# -----------------------------------------------------------------------------


def test_default_redact_value_patterns_exists_and_compiled() -> None:
    """The new value-pattern set must be a non-empty tuple of compiled patterns."""
    import re

    assert isinstance(DEFAULT_REDACT_VALUE_PATTERNS, tuple)
    assert len(DEFAULT_REDACT_VALUE_PATTERNS) >= 3
    assert all(isinstance(p, re.Pattern) for p in DEFAULT_REDACT_VALUE_PATTERNS)


@pytest.mark.parametrize(
    "value, should_redact",
    [
        # API keys
        ("My OpenAI key is sk-abc1234567890_-XYZxyzABC", True),
        ("anth key sk-ant-api03-1234567890abcdefghij", True),
        # Bearer tokens
        ("Authorization header was Bearer abc.def-ghi", True),
        ("Authorization header was bearer abc.def-ghi", True),
        # URL userinfo
        ("Connection failed: postgres://alice:hunter2@db.local/x", True),
        ("connect string mysql://root:secret@127.0.0.1/test", True),
        # Negatives — must remain verbatim
        ("Just a regular log message", False),
        ("User said: 'I love sk-i in winter.'", False),
        ("https://example.com/path?ok=1", False),
        ("token-id=abc", False),  # bare 'token-id' is not Bearer/sk-/userinfo
    ],
)
async def test_redaction_by_value_pattern(
    tmp_path: Path, value: str, should_redact: bool
) -> None:
    sink = JsonlTelemetrySink(tmp_path / "events.jsonl")
    await sink.record("e", {"prompt": value})
    record = _read_first_record(tmp_path / "events.jsonl")
    if should_redact:
        assert "[REDACTED]" in record["data"]["prompt"], (
            f"Expected redaction in {record['data']['prompt']!r}"
        )
    else:
        assert record["data"]["prompt"] == value


async def test_value_redaction_in_nested_structures(tmp_path: Path) -> None:
    """Value-pattern redaction must traverse nested dicts and lists."""
    sink = JsonlTelemetrySink(tmp_path / "events.jsonl")
    await sink.record(
        "e",
        {
            "trace": {
                "messages": [
                    {"role": "user", "content": "use sk-abc1234567890_xyzABCDEFG"},
                    {"role": "system", "content": "ok"},
                ],
            },
        },
    )
    record = _read_first_record(tmp_path / "events.jsonl")
    user_content = record["data"]["trace"]["messages"][0]["content"]
    sys_content = record["data"]["trace"]["messages"][1]["content"]
    assert "[REDACTED]" in user_content
    assert "sk-abc1234567890" not in user_content
    assert sys_content == "ok"


# -----------------------------------------------------------------------------
# Custom override — user can pass their own pattern set
# -----------------------------------------------------------------------------


async def test_custom_value_patterns_override(tmp_path: Path) -> None:
    """Users can pass their own redact_value_patterns to widen or narrow the set."""
    import re

    custom = (re.compile(r"COMPANY_INTERNAL_[A-Z0-9]+"),)
    sink = JsonlTelemetrySink(
        tmp_path / "events.jsonl",
        redact_value_patterns=custom,
    )
    await sink.record("e", {"note": "ref COMPANY_INTERNAL_ABC123 for the deal"})
    record = _read_first_record(tmp_path / "events.jsonl")
    assert "[REDACTED]" in record["data"]["note"]
    assert "COMPANY_INTERNAL_ABC123" not in record["data"]["note"]


async def test_disable_value_patterns(tmp_path: Path) -> None:
    """Passing redact_value_patterns=() disables value-level redaction (key-only)."""
    sink = JsonlTelemetrySink(
        tmp_path / "events.jsonl",
        redact_value_patterns=(),
    )
    secret = "leaked sk-abc1234567890_xyzABCDEFG"
    await sink.record("e", {"prompt": secret})
    record = _read_first_record(tmp_path / "events.jsonl")
    assert record["data"]["prompt"] == secret  # unredacted
