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
