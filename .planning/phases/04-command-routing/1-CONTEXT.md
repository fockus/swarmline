# Phase 4: Command Routing — Context

## Goal

Users can type /commands that are intercepted and handled before reaching the LLM, providing instant responses for registered commands.

## Requirements

- **CMDR-01**: A /command in user input is intercepted and executed via CommandRegistry without calling the LLM
- **CMDR-02**: Non-command text passes through to the LLM unmodified
- **CMDR-03**: Without a CommandRegistry configured, all input passes through unchanged (backward compatibility)
- **CMDR-04**: Command routing happens after UserPromptSubmit hooks (hooks can transform the prompt before command check)

## Existing Infrastructure

### CommandRegistry (`src/swarmline/commands/registry.py`)
- Full implementation: `add()`, `resolve()`, `execute()`, `parse_command()`, `is_command()`
- `is_command(text)` — checks if text starts with `/`
- `parse_command(text)` — splits into `(name, args)`
- `execute(name, args)` — runs handler, returns string result
- Already exported from `swarmline.commands`

### ThinRuntime.run() pipeline (`src/swarmline/runtime/thin/runtime.py`)
Current order in `run()`:
1. Cancellation check
2. Budget check
3. Extract user text
4. **Subagent tool append**
5. **UserPromptSubmit hook** ← command intercept goes AFTER this
6. Input guardrails
7. Input filters
8. Mode detection
9. Strategy execution (conversational/react/planner)
10. Stop hook in finally

### AgentConfig (`src/swarmline/agent/config.py`)
- Frozen dataclass, all new fields must be optional with None default
- Existing pattern: `tool_policy: DefaultToolPolicy | None = None`, `subagent_config: SubagentToolConfig | None = None`

### AgentConfig → ThinRuntime wiring (`src/swarmline/agent/runtime_wiring.py`)
- `build_portable_runtime_plan()` converts AgentConfig fields to `create_kwargs` dict
- Pattern: `if config.field is not None: create_kwargs["field"] = config.field`

## Design Decision

**ADR: CommandInterceptor as a standalone function, not a class**

CommandRegistry already has all the logic. The interceptor is simply:
1. Check if user_text starts with `/`
2. If yes and registry exists: parse + execute → return result as RuntimeEvent.final
3. If no: pass through

This is a ~15-line function, not worth a class. Injected into ThinRuntime via `command_registry` constructor arg.

## Scope

- 1 new function: `intercept_command()` in `runtime.py` or small helper
- Modify `ThinRuntime.__init__` to accept `command_registry`
- Modify `ThinRuntime.run()` to intercept after UserPromptSubmit hook
- Modify `AgentConfig` to add `command_registry` field
- Modify `runtime_wiring.py` to pass through
- ~10 tests (unit + integration)
