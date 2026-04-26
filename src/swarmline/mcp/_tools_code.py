"""Unsafe host code execution tool for the Swarmline MCP server.

This helper runs Python code in a subprocess on the host. It is not a sandbox
and must only be exposed to explicitly trusted callers.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any

import structlog

from swarmline.observability.security import log_security_decision

logger = structlog.get_logger(__name__)


async def exec_code(
    code: str, timeout_seconds: int = 30, *, trusted: bool = False
) -> dict[str, Any]:
    """Execute Python code on the host and return stdout/stderr.

    Parameters
    ----------
    code:
        Python code to execute.
    timeout_seconds:
        Maximum execution time in seconds.
    trusted:
        Must be ``True`` to allow host execution. Defaults to ``False``.

    This helper is intentionally unsafe host execution even when enabled.
    The only built-in controls are the explicit trusted gate, restricted
    environment, timeout enforcement, and temporary working directory.
    """
    if not trusted:
        log_security_decision(
            logger,
            component="mcp._tools_code",
            event_name="security.host_execution_denied",
            reason="trusted_flag_required",
            target="exec_code",
        )
        return {
            "ok": False,
            "error": (
                "Host execution requires trusted=True. "
                "This helper runs Python code on the host."
            ),
        }

    # Restricted environment — inherit PATH (for pyenv etc.) but strip secrets
    _secret_prefixes = (
        "AWS_",
        "AZURE_",
        "GCP_",
        "OPENAI_",
        "ANTHROPIC_",
        "API_KEY",
        "SECRET",
        "TOKEN",
        "PASSWORD",
    )
    safe_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
        "HOME": tempfile.gettempdir(),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
    }
    # Explicitly exclude secret-bearing env vars
    for key in os.environ:
        upper = key.upper()
        if any(upper.startswith(p) or upper.endswith(p) for p in _secret_prefixes):
            safe_env.pop(key, None)

    try:
        process = await asyncio.create_subprocess_exec(
            "python",
            "-c",
            code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=safe_env,
            cwd=tempfile.gettempdir(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {
                "ok": False,
                "error": f"Execution timed out after {timeout_seconds}s",
                "data": {"timeout": True},
            }

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        if process.returncode == 0:
            return {
                "ok": True,
                "data": {
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "returncode": 0,
                },
            }
        else:
            return {
                "ok": False,
                "error": stderr_str or f"Process exited with code {process.returncode}",
                "data": {
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "returncode": process.returncode,
                },
            }
    except Exception as exc:
        logger.warning("host_exec_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}
