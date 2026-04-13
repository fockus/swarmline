# Phase 11: Foundation Filters — Context

## Goal

Agents automatically receive project-specific instructions and dynamic context reminders without any modification to ThinRuntime.run(), using the existing InputFilter pipeline.

## Requirements

- **INST-01**: ThinRuntime автоматически загружает instruction files из cwd -> parent dirs -> home directory
- **INST-02**: Поддержка нескольких форматов: CLAUDE.md, AGENTS.md, GEMINI.md, RULES.md (multi-agent universal)
- **INST-03**: Приоритет загрузки: RULES.md > CLAUDE.md > AGENTS.md > GEMINI.md (первый найденный на каждом уровне)
- **INST-04**: Merge стратегия: home (lowest) -> parent dirs -> project root (highest priority)
- **INST-05**: Инжект через существующий InputFilter pipeline без модификации run()
- **RMND-01**: Conditional context блоки инжектируются в messages по trigger conditions
- **RMND-02**: Reminder budget ограничен (max 500 tokens) для предотвращения prompt bloat
- **RMND-03**: Priority ordering: при бюджетном pressure высокоприоритетные reminders сохраняются
- **RMND-04**: Реализация через InputFilter без модификации ThinRuntime.run()

## Integration Points

### InputFilter Protocol
- **Location**: `src/swarmline/input_filters.py:16-24`
- **Interface**: `async def filter(self, messages: list[Message], system_prompt: str) -> tuple[list[Message], str]`
- **Existing implementations**: MaxTokensFilter, SystemPromptInjector, RagInputFilter

### ThinRuntime InputFilter wiring
- **Location**: `src/swarmline/runtime/thin/runtime.py:285-288`
- **Pipeline**: Sequential filter chain, output of one feeds into the next
- **Position**: After input guardrails, before mode detection (conversational/react/planner)

### RuntimeConfig
- **Location**: `src/swarmline/runtime/types.py:167`
- **Field**: `input_filters: list[Any] = field(default_factory=list)`

### Message type
- **Location**: `src/swarmline/domain_types.py`
- **Fields**: role, content, name, tool_calls, metadata

## Design Decisions

### ProjectInstructionFilter
- Walk-up discovery: start at cwd, walk to root, then check home (~)
- At each directory level, check for files in priority order: RULES.md > CLAUDE.md > AGENTS.md > GEMINI.md
- First found at each level wins (one file per directory level)
- Merge: concatenate all found contents, project root (cwd) content last (highest priority = last = overrides)
- Inject as system_prompt prepend (before existing system prompt content)
- Cache: stat() mtime-based to avoid re-reading on every filter call
- No new dependencies

### SystemReminderFilter
- Reminder = {id, content, trigger, priority, token_budget_estimate}
- Trigger: callable that receives (messages, system_prompt) -> bool
- Budget: sum of selected reminders <= 500 tokens (char heuristic: ~4 chars/token)
- Priority ordering: when over budget, keep highest priority reminders
- Inject: append matching reminders to system_prompt as `<system-reminder>` blocks
- Reminders configured via RuntimeConfig or dedicated config field

## Risks / Gray Areas

1. **File encoding**: UTF-8 assumed. Non-UTF-8 files should be skipped with warning (log)
2. **Symlink security**: Don't follow symlinks outside project tree (like skills/loader.py pattern)
3. **Empty files**: Skip silently
4. **Token estimation**: char_count / 4 is sufficient (no tiktoken dependency per Out of Scope)
5. **Reminder trigger evaluation order**: evaluate all triggers, collect matching, then budget-sort by priority

## Complexity Assessment

LOW — both features are pure InputFilter implementations. No changes to ThinRuntime.run(), no new protocols needed (InputFilter already exists), no new dependencies.
