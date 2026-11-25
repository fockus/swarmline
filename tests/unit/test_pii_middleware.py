"""Unit tests: PiiInputFilter and PiiMiddleware wiring."""

from __future__ import annotations

import pytest

from swarmline.agent.config import AgentConfig
from swarmline.agent.middleware import PiiMiddleware
from swarmline.agent.result import Result
from swarmline.domain_types import Message
from swarmline.pii import PiiInputFilter


# ---------------------------------------------------------------------------
# PiiInputFilter
# ---------------------------------------------------------------------------


class TestPiiInputFilter:
    @pytest.mark.asyncio
    async def test_pii_input_filter_redacts_message_content_and_system_prompt(
        self,
    ) -> None:
        filt = PiiInputFilter()
        messages = [Message(role="user", content="My email is user@example.com")]
        system = "Contact admin@company.com for help."

        redacted_msgs, redacted_sys = await filt.filter(messages, system)

        assert "user@example.com" not in redacted_msgs[0].content
        assert "[REDACTED_EMAIL]" in redacted_msgs[0].content
        assert "admin@company.com" not in redacted_sys
        assert "[REDACTED_EMAIL]" in redacted_sys

    @pytest.mark.asyncio
    async def test_pii_input_filter_preserves_message_role_and_structure(
        self,
    ) -> None:
        filt = PiiInputFilter()
        messages = [
            Message(role="user", content="SSN: 123-45-6789"),
            Message(role="assistant", content="I see your SSN: 123-45-6789"),
        ]
        result, _ = await filt.filter(messages, "")

        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert "123-45-6789" not in result[0].content
        assert "123-45-6789" not in result[1].content

    @pytest.mark.asyncio
    async def test_pii_input_filter_respects_strategy(self) -> None:
        filt = PiiInputFilter(strategy="mask", kinds=["email"])
        messages = [Message(role="user", content="Send to user@example.com")]
        result, _ = await filt.filter(messages, "")

        assert "user@example.com" not in result[0].content
        assert "****" in result[0].content

    @pytest.mark.asyncio
    async def test_pii_input_filter_empty_messages_returns_empty(self) -> None:
        filt = PiiInputFilter()
        result, sys = await filt.filter([], "no pii here")
        assert result == []
        assert sys == "no pii here"

    @pytest.mark.asyncio
    async def test_pii_input_filter_uses_dataclasses_replace_not_mutate(
        self,
    ) -> None:
        # Messages are frozen dataclasses; filter must not mutate originals.
        filt = PiiInputFilter()
        original_content = "My email is user@example.com"
        msg = Message(role="user", content=original_content)
        redacted, _ = await filt.filter([msg], "")

        # Original is unchanged (frozen), redacted is a new object.
        assert msg.content == original_content
        assert redacted[0].content != original_content


# ---------------------------------------------------------------------------
# PiiMiddleware
# ---------------------------------------------------------------------------


class TestPiiMiddlewareBeforeQuery:
    @pytest.mark.asyncio
    async def test_pii_middleware_before_query_redacts_input_prompt(self) -> None:
        mw = PiiMiddleware()
        config = AgentConfig(system_prompt="test")
        prompt = "My email is test@example.com"

        result = await mw.before_query(prompt, config)

        assert "test@example.com" not in result
        assert "[REDACTED_EMAIL]" in result

    @pytest.mark.asyncio
    async def test_pii_middleware_redact_input_false_skips_before_query(
        self,
    ) -> None:
        mw = PiiMiddleware(redact_input=False)
        config = AgentConfig(system_prompt="test")
        prompt = "Email: user@example.com"

        result = await mw.before_query(prompt, config)

        assert result == prompt  # unchanged

    @pytest.mark.asyncio
    async def test_pii_middleware_before_query_respects_kinds(self) -> None:
        mw = PiiMiddleware(kinds=["email"])
        config = AgentConfig(system_prompt="test")
        prompt = "Email: user@example.com, IP: 10.0.0.1"

        result = await mw.before_query(prompt, config)

        assert "user@example.com" not in result
        assert "10.0.0.1" in result  # IP not in kinds → untouched


class TestPiiMiddlewareAfterResult:
    @pytest.mark.asyncio
    async def test_pii_middleware_after_result_redacts_output_text(self) -> None:
        mw = PiiMiddleware()
        r = Result(
            text="Your email test@example.com was received.",
            structured_output={"key": "test@example.com"},
        )

        redacted = await mw.after_result(r)

        assert "test@example.com" not in redacted.text
        assert "[REDACTED_EMAIL]" in redacted.text
        # structured_output intentionally left intact
        assert redacted.structured_output == {"key": "test@example.com"}

    @pytest.mark.asyncio
    async def test_pii_middleware_redact_output_false_skips_after_result(
        self,
    ) -> None:
        mw = PiiMiddleware(redact_output=False)
        r = Result(text="Email: user@example.com")

        result = await mw.after_result(r)

        assert result is r  # same object, no copy made

    @pytest.mark.asyncio
    async def test_pii_middleware_after_result_returns_new_frozen_result(
        self,
    ) -> None:
        # Result is frozen; after_result uses dataclasses.replace, not mutation.
        mw = PiiMiddleware()
        r = Result(text="SSN: 123-45-6789", session_id="abc")

        redacted = await mw.after_result(r)

        assert redacted is not r
        assert "123-45-6789" not in redacted.text
        # Other fields preserved
        assert redacted.session_id == "abc"


class TestPiiMiddlewareStrategies:
    @pytest.mark.asyncio
    async def test_pii_middleware_respects_strategy_mask_and_kinds(self) -> None:
        mw = PiiMiddleware(strategy="mask", kinds=["email"])
        config = AgentConfig(system_prompt="test")
        prompt = "Email: user@example.com, IP: 10.0.0.1"

        result = await mw.before_query(prompt, config)

        assert "user@example.com" not in result
        assert "****" in result
        assert "10.0.0.1" in result  # IP not redacted


# ---------------------------------------------------------------------------
# End-to-end: Agent + PiiMiddleware + MockRuntime
# ---------------------------------------------------------------------------


class TestPiiMiddlewareEndToEnd:
    @pytest.mark.asyncio
    async def test_pii_middleware_runs_on_input_and_output_end_to_end(
        self,
    ) -> None:
        from swarmline import Agent
        from swarmline.testing import MockRuntime

        MockRuntime.register_default()
        agent = Agent(
            AgentConfig(
                system_prompt="You are helpful.",
                runtime="mock",
                middleware=(PiiMiddleware(),),
            )
        )

        result = await agent.query("My SSN is 123-45-6789")

        # SSN must not appear in the final output (was redacted in before_query,
        # so the runtime never sees it, and after_result sees an already-clean text).
        assert "123-45-6789" not in result.text

    @pytest.mark.asyncio
    async def test_pii_middleware_email_scrubbed_in_query_and_result(
        self,
    ) -> None:
        from swarmline import Agent
        from swarmline.testing import MockRuntime

        MockRuntime.register_default()
        agent = Agent(
            AgentConfig(
                system_prompt="You are helpful.",
                runtime="mock",
                middleware=(PiiMiddleware(),),
            )
        )

        result = await agent.query("Contact me at hello@world.com please")

        assert "hello@world.com" not in result.text
