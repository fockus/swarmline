# Knowledge Bank

Knowledge Bank is Cognitia's **domain-agnostic structured knowledge layer** built on top of [Memory Bank](memory-bank.md). While Memory Bank provides raw file-based storage (`read_file`, `write_file`), Knowledge Bank adds typed documents with YAML frontmatter, full-text search, checklists, progress tracking, and episode-to-knowledge consolidation.

Knowledge Bank was introduced in v1.2.0 and works with any domain -- research, business, education, engineering -- without code-development specifics.

## Quick Start

```python
from cognitia.memory_bank.knowledge_types import DocumentMeta, KnowledgeEntry
from cognitia.memory_bank.knowledge_inmemory import (
    InMemoryKnowledgeStore,
    InMemoryKnowledgeSearcher,
)

# 1. Create store and searcher
store = InMemoryKnowledgeStore()
searcher = InMemoryKnowledgeSearcher(store)

# 2. Save a knowledge entry with metadata
entry = KnowledgeEntry(
    path="notes/2026-03-30_api-design.md",
    meta=DocumentMeta(
        kind="note",
        tags=("api", "rest", "design"),
        importance="high",
        created="2026-03-30",
        updated="2026-03-30",
    ),
    content="REST API should use plural nouns for resource endpoints.",
    size_bytes=55,
)
await store.save(entry)

# 3. Search by text
results = await searcher.search("api design", top_k=5)
# [IndexEntry(path="notes/2026-03-30_api-design.md", kind="note", ...)]

# 4. Search by tags
results = await searcher.search_by_tags(["api", "rest"])
```

## Document Types

Every knowledge document carries a `DocumentMeta` header with structured metadata:

```python
from cognitia.memory_bank.knowledge_types import DocumentMeta

meta = DocumentMeta(
    kind="note",              # Document kind (see table below)
    tags=("python", "async"), # Searchable tags
    importance="high",        # "high", "medium", or "low"
    created="2026-03-30",     # ISO date string
    updated="2026-03-30",     # ISO date string
    related=("plan.md",),     # Related document paths
    custom={"author": "bot"}, # Arbitrary key-value pairs
)
```

### Document Kinds

| Kind | Purpose | Example |
|------|---------|---------|
| `status` | Current state overview | Project status, roadmap position |
| `plan` | Priorities and direction | Sprint plan, feature roadmap |
| `checklist` | Task tracking | To-do items with done/pending status |
| `research` | Hypotheses and findings | Experiment registry, literature review |
| `backlog` | Ideas and deferred items | Feature ideas, ADR records |
| `progress` | Append-only execution log | Daily progress entries |
| `lesson` | Learned patterns | Recurring mistakes, best practices |
| `note` | General knowledge | Meeting notes, design decisions |
| `report` | Detailed analysis | Post-mortems, comparison reports |
| `experiment` | Structured experiments | Hypothesis, method, result, outcome |

### YAML Frontmatter

Documents are stored as markdown with YAML frontmatter. The `frontmatter` module handles parsing and rendering:

```python
from cognitia.memory_bank.frontmatter import parse_frontmatter, render_frontmatter

# Parse a document
text = """---
kind: note
tags: [api, design]
importance: high
created: 2026-03-30
---

REST API should use plural nouns."""

meta, body = parse_frontmatter(text)
# meta = DocumentMeta(kind="note", tags=("api", "design"), importance="high", ...)
# body = "REST API should use plural nouns."

# Render back to markdown with frontmatter
output = render_frontmatter(meta, body)
```

Known frontmatter keys (`kind`, `tags`, `importance`, `created`, `updated`, `related`) are parsed into `DocumentMeta` fields. Any extra keys are captured in the `custom` dict.

## Storage

Knowledge Bank provides two store implementations with identical APIs.

### InMemoryKnowledgeStore

Dict-based, zero dependencies. Ideal for tests and development:

```python
from cognitia.memory_bank.knowledge_inmemory import InMemoryKnowledgeStore

store = InMemoryKnowledgeStore()

# CRUD operations
await store.save(entry)
loaded = await store.load("notes/2026-03-30_api-design.md")
exists = await store.exists("notes/2026-03-30_api-design.md")  # True
await store.delete("notes/2026-03-30_api-design.md")

# List entries, optionally filtered by kind
all_entries = await store.list_entries()
notes_only = await store.list_entries(kind="note")
```

### DefaultKnowledgeStore

Wraps any `MemoryBankProvider` (filesystem or database) for persistent storage. Automatically manages a JSON search index (`index.json`):

```python
from cognitia.memory_bank.knowledge_store import DefaultKnowledgeStore
from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider
from cognitia.memory_bank.types import MemoryBankConfig
from pathlib import Path

# Use a filesystem provider as the backend
config = MemoryBankConfig(enabled=True, root_path=Path("./data/kb"))
provider = FilesystemMemoryBankProvider(config, user_id="u1", topic_id="proj1")

store = DefaultKnowledgeStore(provider)

# Save -- writes frontmatter + content, updates index.json
await store.save(entry)

# Load -- parses frontmatter automatically
loaded = await store.load("notes/2026-03-30_api-design.md")
# KnowledgeEntry(path=..., meta=DocumentMeta(kind="note", ...), content="...", size_bytes=55)
```

Documents without frontmatter are loaded with a default `DocumentMeta(kind="note")`.

### Choosing a Backend

| Backend | Persistence | Use case |
|---------|-------------|----------|
| `InMemoryKnowledgeStore` | None | Tests, prototyping |
| `DefaultKnowledgeStore` + Filesystem provider | Disk | Local dev, CLI agents |
| `DefaultKnowledgeStore` + Database provider | DB | Production, multi-tenant |

## Search

Knowledge Bank provides full-text and tag-based search through the `KnowledgeSearcher` protocol.

### InMemoryKnowledgeSearcher

Word-overlap search over `InMemoryKnowledgeStore`. Scores results by the ratio of matching query words:

```python
from cognitia.memory_bank.knowledge_inmemory import (
    InMemoryKnowledgeStore,
    InMemoryKnowledgeSearcher,
)

store = InMemoryKnowledgeStore()
searcher = InMemoryKnowledgeSearcher(store)

# Full-text search (word overlap scoring)
results = await searcher.search("api design patterns", top_k=5)
for r in results:
    print(f"{r.path} [{r.kind}] -- {r.summary}")

# Tag-based search (matches any of the given tags)
results = await searcher.search_by_tags(["api", "rest"], top_k=10)

# Rebuild index from store contents
index = await searcher.rebuild_index()
print(f"Indexed {len(index.entries)} entries")

# Get current index (rebuilds if not yet built)
index = await searcher.get_index()
```

### DefaultKnowledgeSearcher

Wraps a `MemoryBankProvider`, scans all `.md` files, and persists the index as `index.json`:

```python
from cognitia.memory_bank.knowledge_search import DefaultKnowledgeSearcher

searcher = DefaultKnowledgeSearcher(provider)

# Search uses stored index; loads from index.json or rebuilds on first call
results = await searcher.search("database migration", top_k=5)

# Force rebuild (scans all .md files, parses frontmatter, writes index.json)
index = await searcher.rebuild_index()
```

The search algorithm uses word-overlap scoring: query words are compared against each entry's summary and tags. Results are sorted by overlap ratio (higher is better).

### Index Structure

The search index (`KnowledgeIndex`) is a flat list of lightweight `IndexEntry` objects:

```python
from cognitia.memory_bank.knowledge_types import KnowledgeIndex, IndexEntry

# IndexEntry contains metadata without full content
IndexEntry(
    path="notes/2026-03-30_api-design.md",
    kind="note",
    tags=("api", "design"),
    importance="high",
    summary="REST API should use plural nouns for resource endpoin...",  # first 100 chars
    updated="2026-03-30",
)
```

## Checklist

`ChecklistManager` provides structured task tracking via markdown-formatted checklists.

### InMemoryChecklistManager

```python
from cognitia.memory_bank.knowledge_inmemory import InMemoryChecklistManager
from cognitia.memory_bank.knowledge_types import ChecklistItem

checklist = InMemoryChecklistManager()

# Add items
await checklist.add_item(ChecklistItem(text="Design API schema", tags=("api",)))
await checklist.add_item(ChecklistItem(text="Write tests", tags=("testing",)))

# Toggle done status by text prefix
found = await checklist.toggle_item("design api")  # True -- case-insensitive prefix match

# Get all items
all_items = await checklist.get_items()

# Filter by status
pending = await checklist.get_items(done=False)
completed = await checklist.get_items(done=True)

# Clear completed items
removed_count = await checklist.clear_done()
```

### DefaultChecklistManager

Wraps a `MemoryBankProvider`, persists the checklist as a markdown file (`checklist.md` by default):

```python
from cognitia.memory_bank.knowledge_checklist import DefaultChecklistManager

checklist = DefaultChecklistManager(provider, path="checklist.md")
await checklist.add_item(ChecklistItem(text="Deploy to staging"))
```

The markdown format uses standard GitHub-compatible checkboxes:

```markdown
- [ ] Deploy to staging
- [x] Design API schema
- [ ] Write tests
```

## Progress

`ProgressLog` provides append-only timestamped logging for tracking execution history.

### InMemoryProgressLog

```python
from cognitia.memory_bank.knowledge_inmemory import InMemoryProgressLog

progress = InMemoryProgressLog()

# Append with automatic timestamp
await progress.append("Completed API design review")
# Stored as: "[2026-03-30 14:30] Completed API design review"

# Append without timestamp
await progress.append("Raw entry without timestamp", timestamp=False)

# Get recent entries
recent = await progress.get_recent(n=10)

# Get full log as text
full_log = await progress.get_all()
```

### DefaultProgressLog

Wraps a `MemoryBankProvider`, persists to `progress.md` by default:

```python
from cognitia.memory_bank.knowledge_progress import DefaultProgressLog

progress = DefaultProgressLog(provider, path="progress.md")
await progress.append("Deployed v1.2.0 to production")
```

Progress logs are **append-only** -- entries are never edited or deleted. This ensures a reliable audit trail of all actions.

## Knowledge Tools

Knowledge Bank exposes 3 agent tools via `create_knowledge_tools()`. These tools allow agents to search, create, and inspect knowledge during conversations:

```python
from cognitia.memory_bank.tools import create_knowledge_tools

specs, executors = create_knowledge_tools(store, searcher)
# specs: {"knowledge_search": ToolSpec, "knowledge_save_note": ToolSpec, "knowledge_get_context": ToolSpec}
# executors: {"knowledge_search": Callable, "knowledge_save_note": Callable, "knowledge_get_context": Callable}
```

### knowledge_search

Search the knowledge bank by text query.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Search query text |
| `top_k` | integer | no | Max results (default: 5) |

Returns a JSON array of matching entries with `path`, `kind`, `tags`, and `summary`.

### knowledge_save_note

Save a knowledge note with tags and metadata.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | yes | Note topic (used in filename) |
| `content` | string | yes | Note content (markdown) |
| `tags` | string | no | Comma-separated tags |
| `importance` | string | no | `"high"`, `"medium"` (default), or `"low"` |

The note is saved to `notes/{date}_{topic}.md` with a `DocumentMeta(kind="note")` header.

### knowledge_get_context

Get a summary of the knowledge bank state. Takes no parameters.

Returns JSON with:

```json
{
  "total_entries": 42,
  "by_kind": {"note": 20, "plan": 5, "lesson": 8, "report": 9},
  "recent": [
    {"path": "notes/2026-03-30_api-design.md", "kind": "note", "summary": "REST API should..."}
  ]
}
```

## Consolidation

`KnowledgeConsolidator` converts episodic memory (conversation episodes) into structured knowledge entries. This bridges short-term conversation data with the long-term knowledge bank.

```python
from cognitia.memory_bank.knowledge_consolidation import KnowledgeConsolidator

consolidator = KnowledgeConsolidator()

# Episodes are any objects with summary, tags, key_decisions, tools_used attributes
entries = consolidator.consolidate(
    episodes,
    min_episodes=3,  # Only create entries for groups with >= 3 episodes
)

# Save consolidated entries
for entry in entries:
    await store.save(entry)
```

The consolidation pipeline:

1. **Group** episodes by their tags
2. **Filter** groups below the `min_episodes` threshold
3. **Extract** summaries, key decisions, and tools used from each group
4. **Generate** a `KnowledgeEntry` per group with structured markdown content

Each consolidated entry includes:
- **Key Observations** -- summaries from the top 5 episodes in the group
- **Key Decisions** -- deduplicated decisions (up to 10)
- **Tools Used** -- all tools referenced across episodes

The result is a `ConsolidationResult` tracking `entries_created`, `episodes_processed`, and `patterns_found`.

## Additional Types

Knowledge Bank includes several supporting types for structured knowledge management:

```python
from cognitia.memory_bank.knowledge_types import (
    ExperimentRecord,
    LearnedPattern,
    QualityCriterion,
    KnowledgeBankConfig,
)

# Structured experiment tracking
experiment = ExperimentRecord(
    id="EXP-001",
    hypothesis="Batch processing improves throughput by 3x",
    method="Compare sequential vs batch with 10K records",
    result="Batch was 2.8x faster",
    outcome="confirmed",  # "confirmed", "rejected", "inconclusive", "pending"
    tags=("performance", "batch"),
)

# Learned patterns and antipatterns
pattern = LearnedPattern(
    id="H-001",
    pattern="Always validate input before database writes",
    context="Found 3 bugs caused by missing validation",
    recommendation="Add validation layer at service boundary",
    kind="pattern",  # "pattern", "antipattern", "heuristic"
    tags=("validation", "database"),
)

# Quality criteria for verification
criterion = QualityCriterion(
    name="Tests pass",
    description="All unit and integration tests pass",
    met=True,
    evidence="pytest: 142 passed, 0 failed",
)

# Knowledge Bank configuration
config = KnowledgeBankConfig(
    enabled=True,
    core_documents=("STATUS.md", "plan.md", "checklist.md"),
    directories=("plans", "notes", "reports", "experiments"),
    auto_index=True,
    verification_enabled=False,
)
```

## Protocols

Knowledge Bank defines 5 ISP-compliant protocols (all `@runtime_checkable`):

### KnowledgeStore (5 methods)

CRUD for typed knowledge documents.

```python
class KnowledgeStore(Protocol):
    async def save(self, entry: KnowledgeEntry) -> None: ...
    async def load(self, path: str) -> KnowledgeEntry | None: ...
    async def delete(self, path: str) -> None: ...
    async def list_entries(self, kind: DocumentKind | None = None) -> list[IndexEntry]: ...
    async def exists(self, path: str) -> bool: ...
```

### KnowledgeSearcher (4 methods)

Full-text and tag-based search with index management.

```python
class KnowledgeSearcher(Protocol):
    async def search(self, query: str, *, top_k: int = 10) -> list[IndexEntry]: ...
    async def search_by_tags(self, tags: list[str], *, top_k: int = 10) -> list[IndexEntry]: ...
    async def rebuild_index(self) -> KnowledgeIndex: ...
    async def get_index(self) -> KnowledgeIndex: ...
```

### ProgressLog (3 methods)

Append-only execution log.

```python
class ProgressLog(Protocol):
    async def append(self, entry: str, *, timestamp: bool = True) -> None: ...
    async def get_recent(self, n: int = 20) -> list[str]: ...
    async def get_all(self) -> str: ...
```

### ChecklistManager (4 methods)

Task tracking with toggle and filter.

```python
class ChecklistManager(Protocol):
    async def add_item(self, item: ChecklistItem) -> None: ...
    async def toggle_item(self, text_prefix: str) -> bool: ...
    async def get_items(self, *, done: bool | None = None) -> list[ChecklistItem]: ...
    async def clear_done(self) -> int: ...
```

### VerificationStrategy (2 methods)

Pluggable quality verification for plans and deliverables.

```python
class VerificationStrategy(Protocol):
    async def verify(self, criteria: list[QualityCriterion]) -> list[QualityCriterion]: ...
    async def suggest_criteria(self, plan_content: str) -> list[QualityCriterion]: ...
```

A `NullVerifier` implementation is provided that auto-passes all criteria (useful for tests or when verification is disabled).

## Knowledge Bank vs Memory Bank

| Aspect | Memory Bank | Knowledge Bank |
|--------|-------------|----------------|
| **Abstraction** | Raw file storage (read/write/list) | Typed documents with metadata |
| **Metadata** | None (plain text files) | YAML frontmatter (kind, tags, importance) |
| **Search** | Manual file listing | Full-text and tag-based search with index |
| **Task tracking** | Manual markdown editing | ChecklistManager with add/toggle/filter |
| **Progress** | Manual append | ProgressLog with automatic timestamps |
| **Agent tools** | 5 tools (memory_*) | 3 tools (knowledge_*) |
| **Consolidation** | None | Episode-to-knowledge pipeline |
| **Protocols** | 1 (MemoryBankProvider) | 5 ISP-compliant protocols |

Knowledge Bank builds **on top of** Memory Bank -- `DefaultKnowledgeStore` and `DefaultKnowledgeSearcher` use `MemoryBankProvider` as their storage backend. You can use both layers together: Memory Bank for raw file access, Knowledge Bank for structured knowledge management.

## Next Steps

- [Memory Bank](memory-bank.md) -- lower-level file storage that backs Knowledge Bank
- [Memory Providers](memory.md) -- conversation-level memory (messages, facts, goals)
- [Tools & Skills](tools-and-skills.md) -- how agent tools are registered and managed
- [Agent Facade](agent-facade.md) -- wiring Knowledge Bank into agent configurations
