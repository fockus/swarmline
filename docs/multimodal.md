# Multimodal input

Swarmline 1.5.0 introduces structured `ContentBlock` types so a single
`Message` can carry both text and images (and, eventually, more media types).
The default text-only path is unchanged — multimodal is opt-in via
`Message.content_blocks`.

This page covers:

1. The `TextBlock` / `ImageBlock` / `ContentBlock` types.
2. Constructing multimodal messages.
3. Provider compatibility.
4. PDF and Jupyter-notebook extractors that turn binary inputs into blocks.

## Types

```python
from swarmline.domain_types import (
    TextBlock,
    ImageBlock,
    ContentBlock,   # = TextBlock | ImageBlock
    Message,
)
```

Both blocks are frozen dataclasses:

| Type        | Fields                          |
|-------------|---------------------------------|
| `TextBlock` | `text: str`                     |
| `ImageBlock`| `data: str` (base64), `media_type: str` (e.g. `"image/png"`) |

`ImageBlock.data` is **base64-encoded image bytes**, not a URL. If you have a URL,
download and encode it yourself; the runtime does not fetch URLs from
`ImageBlock` for security reasons.

## Constructing a multimodal message

```python
import base64
from swarmline.domain_types import Message, TextBlock, ImageBlock

with open("diagram.png", "rb") as f:
    image_b64 = base64.b64encode(f.read()).decode()

msg = Message(
    role="user",
    content="Describe this diagram.",       # plain-text fallback
    content_blocks=[
        TextBlock(text="Describe this diagram."),
        ImageBlock(data=image_b64, media_type="image/png"),
    ],
)
```

`content` is the plain-text fallback used by adapters that don't (yet) support
multimodal. Set it to a useful description so non-multimodal providers can still
respond.

## Sending it through an Agent

```python
from swarmline.agent import Agent, AgentConfig

agent = Agent(AgentConfig(
    system_prompt="You are a vision-capable assistant.",
    runtime="thin",
    model="claude-sonnet-4",   # or "gpt-4o", "gemini-2.5-pro" — all multimodal
))

reply = await agent.query(messages=[msg])
print(reply.text)
```

The text-only `agent.query("...")` form is unchanged.

## Provider compatibility

The Anthropic, OpenAI, and Google adapters in `runtime/thin/llm_providers.py`
each have a `_to_provider_messages()` function that converts
`Message.content_blocks` into the format the provider expects:

| Provider  | Multimodal? | Image format                                        |
|-----------|-------------|-----------------------------------------------------|
| Anthropic | yes         | `{"type": "image", "source": {"type": "base64", ...}}` |
| OpenAI    | yes         | `{"type": "image_url", "image_url": {"url": "data:..."}}` |
| Google    | yes         | `inline_data` part with `mime_type` and base64 data |
| DeepSeek  | text-only   | falls back to `Message.content`                     |
| Custom    | depends     | adapter must implement the conversion               |

If you target multiple providers, set `Message.content` to a useful caption so
text-only providers degrade gracefully.

## Validation

`Message` is a frozen dataclass with no special validators — it stores whatever
you put in it. Adapters validate on conversion:

- `ImageBlock.data` must be a valid base64 string (provider rejects otherwise).
- `media_type` should be one the provider supports (`image/png`, `image/jpeg`,
  `image/gif`, `image/webp` are universally accepted).

The runtime emits a normal `RuntimeEvent.error(kind="bad_model_input", ...)` if
the provider rejects the request.

## Bundled extractors: PDF and Jupyter

Two async extractors live in `swarmline.tools.extractors` and turn common
non-image binary inputs into Markdown-flavoured text suitable for a `TextBlock`:

```python
from swarmline.tools.extractors import extract_pdf, extract_jupyter

# PDF (path or raw bytes) → markdown string
pdf_text = await extract_pdf("/path/to/spec.pdf")

# .ipynb (path, bytes, or raw JSON string) → text (markdown + code cells)
ipynb_text = await extract_jupyter("/path/to/notebook.ipynb")

msg = Message(
    role="user",
    content="Summarize this document.",
    content_blocks=[
        TextBlock(text="Summarize this document."),
        TextBlock(text=pdf_text),
    ],
)
```

PDF extraction lazy-imports `pymupdf4llm` (and `pymupdf` when reading from
`bytes`); Jupyter parsing lazy-imports `nbformat`. Install them only when you
actually need the extractor:

```bash
pip install pymupdf4llm   # for extract_pdf
pip install nbformat      # for extract_jupyter
```

I/O is wrapped in `asyncio.to_thread()` so the event loop is never blocked.

If you need image-aware PDF rendering (one `ImageBlock` per page), build it on
top of `pymupdf` directly — the bundled extractor returns text only.

## Patterns

### "Read this screenshot and answer"

```python
img_block = ImageBlock(data=screenshot_b64, media_type="image/png")
msg = Message(
    role="user",
    content="What does the error dialog say?",
    content_blocks=[TextBlock(text="What does the error dialog say?"), img_block],
)
```

### Mixed PDF + question

```python
blocks = [TextBlock(text="Find the section about retry policy and quote it.")]
blocks.extend(extract_pdf_blocks("design-spec.pdf"))
msg = Message(role="user", content="Find the retry policy section.", content_blocks=blocks)
```

### Multiple images in one turn

```python
blocks = [
    TextBlock(text="Compare these two designs:"),
    ImageBlock(data=design_a_b64, media_type="image/png"),
    ImageBlock(data=design_b_b64, media_type="image/png"),
    TextBlock(text="Which is more accessible?"),
]
```

## Sessions and resume

`JsonlMessageStore` (Phase 14) persists `content_blocks` verbatim, so resuming
a session restores the exact multimodal context. No special handling required —
treat multimodal messages like any other.

## See also

- `src/swarmline/domain_types.py` — `TextBlock`, `ImageBlock`, `Message`.
- `src/swarmline/runtime/thin/llm_providers.py` — per-provider multimodal converters.
- `docs/sessions.md` — session resume preserves `content_blocks`.
- `CHANGELOG.md` `[1.5.0]` Phase 16 entry.
