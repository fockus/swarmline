"""Этап 25c (taskloom) parity check: `CodexAdapter.send_task` must construct its
`openai.AsyncOpenAI` client with `max_retries=0`, same invariant as
`runtime/thin/llm_providers.py`'s `AnthropicAdapter`/`OpenAICompatAdapter` (Этап 25b) —
"retry only at the LLM-call seam, never let the SDK's own opaque retry loop run
underneath it". `CodexAdapter` has no swarmline-level `retry_policy` wrapped around
`send_task` at all (it is a `multi_agent` `HostAdapter`, not part of the
`react_strategy`/`run_buffered_llm_call` seam), so leaving the SDK default
(`max_retries=2`) would silently retry blind — including on permanent 4xx errors —
which is exactly the failure mode Этап 25b closed for the thin-runtime provider
adapters.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from swarmline.runtime.codex_adapter import CodexAdapter


class TestCodexAdapterMaxRetriesParity:
    async def test_send_task_constructs_client_with_max_retries_zero_no_api_key(
        self,
    ) -> None:
        adapter = CodexAdapter()
        handle = await adapter.spawn_agent("dev", "build feature")

        fake_client = MagicMock()
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content="done"))]
        fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

        with patch("openai.AsyncOpenAI", return_value=fake_client) as mock_ctor:
            await adapter.send_task(handle, "do the thing")

        assert mock_ctor.call_args.kwargs.get("max_retries") == 0

    async def test_send_task_constructs_client_with_max_retries_zero_with_api_key(
        self,
    ) -> None:
        adapter = CodexAdapter(api_key="sk-test-key")
        handle = await adapter.spawn_agent("dev", "build feature")

        fake_client = MagicMock()
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content="done"))]
        fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

        with patch("openai.AsyncOpenAI", return_value=fake_client) as mock_ctor:
            await adapter.send_task(handle, "do the thing")

        assert mock_ctor.call_args.kwargs.get("api_key") == "sk-test-key"
        assert mock_ctor.call_args.kwargs.get("max_retries") == 0
