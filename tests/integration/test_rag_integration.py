"""Integration tests for RAG / Retriever Protocol (IDEA-028).

Tests cover:
- RagInputFilter + SimpleRetriever end-to-end
- ThinRuntime auto-wraps retriever into input_filters
- Full pipeline: retriever -> filter -> LLM call
"""

from __future__ import annotations

from typing import Any

from swarmline.rag import Document, RagInputFilter, SimpleRetriever
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent
import pytest

pytestmark = pytest.mark.integration


class TestRagInputFilterEndToEnd:
    """RagInputFilter + SimpleRetriever full integration."""

    async def test_end_to_end_retrieval_and_injection(self) -> None:
        docs = [
            Document(
                content="The capital of France is Paris", metadata={"source": "geo"}
            ),
            Document(content="Python was created by Guido van Rossum"),
            Document(content="The Eiffel Tower is in Paris, France"),
        ]
        retriever = SimpleRetriever(documents=docs)
        rag_filter = RagInputFilter(retriever=retriever, top_k=2)

        messages = [Message(role="user", content="Tell me about France")]
        filtered_messages, enriched_prompt = await rag_filter.filter(
            messages, "You are a geography assistant."
        )

        # Messages unchanged
        assert len(filtered_messages) == 1
        assert filtered_messages[0].content == "Tell me about France"

        # System prompt enriched with relevant docs
        assert "You are a geography assistant." in enriched_prompt
        assert "<context>" in enriched_prompt
        assert "France" in enriched_prompt
        # Both France-related docs should be retrieved (top_k=2)
        assert (
            "capital of France" in enriched_prompt or "Eiffel Tower" in enriched_prompt
        )


class TestThinRuntimeAutoWrapRetriever:
    """ThinRuntime auto-wraps config.retriever into input_filters."""

    async def test_auto_wraps_retriever_into_input_filters(self) -> None:
        docs = [Document(content="important context for LLM")]
        retriever = SimpleRetriever(documents=docs)

        captured_prompts: list[str] = []

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            captured_prompts.append(system_prompt)
            return "ok"

        config = RuntimeConfig(runtime_name="thin", retriever=retriever)
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        events: list[RuntimeEvent] = []
        async for event in runtime.run(
            messages=[Message(role="user", content="important context")],
            system_prompt="Base prompt.",
            active_tools=[],
            mode_hint="conversational",
        ):
            events.append(event)

        # LLM should have received enriched system prompt
        assert len(captured_prompts) >= 1
        assert "<context>" in captured_prompts[0]
        assert "important context for LLM" in captured_prompts[0]
        assert "Base prompt." in captured_prompts[0]

    async def test_does_not_duplicate_if_rag_filter_already_present(self) -> None:
        docs = [Document(content="doc one")]
        retriever = SimpleRetriever(documents=docs)
        rag_filter = RagInputFilter(retriever=retriever, top_k=3)

        captured_prompts: list[str] = []

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            captured_prompts.append(system_prompt)
            return "ok"

        config = RuntimeConfig(
            runtime_name="thin",
            retriever=retriever,
            input_filters=[rag_filter],
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        async for _ in runtime.run(
            messages=[Message(role="user", content="doc")],
            system_prompt="sys",
            active_tools=[],
            mode_hint="conversational",
        ):
            pass

        # Context should appear only once per call (no duplication from auto-wrap)
        assert len(captured_prompts) >= 1
        count = captured_prompts[0].count("<context>")
        assert count == 1


class TestFullPipelineRetrieverFilterLlm:
    """Full pipeline: retriever -> filter -> LLM call."""

    async def test_full_pipeline(self) -> None:
        import json

        docs = [
            Document(content="Answer to life is 42"),
            Document(content="Water boils at 100C"),
        ]
        retriever = SimpleRetriever(documents=docs)

        received_system: list[str] = []

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            received_system.append(system_prompt)
            return json.dumps(
                {
                    "type": "final",
                    "final_message": "The answer is 42",
                    "citations": [],
                    "next_suggestions": [],
                }
            )

        config = RuntimeConfig(runtime_name="thin", retriever=retriever)
        runtime = ThinRuntime(config=config, llm_call=fake_llm)

        final_text = ""
        async for event in runtime.run(
            messages=[Message(role="user", content="What is the answer to life?")],
            system_prompt="You are a wise oracle.",
            active_tools=[],
            mode_hint="conversational",
        ):
            if event.is_final:
                final_text = event.text

        assert final_text == "The answer is 42"
        assert "Answer to life is 42" in received_system[0]
        assert "You are a wise oracle." in received_system[0]
