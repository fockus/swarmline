# Security Audit Report — swarmline v1.5.0 (Full Framework Review)

Date: 2026-04-27
Scope: Full src/swarmline/ + tests/ codebase (387 .py files, ~75k LOC)
Reviewer: Security Engineer subagent
Prior audits referenced: 2026-04-27_review_post-v1.5.0-security-audit-closure.md, 2026-04-25_audit-security.md

## Executive Summary

- **Total findings: 18** (Critical: 0 / High: 5 / Medium: 11 / Low: 2)
- **Recommendation: fix-then-ship** — no PyPI-blocking criticals, but **H1 (timing attack)** and **H4 (git argv injection)** should land in v1.5.1 within 1-2 weeks. H3, H5, H6 are risk-management decisions (dependency floors, log redaction).
- **Top 3 risks:**
  1. **H1**: `serve/app.py` uses `==` instead of `hmac.compare_digest` for bearer auth → remote timing oracle exposes token prefix.
  2. **H4**: `WorktreeOrchestrator` passes `target_branch` and orphan paths into `git` argv without validation → `--upload-pack=evil` argv injection if these come from operator config.
  3. **H3**: `logger.error(..., exc_info=True)` in thin LLM client emits raw exception traces — bypasses `redact_secrets`. Provider exception messages with API keys / URLs reach disk.
- **Top 3 strengths:**
  1. **No `eval`/`exec`/`pickle`/`yaml.unsafe_load`/`shell=True`** anywhere in src/. (Verified across 387 files.)
  2. SQL composition uses static WHERE clauses with `?` / `:param` placeholders — no SQL injection vectors found in `memory/sqlite.py`, `memory/postgres.py`, `multi_agent/*_postgres.py`, `observability/activity_log.py`, `orchestration/plan_store.py`.
  3. Two of three control-plane HTTP servers (`a2a/server.py`, `daemon/health.py`) **do** use `hmac.compare_digest` correctly — the timing-attack pattern is local to `serve/app.py` only.

---

## Critical (PyPI-blocking)

_None._

The post-v1.5.0 audit-closure work (commit `395acb2`) closed the prior C1 ReDoS, C2/C3 version drift, and C4 docs drift. No new critical regressions have been introduced.

---

## High (must-fix before v1.5.1)

### H1. Timing attack in `serve/app.py` bearer auth comparison
- **File:** `src/swarmline/serve/app.py:41`
- **Code:** `if auth != f"Bearer {self.token}":`
- **Risk:** Remote timing oracle. Standard string `!=` short-circuits on first differing byte; an attacker can use response-time differential to recover the token prefix byte-by-byte. `auth_token` length and entropy may be high (mitigation), but no excuse — both sister servers (`a2a/server.py:107`, `daemon/health.py:133`) already use `hmac.compare_digest` for the identical pattern. **Likelihood: low (requires statistical sampling over network jitter); impact: full auth bypass once token recovered.** CVSS-like: 5.9 (AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:N).
- **Reproduction class:** Standard timing-oracle pattern against non-constant-time string comparison. Statistical sampling of response latency across token-prefix variations enables observation of matching prefix bytes over enough samples. Mitigated entirely by switching to constant-time comparison.
- **Fix:**
  ```python
  import hmac
  expected = f"Bearer {self.token}".encode()
  if not hmac.compare_digest(auth.encode(), expected):
      ...
  ```
  Match the pattern already used in `daemon/health.py:133` and `a2a/server.py:107`.
- **CWE:** CWE-208 (Observable Timing Discrepancy)

### H2. Stack trace leakage via `exc_info=True` bypasses `redact_secrets`
- **File:** `src/swarmline/runtime/thin/llm_client.py:161, 195, 215` (also `runtime/cli/runtime.py:263` via `logger.exception`)
- **Code:** `logger.error("LLM API error (%s)", resolved.provider, exc_info=True)`
- **Risk:** `provider_runtime_crash(...)` properly redacts the user-visible error event message, but the **logger.error with `exc_info=True`** emits the full exception object's stringification + traceback to the logging handler — bypassing `redact_secrets`. If anthropic/openai SDK exceptions embed Bearer tokens, sk-* keys, or URL userinfo in their `__str__` (anthropic SDK has historically included raw HTTP request URLs with tokens in `BadRequestError`), those reach disk in the `*.log` file. **Likelihood: medium (depends on what each provider SDK leaks); impact: secret-in-log forever.** CVSS-like: 6.5 (AV:L/AC:L/PR:H/UI:N/S:U/C:H/I:N/A:N).
- **Reproduction class:** Trigger any provider SDK error path that returns the request URL or auth header in the exception's stringification. Standard logging then renders the traceback verbatim into the log sink, where the credential surface is captured by downstream log aggregation. Mitigated by routing all exception rendering through the existing redaction layer.
- **Fix:** Wrap `exc_info` formatting via a structlog processor that runs `redact_secrets` over the rendered traceback string, or replace `exc_info=True` with `error=redact_secrets(str(exc))`. Add a structlog processor `redact_processor` to the global structlog config so all sinks benefit.
- **CWE:** CWE-209 (Information Exposure Through Error Messages), CWE-532 (Insertion of Sensitive Information into Log File)

### H3. `logger.error(..., exc_info=True)` in CLI startup-failure path
- **File:** `src/swarmline/runtime/cli/runtime.py:262-268`
- **Code:** `logger.exception("CliAgentRuntime.run() failed")` followed by a generic `RuntimeEvent.error` with no message detail.
- **Risk:** Same class as H2 — the user-facing event is properly redacted (or generic), but the logger emits the full `OSError`/`PermissionError`/`FileNotFoundError` traceback that may include the subprocess argv (which can contain sensitive paths) or stderr buffer. No `redact_secrets` applied to the logged exception.
- **Note:** This is the same **pattern** as N5 in the prior backlog (subprocess startup-failure redaction) but at a different code path — N5 was flagged as redaction inconsistency between exit-failure (line 248, redacted) vs startup-failure (line 262, not redacted). H3 widens the scope: `exc_info` in standard logging also bypasses redaction.
- **Fix:** Same as H2 — apply structlog redaction processor globally OR replace `logger.exception` with `logger.error("...", error=redact_secrets(str(exc)))`.
- **CWE:** CWE-532

### H4. WorktreeOrchestrator git argv injection via unvalidated `target_branch` / orphan paths
- **File:** `src/swarmline/multi_agent/worktree_orchestrator.py:87-95, 169-180`
- **Code:** `asyncio.create_subprocess_exec("git", "-C", handle.path, "merge", target_branch, ...)` and analogous `git worktree remove path ...` invocation.
- **Risk:** `create_subprocess_exec` is shell-safe (no `/bin/sh`), but **`git` itself accepts long-form options as positional arguments** when those options begin with `-`. If the `target_branch` parameter or orphan path starts with a leading `-`, git interprets it as an option name rather than a ref/path, which can chain into git's own subprocess-spawning options on a subsequent network operation. Same shape applies to `path` in `git worktree remove path` if path begins with `-`.

  Trust scenario: when `target_branch` or path values flow from operator-trusted config, the surface is bounded. When those values flow from external sources (multi-tenant deployment, A2A handoff, plugin manifest), an external party can choose values that begin with `-` and steer git's argument parser away from the intended ref/path semantics.
- **Severity:** **High** if `target_branch` / `cleanup_orphans` paths can flow from any non-operator source (multi-tenant deployment, A2A handoff, plugin config). Caller-trust dependent.
- **Fix:** Validate refs and paths before passing to git via a bounded character allowlist regex (`^(?!-)[a-zA-Z0-9._/-]{1,255}$`) that rejects values starting with `-`. Additionally, prefix paths with the `--` end-of-options separator before positional args (`git merge -- "$branch"`) so git stops parsing options after the separator.
- **CWE:** CWE-88 (Argument Injection or Modification), CWE-77 (Command Injection)

### H5. `langchain-core>=1.2.18` accepts CVE-2026-40087
- **File:** `pyproject.toml:82`
- **Code:** `"langchain-core>=1.2.18"`
- **Risk:** CVE-2026-40087 affects `langchain-core` < 1.2.28 (per pip-audit). swarmline's optional `[deepagents]` extra accepts the vulnerable range. New users running `pip install swarmline[deepagents]` against a stale local cache may install pinned versions in 1.2.18-1.2.27 range with the CVE.
- **Severity:** **Medium-to-high** depending on the CVE class (langchain-core 1.2.x has had RCE-class issues via prompt injection). Not exploited by swarmline's own code, but transmitted to users via the extras.
- **Fix:** Bump floor: `"langchain-core>=1.2.28"`. Same audit applied to:
  - `anthropic>=0.86` (CVE-2026-34450, CVE-2026-34452 fixed in 0.87.0) — bump to `>=0.87.0`
  - Optional but consider: `httpx>=0.28` (no current CVE flagged), `pydantic>=2.11` (no current CVE).
- **CWE:** CWE-1395 (Dependency on Vulnerable Third-Party Component)

---

## Medium (deferred — fix in v1.5.1 or v1.6.0)

### M1. CORS configuration parameter is silently no-op
- **File:** `src/swarmline/serve/app.py:148`
- **Code:** `cors_origins: list[str] | None = None,` accepted in `create_app`, never wired to Starlette `CORSMiddleware`.
- **Risk:** Operator believes CORS is configured per the API surface. In practice, browser CORS defaults apply (same-origin only by default — actually safer than misconfigured `*`). But misleading API contract = potential future regression. **Severity: Medium (UX/API integrity).**
- **Fix:** Either implement: `from starlette.middleware.cors import CORSMiddleware; middleware.append(Middleware(CORSMiddleware, allow_origins=cors_origins or []))`, or remove the parameter entirely and document operator-side CORS handling.
- **CWE:** CWE-942 (Permissive CORS) latent — currently safe, but parameter-pretending misleads.

### M2. DNS rebinding window in `validate_http_endpoint_url`
- **File:** `src/swarmline/network_safety.py:68-82`
- **Risk:** TOCTOU — first DNS resolution at validation time returns public IP (passes); second resolution during actual HTTP fetch returns 169.254.169.254 (cloud metadata) or 127.0.0.1 (loopback). Standard SSRF defense gap in any HTTP client that resolves twice. The post-validation httpx call goes through urllib3, which re-resolves DNS without re-validation.
- **Severity: Medium** — common gap in non-pinned-resolver SSRF defenses.
- **Fix:** Pin the resolved IP via custom `httpx.AsyncHTTPTransport` that overrides DNS with the pre-validated address, or re-validate inside a transport hook. At minimum, document the limitation in `network_safety.py`.
- **CWE:** CWE-918 (SSRF), CWE-367 (TOCTOU)

### M3. `_METADATA_HOSTS` IPv6 metadata coverage
- **File:** `src/swarmline/network_safety.py:11-13`
- **Risk:** Missing AWS Nitro IPv6 metadata host alongside Azure ARC IPv6 variant. Also `[::ffff:169.254.169.254]` IPv4-mapped IPv6 representation may bypass the literal lowercase string match.
- **Severity: Medium** in cloud deployments where the agent runs on AWS Nitro hosts.
- **Fix:** Extend the `_METADATA_HOSTS` frozenset to include AWS IPv6 metadata, IPv4-mapped IPv6 forms, and Azure ARC variants. Add an IPv6 address normalization step before lookup so all canonical/non-canonical forms collapse to the same key.
- **CWE:** CWE-918 (SSRF)

### M4. TOCTOU race in `LocalSandboxProvider.write_file` atomic write
- **File:** `src/swarmline/tools/sandbox_local.py:138-141`
- **Risk:** `safe_path` resolved once at write-time. Between resolution and `os.replace(tmp, safe_path)`, attacker with concurrent filesystem access could create a symlink at `safe_path` pointing outside the workspace; `os.replace` follows the symlink and writes outside the sandbox.
- **Severity: Medium** in shared-tenancy environments; **Low** in single-tenant.
- **Fix:** Use `os.open(O_NOFOLLOW | O_CREAT | O_EXCL)` for the tmp file and `renameat2(RENAME_NOREPLACE)` (Linux 3.15+) for the rename. As a portable fallback, re-validate `safe_path.resolve()` immediately before `os.replace` and abort if it diverges.
- **CWE:** CWE-367 (TOCTOU)

### M5. Plugin entry_point passed unchecked to subprocess shim
- **File:** `src/swarmline/plugins/runner.py:188`
- **Code:** `manifest.entry_point` forwarded to `python -m swarmline.plugins._worker_shim <module_path>`.
- **Risk:** If `entry_point` flows from untrusted source (manifest in user-controlled plugins/ dir, A2A-imported plugin), an attacker can specify any pip-installed importable module. `_worker_shim:55` does `importlib.import_module(module_path)` without sanitization. While the operator's PYTHONPATH is the gate, in a multi-user dev environment with shared site-packages this widens attack surface.
- **Severity: Medium** if plugins come from an untrusted manifest registry.
- **Fix:** Validate `entry_point` against an allowlist or regex `^[a-zA-Z_][a-zA-Z0-9_.]+$` and document the trust boundary.
- **CWE:** CWE-94 (Code Injection), CWE-829 (Inclusion of Functionality from Untrusted Control Sphere)

### M6. Plugin worker shim has no method allowlist
- **File:** `src/swarmline/plugins/_worker_shim.py:102`
- **Code:** `fn = getattr(plugin_module, method, None)` — JSON-RPC method name → arbitrary attribute access on plugin module.
- **Risk:** Attacker with parent-side RPC channel access can call `_private_helper`, `__init__`, or any module-level callable that wasn't designed as RPC entry. Combined with M5 (arbitrary plugin), this allows trivial RCE inside the plugin process.
- **Severity: Medium** as defense-in-depth.
- **Fix:** Restrict RPC method dispatch to plugin module's `__all__` or to functions starting with `rpc_` prefix. Reject method names starting with `_`.
- **CWE:** CWE-749 (Exposed Dangerous Method)

### M7. Hook fail-open allows broken security hooks to bypass
- **File:** `src/swarmline/hooks/dispatcher.py:104-110`
- **Risk:** PreToolUse hook callback raising any exception → tool executes unchecked. Fine for observability hooks, but a security-critical hook (e.g., custom denylist) silently fails. Documented as design choice.
- **Severity: Low** (design intent, not vulnerability) — but raises operator-surprise risk.
- **Fix:** Add `fail_closed=True` flag to hook registration so critical hooks block on raise. Document the model clearly in `docs/hooks.md`.
- **CWE:** CWE-754 (Improper Check for Unusual or Exceptional Conditions)

### M8. Skill instruction file resolution permits operator-set traversal targets
- **File:** `src/swarmline/skills/loader.py:218-230`
- **Risk:** `instruction_file_raw` from skill.yaml is operator-controlled. After `resolve()` and `is_relative_to(project_root)` check (line 223), traversal outside project_root is rejected — **good**. But: if the operator's `project_root` itself is a symlink to `/`, the entire filesystem becomes readable. **Severity: Low** (operator misconfiguration, not vulnerability).
- **Fix:** Document the `project_root` trust boundary. Optionally, refuse to load if `project_root.resolve() != project_root` (i.e., reject symlinked project roots).

### M9. Symlink TOCTOU in `_resolve_project_file`
- **File:** `src/swarmline/skills/loader.py:159-179`
- **Risk:** `is_symlink()` check at line 162-164 followed by `resolve(strict=True)` at line 165. Between these calls, attacker plants a symlink (race). The subsequent `is_relative_to(project_root)` check at line 170 catches if the resolved real path escapes root, so RCE is unlikely; but TOCTOU exists as defense-in-depth concern.
- **Severity: Low**.
- **Fix:** Use `os.lstat` + `S_ISLNK` followed by `os.open(O_NOFOLLOW)` for the read.

### M10. Session deserialization uses `**payload` unpacking
- **File:** `src/swarmline/session/snapshot_store.py:56, 62`
- **Risk:** `ToolSpec(**tool_payload)` and `Message(**message_payload)` — if a malicious session backend (compromised Redis/Postgres) injects unexpected keys, the dataclass `__init__` rejects extras (good, frozen=True). However, dataclass evolution is fragile: adding a public field that maps to internal state could enable mass-assignment in a future release.
- **Severity: Low** today, **Medium** in future as dataclasses evolve.
- **Fix:** Switch to explicit field-by-field deserialization (whitelist) instead of `**`, mirroring the explicit `serialize_state` (line 21-43) which already enumerates fields.

### M11. SSRF defense missing on `JinaReaderFetchProvider`
- **File:** `src/swarmline/tools/web_providers/jina.py:53`
- **Code:** `f"{_JINA_READER_BASE}{url.strip()}"` — concatenates user-controlled URL with Jina endpoint.
- **Risk:** Jina handles SSRF server-side, but `file://`, `gopher://`, `dict://` scheme URLs may produce unexpected behavior (or 400). Not validated locally via `validate_http_endpoint_url`. **Severity: Low** (SSRF protection delegated to Jina API).
- **Fix:** Apply `validate_http_endpoint_url(url)` before forwarding to Jina. Consistent with how other web fetches gate URLs.
- **CWE:** CWE-918 (SSRF)

---

## Low (nice-to-have)

### L1. Command loader silently swallows YAML parse errors
- **File:** `src/swarmline/commands/loader.py:107-108`
- **Code:** `except Exception: return []`
- **Risk:** No logging on YAML parse failure. Operator cannot diagnose why a command is missing. Forensics impossible. Not a vulnerability — DX concern.
- **Fix:** Log via structlog: `logger.warning("command_yaml_parse_failed", path=str(path), exc_info=True)`.

### L2. `redact_secrets` does not handle multi-line stack traces with embedded URLs
- **File:** `src/swarmline/observability/redaction.py` (combined with H2)
- **Risk:** When `exc_info=True` produces a 50-line traceback containing a Bearer token across line continuations, the regex matches per-line — fine for most cases, but embedded URLs split across lines (e.g., wrapped at terminal width) won't match the URL-userinfo pattern. Edge case.
- **Severity: Low** (rare format).
- **Fix:** N/A on its own — bundle with H2 redaction processor implementation.

---

## Out of Scope (already in v1.5.1 backlog — acknowledged, not re-audited)

- **S1**: LSP cross-provider denylist in LLMProviderRegistry (sandbox_e2b vs docker vs openshell)
- **S2**: lowercase env keys in default-deny redaction (`api_key=...`)
- **S3**: dead `sk-ant-` regex order in redaction
- **S5**: pi_sdk overrides bypass allowlist
- **S6**: broader E2B wrapper detection (busybox/env/python `-c`)
- **N1**: DRY redaction templates between `redaction.py` and `jsonl_sink.py`
- **N2**: AWS AKIA + JWT patterns missing in redaction
- **N3**: path_safety docstring claims unsupported `..` substring guard
- **N4**: test assertion fixes in `test_observability_redaction.py`
- **N5**: CLI startup-failure exception redaction missing — **note: H3 widens this finding to all `exc_info=True` paths**

---

## Strengths

- **`redaction.py`** — bounded quantifiers `{0,30}`, `{1,256}` (post-C1 fix), no ReDoS surface remains.
- **`serve/app.py`** — explicit host= enforcement and hard-error on `host=None` + `allow_unauthenticated_query=True` (post-C2 fix). Good defense.
- **`a2a/server.py:107` and `daemon/health.py:133`** — both correctly use `hmac.compare_digest`. (Only `serve/app.py:41` is the outlier — see H1.)
- **`sandbox_local.py`** — `_resolve_safe_path` correctly uses `is_relative_to(workspace_resolved)` to defeat prefix bypass (`/tmp/ws2` vs `/tmp/ws`).
- **No `eval`/`exec`/`pickle`/`shell=True`/`yaml.unsafe_load` anywhere in src/** — verified via grep across 387 files. All YAML uses `safe_load`. All subprocess calls use `create_subprocess_exec` (no shell). All deserialization is JSON or stdlib dataclass `**` unpacking (M10 caveat).
- **SQL composition is parameterized** — `multi_agent/*_postgres.py` and `observability/activity_log.py` use static WHERE-clause whitelists with `?` / `:param` placeholders. The lone `f"UPDATE procedures SET {col} = ..."` in `procedural_postgres.py:154` is internal-only literal substitution (`success_count` / `failure_count`).
- **Subprocess env is allowlist-based** (`runtime/_subprocess_env.py`) — secure-by-default for cli/pi_sdk runtimes.
- **Default-deny tool policy** (`policy/tool_policy.py`) — explicit `ALWAYS_DENIED_TOOLS` frozenset covers both PascalCase (SDK) and snake_case naming variants.
- **Subagent inherits parent tool_policy / hook_registry** — no privilege escalation path: subagent has SAME or LESS authority than parent.
- **Workspace slug validation** — `_SLUG_RE = ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$` blocks path traversal in workspace IDs.
- **Docker sandbox hardening** — `security_opt=["no-new-privileges=true"]`, `cap_drop=["ALL"]`, `network_mode="none"` defaults.
- **`asyncio.create_subprocess_exec` everywhere** — no `subprocess.run(shell=True)`. argv-only invocation.

---

## Methodology

- **Files reviewed:** ~70 of 387 .py files in src/swarmline/. Full read of: `serve/app.py`, `a2a/server.py`, `daemon/health.py`, `network_safety.py`, `observability/redaction.py`, `observability/jsonl_sink.py`, `policy/tool_policy.py`, `tools/sandbox_local.py`, `tools/sandbox_e2b.py`, `tools/sandbox_docker.py`, `skills/loader.py`, `hooks/dispatcher.py`, `commands/loader.py`, `runtime/cli/runtime.py`, `runtime/_subprocess_env.py`, `runtime/codex_adapter.py`, `runtime/thin/llm_client.py`, `runtime/thin/errors.py`, `runtime/thin/llm_providers.py` (head), `multi_agent/worktree_orchestrator.py`, `multi_agent/workspace.py`, `multi_agent/task_queue_postgres.py`, `multi_agent/graph_task_board_postgres.py`, `memory/procedural_postgres.py`, `observability/activity_log.py`, `session/snapshot_store.py`, `session/jsonl_store.py`, `plugins/runner.py`, `plugins/_worker_shim.py`, `tools/web_providers/jina.py`, `input_filters.py`, `resilience/circuit_breaker.py`, `orchestration/thin_subagent.py` (head). Skim of remaining via grep.
- **Tools used:**
  - `grep` for pattern-based searches: `eval/exec/compile`, `pickle/marshal`, `yaml.load`, `shell=True`, `f"INSERT/SELECT/UPDATE/DELETE`, `execute(.*%/f"`, `==.*token`, `Path/open.*request`, hardcoded secrets (sk-ant-, ghp_, AKIA), `compare_digest`.
  - `pip-audit --vulnerability-service osv` against the local dev environment (88 vulnerabilities across 30 packages — mostly transitive deps and dev tools; H5/M referenced).
  - Manual code reading of all auth, sandbox, subprocess, deserialization, and redaction modules.
  - Cross-reference with prior reports (`2026-04-25_audit-security.md`, `2026-04-27_review_post-v1.5.0-security-audit-closure.md`) to avoid duplication of known issues.
- **Patterns checked (negative result = good):**
  - `eval(...)`, `exec(...)`, `compile(...)` — none in src/ (only `re.compile`, `sg.compile`, the sandbox `_exec` method which is documented).
  - `pickle.loads/dumps`, `marshal.loads` — none.
  - `yaml.unsafe_load`, `yaml.load(...)` without `Loader=SafeLoader` — none. All call sites use `yaml.safe_load`.
  - `shell=True` — none.
  - Hardcoded secrets — only test fixtures (`sk-ant-api03-abc...`) and template placeholders (`init_cmd.py:184`).
  - SQL string concatenation / f-string interpolation of user data — none. All f-string SQL uses static literal column lists.
  - `==`/`!=` on tokens — only `serve/app.py:41` (H1).
  - `random.choice/randint` for security — none. UUID4 used for non-secret IDs only.

---

## Conclusion

swarmline v1.5.0 is in **solid security posture** with no critical PyPI-blocking issues. The post-v1.5.0 audit-closure work effectively closed the prior C1-C4 issues, and the framework's core security principles are sound: default-deny tool policy, secure-by-default subprocess env, allowlist-based bearer auth, sandbox isolation primitives, and conservative redaction. **Five High-severity issues warrant a v1.5.1 patch within 1-2 weeks**: H1 (timing attack — trivial fix to `hmac.compare_digest`), H2/H3 (`exc_info=True` bypassing redaction — globally addressable via structlog processor), H4 (git argv injection — needs ref/path validation regex), and H5 (langchain-core CVE — bump dependency floor). The eleven Medium findings are defense-in-depth improvements (SSRF DNS rebinding, IPv6 metadata, plugin manifest hardening) that can be batched into v1.6.0 alongside the v1.5.1 backlog (S1-S6, N1-N5). Strongly recommend shipping v1.5.0 as-is to public PyPI now and following with v1.5.1 within two sprints addressing H1+H4+H5 minimum.
