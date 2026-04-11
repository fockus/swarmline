"""CLI Agent Runtime: run external CLI processes as swarmline runtimes.

Demonstrates: CliAgentRuntime, CliConfig, NdjsonParser, registry integration.
No API keys required (uses mock subprocess).
"""

import asyncio
import json

from swarmline.runtime.cli.parser import ClaudeNdjsonParser, GenericNdjsonParser
from swarmline.runtime.cli.types import CliConfig
from swarmline.runtime.registry import get_default_registry


async def main() -> None:
    # 1. CLI runtime is registered in the global registry
    print("=== Registry Integration ===")
    registry = get_default_registry()
    print(f"CLI registered: {registry.is_registered('cli')}")
    caps = registry.get_capabilities("cli")
    if caps:
        print(f"CLI tier: {caps.tier}")
        print(f"CLI flags: {caps.enabled_flags()}")

    # 2. CliConfig -- configure the CLI subprocess
    print("\n=== CliConfig ===")
    default_config = CliConfig(
        command=["claude", "--print", "--verbose", "--output-format", "stream-json", "-"]
    )
    print(f"Command: {default_config.command}")
    print(f"Timeout: {default_config.timeout_seconds}s")
    print(f"Max output: {default_config.max_output_bytes} bytes")

    custom_config = CliConfig(
        command=["my-agent", "--json"],
        timeout_seconds=60.0,
        max_output_bytes=1_000_000,
        env={"MY_API_KEY": "sk-xxx"},
    )
    print(f"\nCustom command: {custom_config.command}")

    # 3. NDJSON parsers
    print("\n=== ClaudeNdjsonParser ===")
    claude_parser = ClaudeNdjsonParser()

    # Simulate Claude NDJSON output lines
    claude_lines = [
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello!"}]}}),
        json.dumps({"type": "result", "result": "Done", "cost_usd": 0.01}),
    ]
    for line in claude_lines:
        event = claude_parser.parse_line(line)
        if event:
            print(f"  Parsed: type={event.type}, data={dict(list(event.data.items())[:2])}")
        else:
            print(f"  Skipped: {line[:50]}")

    print("\n=== GenericNdjsonParser ===")
    generic_parser = GenericNdjsonParser()

    # Generic NDJSON format
    generic_lines = [
        json.dumps({"type": "text", "content": "Thinking..."}),
        json.dumps({"type": "tool_call", "name": "search", "args": {"q": "python"}}),
        json.dumps({"type": "final", "text": "Here are the results."}),
    ]
    for line in generic_lines:
        event = generic_parser.parse_line(line)
        if event:
            print(f"  Parsed: type={event.type}")
        else:
            print("  Skipped (no matching type)")

    # Non-JSON lines are gracefully skipped
    event = generic_parser.parse_line("not json at all")
    print(f"  Non-JSON: {event}")

    # 4. Full runtime usage (requires CLI tool installed)
    print("\n=== Full Usage (requires CLI) ===")
    print("# from swarmline.runtime.cli.runtime import CliAgentRuntime")
    print("# from swarmline.runtime.types import RuntimeConfig, Message")
    print("#")
    print("# async with CliAgentRuntime(")
    print("#     config=RuntimeConfig(runtime_name='cli'),")
    print("#     cli_config=CliConfig(command=['claude', '--print', '--verbose', '--output-format', 'stream-json', '-']),")
    print("# ) as runtime:")
    print("#     async for event in runtime.run(")
    print("#         messages=[Message(role='user', content='Hello')],")
    print("#         system_prompt='You are helpful.',")
    print("#         active_tools=[],")
    print("#     ):")
    print("#         if event.is_text:")
    print("#             print(event.text, end='')")


if __name__ == "__main__":
    asyncio.run(main())
