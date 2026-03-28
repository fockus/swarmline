# OpenAI Codex

Use Codex tools for autonomous code generation and editing tasks.

## Available Tools

- `codex` — Start a new Codex session. Parameters:
  - `prompt` (required): Task description
  - `sandbox` (optional): "network-off" (default) or "network-on"
  - `approval-policy` (optional): "suggest" (default), "auto-edit", or "full-auto"
- `codex-reply` — Continue an existing session. Parameters:
  - `threadId` (required): ID from previous codex call
  - `prompt` (required): Follow-up instruction

## Usage Pattern

1. Start with `codex` tool for the initial task
2. Use `codex-reply` with the returned `threadId` for follow-ups
3. Each session maintains file context and conversation history

## Guidelines

- Use `approval-policy: "full-auto"` for trusted automated workflows
- Use `sandbox: "network-off"` (default) for security
- Codex works best with specific, well-scoped coding tasks
- For multi-step tasks, use `codex-reply` to iterate within the same session
