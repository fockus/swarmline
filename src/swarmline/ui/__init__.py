"""UI layer — event projection for building chat UIs from RuntimeEvent streams."""

from swarmline.ui.projection import (
    ChatProjection,
    ErrorBlock,
    EventProjection,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    UIBlock,
    UIMessage,
    UIState,
    project_stream,
)

__all__ = [
    "ChatProjection",
    "ErrorBlock",
    "EventProjection",
    "TextBlock",
    "ToolCallBlock",
    "ToolResultBlock",
    "UIBlock",
    "UIMessage",
    "UIState",
    "project_stream",
]
