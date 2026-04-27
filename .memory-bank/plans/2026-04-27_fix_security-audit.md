# Plan: fix — security audit 2026-04-27 (6 findings)

**Дата:** 2026-04-27
**Тип:** fix (security hardening)
**Статус:** Approved → ready for execution
**Complexity:** M
**Baseline commit:** `f4faa9c` (`main`, working tree clean, 4 ahead of `origin/main`)
**Целевой релиз:** **v1.5.1 (PATCH)** — security fixes. Stage 5 минорно breaking но warned-in-v1.5.0 → допустимо как PATCH с явной CHANGELOG-нотой. Альтернатива: v1.6.0 (MINOR) если хочется консервативно.

---

## Цель

Закрыть 6 findings из security-аудита 2026-04-27 (P1×2 + P2×4), не сломав 5452 existing offline-теста и сохранив baseline `ty=0`. Все fixes — TDD-first, atomic commits, минимально-инвазивные.

## Scope

### Входит:
- **Stage 1 (P1):** namespace `.` segment rejection в `path_safety.py` — закрывает cross-tenant filesystem collision.
- **Stage 2 (P1):** pi_sdk env allowlist — parity с CLI runtime, защита от secret exfiltration через child process.
- **Stage 3 (P2):** E2B sandbox shell-wrapper denylist resolution (`sh -c` / `bash -c` parsing).
- **Stage 4 (P2):** web_fetch scheme allowlist — `{http, https}` only, blocks `file://` / `ftp://` / `data:`.
- **Stage 5 (P2):** `serve.create_app` `host=None + allow_unauthenticated_query=True` → ValueError (вместо warning).
- **Stage 6 (P2):** secret redaction utility для error messages (Bearer tokens, basic auth userinfo, common secret patterns).
- **Stage 7:** final validation + version bump candidate.

### НЕ входит:
- Refactor `path_safety` API — только additive guard.
- Полный sandbox redesign (Local/Docker уже корректны — fix только E2B).
- Audit log surface — только error message redaction в `errors.py` / `cli/runtime.py` / `serve/app.py`. JSONL sink уже redacts (Stage 20 v1.5.0).
- Backward-compat shim для Stage 5 — warning ushёл в v1.5.0, в v1.5.1 hard-fail оправдан.

## Assumptions

- Repo на `main`, baseline `f4faa9c`, working tree clean. Pre-flight `git status` подтвердит.
- 5452 offline-тестов зелёные сейчас. После каждого Stage — full pytest run = gate.
- `ty check src/swarmline/` = 0 (baseline locked). Не должна расти.
- Existing public API — additive только. Кроме Stage 5 (см. Риски).
- Все 6 findings — реальные exploit paths (verified чтением кода 2026-04-27).
- Audit findings от пользователя точно соответствуют состоянию `f4faa9c`.

## Риски

| Риск | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Stage 1 (`.` rejection) ломает existing tests, опирающиеся на `topic_id="."` | L | M | Grep `validate_namespace_segment` callers + tests на `topic_id="."` / `user_id="."` ДО изменения. Если найдены legitimate uses — пересмотреть payload (вероятно не найдём — `.` всегда indicate error). |
| Stage 2 (pi_sdk env allowlist) ломает downstream pi_sdk users, опирающихся на implicit env inheritance (e.g. `OPENAI_API_KEY`) | M | M | Добавить `PiSdkOptions.env_allowlist` (default = `DEFAULT_ENV_ALLOWLIST` ∪ `{"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}`) + `inherit_host_env: bool = False` flag. Документировать в CHANGELOG как **security fix** + migration step. |
| Stage 3 (E2B shell wrapper) ломает legitimate `sh -c "..."` calls без denied tokens | L | L | Recursive parse только при detected wrapper И только если internal arg содержит denied tokens. Без denylist — без изменения. Все existing tests на E2B продолжают проходить. |
| Stage 4 (scheme allowlist) ломает downstream code, читающий `file://` через `web_fetch` | L | L | `file://` через `web_fetch` — security anti-pattern. Если кто-то использует — это ошибка. Документировать в CHANGELOG. Migration: использовать `read_file` tool вместо `web_fetch("file://...")`. |
| Stage 5 (host=None hard-fail) ломает downstream test infra, ожидающий v1.4.x signature | M | M | Warning шёл в v1.5.0 — пользователи were warned 1 release ago. В CHANGELOG: "v1.5.1 turns the v1.5.0 deprecation warning into ValueError". Migration: `create_app(agent, allow_unauthenticated_query=True, host="127.0.0.1")` (loopback explicit). |
| Stage 6 (redaction utility) изменяет error message format → ломает tests, проверяющие подстроки в `error.message` | M | L | Redaction только для known patterns (Bearer, basic auth userinfo). Token-free messages не меняются. Run pytest после каждого внедрения, при regression — narrow regex. |
| Total effort ≥ 8h (out of single-session range) | M | L | План на 6 atomic stages, можно execute по частям. P1 первыми (Stage 1 + 2) = 2-3h = достаточно для одной сессии. P2 = вторая сессия. |

---

## Этапы

<!-- mb-stage:1 -->
## Stage 1: P1 — `path_safety.validate_namespace_segment` rejects `.` and `..`

**Source:** Audit finding #1 (path_safety cross-tenant collision)
**Effort:** ~30 min
**Type:** security fix (1 LOC fix + tests)
**Files:**
- `src/swarmline/path_safety.py:12-18` (modify)
- `tests/unit/test_path_safety.py` (extend)

**Что не так сейчас:**
`validate_namespace_segment("." )` проходит — substring check `".." in name` возвращает False для `name="."`, `_SAFE_SEGMENT_CHARS` явно содержит `.`. Результат: `SandboxConfig(user_id=".", topic_id="alice")` и `SandboxConfig(user_id="alice", topic_id=".")` резолвятся в один путь `/root/alice/workspace` — tenant boundary bypass.

**Что делаем:**
Добавить explicit reject `name in {".", ".."}` ДО character check:
```python
def validate_namespace_segment(name: str, label: str) -> str:
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError(f"Invalid {label}: {name!r}")
    if not all(ch in _SAFE_SEGMENT_CHARS for ch in name):
        raise ValueError(f"Invalid characters in {label}: {name!r}")
    return name
```

**Testing (TDD — tests BEFORE implementation):**
1. `test_validate_namespace_segment_rejects_single_dot` — `validate_namespace_segment(".", "user_id")` raises `ValueError`.
2. `test_validate_namespace_segment_rejects_double_dot` — `"..", "topic_id"` raises (regression — уже работает через substring; добавить assert).
3. `test_sandbox_config_rejects_dot_user_id` — `SandboxConfig(root_path="/r", user_id=".", topic_id="x")` raises в `__post_init__`.
4. `test_sandbox_config_rejects_dot_topic_id` — симметрично.
5. `test_path_collision_prevented` — параметризованный тест: `("alice", ".")` и (".", "alice")` оба raises (а не дают равный workspace_path).
6. `test_fs_provider_rejects_dot_namespace` — `todo/fs_provider.py` + `memory_bank/fs_provider.py` callers тоже raise.

**Edge cases:**
- `..` (через substring уже ловится; теперь явно через set).
- `...` (3 dots) — должно проходить (valid namespace name); `...` ∉ `{".", ".."}` и `..` substring matches → raises (текущее поведение НЕ меняем — `...` уже rejected). Добавить test `test_three_dots_still_rejected`.
- Empty string — уже rejected (`not name`).
- Unicode lookalikes (`․` U+2024) — уже rejected character check (не в `_SAFE_SEGMENT_CHARS`).

**Commands to verify:**
```bash
pytest tests/unit/test_path_safety.py -v       # new tests + existing pass
pytest tests/unit/test_sandbox_local.py -v     # SandboxConfig integration
pytest -q                                       # full green
ty check src/swarmline/                         # baseline = 0
```

**DoD (SMART):**
- [ ] 6 new test functions added + green
- [ ] `validate_namespace_segment` rejects `"."` and `".."` explicitly via set membership
- [ ] All callers (`tools/types.py`, `todo/fs_provider.py`, `memory_bank/fs_provider.py`) inherit fix without modification
- [ ] No regression in 5452 existing tests
- [ ] `ty check` baseline = 0

**Commit message:**
```
fix(security): reject `.` and `..` namespace segments in path_safety

Closes audit finding P1 #1 — cross-tenant filesystem collision via
`SandboxConfig(user_id=".", topic_id="alice")` resolving to the same
workspace as `("alice", ".")`. Both now raise ValueError.

Affects: path_safety + tools/types + todo/fs_provider + memory_bank/fs_provider
```

---

<!-- mb-stage:2 -->
## Stage 2: P1 — `pi_sdk` runtime subprocess env allowlist

**Source:** Audit finding #2 (pi_sdk env inheritance secret leak)
**Effort:** ~1.5 h
**Type:** security fix (mirror CLI runtime pattern)
**Files:**
- `src/swarmline/runtime/pi_sdk/types.py` (extend `PiSdkOptions`)
- `src/swarmline/runtime/pi_sdk/runtime.py:68-73` (pass `env=`)
- `tests/unit/test_pi_sdk_runtime.py` (extend)

**Что не так сейчас:**
`asyncio.create_subprocess_exec(*cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)` без `env=` → child Node bridge inherits `os.environ` целиком. `OPENAI_API_KEY`, `AWS_*`, CI tokens etc становятся доступны `@mariozechner/pi-coding-agent` (или compromised replacement).

**Что делаем:**
Mirror CLI runtime pattern (`runtime/cli/runtime.py:34-45` + `runtime/cli/types.py:55`):

1. В `pi_sdk/types.py` добавить в `PiSdkOptions`:
   ```python
   inherit_host_env: bool = False  # secure-by-default
   env_allowlist: frozenset[str] = DEFAULT_PI_SDK_ENV_ALLOWLIST
   env: dict[str, str] = field(default_factory=dict)  # explicit overrides
   ```
   `DEFAULT_PI_SDK_ENV_ALLOWLIST = DEFAULT_ENV_ALLOWLIST | {"NODE_PATH", "NODE_ENV", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}` — pi-coding-agent нужен Node + provider keys.
2. Extract `_build_subprocess_env(cli_config)` из `cli/runtime.py:34-45` в shared helper `runtime/_subprocess_env.py` (DRY) — принимает `inherit, allowlist, overrides`.
3. В `pi_sdk/runtime.py:68` передать `env=_build_subprocess_env(self._pi_options.inherit_host_env, self._pi_options.env_allowlist, self._pi_options.env)`.

**Testing (TDD):**
1. `test_pi_sdk_subprocess_env_excludes_arbitrary_secret_by_default` — set `os.environ["MY_SECRET"]="leaky"`, mock `create_subprocess_exec`, assert kwargs `env` doesn't contain `"MY_SECRET"`.
2. `test_pi_sdk_subprocess_env_includes_openai_api_key_by_default` — `OPENAI_API_KEY` пропущен (default allowlist).
3. `test_pi_sdk_subprocess_env_inherits_all_when_inherit_host_env_true` — explicit opt-in для legacy behavior.
4. `test_pi_sdk_subprocess_env_explicit_overrides_take_precedence` — `PiSdkOptions(env={"OPENAI_API_KEY": "override"})` + `os.environ["OPENAI_API_KEY"]="host"` → child sees "override".
5. `test_pi_sdk_subprocess_env_extra_allowlist_field` — кастомный `env_allowlist=frozenset({"MY_VAR"})` пропускает `MY_VAR`.
6. `test_subprocess_env_helper_dry` — extracted helper used by both CLI and pi_sdk runtimes (assert importable from shared location).

**Edge cases:**
- `os.environ` empty (CI без env) — should not raise.
- Allowlist contains key NOT in os.environ — should silently skip (no KeyError).
- `inherit_host_env=True` ignores allowlist (matches CLI behavior).

**Commands to verify:**
```bash
pytest tests/unit/test_pi_sdk_runtime.py -v
pytest tests/unit/test_cli_runtime.py -v       # ensure DRY refactor doesn't break CLI
pytest -q                                       # full green
ty check src/swarmline/                         # baseline = 0
```

**DoD (SMART):**
- [ ] 6 new tests + green
- [ ] `PiSdkOptions` has `inherit_host_env`, `env_allowlist`, `env` fields with secure defaults
- [ ] `_build_subprocess_env` extracted to `runtime/_subprocess_env.py`, used by both CLI and pi_sdk
- [ ] CLI runtime tests pass after DRY refactor (regression gate)
- [ ] No regression in 5452 existing tests
- [ ] `ty check` baseline = 0

**Commit message:**
```
fix(security): pi_sdk subprocess env allowlist (parity with CLI runtime)

Closes audit finding P1 #2 — pi_sdk Node bridge inherited full host env
including OPENAI_API_KEY, AWS_*, CI tokens. Now uses default allowlist
(PATH/HOME/Node + provider keys); legacy behavior via inherit_host_env=True.

Extracts shared _build_subprocess_env helper used by CLI + pi_sdk runtimes.
```

---

<!-- mb-stage:3 -->
## Stage 3: P2 — E2B sandbox `sh -c` / `bash -c` denylist resolution

**Source:** Audit finding #3 (E2B shell wrapper bypass)
**Effort:** ~1 h
**Type:** security fix (parser hardening)
**Files:**
- `src/swarmline/tools/sandbox_e2b.py:77-85` (extend `_check_denied_command`)
- `tests/unit/test_sandbox_e2b.py` (extend)

**Что не так сейчас:**
`_check_denied_command("sh -c 'rm -rf /workspace'")` → `shlex.split` даёт `["sh", "-c", "rm -rf /workspace"]`. Loop проверяет `os.path.basename(word) in denied`: `"sh"`, `"-c"`, `"rm -rf /workspace"` — ни один не в `{"rm", "sudo"}` → bypass. Local/Docker/OpenShell providers корректны (используют другую логику).

**Что делаем:**
Добавить shell wrapper detection + recursive parse:
```python
_SHELL_WRAPPERS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})

def _check_denied_command(self, command: str) -> None:
    denied = self._config.denied_commands or frozenset()
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    if not words:
        return
    # Recurse into shell wrapper -c argument
    if os.path.basename(words[0]) in _SHELL_WRAPPERS:
        for i, w in enumerate(words[1:], start=1):
            if w == "-c" and i + 1 < len(words):
                self._check_denied_command(words[i + 1])
                return
    for word in words:
        if os.path.basename(word) in denied:
            raise SandboxViolation(f"Command '{word}' is denied", path=command)
```

**Testing (TDD):**
1. `test_e2b_blocks_sh_c_with_denied_command` — `denied={"rm"}`, `execute("sh -c 'rm -rf /workspace'")` raises `SandboxViolation`.
2. `test_e2b_blocks_bash_c_with_denied_command` — `bash -c "sudo apt install x"` с `denied={"sudo"}` raises.
3. `test_e2b_allows_sh_c_with_safe_command` — `sh -c 'echo hello'` с `denied={"rm"}` proceeds.
4. `test_e2b_blocks_nested_shell_wrapper` — `sh -c 'bash -c "rm /x"'` raises (recursion).
5. `test_e2b_zsh_dash_ksh_fish_wrapped` — параметризованный по wrappers.
6. `test_e2b_no_recursion_when_denylist_empty` — без denylist никаких recursive parse (DRY: same path как до fix).

**Edge cases:**
- `sh -c 'echo "rm not really called"'` — `rm` matches basename of arg `"rm not really called"` → false positive. **Mitigation:** правый-side parse через `shlex.split(words[i+1])` тоже, basename per word.
- `sh` без `-c` (interactive) — пропустить recursion (нет inner command).
- `sh -c` без 3-го аргумента — graceful skip, не crash.
- Quoted denied (`'rm'`) — `shlex.split` strips quotes, basename = `"rm"` — already caught by inner recursion.

**Commands to verify:**
```bash
pytest tests/unit/test_sandbox_e2b.py -v
pytest tests/unit/test_sandbox_local.py tests/unit/test_sandbox_docker.py tests/unit/test_sandbox_openshell.py -v  # parity check
pytest -q
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] 6 new tests + green
- [ ] `sh -c` / `bash -c` / `zsh -c` / `dash -c` / `ksh -c` / `fish -c` все trigger recursive parse
- [ ] Без denylist — no behavioral change (existing tests pass)
- [ ] No regression in Local/Docker/OpenShell providers
- [ ] `ty check` baseline = 0

**Commit message:**
```
fix(security): resolve shell wrapper bypass in E2B sandbox denylist

Closes audit finding P2 #3 — `sh -c 'rm -rf /workspace'` previously
bypassed denylist={"rm"} because the rm token sat inside a quoted argument.
Now recursively parses sh/bash/zsh/dash/ksh/fish -c arguments.

Brings E2B provider to parity with Local/Docker/OpenShell.
```

---

<!-- mb-stage:4 -->
## Stage 4: P2 — `web_fetch` URL scheme allowlist (`{http, https}`)

**Source:** Audit finding #4 (non-HTTP schemes pass validator)
**Effort:** ~30 min
**Type:** security fix (1 LOC + tests)
**Files:**
- `src/swarmline/tools/web_httpx.py:210-260` (`_validate_url`)
- `tests/unit/test_web_httpx.py` (extend) или `tests/security/test_ssrf.py`

**Что не так сейчас:**
`_validate_url("file:///etc/passwd")` → `parsed.scheme="file"`, `parsed.hostname=""`, `_BLOCKED_HOSTS` check skip (hostname empty), IP check skip (empty), DNS skip (empty), returns `None` → URL approved. Default httpx path обычно crashes на `file://`, но **delegated provider** (Crawl4AI с browser engine) принимает URL напрямую и может open local file.

**Что делаем:**
Добавить scheme guard В НАЧАЛЕ `_validate_url`:
```python
@staticmethod
def _validate_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        return "Invalid URL"

    # Scheme allowlist — block file://, ftp://, data:, javascript:, gopher://, etc.
    if parsed.scheme not in ("http", "https"):
        return f"Scheme blocked: {parsed.scheme!r} (only http/https allowed)"

    # ... rest unchanged ...
```

**Testing (TDD):**
1. `test_validate_url_rejects_file_scheme` — `_validate_url("file:///etc/passwd")` returns scheme rejection.
2. `test_validate_url_rejects_ftp_scheme` — `ftp://example.com/x` rejected.
3. `test_validate_url_rejects_data_scheme` — `data:text/plain,hi` rejected.
4. `test_validate_url_rejects_javascript_scheme` — `javascript:alert(1)` rejected.
5. `test_validate_url_rejects_gopher_scheme` — `gopher://internal` rejected.
6. `test_validate_url_accepts_https` — `https://example.com` returns `None` (not rejected by scheme check; rest of validator runs).
7. `test_validate_url_accepts_http` — `http://example.com` similarly.
8. `test_web_fetch_blocks_file_scheme_with_crawl4ai_provider` — integration: `HttpxWebProvider(fetch_provider=Crawl4AIFetchProvider())` + `fetch("file:///etc/passwd")` returns "URL blocked: ..." без вызова provider's fetch.

**Edge cases:**
- Schemeless URL (`example.com`) — `urlparse` gives `scheme=""` → rejected (правильно — заставляет user написать `https://`).
- Mixed-case `HTTP://` — `parsed.scheme.lower()` для consistency.
- Empty URL — already returns "Invalid URL".

**Commands to verify:**
```bash
pytest tests/unit/test_web_httpx.py -v
pytest tests/security/ -v       # SSRF / network safety tests
pytest -q
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] 8 new tests + green
- [ ] `_validate_url` rejects scheme ∉ `{"http", "https"}` (case-insensitive)
- [ ] Crawl4AI delegated path also blocked (integration test)
- [ ] No regression in existing web_fetch tests
- [ ] `ty check` baseline = 0

**Commit message:**
```
fix(security): web_fetch scheme allowlist (http/https only)

Closes audit finding P2 #4 — `file://`, `ftp://`, `data:`, `javascript:`
URLs previously passed _validate_url and could reach delegated browser
providers (Crawl4AI). Now blocked at validator entry.
```

---

<!-- mb-stage:5 -->
## Stage 5: P2 — `serve.create_app` host=None hard-fail when `allow_unauthenticated_query=True`

**Source:** Audit finding #5 (host=None backward-compat path)
**Effort:** ~45 min
**Type:** security fix (BC-tightening — warned in v1.5.0)
**Files:**
- `src/swarmline/serve/app.py:161-184` (modify)
- `tests/unit/test_serve_app_loopback_enforcement.py` (extend)
- `CHANGELOG.md` (entry under [1.5.1])

**Что не так сейчас:**
v1.5.0 path: `host=None + allow_unauthenticated_query=True` → log warning + create app anyway. Operator может затем `uvicorn app --host 0.0.0.0` → public unauth `/v1/query` exposed.

**Что делаем:**
Заменить warning-with-allow на ValueError:
```python
if allow_unauthenticated_query and auth_token is None:
    if host is None:
        raise ValueError(
            "serve.create_app(allow_unauthenticated_query=True) requires an "
            "explicit host= argument since v1.5.1. Pass host='127.0.0.1' (or "
            "another loopback) for local-only mode, or pass auth_token= for "
            "production."
        )
    if not is_loopback_host(host):
        raise ValueError(...)  # existing branch, unchanged
```
Удалить `else: log_security_decision(...) + _log.warning(...)` branch.

**Testing (TDD):**
1. `test_create_app_unauth_query_with_host_none_raises_in_v151` — `create_app(agent, allow_unauthenticated_query=True)` (no host) raises `ValueError` с сообщением "requires an explicit host=".
2. `test_create_app_unauth_query_with_loopback_host_works` — `host="127.0.0.1"` works (regression).
3. `test_create_app_unauth_query_with_public_host_raises` — `host="0.0.0.0"` raises (existing behavior, regression test).
4. `test_create_app_with_auth_token_no_host_works` — auth path doesn't require explicit host (regression).
5. `test_create_app_default_no_unauth_no_host_works` — `create_app(agent)` (default secure) works без host (no requirement).

**Edge cases:**
- `host=""` (empty string) — treat как None? **Decision:** `not host` → raise (`if not host`). Документировать.
- IPv6 loopback `host="::1"` — `is_loopback_host` уже ловит.
- `host="localhost"` — `is_loopback_host` ловит.

**Migration / CHANGELOG entry:**
```markdown
## [1.5.1] — 2026-04-XX

### Security

- **BREAKING (warned in v1.5.0):** `serve.create_app(allow_unauthenticated_query=True)`
  now requires an explicit `host=` argument. Previously logged a deprecation warning;
  now raises `ValueError`. Migration: pass `host="127.0.0.1"` for local-only, or
  use `auth_token=` for production.
- ... (other Stage 1-4, 6 entries)
```

**Commands to verify:**
```bash
pytest tests/unit/test_serve_app_loopback_enforcement.py -v
pytest tests/integration/test_serve.py -v  # if exists
pytest -q
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] 5 new/updated tests + green
- [ ] `host=None + allow_unauthenticated_query=True` raises `ValueError` (no warning fallback)
- [ ] CHANGELOG `[1.5.1]` entry written с migration note
- [ ] No regression in 5452 existing tests
- [ ] `ty check` baseline = 0

**Commit message:**
```
fix(security)!: require explicit host= for unauthenticated serve

Closes audit finding P2 #5 — v1.5.0 warning-with-allow path could be
combined with `uvicorn --host 0.0.0.0` to expose unauth /v1/query publicly.
v1.5.1 turns the v1.5.0 deprecation warning into ValueError.

Migration: create_app(agent, allow_unauthenticated_query=True, host="127.0.0.1")

BREAKING-CHANGE: only when host=None and allow_unauthenticated_query=True;
warned in v1.5.0 release notes.
```

---

<!-- mb-stage:6 -->
## Stage 6: P2 — Secret redaction utility for runtime/serve error messages

**Source:** Audit finding #6 (raw exceptions leak secrets)
**Effort:** ~2 h
**Type:** security fix (defense in depth)
**Files:**
- `src/swarmline/observability/redaction.py` (NEW — extract patterns)
- `src/swarmline/runtime/thin/errors.py:41-52` (apply)
- `src/swarmline/runtime/cli/runtime.py:240-250` (apply)
- `src/swarmline/serve/app.py:128-131` (apply)
- `src/swarmline/observability/jsonl_sink.py` (refactor — use shared helper)
- `tests/unit/test_redaction.py` (NEW)
- `tests/unit/test_runtime_errors_redaction.py` (NEW)

**Что не так сейчас:**
- `provider_runtime_crash("openai", RuntimeError("Bearer secret-token is invalid"))` → `error.message = "LLM API error (openai): RuntimeError: Bearer secret-token is invalid"`. Secret в RuntimeEvent.error.
- CLI runtime: `stderr_data.decode()` пишется raw в `error.message` — может содержать `proxy=https://user:pass@proxy.example.com` или DSN.
- `serve/app.py` `JSONResponse({"error": str(exc), ...}, status_code=500)` — exc может содержать env-injected secret.

**Что делаем:**
1. Создать `observability/redaction.py` с `redact_secrets(text: str) -> str` который применяет regex set:
   ```python
   _PATTERNS = [
       # Bearer / Token: sk-..., sk-ant-..., gh*_..., etc.
       (re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.~+/=]{16,}", re.I), "Bearer ***"),
       (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), "sk-***"),
       (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "sk-ant-***"),
       (re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), r"\1_***"),
       # URL userinfo: scheme://user:pass@host
       (re.compile(r"(\w+://)([^:/@\s]+):([^@/\s]+)@"), r"\1***:***@"),
       # Common env-style: KEY=value where KEY ends in _KEY/_TOKEN/_SECRET/_PASSWORD
       (re.compile(r"\b([A-Z_]+(?:_KEY|_TOKEN|_SECRET|_PASSWORD))=([^\s'\"]+)"), r"\1=***"),
   ]

   def redact_secrets(text: str) -> str:
       for pattern, replacement in _PATTERNS:
           text = pattern.sub(replacement, text)
       return text
   ```
2. В `runtime/thin/errors.py:provider_runtime_crash` обернуть exc message:
   ```python
   message=redact_secrets(f"LLM API error ({provider}): {type(exc).__name__}: {exc}")
   ```
3. В `runtime/cli/runtime.py:248` обернуть `stderr_data.decode()`.
4. В `serve/app.py:128-131` обернуть `str(exc)`.
5. В `jsonl_sink.py` — использовать те же patterns (DRY) для default `redact_value_patterns`.

**Testing (TDD):**
1. `test_redact_secrets_bearer_token` — `redact_secrets("Bearer abc123def456ghijklmnop")` → `"Bearer ***"`.
2. `test_redact_secrets_openai_key` — `"sk-proj-abc123def456ghi789jkl012"` → `"sk-***"`.
3. `test_redact_secrets_anthropic_key` — `"sk-ant-api03-..."` → `"sk-ant-***"`.
4. `test_redact_secrets_github_token` — `"ghp_abcd1234..."` → `"ghp_***"`.
5. `test_redact_secrets_url_userinfo` — `"https://user:pass@proxy.example.com"` → `"https://***:***@proxy.example.com"`.
6. `test_redact_secrets_env_assignment` — `"OPENAI_API_KEY=sk-real-secret"` → `"OPENAI_API_KEY=***"`.
7. `test_redact_secrets_no_match_unchanged` — `"hello world"` → `"hello world"` (idempotent).
8. `test_redact_secrets_multiple_patterns_in_one_text` — все matchings simultaneously.
9. `test_provider_runtime_crash_redacts_message` — `provider_runtime_crash("openai", RuntimeError("Bearer secret-token-here"))` → `error.message` does NOT contain `"secret-token-here"`.
10. `test_cli_runtime_error_redacts_stderr` — mock CLI subprocess returncode!=0 with stderr containing `"sk-real-key"` → resulting RuntimeEvent.error.message redacted.
11. `test_serve_500_response_redacts_secrets` — `agent.query` raises `RuntimeError("OPENAI_API_KEY=sk-real")` → response JSON `error` field redacted.
12. `test_jsonl_sink_uses_shared_redaction` — DRY check: `JsonlTelemetrySink` default redact_value_patterns включает те же patterns.

**Edge cases:**
- Multiline text (CLI stderr) — patterns с `re.MULTILINE`? **Decision:** все regex без MULTILINE, но используют `\b` boundaries — работают line-by-line автоматически.
- Unicode в secret — `[A-Za-z0-9_\-]` exclusively ASCII; non-ASCII secrets не matchятся (acceptable — known providers all use ASCII).
- Performance: patterns compiled module-level (single compilation). 6 patterns × short error message → microseconds.
- False positives: short tokens (<16 chars) НЕ matchятся → реальные API keys всегда длиннее.

**Commands to verify:**
```bash
pytest tests/unit/test_redaction.py -v
pytest tests/unit/test_runtime_errors_redaction.py -v
pytest tests/unit/test_serve_app.py -v
pytest tests/unit/test_jsonl_telemetry_sink.py -v
pytest -q
ty check src/swarmline/
```

**DoD (SMART):**
- [ ] 12 new tests + green
- [ ] `observability/redaction.py` с `redact_secrets(text)` exported via `swarmline.observability.__init__.py`
- [ ] `provider_runtime_crash` + CLI runtime stderr + serve 500 response — все применяют redaction
- [ ] `JsonlTelemetrySink` default `redact_value_patterns` использует те же compiled patterns (DRY)
- [ ] No regression in 5452 existing tests
- [ ] `ty check` baseline = 0

**Commit message:**
```
feat(security): redact secrets in runtime/CLI/serve error messages

Closes audit finding P2 #6 — provider exceptions, CLI subprocess stderr,
and HTTP 500 responses could include Bearer tokens, sk-* API keys,
URL userinfo, and KEY=value env strings.

New observability/redaction.py applies common secret patterns; reused by
JsonlTelemetrySink for DRY compliance.
```

---

<!-- mb-stage:7 -->
## Stage 7: Final validation + version bump candidate

**Source:** Release gate
**Effort:** ~30 min
**Type:** release prep

**Что делаем:**
1. Final full-suite test run, baseline metrics:
   ```bash
   pytest --tb=no -q                    # expect 5452 + ~37 new tests = ~5489 passed
   ruff check src/ tests/               # All checks passed
   ruff format --check src/ tests/
   ty check src/swarmline/              # baseline = 0
   pip-audit --strict --ignore-vuln GHSA-*-*-*  # if any prior allowlist
   ```
2. Bump `pyproject.toml` version `1.5.0 → 1.5.1`.
3. Bump `src/swarmline/serve/app.py` `_VERSION = "1.5.1"`.
4. Finalize `CHANGELOG.md [1.5.1]` entry с reference на audit findings.
5. Smoke test: `python examples/00_hello_world.py` (offline) — passes.

**DoD (SMART):**
- [ ] All 7 quality gates green (pytest, ruff×2, ty, pip-audit, smoke, version bump)
- [ ] CHANGELOG [1.5.1] entry references all 6 findings + Stage 5 BC note
- [ ] `pyproject.toml` version = 1.5.1
- [ ] `src/swarmline/serve/app.py` `_VERSION` = 1.5.1
- [ ] All commits pushed to private `origin` (NOT public sync — operator decision per usual)

**Commit message:**
```
release: v1.5.1 (security audit 2026-04-27 closure)

6 findings fixed:
- P1: namespace `.` rejection (cross-tenant FS collision)
- P1: pi_sdk env allowlist (subprocess secret leak)
- P2: E2B sh -c denylist resolution
- P2: web_fetch scheme allowlist (http/https only)
- P2: serve host=None hard-fail (BREAKING, warned in v1.5.0)
- P2: secret redaction in error messages

Plan: .memory-bank/plans/2026-04-27_fix_security-audit.md
```

---

## Suggested execution order

| Order | Stage | Severity | Effort | Notes |
|-------|-------|----------|--------|-------|
| 1 | Stage 1 (path `.`) | P1 | 30 min | Simplest, highest severity → first |
| 2 | Stage 2 (pi_sdk env) | P1 | 1.5 h | Includes DRY refactor of CLI helper |
| 3 | Stage 4 (URL scheme) | P2 | 30 min | Quick win, low risk |
| 4 | Stage 3 (E2B shell) | P2 | 1 h | Localized to one provider |
| 5 | Stage 6 (redaction) | P2 | 2 h | Most cross-cutting, last before BC change |
| 6 | Stage 5 (host=None) | P2 BC | 45 min | Last because BC; ensures other fixes shipped even if BC reverted |
| 7 | Stage 7 (release) | — | 30 min | Final validation + version bump |

**Total estimate:** ~7 h (1 focused day или 2 split sessions: P1 stages on day 1, P2 + release on day 2).

---

## Out-of-scope mentioned for traceability (NOT in this plan)

- General sandbox redesign — Local/Docker/OpenShell уже корректны.
- Audit log of secret-redaction events — defer; current reasonable assumption that operator monitors `error_count` metric.
- LSP-style type narrowing для `urlparse` returns — defer.
- Refactor `serve/app.py` middleware ordering — defer (M-1 + M-3 already shipped в v1.5.0).
