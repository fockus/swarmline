"""Tests for observability/redaction.py — secret-pattern stripping.

Stage 6 of plans/2026-04-27_fix_security-audit.md — closes audit finding P2 #6
(raw provider/CLI/HTTP exceptions leak Bearer tokens, sk-* keys, URL userinfo,
KEY=value env strings into RuntimeEvent.error.message, logs, and 500 responses).
"""

from __future__ import annotations

import re

import pytest

from swarmline.observability.redaction import (
    DEFAULT_SECRET_PATTERNS,
    redact_secrets,
)


class TestRedactSecretsKnownPatterns:
    """redact_secrets strips well-known credential patterns."""

    def test_redact_secrets_bearer_token(self) -> None:
        result = redact_secrets("Authorization: Bearer abc123def456ghijklmnopqrstuvwx")
        assert "abc123def456ghijklmnopqrstuvwx" not in result
        assert "[REDACTED]" in result or "***" in result

    def test_redact_secrets_lowercase_bearer(self) -> None:
        result = redact_secrets("auth: bearer abc123def456ghijklmnop")
        assert "abc123def456ghijklmnop" not in result

    def test_redact_secrets_openai_api_key(self) -> None:
        secret = "sk-proj-abc123def456ghi789jkl012mno345"
        result = redact_secrets(f"key={secret}")
        assert secret not in result

    def test_redact_secrets_anthropic_api_key(self) -> None:
        secret = "sk-ant-api03-abc123def456ghi789jkl012mno345pqr"
        result = redact_secrets(f"using {secret} for auth")
        assert secret not in result

    @pytest.mark.parametrize(
        "secret",
        [
            "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
            "gho_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
            "ghu_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
            "ghs_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
        ],
    )
    def test_redact_secrets_github_tokens(self, secret: str) -> None:
        result = redact_secrets(f"GITHUB_TOKEN={secret}")
        assert secret not in result

    def test_redact_secrets_url_userinfo(self) -> None:
        result = redact_secrets("proxy=https://alice:topsecret@proxy.example.com:8080")
        assert "alice" not in result or "topsecret" not in result
        assert "topsecret" not in result

    @pytest.mark.parametrize(
        "key",
        [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "GITHUB_TOKEN",
            "DATABASE_PASSWORD",
            "DB_PASSWORD",
            "API_TOKEN",
        ],
    )
    def test_redact_secrets_env_style_assignment(self, key: str) -> None:
        result = redact_secrets(f"{key}=actually-secret-value-here-very-long")
        assert "actually-secret-value-here-very-long" not in result
        assert key in result  # variable name preserved for context


class TestRedactSecretsBenignText:
    """Benign text must remain intact — patterns conservative."""

    def test_redact_secrets_plain_text_unchanged(self) -> None:
        text = "hello world, this is a normal message"
        assert redact_secrets(text) == text

    def test_redact_secrets_idempotent(self) -> None:
        text = "Bearer xyzlongtokenxyzlongtoken"
        once = redact_secrets(text)
        twice = redact_secrets(once)
        assert once == twice

    def test_redact_secrets_short_token_not_matched(self) -> None:
        """Short tokens (under threshold) — likely false positives."""
        text = "sk-abc"  # 6 chars total — below 20-char minimum
        # Should NOT redact (too short to be a real key)
        result = redact_secrets(text)
        assert "sk-abc" in result

    def test_redact_secrets_empty_string(self) -> None:
        assert redact_secrets("") == ""

    def test_redact_secrets_handles_none_input_gracefully(self) -> None:
        """Non-str inputs returned via str() — no crash."""
        result = redact_secrets(None)  # type: ignore[arg-type]
        assert isinstance(result, str)


class TestRedactSecretsMultiplePatternsInOneText:
    def test_redact_secrets_multiple_patterns_simultaneously(self) -> None:
        text = (
            "Error: connecting to https://user:pwd@db.example.com "
            "with Bearer tok_abc123def456ghi789jklmn "
            "and OPENAI_API_KEY=sk-real-key-stuff-here-123456"
        )
        result = redact_secrets(text)
        assert "user:pwd" not in result
        assert "tok_abc123def456ghi789jklmn" not in result
        assert "sk-real-key-stuff-here-123456" not in result


class TestDefaultSecretPatternsExposed:
    """DEFAULT_SECRET_PATTERNS is the canonical list reused by JsonlSink."""

    def test_default_secret_patterns_is_compiled_tuple(self) -> None:
        assert isinstance(DEFAULT_SECRET_PATTERNS, tuple)
        assert len(DEFAULT_SECRET_PATTERNS) > 0
        for pattern in DEFAULT_SECRET_PATTERNS:
            # Each entry is (compiled_regex, replacement_str)
            assert isinstance(pattern[0], re.Pattern)
            assert isinstance(pattern[1], str)


class TestProviderRuntimeCrashRedacts:
    """provider_runtime_crash now sanitizes exception messages."""

    def test_provider_runtime_crash_redacts_bearer_in_exc_message(self) -> None:
        from swarmline.runtime.thin.errors import provider_runtime_crash

        exc = RuntimeError("Bearer secret-token-value-here-1234567890")
        wrapped = provider_runtime_crash("openai", exc)
        assert "secret-token-value-here-1234567890" not in wrapped.error.message

    def test_provider_runtime_crash_redacts_sk_key(self) -> None:
        from swarmline.runtime.thin.errors import provider_runtime_crash

        exc = RuntimeError("sk-proj-real-leaky-key-1234567890abcdef")
        wrapped = provider_runtime_crash("openai", exc)
        assert "sk-proj-real-leaky-key-1234567890abcdef" not in wrapped.error.message

    def test_provider_runtime_crash_preserves_provider_name(self) -> None:
        """Redaction must not erase the provider identifier itself."""
        from swarmline.runtime.thin.errors import provider_runtime_crash

        exc = RuntimeError("Bearer leakytoken1234567890abcdef")
        wrapped = provider_runtime_crash("anthropic", exc)
        assert "anthropic" in wrapped.error.message

    async def test_default_llm_call_logs_redacted_provider_exception(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from unittest.mock import AsyncMock
        from unittest.mock import patch

        from swarmline.runtime.thin.llm_client import default_llm_call
        from swarmline.runtime.types import RuntimeConfig

        secret = "sk-proj-leaky-provider-key-1234567890abcdef"
        adapter = AsyncMock()
        adapter.call = AsyncMock(side_effect=RuntimeError(f"provider failed: {secret}"))

        caplog.set_level("ERROR", logger="swarmline.runtime.thin.llm_client")
        with patch(
            "swarmline.runtime.thin.llm_client.get_cached_adapter",
            return_value=adapter,
        ):
            with pytest.raises(Exception):
                await default_llm_call(
                    RuntimeConfig(runtime_name="thin"),
                    [{"role": "user", "content": "hi"}],
                    "system",
                )

        assert secret not in caplog.text
        assert "RuntimeError" in caplog.text


class TestServe500ResponseRedacts:
    """serve/app.py /v1/query 500 path strips secrets from str(exc)."""

    async def test_serve_query_500_response_redacts_bearer(self) -> None:
        import json
        from unittest.mock import MagicMock

        from starlette.testclient import TestClient

        from swarmline.serve.app import create_app

        agent = MagicMock()

        async def boom(_prompt: str) -> object:
            raise RuntimeError("Bearer leaky-token-here-1234567890abcdefghi")

        agent.query = boom

        app = create_app(agent, auth_token="t1")
        client = TestClient(app)
        resp = client.post(
            "/v1/query",
            json={"prompt": "hi"},
            headers={"Authorization": "Bearer t1"},
        )
        body = json.loads(resp.text)
        assert resp.status_code == 500
        assert "leaky-token-here-1234567890abcdefghi" not in body["error"]


# ---------------------------------------------------------------------------
# Stage 1 of plans/2026-04-27_fix_post-review-polish.md — closes review C1
# (HIGH security): URL-userinfo regex `(\w+://)([^:/@\s]+):([^@/\s]+)@` is
# vulnerable to ReDoS — 50KB input → 3.4s, 100KB → ~15s catastrophic
# backtracking. Reachable from every redacted error path: serve/app.py 500,
# runtime/thin/errors.py provider_runtime_crash, runtime/cli/runtime.py stderr.
# Fix: bounded-quantifier variant `[a-zA-Z][a-zA-Z0-9+.\-]{0,30}://...{1,256}:...{1,256}@`.
# ---------------------------------------------------------------------------


class TestRedactionReDoSResistance:
    """Bounded-quantifier guarantees: pathological inputs do not stall."""

    def test_redact_secrets_handles_100kb_userinfo_payload_under_100ms(self) -> None:
        """C1 closure: 100KB attacker-shaped input must run in <100ms.

        Pre-fix pattern `[^:/@\\s]+):([^@/\\s]+)@` exhibits catastrophic
        backtracking on long alternating user/password strings. Bounded
        `{1,256}` quantifiers eliminate the explosion.
        """
        import time

        # Mimic worst-case: long userinfo + long password, no terminator hit.
        # 50_000 + 50_000 = 100KB body, no @ at the end → forces full backtrack
        # under the unbounded pattern.
        payload = "https://" + ("a" * 50_000) + ":" + ("b" * 50_000) + "@host"
        start = time.perf_counter()
        result = redact_secrets(payload)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, (
            f"redact_secrets took {elapsed:.3f}s on 100KB payload — "
            "expected <0.1s under bounded-quantifier pattern. ReDoS regression."
        )
        # Sanity: function still returned a string (no crash).
        assert isinstance(result, str)

    def test_redact_secrets_handles_legitimate_url_with_userinfo(self) -> None:
        """Happy path: bounded regex still redacts normal URLs."""
        result = redact_secrets("postgres://alice:secret123@db.example.com:5432/app")
        assert "alice" not in result
        assert "secret123" not in result
        assert "[REDACTED]" in result
        # Scheme + host preserved
        assert "postgres://" in result
        assert "db.example.com" in result

    def test_redact_secrets_handles_short_userinfo_at_lower_boundary(self) -> None:
        """1-char userinfo / password (boundary {1,256}) — still matches."""
        result = redact_secrets("ftp://a:b@host.example.org")
        assert "a:b@" not in result
        assert "[REDACTED]" in result

    def test_redact_secrets_handles_long_userinfo_at_boundary(self) -> None:
        """256-char userinfo (boundary): still redacted. 300-char: no match
        (acceptable — pathological case beyond real-world cap)."""
        # At boundary: 256 chars exactly — within bounds → matches.
        boundary = "https://" + ("u" * 256) + ":" + ("p" * 256) + "@host"
        result_boundary = redact_secrets(boundary)
        assert "[REDACTED]" in result_boundary

        # Beyond boundary: 300 chars — outside bounds → does NOT match
        # (acceptable trade-off — no real userinfo is 300+ chars).
        beyond = "https://" + ("u" * 300) + ":" + ("p" * 300) + "@host"
        result_beyond = redact_secrets(beyond)
        # Original userinfo survives — this is the intentional bound.
        assert ("u" * 300) in result_beyond

    def test_redact_secrets_handles_unicode_in_userinfo(self) -> None:
        """Non-ASCII userinfo: function does not crash regardless of match."""
        text = "ldap://пользователь:пароль@example.com"
        result = redact_secrets(text)
        # Primary contract: no crash, returns a string.
        assert isinstance(result, str)

    def test_redact_secrets_handles_pathological_alternating_input(self) -> None:
        """Alternating delimiters (`a:a:a:a:`) — common ReDoS amplifier."""
        import time

        payload = ("a:" * 5_000) + "@host"  # 10KB, alternating colons
        start = time.perf_counter()
        result = redact_secrets("https://" + payload)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, f"alternating-delimiter ReDoS regression: {elapsed:.3f}s"
        assert isinstance(result, str)
