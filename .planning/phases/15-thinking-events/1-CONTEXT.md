# Phase 15: Thinking Events — Context

## Goal

Developers can observe the model's reasoning process as a separate event stream, with Anthropic extended thinking budget control and multi-turn signature preservation.

## Requirements

- **THNK-01**: RuntimeEvent.thinking_delta events stream thinking content separately from text_delta
- **THNK-02**: Anthropic extended thinking activated via budget_tokens config, thinking blocks returned
- **THNK-03**: Recent thinking blocks marked non-compactable (survive compaction)
- **THNK-04**: Non-Anthropic providers emit status warning when thinking mode enabled

## Codebase Analysis

### Existing Infrastructure

1. **RuntimeEvent** (`domain_types.py:191`): Frozen dataclass with `type: str, data: dict`. Factory methods: `assistant_delta`, `status`, `tool_call_started`, etc. Needs `thinking_delta` factory.

2. **AnthropicAdapter** (`runtime/thin/llm_providers.py:44`): Has `call()`, `stream()`, `call_with_tools()`. Currently does NOT pass thinking config to API. Only extracts `max_tokens` from kwargs. Needs to accept and pass `thinking` param.

3. **RuntimeConfig** (`runtime/types.py:120`): Central config. No `thinking` field yet. AgentConfig has `thinking: dict | None` but that lives in the agent layer, not runtime layer.

4. **ThinkingConfig resolution** (`runtime/options_builder.py:143-175`): `_resolve_thinking()` resolves `thinking` dict to ThinkingConfigEnabled/Adaptive/Disabled. Used by Claude Agent SDK path, NOT by ThinRuntime path.

5. **Compaction** (`compaction.py`): ConversationCompactionFilter with 3-tier cascade. Needs a way to mark messages as non-compactable (thinking blocks).

6. **Strategies** (`runtime/thin/conversational.py`, `react_strategy.py`): Yield RuntimeEvent to ThinRuntime.run(). Currently only yield `assistant_delta`. Need to yield `thinking_delta`.

7. **RuntimeEventAdapter** (`agent/runtime_dispatch.py:239`): Converts RuntimeEvent to StreamEvent-like interface. Needs `thinking_delta` handling.

### Design Decisions

- **AD-01**: RuntimeConfig gets `thinking: ThinkingConfig | None = None` field (optional, None default per L-004)
- **AD-02**: AnthropicAdapter passes thinking config as API param when present in kwargs
- **AD-03**: Return type for thinking-aware calls: `LlmResult(text, thinking_text)` instead of plain `str`
- **AD-04**: Compaction marks messages with `metadata.non_compactable=True` to skip
- **AD-05**: Non-Anthropic adapters: `RuntimeEvent.status("Warning: thinking mode not supported for provider ...")`

## Scope

- S-scope (3 tasks): domain type + adapter wiring + compaction exclusion
- Team: 2 developers + team lead
