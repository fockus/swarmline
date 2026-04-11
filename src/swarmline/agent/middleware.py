"""Middleware - composable request handling for the Agent facade."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from swarmline.hooks.registry import HookRegistry

if TYPE_CHECKING:
    from swarmline.agent.config import AgentConfig
    from swarmline.agent.result import Result


class BudgetExceededError(RuntimeError):
    """Budget exceeded (max_budget_usd)."""


class Middleware:
    """Base middleware for the Agent facade.

    All methods are default passthrough (override the ones you need in subclasses).
    """

    async def before_query(self, prompt: str, config: AgentConfig) -> str:
        """Before the request. Can modify the prompt. Raise -> block."""
        return prompt

    async def after_result(self, result: Result) -> Result:
        """After the result. Can modify/enrich the Result."""
        return result

    def get_hooks(self) -> HookRegistry | None:
        """Hooks for the runtime (optional)."""
        return None


class CostTracker(Middleware):
    """Middleware: accumulate cost and enforce a budget."""

    def __init__(self, budget_usd: float) -> None:
        self._budget_usd = budget_usd
        self._total_cost: float = 0.0

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost

    def reset(self) -> None:
        self._total_cost = 0.0

    async def after_result(self, result: Result) -> Result:
        cost = result.total_cost_usd
        if cost is not None:
            self._total_cost += cost
            if self._total_cost > self._budget_usd:
                raise BudgetExceededError(
                    f"Budget exceeded: ${self._total_cost:.4f} > ${self._budget_usd:.2f}"
                )
        return result


class SecurityGuard(Middleware):
    """Middleware: block dangerous patterns in tool input via a PreToolUse hook."""

    def __init__(self, block_patterns: list[str]) -> None:
        self._patterns = block_patterns

    def get_hooks(self) -> HookRegistry:
        registry = HookRegistry()
        registry.on_pre_tool_use(self._check_tool_input)
        return registry

    async def _check_tool_input(self, **kwargs: Any) -> dict[str, Any]:
        tool_input = kwargs.get("tool_input") or {}
        text = " ".join(str(v) for v in tool_input.values())

        for pattern in self._patterns:
            if pattern in text:
                return {
                    "decision": "block",
                    "reason": f"Blocked: pattern '{pattern}' found in tool input",
                }
        return {"continue_": True}


class ToolOutputCompressor(Middleware):
    """Turn-level middleware: compresses tool output between turns.

    Content-type aware:
    - JSON: truncate arrays + add "... (truncated)"
    - HTML: strip tags, then truncate
    - Text: truncate at head+tail boundary
    """

    def __init__(self, max_result_chars: int = 10000) -> None:
        self.max_result_chars = max_result_chars

    def get_hooks(self) -> HookRegistry:
        registry = HookRegistry()
        registry.on_post_tool_use(self._compress_output)
        return registry

    async def _compress_output(self, **kwargs: Any) -> dict[str, Any]:
        tool_result = kwargs.get("tool_result")
        if not isinstance(tool_result, str) or len(tool_result) <= self.max_result_chars:
            return {"continue_": True}
        compressed = self.compress(tool_result)
        return {"tool_result": compressed}

    def compress(self, text: str) -> str:
        """Compress text based on the detected content type."""
        if len(text) <= self.max_result_chars:
            return text
        if self._looks_like_json(text):
            return self._compress_json(text)
        if self._looks_like_html(text):
            return self._compress_html(text)
        return self._compress_text(text)

    def _looks_like_json(self, text: str) -> bool:
        stripped = text.strip()
        return (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        )

    def _looks_like_html(self, text: str) -> bool:
        lower_head = text[:200].lower()
        return "<html" in lower_head or "<!doctype" in lower_head

    def _compress_json(self, text: str) -> str:
        try:
            data = json.loads(text)
            if isinstance(data, list) and len(data) > 3:
                truncated = data[:3]
                result = json.dumps(truncated, ensure_ascii=False, indent=2)
                return f"{result}\n[...{len(data) - 3} more items truncated]"
            if isinstance(data, dict):
                result = json.dumps(data, ensure_ascii=False, indent=2)
                if len(result) <= self.max_result_chars:
                    return result
        except (json.JSONDecodeError, RecursionError):
            pass
        return self._compress_text(text)

    def _compress_html(self, text: str) -> str:
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        return self._compress_text(clean)

    def _compress_text(self, text: str) -> str:
        head_size = int(self.max_result_chars * 0.75)
        tail_size = self.max_result_chars - head_size - 50
        if tail_size < 0:
            tail_size = 0
        truncated_count = len(text) - head_size - tail_size
        head = text[:head_size]
        tail = text[-tail_size:] if tail_size > 0 else ""
        return f"{head}\n[...{truncated_count} chars truncated...]\n{tail}"


def build_middleware_stack(
    *,
    cost_tracker: bool = False,
    tool_compressor: bool = True,
    security_guard: bool = False,
    max_result_chars: int = 10000,
    budget_usd: float = 0.0,
    blocked_patterns: list[str] | None = None,
) -> tuple[Middleware, ...]:
    """Build a standard middleware stack with common defaults."""
    stack: list[Middleware] = []
    if security_guard:
        stack.append(SecurityGuard(blocked_patterns or []))
    if tool_compressor:
        stack.append(ToolOutputCompressor(max_result_chars=max_result_chars))
    if cost_tracker:
        stack.append(CostTracker(budget_usd=budget_usd))
    return tuple(stack)
