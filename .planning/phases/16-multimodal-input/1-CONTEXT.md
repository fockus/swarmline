# Phase 16: Multimodal Input — Context

## Goal

Agents can process images, PDFs, and Jupyter notebooks alongside text, with automatic provider-specific conversion for Anthropic, OpenAI, and Google vision APIs.

## Requirements

- **MMOD-01**: Message supports multi-part content via additive content_blocks field (keep content: str)
- **MMOD-02**: Read tool returns ImageBlock when reading PNG/JPG files
- **MMOD-03**: Provider adapters convert content_blocks: Anthropic vision blocks, OpenAI image_url, Google inline_data
- **MMOD-04**: PDF extraction via optional pymupdf4llm
- **MMOD-05**: Jupyter extraction via optional nbformat

## Codebase Analysis

### Key Files

1. **Message** (`domain_types.py:25-57`): Frozen dataclass with `role, content, name, tool_calls, metadata`. Needs additive `content_blocks: list[ContentBlock] | None = None`.

2. **_messages_to_lm** (`runtime/thin/helpers.py:14-22`): Converts Message → `{"role", "content"}` dict. Needs to handle content_blocks.

3. **_filter_chat_messages** (`runtime/thin/llm_providers.py:35-44`): Filters user/assistant messages for API. Needs to pass through content_blocks.

4. **AnthropicAdapter** (`llm_providers.py:47`): `call()` sends simple text messages. Needs Anthropic vision block conversion.

5. **OpenAICompatAdapter** (`llm_providers.py:136`): Needs image_url content conversion.

6. **GoogleAdapter** (`llm_providers.py:250+`): Needs inline_data conversion.

7. **Read tool** (`tools/builtin.py:174-185`): `_create_read_executor` reads file as text via `sandbox.read_file()`. Needs image detection + base64 encoding.

8. **SandboxProvider** (`tools/protocols.py:24`): `read_file(path) -> str`. Needs `read_file_bytes(path) -> bytes` for binary files.

### Design Decisions

- **AD-01**: ContentBlock = TextBlock | ImageBlock (union type, frozen dataclasses in domain_types.py)
- **AD-02**: Message.content_blocks is additive — when None, adapters use content: str (backward compat)
- **AD-03**: When content_blocks is set, adapters use it; content: str is still set for logging/display
- **AD-04**: Provider conversion in _filter_chat_messages or a new _convert_content_blocks helper
- **AD-05**: Image detection by file extension in read tool executor
- **AD-06**: PDF/Jupyter are text extractors — return text content, not ContentBlock
- **AD-07**: No new core deps — pymupdf4llm and nbformat are lazy imports with graceful fallback
