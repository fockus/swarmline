"""JSON-RPC worker shim -- child process entry point.

Usage: python -m swarmline.plugins._worker_shim <module_path>

Reads JSON-RPC requests from stdin (one per line), dispatches to the
loaded module, writes JSON-RPC responses to stdout.

Built-in methods:
  __ping__     -> {"ok": true}
  __shutdown__ -> clean exit
"""

# NOTE: No `from __future__ import annotations` here.
# This module runs as __main__ in a subprocess and needs regular imports.

import asyncio
import importlib
import json
import sys


def _respond(response: dict) -> None:
    """Write a JSON-RPC response line to stdout and flush."""
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _error_response(request_id: str | None, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "id": request_id,
    }


def _success_response(request_id: str | None, result: object) -> dict:
    return {
        "jsonrpc": "2.0",
        "result": result,
        "id": request_id,
    }


def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: python -m swarmline.plugins._worker_shim <module_path>\n")
        sys.stderr.flush()
        sys.exit(1)

    module_path = sys.argv[1]

    try:
        plugin_module = importlib.import_module(module_path)
    except Exception as exc:
        sys.stderr.write(f"Failed to import plugin module {module_path!r}: {exc}\n")
        sys.stderr.flush()
        sys.exit(1)

    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            break

        if not line:
            # EOF — parent closed stdin
            break

        line = line.strip()
        if not line:
            continue

        request_id = None
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _respond(_error_response(None, -32700, f"Parse error: {exc}"))
            continue

        request_id = request.get("id")
        method = request.get("method")

        if not method:
            _respond(_error_response(request_id, -32600, "Invalid request: missing method"))
            continue

        # Built-in: ping
        if method == "__ping__":
            _respond(_success_response(request_id, {"ok": True}))
            continue

        # Built-in: shutdown
        if method == "__shutdown__":
            _respond(_success_response(request_id, {"ok": True}))
            sys.exit(0)

        # Dispatch to plugin module
        fn = getattr(plugin_module, method, None)
        if fn is None:
            _respond(_error_response(request_id, -32601, f"Method not found: {method}"))
            continue

        try:
            params = request.get("params") or {}
            result = fn(**params)
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            _respond(_success_response(request_id, result))
        except Exception as exc:
            _respond(_error_response(request_id, -32000, str(exc)))


if __name__ == "__main__":
    main()
