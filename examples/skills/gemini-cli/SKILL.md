---
name: gemini-cli
description: "Code generation and analysis via Google Gemini CLI"
allowed-tools:
  - mcp__gemini__gemini
mcp-servers:
  - name: gemini
    transport: stdio
    command: gemini
    args: ["--output", "json"]
intents: [gemini, google-code]
---

# Google Gemini CLI

Use Gemini CLI for code generation and analysis tasks powered by Google's Gemini models.

## Available Tools

- `gemini` — Execute a Gemini CLI task with JSON output

## Guidelines

- Gemini CLI must be installed: `npm install -g @google/gemini-cli`
- Set `GOOGLE_API_KEY` or `GEMINI_API_KEY` environment variable
- Best for: code review, refactoring suggestions, documentation generation
- JSON output mode provides structured responses parseable by Cognitia
