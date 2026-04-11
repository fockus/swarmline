# Memory Providers

Cognitia provides 3 interchangeable memory providers behind a unified protocol interface.

## Protocols

Memory is split into 8 ISP-compliant protocols (each <=5 methods):

| Protocol | Methods | Purpose |
|----------|---------|---------|
| `MessageStore` | `save_message`, `get_messages`, `count_messages`, `delete_messages_before` | Conversation history |
| `FactStore` | `upsert_fact`, `get_facts` | Key-value user facts |
| `GoalStore` | `save_goal`, `get_active_goal` | User goals |
| `SummaryStore` | `save_summary`, `get_summary` | Conversation summaries |
| `UserStore` | `ensure_user`, `get_user_profile` | User identity |
| `SessionStateStore` | `save_session_state`, `get_session_state` | Session metadata |
| `PhaseStore` | `save_phase_state`, `get_phase_state` | User phase tracking |
| `ToolEventStore` | `save_tool_event` | Tool usage audit trail |

All three providers implement all 8 protocols.

## InMemoryMemoryProvider

Zero-dependency, great for tests and development:

```python
from cognitia.memory import InMemoryMemoryProvider

memory = InMemoryMemoryProvider()

# Store a fact
await memory.upsert_fact("user_1", "name", "Alice")

# Retrieve facts
facts = await memory.get_facts("user_1")
print(facts)  # {"name": "Alice"}

# Store a message
await memory.save_message("user_1", "topic_1", "user", "Hello!")

# Get messages
messages = await memory.get_messages("user_1", "topic_1", limit=10)
```

Data lives in memory and is lost when the process exits.

## PostgresMemoryProvider

Production-ready with SQLAlchemy async:

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from cognitia.memory import PostgresMemoryProvider

engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/db")
session_factory = async_sessionmaker(engine, expire_on_commit=False)

memory = PostgresMemoryProvider(session_factory)
```

Requires `pip install cognitia[postgres]`.

### Schema

Tables are managed by the application (via Alembic or raw SQL). Required tables:

- `messages` (user_id, topic_id, role, content, metadata, created_at)
- `facts` (user_id, topic_id, key, value, source, updated_at)
- `goals` (user_id, topic_id, data, created_at)
- `summaries` (user_id, topic_id, summary, messages_covered, created_at)
- `users` (external_id, user_id, created_at)
- `session_state` (user_id, topic_id, role_id, active_skill_ids, prompt_hash)
- `phase_state` (user_id, phase, notes, updated_at)
- `tool_events` (user_id, event_data, created_at)

## SQLiteMemoryProvider

Lightweight persistence without a database server:

```python
from cognitia.memory import SQLiteMemoryProvider

memory = SQLiteMemoryProvider(db_path="./agent.db")
# Tables are created automatically on first use
```

Requires `pip install cognitia[sqlite]`.

## Choosing a Provider

| Provider | Persistence | Setup | Best For |
|----------|-------------|-------|----------|
| InMemory | None | Zero | Tests, prototyping |
| SQLite | File-based | Minimal | Single-user apps, CLIs |
| PostgreSQL | Full | Database | Production, multi-user |

## Dependency Injection

All providers implement the same protocols. Swap with one line:

```python
# Development
memory = InMemoryMemoryProvider()

# Production
memory = PostgresMemoryProvider(session_factory)

# Your code uses protocols, not concrete classes:
async def save_user_fact(store: FactStore, user_id: str):
    await store.upsert_fact(user_id, "onboarded", "true")
```

## Data Types

The memory module uses these core data types (`cognitia.memory.types`):

| Type | Fields | Purpose |
|------|--------|---------|
| `MemoryMessage` | `role`, `content`, `tool_calls` | A single message in conversation history |
| `UserProfile` | `user_id`, `facts`, `created_at` | User identity with extracted facts |
| `GoalState` | `goal_id`, `title`, `target_amount`, `current_amount`, `phase`, `plan`, `is_main` | User goal tracking |
| `PhaseState` | `user_id`, `phase`, `notes` | Current conversation phase |
| `ToolEvent` | `topic_id`, `tool_name`, `input_json`, `output_json`, `latency_ms` | Tool usage audit entry |

## Summarization

Cognitia includes two summarizers for managing conversation history.

### TemplateSummaryGenerator

Zero-dependency, formats recent messages as a bullet list:

```python
from cognitia.memory.summarizer import TemplateSummaryGenerator
from cognitia.memory.types import MemoryMessage

summarizer = TemplateSummaryGenerator(max_messages=20, max_message_chars=200)

messages = [
    MemoryMessage(role="user", content="What's the weather?"),
    MemoryMessage(role="assistant", content="It's sunny today."),
]
summary = summarizer.summarize(messages)
# "- [user]: What's the weather?\n- [assistant]: It's sunny today."
```

### LlmSummaryGenerator

Uses an LLM call for richer summaries with automatic fallback to `TemplateSummaryGenerator` on error:

```python
from cognitia.memory.llm_summarizer import LlmSummaryGenerator

async def my_llm_call(prompt: str, text: str) -> str:
    # Your LLM integration here
    return await call_claude(prompt + "\n\n" + text)

summarizer = LlmSummaryGenerator(llm_call=my_llm_call)

# Sync (delegates to template fallback):
summary = summarizer.summarize(messages)

# Async (calls LLM, falls back on error):
summary = await summarizer.asummarize(messages)
```

If the LLM returns a response shorter than 50 characters or raises an exception, the template fallback is used automatically.

## Episodic Memory

*Introduced in v1.2.0.* Episodic memory stores structured records of past agent interactions -- what happened, which tools were used, what decisions were made, and whether the outcome was successful. The agent can later recall relevant episodes to inform future behavior.

### Episode Data Model

Each episode is a frozen dataclass (`cognitia.memory.episodic_types.Episode`):

| Field | Type | Purpose |
|-------|------|---------|
| `id` | `str` | Unique episode identifier |
| `summary` | `str` | Human-readable description of what happened |
| `key_decisions` | `tuple[str, ...]` | Decisions made during the interaction |
| `tools_used` | `tuple[str, ...]` | Tools invoked during the episode |
| `outcome` | `str` | Result: `"success"`, `"failure"`, or `"partial"` |
| `session_id` | `str` | Session that produced this episode |
| `timestamp` | `datetime` | When the episode occurred (UTC) |
| `tags` | `tuple[str, ...]` | Searchable tags for categorization |
| `metadata` | `dict[str, Any]` | Arbitrary extra data |

### EpisodicMemory Protocol

The `EpisodicMemory` protocol defines 5 methods (ISP-compliant):

| Method | Signature | Purpose |
|--------|-----------|---------|
| `store` | `(episode: Episode) -> None` | Store an episode |
| `recall` | `(query: str, *, top_k: int = 5) -> list[Episode]` | Semantic/keyword search |
| `recall_recent` | `(n: int = 10) -> list[Episode]` | Get N most recent episodes |
| `recall_by_tag` | `(tag: str) -> list[Episode]` | Filter by tag |
| `count` | `() -> int` | Total stored episodes |

### Storage Backends

| Backend | Class | Search | Best For |
|---------|-------|--------|----------|
| InMemory | `InMemoryEpisodicMemory` | Word overlap | Tests, development |
| SQLite | `SqliteEpisodicMemory` | FTS5 full-text | Single-user apps, CLIs |
| PostgreSQL | `PostgresEpisodicMemory` | tsvector full-text | Production, multi-user |

### Usage Examples

**Store and recall episodes (InMemory):**

```python
from cognitia.memory.episodic_types import Episode
from cognitia.memory.episodic import InMemoryEpisodicMemory

memory = InMemoryEpisodicMemory()

# Store an episode
episode = Episode(
    id="ep-001",
    summary="User asked to deploy app to staging. Used sandbox tool.",
    key_decisions=("chose blue-green deployment", "skipped canary"),
    tools_used=("sandbox", "web"),
    outcome="success",
    session_id="sess-42",
    tags=("deployment", "staging"),
)
await memory.store(episode)

# Recall by keyword search
results = await memory.recall("deployment staging", top_k=3)

# Recall recent episodes
recent = await memory.recall_recent(n=5)

# Recall by tag
deployments = await memory.recall_by_tag("deployment")
```

**SQLite backend with FTS5 search:**

```python
from cognitia.memory.episodic_sqlite import SqliteEpisodicMemory

memory = SqliteEpisodicMemory(db_path="./episodes.db")
# Tables and FTS5 index are created automatically on first use

await memory.store(episode)
results = await memory.recall("deploy staging")  # Uses FTS5 full-text search
```

**PostgreSQL backend:**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from cognitia.memory.episodic_postgres import PostgresEpisodicMemory

engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/db")
session_factory = async_sessionmaker(engine, expire_on_commit=False)

memory = PostgresEpisodicMemory(session_factory)
results = await memory.recall("deploy staging")  # Uses tsvector full-text search
```

PostgreSQL requires the `episodes` table. Schema is available as `POSTGRES_EPISODIC_SCHEMA` in the module.

## Procedural Memory

*Introduced in v1.2.0.* Procedural memory stores learned tool sequences -- multi-step patterns that the agent has used to accomplish tasks. When a similar task appears, the agent can recall proven procedures and apply them, improving over time through reinforcement.

### Data Model

**ProcedureStep** -- a single step in a learned procedure:

| Field | Type | Purpose |
|-------|------|---------|
| `tool_name` | `str` | Tool to invoke |
| `args_template` | `dict[str, str]` | Template for tool arguments |
| `expected_outcome` | `str` | What this step should produce |

**Procedure** -- a complete learned sequence:

| Field | Type | Purpose |
|-------|------|---------|
| `id` | `str` | Unique procedure identifier |
| `name` | `str` | Human-readable name |
| `description` | `str` | What this procedure does |
| `trigger` | `str` | When to suggest this procedure (task pattern) |
| `steps` | `tuple[ProcedureStep, ...]` | Ordered sequence of tool calls |
| `success_count` | `int` | Times this procedure succeeded |
| `failure_count` | `int` | Times this procedure failed |
| `tags` | `tuple[str, ...]` | Searchable tags |
| `metadata` | `dict[str, Any]` | Arbitrary extra data |

Computed properties: `total_uses` (success + failure count) and `success_rate` (0.0 to 1.0).

### ProceduralMemory Protocol

The `ProceduralMemory` protocol defines 5 methods (ISP-compliant):

| Method | Signature | Purpose |
|--------|-----------|---------|
| `store` | `(procedure: Procedure) -> None` | Store a learned procedure |
| `suggest` | `(query: str, *, top_k: int = 3) -> list[Procedure]` | Find procedures for a task |
| `record_outcome` | `(proc_id: str, *, success: bool) -> None` | Reinforce with success/failure |
| `get` | `(proc_id: str) -> Procedure \| None` | Get procedure by ID |
| `count` | `() -> int` | Total stored procedures |

### Storage Backends

| Backend | Class | Search | Best For |
|---------|-------|--------|----------|
| InMemory | `InMemoryProceduralMemory` | Word overlap + success rate | Tests, development |
| SQLite | `SqliteProceduralMemory` | FTS5 + success rate ranking | Single-user apps, CLIs |
| PostgreSQL | `PostgresProceduralMemory` | tsvector + success rate ranking | Production, multi-user |

### Usage Examples

**Define and store a procedure:**

```python
from cognitia.memory.procedural_types import Procedure, ProcedureStep
from cognitia.memory.procedural import InMemoryProceduralMemory

memory = InMemoryProceduralMemory()

# Define a learned procedure
deploy_proc = Procedure(
    id="proc-001",
    name="Deploy to staging",
    description="Full deployment pipeline for staging environment",
    trigger="deploy application to staging",
    steps=(
        ProcedureStep(
            tool_name="sandbox",
            args_template={"command": "run tests"},
            expected_outcome="All tests pass",
        ),
        ProcedureStep(
            tool_name="sandbox",
            args_template={"command": "build docker image"},
            expected_outcome="Image built successfully",
        ),
        ProcedureStep(
            tool_name="sandbox",
            args_template={"command": "deploy to staging"},
            expected_outcome="Deployment complete",
        ),
    ),
    tags=("deployment", "staging"),
)
await memory.store(deploy_proc)

# Suggest procedures for a task
suggestions = await memory.suggest("deploy app to staging", top_k=3)
# Returns procedures ranked by relevance + success rate

# Record outcome to improve future suggestions
await memory.record_outcome("proc-001", success=True)

# Check procedure stats
proc = await memory.get("proc-001")
print(f"Success rate: {proc.success_rate:.0%}")  # "Success rate: 100%"
```

**SQLite backend with FTS5:**

```python
from cognitia.memory.procedural_sqlite import SqliteProceduralMemory

memory = SqliteProceduralMemory(db_path="./procedures.db")
# Tables and FTS5 index created automatically

await memory.store(deploy_proc)
suggestions = await memory.suggest("deploy staging")
```

**PostgreSQL backend:**

```python
from cognitia.memory.procedural_postgres import PostgresProceduralMemory

memory = PostgresProceduralMemory(session_factory)
# Requires the `procedures` table — schema available as POSTGRES_PROCEDURAL_SCHEMA
```

### Reinforcement Learning

Procedural memory improves over time. Each `record_outcome` call updates the procedure's success/failure counters. When `suggest()` is called, results are ranked by a combination of text relevance and success rate -- procedures that work well float to the top.

## Memory Consolidation

*Introduced in v1.2.0.* The consolidation pipeline bridges episodic memory and long-term knowledge. It scans recent episodes, extracts recurring patterns, and stores them as facts -- turning raw experience into reusable knowledge.

### How It Works

1. **Recall** recent episodes from episodic memory
2. **Extract** patterns using a `FactExtractor` (keyword-based by default, or LLM-powered)
3. **Deduplicate** against previously stored facts
4. **Store** new facts in a fact store (if provided)

### Components

**FactExtractor** protocol -- pluggable pattern extraction:

```python
class FactExtractor(Protocol):
    async def extract(self, episodes: list[Episode]) -> list[str]: ...
```

**KeywordFactExtractor** -- built-in, zero-dependency extractor that finds patterns without an LLM:

- Counts keyword co-occurrences across episodes
- Identifies tools frequently used in successful tasks
- Detects tag-based success patterns (e.g., "Tasks tagged 'deployment' succeed 8/10 times")

**ConsolidationResult** -- returned after each consolidation run:

| Field | Type | Purpose |
|-------|------|---------|
| `new_facts` | `tuple[str, ...]` | Facts extracted in this run |
| `episodes_processed` | `int` | Number of episodes analyzed |
| `clusters_found` | `int` | Total patterns found (before dedup) |

### Usage Examples

**Basic consolidation (keyword-based):**

```python
from cognitia.memory.episodic import InMemoryEpisodicMemory
from cognitia.memory.episodic_types import Episode
from cognitia.memory.consolidation import ConsolidationPipeline

episodic = InMemoryEpisodicMemory()

# Store several episodes over time...
await episodic.store(Episode(
    id="ep-1", summary="Deployed to staging using sandbox",
    tools_used=("sandbox",), outcome="success", tags=("deployment",),
))
await episodic.store(Episode(
    id="ep-2", summary="Deployed to production using sandbox",
    tools_used=("sandbox",), outcome="success", tags=("deployment",),
))
await episodic.store(Episode(
    id="ep-3", summary="Ran data migration using sandbox",
    tools_used=("sandbox",), outcome="success", tags=("deployment",),
))

# Run consolidation
pipeline = ConsolidationPipeline(episodic=episodic)
result = await pipeline.consolidate(min_episodes=3, max_episodes=50)

print(result.new_facts)
# ("Tool 'sandbox' is frequently used in successful tasks",
#  "Tasks tagged 'deployment' succeed 3/3 times")
print(result.episodes_processed)  # 3
```

**With a fact store for persistence:**

```python
pipeline = ConsolidationPipeline(
    episodic=episodic,
    fact_store=my_fact_store,  # any object with async add_fact(user_id, fact)
)
result = await pipeline.consolidate()
# New facts are automatically stored in the fact store
```

**With a custom LLM-powered extractor:**

```python
from cognitia.memory.consolidation import FactExtractor

class LlmFactExtractor:
    """Extract facts using an LLM for richer semantic understanding."""

    async def extract(self, episodes: list[Episode]) -> list[str]:
        summaries = "\n".join(ep.summary for ep in episodes)
        # Call your LLM to extract patterns
        response = await call_llm(
            f"Extract recurring patterns from these episodes:\n{summaries}"
        )
        return response.split("\n")

pipeline = ConsolidationPipeline(
    episodic=episodic,
    extractor=LlmFactExtractor(),
)
```

### Consolidation Parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `min_episodes` | 3 | Minimum episodes required before consolidation runs |
| `max_episodes` | 50 | Maximum recent episodes to analyze per run |

If fewer than `min_episodes` are available, consolidation returns immediately with no facts extracted.

## Related: Memory Bank

For **long-term project memory** that persists across sessions (plans, decisions, progress logs), see [Memory Bank](memory-bank.md). Memory Bank is a separate capability with its own protocol and file-based API.
