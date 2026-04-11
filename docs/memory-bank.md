# Memory Bank

Memory Bank is Swarmline's **long-term project memory** — a file-based knowledge store that persists across agent sessions. While the core [Memory](memory.md) module handles conversation-level data (messages, facts, goals), Memory Bank stores higher-level project knowledge: plans, decisions, lessons learned, and progress logs.

## How It Works

Memory Bank presents a **file-like API** to the agent — `read_file`, `write_file`, `list_files`, etc. Under the hood, the actual storage can be a filesystem directory or a database table. The agent interacts with the same 5 tools regardless of backend.

Data is isolated per **user_id + topic_id** pair, ensuring multi-tenant safety.

## Protocol

`MemoryBankProvider` follows ISP (≤5 methods):

```python
from swarmline.memory_bank.protocols import MemoryBankProvider

class MemoryBankProvider(Protocol):
    async def read_file(self, path: str) -> str | None: ...
    async def write_file(self, path: str, content: str) -> None: ...
    async def append_to_file(self, path: str, content: str) -> None: ...
    async def list_files(self, prefix: str = "") -> list[str]: ...
    async def delete_file(self, path: str) -> None: ...
```

All paths are **relative** with a maximum depth of 2 (e.g., `plans/feature.md`). Path traversal (`..`) is rejected.

## Providers

### FilesystemMemoryBankProvider

Stores files on disk under `{root}/{user_id}/{topic_id}/memory/`.

```python
from swarmline.memory_bank.fs_provider import FilesystemMemoryBankProvider
from swarmline.memory_bank.types import MemoryBankConfig

config = MemoryBankConfig(
    enabled=True,
    backend="filesystem",
    root_path=Path("./data/memory-banks"),
    max_file_size_bytes=100 * 1024,  # 100 KB per file
    max_total_size_bytes=1024 * 1024,  # 1 MB total
    max_depth=2,
)

provider = FilesystemMemoryBankProvider(config, user_id="user_1", topic_id="project_1")

# Write a file
await provider.write_file("STATUS.md", "# Status\nPhase: MVP")

# Read it back
content = await provider.read_file("STATUS.md")

# List all files
files = await provider.list_files()  # ["STATUS.md"]

# List files in a subfolder
plans = await provider.list_files(prefix="plans/")
```

Writes are **atomic** (write to `.tmp`, then `os.replace`). Subdirectories are created automatically.

**Best for:** local development, CLI agents, single-machine deployments.

### DatabaseMemoryBankProvider

Stores files as rows in a `memory_bank` SQL table via SQLAlchemy async. Works with both PostgreSQL and SQLite.

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from swarmline.memory_bank.db_provider import DatabaseMemoryBankProvider

engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/db")
session_factory = async_sessionmaker(engine, expire_on_commit=False)

provider = DatabaseMemoryBankProvider(
    session_factory=session_factory,
    user_id="user_1",
    topic_id="project_1",
)
```

**Schema setup** — use the DDL helper in your Alembic migration or startup:

```python
from swarmline.memory_bank.schema import get_memory_bank_ddl

# For PostgreSQL
statements = get_memory_bank_ddl(dialect="postgres")

# For SQLite
statements = get_memory_bank_ddl(dialect="sqlite")

# Execute in your migration
for stmt in statements:
    await session.execute(text(stmt))
```

The table schema:

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | TEXT | Tenant/user identifier |
| `topic_id` | TEXT | Project/conversation scope |
| `path` | TEXT | Virtual file path |
| `content` | TEXT | File content |
| `created_at` | TIMESTAMP | Creation time |
| `updated_at` | TIMESTAMP | Last modification |

Unique constraint on `(user_id, topic_id, path)` enables upsert semantics.

**Best for:** production multi-user deployments, cloud environments.

### Choosing a Provider

| Provider | Persistence | Multi-process safe | Best for |
|----------|-------------|-------------------|----------|
| Filesystem | Disk | No | Dev, CLI, single-process |
| Database | DB | Yes | Production, multi-tenant |

## Configuration

`MemoryBankConfig` controls limits and behavior:

```python
from swarmline.memory_bank.types import MemoryBankConfig

config = MemoryBankConfig(
    enabled=True,                         # Master toggle
    backend="filesystem",                 # "filesystem" or "database"
    root_path=Path("./data"),             # FS root (filesystem backend only)
    max_file_size_bytes=100 * 1024,       # 100 KB per file
    max_total_size_bytes=1024 * 1024,     # 1 MB total bank size
    max_entries=200,                      # Max files in the bank
    max_depth=2,                          # Max path depth (root/subfolder/file)
    retention_days=None,                  # Auto-cleanup (None = keep forever)
    auto_load_on_turn=True,              # Auto-inject MEMORY.md into context
    auto_load_max_lines=200,             # Truncate auto-loaded content
    default_folders=["plans", "reports", "notes"],
)
```

## Connecting Memory Bank to an Agent

Memory Bank integrates via `SwarmlineStack.create()` — pass the provider and an optional prompt:

```python
from swarmline.bootstrap.stack import SwarmlineStack
from swarmline.memory_bank.fs_provider import FilesystemMemoryBankProvider
from swarmline.memory_bank.types import MemoryBankConfig

# 1. Create provider
mb_config = MemoryBankConfig(enabled=True, root_path=Path("./data/mb"))
mb_provider = FilesystemMemoryBankProvider(mb_config, user_id="u1", topic_id="proj1")

# 2. Wire into agent stack
stack = SwarmlineStack.create(
    # ... other params ...
    memory_bank_provider=mb_provider,
    # Optional: custom prompt injected into system message
    memory_bank_prompt="You have a Memory Bank. Use memory_* tools to persist knowledge.",
)
```

When `memory_bank_provider` is set:

1. **5 tools** are automatically registered: `memory_read`, `memory_write`, `memory_append`, `memory_list`, `memory_delete`
2. A **Memory Bank prompt** (P_MEMORY layer) is injected into the system prompt between the role and goal sections
3. If `auto_load_on_turn` is enabled, `MEMORY.md` content is auto-loaded into context each turn

## Agent Tools Reference

The agent receives 5 tools via `create_memory_bank_tools()`:

| Tool | Parameters | Description |
|------|-----------|-------------|
| `memory_read` | `path` (required) | Read a file from the bank. Returns `{status, content}` or `{status: "not_found"}` |
| `memory_write` | `path`, `content` (required) | Write/overwrite a file. Creates subdirectories as needed |
| `memory_append` | `path`, `content` (required) | Append content to the end of a file (creates if missing) |
| `memory_list` | `prefix` (optional) | List files, optionally filtered by path prefix |
| `memory_delete` | `path` (required) | Delete a file. No-op if it doesn't exist |

All tools return JSON: `{"status": "ok", ...}` on success, `{"status": "error", "message": "..."}` on failure.

## Path Validation & Security

Paths are validated by `validate_memory_path()`:

- Must be **non-empty** and **relative** (no leading `/`)
- **No path traversal** (`..` segments are rejected)
- **Depth limit** enforced (default: 2 levels — e.g., `plans/feature.md` is OK, `a/b/c.md` is rejected)
- Filesystem provider additionally checks `is_relative_to` against the resolved base path

Violations raise `MemoryBankViolation`.

## Example: Agent with Persistent Knowledge

```python
from pathlib import Path
from swarmline.memory_bank.fs_provider import FilesystemMemoryBankProvider
from swarmline.memory_bank.types import MemoryBankConfig

# Setup
config = MemoryBankConfig(enabled=True, root_path=Path("./data/mb"))
mb = FilesystemMemoryBankProvider(config, user_id="alice", topic_id="my-project")

# Session 1: Agent learns about the project
await mb.write_file("MEMORY.md", "# Project Memory\n- [status](notes/status.md)")
await mb.write_file("notes/status.md", "Phase: MVP. DB: PostgreSQL. Deploy: Docker.")

# Session 2: Agent reads previous knowledge
index = await mb.read_file("MEMORY.md")
# "# Project Memory\n- [status](notes/status.md)"

status = await mb.read_file("notes/status.md")
# "Phase: MVP. DB: PostgreSQL. Deploy: Docker."

# Agent appends a progress entry
await mb.append_to_file("progress.md", "\n## 2026-03-15\n- Added user auth module")

# List everything
files = await mb.list_files()
# ["MEMORY.md", "notes/status.md", "progress.md"]
```

## Memory vs Memory Bank

| Aspect | Memory (core) | Memory Bank |
|--------|--------------|-------------|
| **Scope** | Conversation-level | Project-level |
| **Data** | Messages, facts, goals, summaries | Plans, notes, progress, decisions |
| **Lifetime** | Per conversation/session | Across all sessions |
| **Protocols** | 8 ISP protocols (MessageStore, FactStore, ...) | 1 protocol (MemoryBankProvider) |
| **Providers** | InMemory, SQLite, PostgreSQL | Filesystem, Database |
| **Agent tools** | Accessed by runtime internally | 5 explicit `memory_*` tools |
