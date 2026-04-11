# Proposal: Scratchpad Module

**Status:** Draft
**Author:** Anton Ivanov
**Date:** 2026-04-10
**Related:** [Knowledge Bank](../knowledge-bank.md), [Memory](../memory.md), [MCP Server](../mcp-server.md)

## Motivation

Agents need ephemeral within-run working memory for intermediate state: research notes, observations, hypotheses, partial results. This is different from:

- **Memory** (cross-run, persistent) — what the agent remembers long-term
- **Knowledge Bank** (structured, domain docs) — curated knowledge with metadata
- **Todo** (task checklist) — what needs to be done

**Scratchpad** is the agent's notepad during a single task execution — analogous to how Manus maintains a working file system, or how a human developer keeps scratch notes while debugging.

## Inspiration

| System | Working Memory |
|--------|---------------|
| **Manus** | File system: agent writes/reads files, sees descriptions in context |
| **Claude Code** | TodoWrite/TodoRead + file system |
| **OpenViking AGFS** | `write()`, `read()`, `ls()`, `grep()` on namespaced file system |
| **Cognitia (current)** | No scratchpad — only persistent memory and todo |

## Design

### API (4 tools)

```python
# Write/update a scratchpad entry
scratch_write(key: str, content: str, tags: list[str] = []) -> str

# Read one entry or list all
scratch_read(key: str | None = None) -> str

# Search entries by content/key/tags
scratch_search(query: str) -> str

# Delete an entry
scratch_delete(key: str) -> str
```

### Data Model

```python
@dataclass
class ScratchpadEntry:
    key: str                    # unique identifier (e.g., "research_notes", "draft_v2")
    content: str                # the actual content
    tags: tuple[str, ...] = ()  # optional tags for filtering
    created_at: datetime
    updated_at: datetime
```

### Providers (pluggable backend)

| Provider | Use Case | Persistence |
|----------|----------|-------------|
| `InMemoryScratchpadProvider` | Single-run, testing | None (lost on exit) |
| `OpenVikingScratchpadProvider` | Production with OV | AGFS namespace + semantic search |
| `FilesystemScratchpadProvider` | Local dev, CLI agents | JSON files on disk |
| `DatabaseScratchpadProvider` | Production without OV | SQLAlchemy async |

### OpenViking Integration

When OpenViking is available, the scratchpad maps directly to AGFS:

```
viking://tenant/{tid}/workspace/{wid}/scratchpad/
  ├── research_notes.md      ← scratch_write("research_notes", "...")
  ├── draft_v2.md            ← scratch_write("draft_v2", "...")
  └── .meta/                 ← tags, timestamps (JSON sidecar)
```

Key benefit: entries are **auto-indexed** by OpenViking for semantic search.
`workspace_search("API design patterns")` finds relevant scratchpad notes alongside files and artifacts.

### Context Injection

Scratchpad summary injected into system prompt (similar to todo recitation):

```
[Scratchpad: 3 entries]
- research_notes (updated 2m ago, tags: market, analysis)
- competitor_list (updated 5m ago, tags: research)
- draft_outline (updated 1m ago, tags: report)
```

Agent sees entry keys + metadata. To read content, uses `scratch_read("research_notes")`.

## Module Structure

```
packages/cognitia/src/cognitia/scratchpad/
  ├── __init__.py           # public API: create_scratchpad_tools, providers
  ├── types.py              # ScratchpadEntry, ScratchpadConfig
  ├── provider.py           # InMemoryScratchpadProvider
  ├── openviking_provider.py # OpenVikingScratchpadProvider (AGFS-backed)
  ├── fs_provider.py        # FilesystemScratchpadProvider
  ├── db_provider.py        # DatabaseScratchpadProvider (SQLAlchemy)
  └── tools.py              # create_scratchpad_tools() → ToolSpec + executors
```

## MCP Server Integration

Scratchpad tools exposed through Cognitia MCP server (headless mode):

```python
# In cognitia/mcp/_server.py, register scratchpad tools alongside memory/plan/team
@mcp.tool()
async def cognitia_scratch_write(key: str, content: str, tags: list[str] = []) -> dict: ...

@mcp.tool()
async def cognitia_scratch_read(key: str | None = None) -> dict: ...
```

## Implementation Plan

1. **Core types + InMemory provider** — `types.py`, `provider.py` (~1h)
2. **Tools** — `tools.py` with `create_scratchpad_tools()` (~1h)
3. **OpenViking provider** — `openviking_provider.py` using AGFS (~2h)
4. **DB provider** — `db_provider.py` for non-OV production (~1h)
5. **MCP integration** — register in `_server.py` headless mode (~30m)
6. **Context injection** — scratchpad summary in system prompt (~30m)
7. **Tests** — unit + integration for each provider (~2h)

Total: ~8 hours

## Relationship to OpenViking

Scratchpad is a **Cognitia-level abstraction** that can use OpenViking as a backend.
This keeps Cognitia independent (no hard OV dependency) while leveraging OV when available:

```
Agent → Cognitia Scratchpad API → InMemoryProvider (default)
                                → OpenVikingScratchpadProvider (when OV available)
                                → DatabaseProvider (when DB available)
```

The OpenViking provider maps scratchpad operations to AGFS calls,
getting semantic search for free via OV's indexing pipeline.
