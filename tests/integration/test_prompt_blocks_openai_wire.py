"""Integration: ``Agent.query(prompt_blocks=[ImageBlock])`` reaches the OpenAI wire as an image part.

The real ``Agent`` → ``ThinRuntime`` text-ReAct loop → ``OpenAICompatAdapter`` → the real
``openai.AsyncOpenAI`` client; the ONLY fake is the HTTP transport under that client
(``httpx.MockTransport`` scripting the model), so no provider is ever called.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import openai
import pytest

from swarmline import Agent, AgentConfig
from swarmline.agent.tool import ToolDefinition
from swarmline.context.budget import IMAGE_TOKEN_ESTIMATE
from swarmline.domain_types import ImageBlock, Message
from swarmline.runtime.thin import llm_providers

PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()
IMAGE = ImageBlock(data=PNG_B64, media_type="image/png")
DATA_URI = f"data:image/png;base64,{PNG_B64}"


class _ScriptedProvider:
    """The provider's HTTP side: replays scripted ReAct steps and records every request body."""

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self._steps = steps
        self.requests: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        step = self._steps[min(len(self.requests), len(self._steps)) - 1]
        reply = json.dumps(step)
        if body.get("stream"):
            chunk = {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {"index": 0, "delta": {"content": reply}, "finish_reason": "stop"}
                ],
            }
            sse = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"
            return httpx.Response(
                200, content=sse.encode(), headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    def user_messages(self, request_index: int) -> list[dict[str, Any]]:
        return [
            m for m in self.requests[request_index]["messages"] if m["role"] == "user"
        ]


@pytest.fixture
def provider_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[list[dict[str, Any]]], _ScriptedProvider]:
    real_client = openai.AsyncOpenAI

    def _install(steps: list[dict[str, Any]]) -> _ScriptedProvider:
        provider = _ScriptedProvider(steps)
        transport = httpx.MockTransport(provider.handle)

        def _client(**kwargs: Any) -> openai.AsyncOpenAI:
            return real_client(
                **kwargs, http_client=httpx.AsyncClient(transport=transport)
            )

        monkeypatch.setattr(openai, "AsyncOpenAI", _client)
        monkeypatch.setattr(llm_providers, "_adapter_cache", {})
        return provider

    return _install


def _final(text: str) -> dict[str, Any]:
    return {"type": "final", "final_message": text}


def _agent(*tools: ToolDefinition) -> Agent:
    return Agent(
        AgentConfig(
            system_prompt="You describe images.",
            runtime="thin",
            model="openrouter:deepseek/deepseek-v4.1-flash",
            base_url="https://openrouter.ai/api/v1",
            api_key="test-key-not-real",
            tools=tools,
        )
    )


def _image_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message["content"]
    if not isinstance(content, list):
        return []
    return [part for part in content if part.get("type") == "image_url"]


async def test_image_block_reaches_wire_as_image_url_data_uri(
    provider_factory: Callable[[list[dict[str, Any]]], _ScriptedProvider],
) -> None:
    provider = provider_factory([_final("A small PNG.")])

    result = await _agent().query("What is on the picture?", prompt_blocks=[IMAGE])

    assert result.ok is True and result.text == "A small PNG."
    last_user = provider.user_messages(0)[-1]
    assert last_user["content"][0] == {
        "type": "text",
        "text": "What is on the picture?",
    }
    assert _image_parts(last_user) == [
        {"type": "image_url", "image_url": {"url": DATA_URI}}
    ]


async def test_image_repeated_in_later_rounds_of_same_turn_only(
    provider_factory: Callable[[list[dict[str, Any]]], _ScriptedProvider],
) -> None:
    async def _lookup(query: str) -> str:
        return f"looked up {query}"

    lookup = ToolDefinition(
        name="lookup",
        description="Look something up.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_lookup,
    )
    provider = provider_factory(
        [
            {"type": "tool_call", "tool": {"name": "lookup", "args": {"query": "cat"}}},
            _final("A cat."),
        ]
    )

    first = await _agent(lookup).query("Which animal?", prompt_blocks=[IMAGE])
    provider_factory_next = provider_factory([_final("Still a cat.")])
    await _agent(lookup).query(
        "And now?",
        messages=[
            Message(role="user", content="Which animal?"),
            Message(role="assistant", content=first.text),
        ],
    )

    assert len(provider.requests) == 2, "tool round + final round of the same turn"
    for index in range(2):
        with_images = [m for m in provider.user_messages(index) if _image_parts(m)]
        assert len(with_images) == 1, (
            f"round {index + 1} carries the image exactly once"
        )
    next_turn = provider_factory_next.requests[0]["messages"]
    assert not any(_image_parts(m) for m in next_turn if m["role"] == "user")


async def test_image_block_counted_in_token_estimate(
    provider_factory: Callable[[list[dict[str, Any]]], _ScriptedProvider],
) -> None:
    provider_factory([_final("same")])
    without = await _agent().query("Describe it.")
    provider_factory([_final("same")])
    with_two = await _agent().query("Describe it.", prompt_blocks=[IMAGE, IMAGE])

    assert without.usage is not None and with_two.usage is not None
    assert (
        without.usage["usage_source"] == with_two.usage["usage_source"] == "estimated"
    )
    delta = with_two.usage["input_tokens"] - without.usage["input_tokens"]
    assert delta == 2 * IMAGE_TOKEN_ESTIMATE
