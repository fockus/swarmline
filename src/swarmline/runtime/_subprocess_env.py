"""Shared helper for building subprocess env from an allowlist.

Used by `runtime/cli` and `runtime/pi_sdk` to apply identical secure-by-default
env handling: child processes only receive vars explicitly listed in
``env_allowlist`` (plus operator-supplied ``overrides``), unless the operator
opts into ``inherit_host_env=True`` for legacy parity.

Closes audit finding P1 #2 (Stage 2 of plans/2026-04-27_fix_security-audit.md):
the pi_sdk Node bridge previously inherited the full host env, leaking
``OPENAI_API_KEY``, AWS creds, CI tokens, etc. to ``@mariozechner/pi-coding-agent``
or any malicious replacement.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping


def build_subprocess_env(
    *,
    inherit_host_env: bool,
    env_allowlist: Iterable[str],
    overrides: Mapping[str, str],
) -> dict[str, str]:
    """Build a subprocess env dict, secure-by-default.

    - When ``inherit_host_env`` is False (default), only keys in
      ``env_allowlist`` are forwarded from ``os.environ``. Keys not present
      in the host env are silently skipped.
    - When ``inherit_host_env`` is True, the full host env is forwarded
      (legacy behavior, opt-in only).
    - ``overrides`` are applied last and always win (operator-supplied
      explicit values).
    """
    if inherit_host_env:
        env = dict(os.environ)
    else:
        allow = set(env_allowlist)
        env = {key: value for key, value in os.environ.items() if key in allow}
    env.update(overrides)
    return env
