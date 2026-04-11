"""Unit tests for guardrails module.

Tests cover:
- GuardrailContext creation and defaults
- GuardrailResult defaults
- ContentLengthGuardrail: pass/fail
- RegexGuardrail: pass/fail/multiple patterns
- CallerAllowlistGuardrail: pass/fail/None session
- Parallel execution
- Tripwire result
- RuntimeConfig guardrail fields
- RUNTIME_ERROR_KINDS includes guardrail_tripwire
- InputGuardrail/OutputGuardrail marker protocols
"""

from __future__ import annotations

import asyncio

import pytest

from swarmline.guardrails import (
    CallerAllowlistGuardrail,
    ContentLengthGuardrail,
    GuardrailContext,
    GuardrailResult,
    InputGuardrail,
    OutputGuardrail,
    RegexGuardrail,
)
from swarmline.runtime.types import RUNTIME_ERROR_KINDS, RuntimeConfig


# ---------------------------------------------------------------------------
# GuardrailContext
# ---------------------------------------------------------------------------


class TestGuardrailContext:
    def test_creation_defaults(self) -> None:
        ctx = GuardrailContext()
        assert ctx.session_id is None
        assert ctx.model == ""
        assert ctx.turn == 0

    def test_creation_with_values(self) -> None:
        ctx = GuardrailContext(session_id="s1", model="gpt-4", turn=3)
        assert ctx.session_id == "s1"
        assert ctx.model == "gpt-4"
        assert ctx.turn == 3

    def test_frozen(self) -> None:
        ctx = GuardrailContext()
        with pytest.raises(AttributeError):
            ctx.session_id = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# GuardrailResult
# ---------------------------------------------------------------------------


class TestGuardrailResult:
    def test_defaults(self) -> None:
        result = GuardrailResult(passed=True)
        assert result.passed is True
        assert result.reason is None
        assert result.tripwire is False

    def test_failed_with_reason(self) -> None:
        result = GuardrailResult(passed=False, reason="Too long", tripwire=True)
        assert result.passed is False
        assert result.reason == "Too long"
        assert result.tripwire is True


# ---------------------------------------------------------------------------
# ContentLengthGuardrail
# ---------------------------------------------------------------------------


class TestContentLengthGuardrail:
    @pytest.mark.asyncio
    async def test_pass_when_under_limit(self) -> None:
        g = ContentLengthGuardrail(max_length=100)
        result = await g.check(GuardrailContext(), "short text")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fail_when_over_limit(self) -> None:
        g = ContentLengthGuardrail(max_length=5)
        result = await g.check(GuardrailContext(), "this is too long")
        assert result.passed is False
        assert result.reason is not None
        assert "5" in result.reason

    @pytest.mark.asyncio
    async def test_pass_at_exact_limit(self) -> None:
        g = ContentLengthGuardrail(max_length=5)
        result = await g.check(GuardrailContext(), "12345")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_default_max_length(self) -> None:
        g = ContentLengthGuardrail()
        result = await g.check(GuardrailContext(), "x" * 100_000)
        assert result.passed is True
        result2 = await g.check(GuardrailContext(), "x" * 100_001)
        assert result2.passed is False


# ---------------------------------------------------------------------------
# RegexGuardrail
# ---------------------------------------------------------------------------


class TestRegexGuardrail:
    @pytest.mark.asyncio
    async def test_pass_when_no_match(self) -> None:
        g = RegexGuardrail(patterns=[r"SECRET_\d+"])
        result = await g.check(GuardrailContext(), "nothing special here")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fail_when_pattern_matches(self) -> None:
        g = RegexGuardrail(patterns=[r"SECRET_\d+"])
        result = await g.check(GuardrailContext(), "found SECRET_123 in text")
        assert result.passed is False
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_multiple_patterns_any_match_fails(self) -> None:
        g = RegexGuardrail(patterns=[r"password", r"secret", r"token"])
        result = await g.check(GuardrailContext(), "my token is abc")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_custom_reason(self) -> None:
        g = RegexGuardrail(patterns=[r"bad"], reason="Custom rejection")
        result = await g.check(GuardrailContext(), "bad word")
        assert result.reason == "Custom rejection"


# ---------------------------------------------------------------------------
# CallerAllowlistGuardrail
# ---------------------------------------------------------------------------


class TestCallerAllowlistGuardrail:
    @pytest.mark.asyncio
    async def test_pass_when_in_allowlist(self) -> None:
        g = CallerAllowlistGuardrail(allowed_session_ids={"s1", "s2"})
        ctx = GuardrailContext(session_id="s1")
        result = await g.check(ctx, "hello")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fail_when_not_in_allowlist(self) -> None:
        g = CallerAllowlistGuardrail(allowed_session_ids={"s1", "s2"})
        ctx = GuardrailContext(session_id="s3")
        result = await g.check(ctx, "hello")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_fail_when_session_id_is_none(self) -> None:
        g = CallerAllowlistGuardrail(allowed_session_ids={"s1"})
        ctx = GuardrailContext(session_id=None)
        result = await g.check(ctx, "hello")
        assert result.passed is False
        assert result.tripwire is True


# ---------------------------------------------------------------------------
# Parallel execution
# ---------------------------------------------------------------------------


class TestParallelExecution:
    @pytest.mark.asyncio
    async def test_multiple_guardrails_run_concurrently(self) -> None:
        g1 = ContentLengthGuardrail(max_length=1000)
        g2 = RegexGuardrail(patterns=[r"forbidden"])
        g3 = CallerAllowlistGuardrail(allowed_session_ids={"s1"})

        ctx = GuardrailContext(session_id="s1")
        text = "hello world"

        results = await asyncio.gather(
            g1.check(ctx, text),
            g2.check(ctx, text),
            g3.check(ctx, text),
        )
        assert all(r.passed for r in results)


# ---------------------------------------------------------------------------
# Tripwire semantics
# ---------------------------------------------------------------------------


class TestTripwire:
    @pytest.mark.asyncio
    async def test_tripwire_result_has_tripwire_true(self) -> None:
        g = CallerAllowlistGuardrail(allowed_session_ids={"s1"})
        ctx = GuardrailContext(session_id=None)
        result = await g.check(ctx, "text")
        assert result.tripwire is True


# ---------------------------------------------------------------------------
# Marker protocols
# ---------------------------------------------------------------------------


class TestMarkerProtocols:
    def test_input_guardrail_is_runtime_checkable(self) -> None:
        """ContentLengthGuardrail can satisfy InputGuardrail if it's registered."""
        # InputGuardrail and OutputGuardrail are structural protocols
        g = ContentLengthGuardrail(max_length=100)
        assert isinstance(g, InputGuardrail)
        assert isinstance(g, OutputGuardrail)

    def test_regex_guardrail_satisfies_protocols(self) -> None:
        g = RegexGuardrail(patterns=[r"x"])
        assert isinstance(g, InputGuardrail)
        assert isinstance(g, OutputGuardrail)


# ---------------------------------------------------------------------------
# RuntimeConfig integration
# ---------------------------------------------------------------------------


class TestRuntimeConfigGuardrails:
    def test_config_has_guardrail_fields(self) -> None:
        cfg = RuntimeConfig(runtime_name="thin")
        assert cfg.input_guardrails == []
        assert cfg.output_guardrails == []

    def test_config_accepts_guardrails(self) -> None:
        g_in = ContentLengthGuardrail(max_length=100)
        g_out = RegexGuardrail(patterns=[r"secret"])
        cfg = RuntimeConfig(
            runtime_name="thin",
            input_guardrails=[g_in],
            output_guardrails=[g_out],
        )
        assert len(cfg.input_guardrails) == 1
        assert len(cfg.output_guardrails) == 1


# ---------------------------------------------------------------------------
# RUNTIME_ERROR_KINDS
# ---------------------------------------------------------------------------


class TestErrorKinds:
    def test_guardrail_tripwire_in_error_kinds(self) -> None:
        assert "guardrail_tripwire" in RUNTIME_ERROR_KINDS
