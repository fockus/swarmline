"""Shared fakes for the Sprint 1ce Stage 2 compaction tests (no LLM is ever called)."""

from __future__ import annotations

from swarmline.domain_types import Message

FILLER = "lorem ipsum dolor sit amet " * 40  # ~1080 chars ~ 270 tokens


def structured_summary(
    marker: str = "SUMMARY_MARKER", *, omit: str | None = None
) -> str:
    """A well-formed 7-section summary; ``omit`` drops one section line."""
    lines = {
        "Goal": f"migrate the billing module ({marker})",
        "Constraints": "keep the public API stable",
        "Progress": "read the legacy code and wrote the adapter",
        "Key Decisions": "adapter over rewrite, because callers are many",
        "Errors": "none",
        "Files": "billing/legacy.py",
        "Next Steps": "wire the adapter into the service",
    }
    return "\n".join(f"{name}: {text}" for name, text in lines.items() if name != omit)


def scripted_summarizer(response: object, calls: list[tuple[str, str]] | None = None):
    """An ``llm_call`` returning a fixed response and recording (prompt, dialog)."""

    async def _call(prompt: str, dialog_text: str) -> str:
        if calls is not None:
            calls.append((prompt, dialog_text))
        return response  # type: ignore[return-value]

    return _call


def long_history(
    first_request: str = "Please migrate the billing module to the new API.",
    rounds: int = 8,
) -> list[Message]:
    """One human request followed by ``rounds`` assistant/user filler pairs."""
    messages = [Message(role="user", content=first_request)]
    for i in range(rounds):
        messages.append(Message(role="assistant", content=f"step {i}: {FILLER}"))
        messages.append(Message(role="user", content=f"continue {i}: {FILLER}"))
    return messages


def summary_messages(messages: list[Message]) -> list[Message]:
    return [
        m
        for m in messages
        if m.role == "system" and m.content.startswith("[Conversation summary]: ")
    ]
