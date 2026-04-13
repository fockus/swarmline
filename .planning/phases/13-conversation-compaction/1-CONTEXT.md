# Phase 13: Conversation Compaction — Context

## Goal

Long-running agents maintain coherent context by automatically compacting conversation history through a 3-tier pipeline instead of losing information to naive truncation.

## Requirements

- **CMPCT-01**: When conversation approaches token budget, early messages are automatically replaced with an LLM-generated summary
- **CMPCT-02**: Compaction summary preserves key decisions, tool results, and project instructions from the compacted region
- **CMPCT-03**: 3-tier pipeline activates in order: tool result collapse first, then LLM summarization, then emergency truncation as fallback
- **CMPCT-04**: Compaction behavior is configurable via RuntimeConfig (enable/disable, budget threshold, summarization model)

## What Already Exists

### MaxTokensFilter (Tier 3 — emergency truncation)
- `src/swarmline/input_filters.py:27-69` — drops oldest messages to fit budget
- Simple char-based token estimation (len/4)
- System prompt protected, last message always preserved
- **This becomes Tier 3 fallback — already done**

### LLM Summarization infrastructure
- `src/swarmline/memory/llm_summarizer.py:31-91` — LlmSummaryGenerator with async summarization
- Prompt generates ~1000-1500 char summary preserving key facts, decisions, task state
- Falls back to TemplateSummaryGenerator if LLM unavailable
- **Reuse pattern for Tier 2**

### Token estimation
- `src/swarmline/context/budget.py:31-41` — `estimate_tokens(text)` (len//4+1)
- Used consistently across codebase

### Message structure
- `src/swarmline/domain_types.py:25-57` — Message(role, content, name, tool_calls, metadata)
- Tool call: role="assistant", metadata={"tool_call": name}
- Tool result: role="tool", content=result_str, name=tool_name
- **Tool pairs are easy to identify for Tier 1 collapse**

### InputFilter protocol
- `src/swarmline/input_filters.py:16-24` — async filter(messages, system_prompt) → (messages, system_prompt)
- Applied sequentially in ThinRuntime.run() before LLM call

## Design

### ConversationCompactionFilter (new InputFilter)

Single filter implementing all 3 tiers in cascade:

```
1. Estimate total tokens (messages + system_prompt)
2. If total <= threshold → return unchanged
3. Tier 1: Collapse tool results → re-estimate
4. If total <= threshold → return
5. Tier 2: LLM summarize oldest messages → re-estimate
6. If total <= threshold → return
7. Tier 3: Emergency truncate (MaxTokensFilter logic)
```

### Tier 1: Tool Result Collapse
- Find (assistant tool_call → tool result) message pairs
- Keep only most recent N pairs intact (configurable, default 3)
- Replace older pairs with: `Message(role="system", content="[Tool {name}: {first 100 chars of result}...]")`
- Preserves what tool was called and approximate result

### Tier 2: LLM Summarization
- Take oldest messages (up to compaction region)
- Call LLM with summarization prompt
- Replace with: `Message(role="system", content="[Compaction summary]: {summary}")`
- Needs async LLM call — passed via constructor or RuntimeConfig

### Tier 3: Emergency Truncation
- Drop oldest messages (current MaxTokensFilter logic)
- Last resort when LLM summarization unavailable or insufficient

### CompactionConfig (frozen dataclass)
```python
@dataclass(frozen=True)
class CompactionConfig:
    enabled: bool = True
    threshold_tokens: int = 80_000  # trigger compaction
    preserve_recent_pairs: int = 3   # keep N recent tool pairs
    summarization_model: str | None = None  # LLM model for Tier 2
    tier_1_enabled: bool = True
    tier_2_enabled: bool = True
    tier_3_enabled: bool = True
```

### RuntimeConfig integration
- `compaction: CompactionConfig | None = None` — optional field

## Files

### New
- `src/swarmline/compaction.py` — CompactionConfig + ConversationCompactionFilter
- `tests/unit/test_compaction.py` — unit tests for all 3 tiers
- `tests/integration/test_compaction_integration.py` — integration with ThinRuntime

### Modified
- `src/swarmline/runtime/types.py` — compaction field in RuntimeConfig
- `src/swarmline/__init__.py` — export CompactionConfig, ConversationCompactionFilter
