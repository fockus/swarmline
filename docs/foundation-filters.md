# Foundation filters

Swarmline 1.5.0 adds two input filters that automate context-injection patterns
made popular by Claude Code:

1. **`ProjectInstructionFilter`** — auto-loads `CLAUDE.md`, `AGENTS.md`,
   `RULES.md`, `GEMINI.md` from the working directory upward (and from the
   user home).
2. **`SystemReminderFilter`** — injects dynamic system reminders into the
   prompt before each turn.

Both implement the `InputFilter` protocol — they plug into ThinRuntime via
`RuntimeConfig.input_filters` and require **zero changes** to runtime code.

## `ProjectInstructionFilter`

### What it does

On every turn, the filter walks up from `cwd` to the filesystem root, looking
for instruction files at each directory level. It also checks the user's home
directory. All discovered content is merged and prepended to the system prompt.

### File precedence (per directory)

If multiple instruction files exist at the same level, they are loaded in this
order (later wins on conflicts):

1. `AGENTS.md`
2. `RULES.md`
3. `CLAUDE.md`
4. `GEMINI.md`

This matches the convention you see in projects that target multiple agentic
tools — `CLAUDE.md` is the canonical Claude Code file, `AGENTS.md` for Codex,
`RULES.md` for project-wide rules, `GEMINI.md` for Gemini CLI.

### Walk-up merge order

Outer parents have **lower** priority; cwd has the **highest**. The merge order
when calling `filter()` is:

```
home (lowest) → outermost ancestor → ... → parent of cwd → cwd (highest) → original system_prompt
```

So a project-local `CLAUDE.md` overrides anything in `~/CLAUDE.md` because it
appears later in the merged prompt.

Symlinks are skipped to prevent loops.

### Caching

File content is cached by `(path, mtime)`. A re-read happens only when the file
changes on disk, so the per-turn overhead is essentially the cost of `os.stat()`
for each candidate path.

### Usage

```python
from swarmline import ProjectInstructionFilter
from swarmline.runtime.types import RuntimeConfig

config = RuntimeConfig(
    model="sonnet",
    input_filters=(ProjectInstructionFilter(),),
)
```

You can also pin the directories explicitly (useful in tests):

```python
ProjectInstructionFilter(
    cwd="/path/to/project",
    home="/path/to/test-home",
)
```

### Example

Project layout:

```
/Users/anton/Apps/swarmline/
├── CLAUDE.md          ← high-priority project rules
├── src/
└── ...

/Users/anton/CLAUDE.md ← user-wide rules
```

When you launch an agent from `/Users/anton/Apps/swarmline/src/`, the filter
prepends to the system prompt (in this order):

1. `~/CLAUDE.md` content (lowest priority).
2. `/Users/anton/Apps/swarmline/CLAUDE.md` content (project — highest priority).
3. The `system_prompt` you actually configured on `AgentConfig`.

The model sees one merged system prompt and treats the lower-priority blocks
as base context that the higher-priority blocks may override.

### When to use it

- You ship a project-aware Swarmline-based CLI and want it to honour the
  user's existing `CLAUDE.md` / `AGENTS.md`.
- You build a coding-agent product where users expect "drop in a `CLAUDE.md`,
  see your changes" semantics.
- You want a quick way for users to give the agent stable, persistent
  guidance without modifying the system prompt your code passes in.

### When **not** to use it

- Headless service deployments where the agent should never read the
  filesystem outside its working directory — the filter walks all the way to
  the filesystem root.
- Tests of business logic — pin `cwd` and `home` to fixtures, or omit the
  filter entirely.

## `SystemReminderFilter`

### What it does

Injects priority-ordered, conditionally-active `<system-reminder>` blocks into
the system prompt under a token budget. Useful for:

- Time-sensitive context ("Today is 2026-04-25").
- Stateful reminders that activate only when a predicate fires
  ("Last action failed; remind the model to be careful").
- Cross-cutting policy reinforcement ("Never run `rm -rf` without confirming").

A reminder is a `SystemReminder` dataclass with an `id`, `content`, optional
`priority`, optional `trigger` predicate, and optional `token_estimate`. The
filter evaluates triggers per turn, sorts active reminders by priority, and
selects as many as fit under `budget_tokens`. The highest-priority reminder is
always included even if it alone exceeds the budget (no silent no-op).

### Usage

```python
from swarmline.system_reminder_filter import (
    SystemReminderFilter,
    SystemReminder,
)
from swarmline.runtime.types import RuntimeConfig

reminders = [
    SystemReminder(
        id="never-rm-rf",
        content="Never call `rm -rf` without an explicit user confirmation.",
        priority=100,
    ),
    SystemReminder(
        id="failing-tests",
        content="Tests are currently red. Be careful when editing src/.",
        priority=50,
        trigger=lambda messages, system_prompt: any(
            "tests are red" in m.content for m in messages if m.role == "user"
        ),
    ),
]

config = RuntimeConfig(
    model="sonnet",
    input_filters=(SystemReminderFilter(reminders=reminders, budget_tokens=500),),
)
```

The filter formats each selected reminder as
`<system-reminder id="...">\n<content>\n</system-reminder>` and appends it to
the system prompt — the model treats it as ambient context rather than user
input.

## Combining the two

Filters compose: pass them as a tuple. Order matters — earlier filters run first
and their outputs are visible to later filters.

```python
from swarmline import ProjectInstructionFilter
from swarmline.system_reminder_filter import SystemReminderFilter, SystemReminder
from swarmline.runtime.types import RuntimeConfig

config = RuntimeConfig(
    model="sonnet",
    input_filters=(
        ProjectInstructionFilter(),                            # 1. inject project rules
        SystemReminderFilter(reminders=[                       # 2. ambient reminders
            SystemReminder(id="be-precise", content="Cite file:line for any code claim.", priority=10),
        ]),
    ),
)
```

The merged prompt the model sees:

```
<reminder text>

<merged CLAUDE.md / AGENTS.md content>

<your original system_prompt>
```

## Performance

- `ProjectInstructionFilter` does an `os.stat()` per candidate path per turn,
  but only re-reads on `mtime` change. For a project of 5 ancestor directories
  with 4 candidate filenames each, that's 20 stat calls per turn — fast enough
  to be invisible.
- `SystemReminderFilter` cost is dominated by your `trigger` predicates. Keep
  them pure and fast — they run on every turn.

## See also

- `src/swarmline/project_instruction_filter.py` — full source, including
  walk-up algorithm and home handling.
- `src/swarmline/system_reminder_filter.py` — `SystemReminderFilter` and
  `SystemReminder` dataclass.
- `swarmline.runtime.types.RuntimeConfig.input_filters` — protocol contract.
- `CHANGELOG.md` `[1.5.0]` Phase 11 entry.
