"""Tests for ToolOutputCompressor middleware and build_middleware_stack factory."""

from __future__ import annotations

import json

import pytest
from swarmline.agent.middleware import (
    CostTracker,
    Middleware,
    SecurityGuard,
    ToolOutputCompressor,
    build_middleware_stack,
)
from swarmline.hooks.registry import HookRegistry


class TestToolOutputCompressorCompress:
    def test_compressor_preserves_short_text(self) -> None:
        compressor = ToolOutputCompressor(max_result_chars=100)
        short = "Hello, world!"
        assert compressor.compress(short) == short

    def test_compressor_truncates_long_json(self) -> None:
        compressor = ToolOutputCompressor(max_result_chars=200)
        data = [{"id": i, "name": f"item_{i}", "value": "x" * 50} for i in range(20)]
        raw = json.dumps(data)
        result = compressor.compress(raw)
        assert "[...17 more items truncated]" in result
        parsed_part = json.loads(result.split("\n[...")[0])
        assert len(parsed_part) == 3

    def test_compressor_strips_html_tags(self) -> None:
        compressor = ToolOutputCompressor(max_result_chars=100)
        html = "<html><body>" + "<p>paragraph</p>" * 100 + "</body></html>"
        result = compressor.compress(html)
        assert "<p>" not in result
        assert "<html>" not in result
        assert "paragraph" in result
        assert "truncated" in result

    def test_compressor_truncates_plain_text_with_head_tail(self) -> None:
        compressor = ToolOutputCompressor(max_result_chars=200)
        text = "A" * 1000
        result = compressor.compress(text)
        assert "truncated" in result
        assert len(result) < 1000


class TestToolOutputCompressorHooks:
    def test_compressor_hooks_registered(self) -> None:
        compressor = ToolOutputCompressor()
        hooks = compressor.get_hooks()
        assert isinstance(hooks, HookRegistry)
        post_hooks = hooks.get_hooks("PostToolUse")
        assert len(post_hooks) == 1
        assert post_hooks[0].event == "PostToolUse"

    @pytest.mark.asyncio
    async def test_compress_output_hook_shortcircuits_small_result(self) -> None:
        compressor = ToolOutputCompressor(max_result_chars=1000)
        result = await compressor._compress_output(tool_result="short text")
        assert result == {"continue_": True}

    @pytest.mark.asyncio
    async def test_compress_output_hook_compresses_large_result(self) -> None:
        compressor = ToolOutputCompressor(max_result_chars=100)
        large = "X" * 500
        result = await compressor._compress_output(tool_result=large)
        assert "tool_result" in result
        assert len(result["tool_result"]) < 500


class TestBuildMiddlewareStack:
    def test_default_stack_has_compressor_only(self) -> None:
        stack = build_middleware_stack()
        assert len(stack) == 1
        assert isinstance(stack[0], ToolOutputCompressor)

    def test_all_middleware_enabled(self) -> None:
        stack = build_middleware_stack(
            cost_tracker=True,
            tool_compressor=True,
            security_guard=True,
            budget_usd=10.0,
            blocked_patterns=["rm -rf"],
        )
        assert len(stack) == 3
        types = [type(m) for m in stack]
        assert SecurityGuard in types
        assert ToolOutputCompressor in types
        assert CostTracker in types

    def test_empty_stack(self) -> None:
        stack = build_middleware_stack(
            cost_tracker=False, tool_compressor=False, security_guard=False
        )
        assert stack == ()

    def test_stack_returns_middleware_instances(self) -> None:
        stack = build_middleware_stack()
        for m in stack:
            assert isinstance(m, Middleware)

    def test_custom_max_result_chars(self) -> None:
        stack = build_middleware_stack(max_result_chars=5000)
        compressor = stack[0]
        assert isinstance(compressor, ToolOutputCompressor)
        assert compressor.max_result_chars == 5000
