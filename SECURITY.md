# Security Policy

## Supported Versions

The swarmline maintainers commit to providing security updates for the
following versions:

| Version  | Status       | Security Updates                                    |
| :------- | :----------- | :-------------------------------------------------- |
| 1.5.x    | Current      | Active — all severity levels                        |
| 1.4.x    | Maintenance  | Critical-only fixes, until 2026-10-27 (6 months)    |
| < 1.4    | End-of-life  | No security updates                                 |

PATCH releases (1.5.0 → 1.5.1 → 1.5.2) carry security fixes within a minor
line. Users are strongly encouraged to track the latest PATCH on their minor
line and to upgrade minor lines within 6 months of release.

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, report privately via GitHub's Security Advisory mechanism:

- <https://github.com/fockus/swarmline/security/advisories/new>

If you cannot use GitHub Security Advisories, email the maintainers at the
contact address listed in `pyproject.toml` `[project.authors]` or open a
GitHub issue *without* exploit details and request a private channel.

### What to include

A useful report contains:

1. **Affected component** (file path, function, or feature) and version
   range
2. **Vulnerability class** (e.g. argument injection, SSRF, ReDoS, secret
   leakage, auth bypass) — CWE reference if you have one
3. **Reproduction steps** — minimal code or sequence that triggers the
   issue
4. **Impact assessment** — what an attacker can achieve, prerequisites,
   blast radius
5. **Suggested fix** if you have one

Reports that include a working proof-of-concept are prioritized.

## Response SLA

| Phase            | Target   | What happens                                                  |
| :--------------- | :------- | :------------------------------------------------------------ |
| Acknowledgement  | ≤ 48 h   | Maintainer confirms receipt and assigns a tracking ID         |
| Triage           | ≤ 14 d   | Severity classified (Critical / High / Medium / Low), CVE if applicable |
| Fix — Critical   | ≤ 30 d   | Patch + advisory + PyPI release; coordinated disclosure       |
| Fix — High       | ≤ 60 d   | Patch + advisory + PyPI release                               |
| Fix — Medium     | ≤ 90 d   | Patch in next PATCH release                                   |
| Fix — Low        | Best effort | Tracked in backlog, addressed in routine maintenance       |

These SLAs apply to vulnerabilities affecting the latest PATCH of each
supported minor line.

## Coordinated Disclosure

For Critical and High severity issues we coordinate disclosure:

1. Maintainer acknowledges and triages privately
2. Fix is developed in a private branch
3. Reporter is invited to review the fix and verify the mitigation
4. PyPI release is scheduled
5. Public advisory is published 7-14 days after PyPI release to give
   downstream users time to upgrade
6. CVE is requested via GitHub Security Advisory if applicable
7. Reporter is credited in the advisory and CHANGELOG (with their consent)

## Security Posture & Audit History

swarmline ships secure-by-default:

- **Default-deny tool policy** — explicit `ALWAYS_DENIED_TOOLS` frozenset
  (PascalCase + snake_case naming variants)
- **Sandbox isolation** — Docker default `cap_drop=["ALL"]`, `network_mode="none"`,
  `no-new-privileges=true`; E2B and OpenShell adapters available
- **Secret redaction** — structured logging emits redacted strings via
  `swarmline.observability.redaction` (URL userinfo, Anthropic / OpenAI keys,
  GitHub PATs)
- **Loopback gates** — control-plane HTTP servers (`a2a/server.py`,
  `daemon/health.py`, `serve/app.py`) refuse to bind unauthenticated
  endpoints to non-loopback hosts
- **`hmac.compare_digest`** — bearer token comparison uses constant-time
  comparison to defeat timing oracles
- **No `eval`/`exec`/`pickle`/`yaml.unsafe_load`/`shell=True`** anywhere in
  source — verified by grep across all 387 .py files
- **Parameterized SQL** — all SQL composition uses static WHERE clauses
  with bound parameters; no f-string interpolation of user data
- **Subprocess argv-only** — `asyncio.create_subprocess_exec` exclusively;
  no shell invocation; argv constructed from validated literals + bounded
  user input

### Past audits

| Date         | Scope                                  | Outcome                                              | Reference                |
| :----------- | :------------------------------------- | :--------------------------------------------------- | :----------------------- |
| 2026-04-25   | v1.5.0 release-blockers (T4 security)  | 30+ fixes; secret redaction; loopback gates          | `CHANGELOG.md` § 1.5.0   |
| 2026-04-27   | Post-release multi-perspective audit   | C1 ReDoS closure, C2/C3 version drift, C4 docs drift | `CHANGELOG.md` § 1.5.0   |
| 2026-04-27   | Full framework re-audit                | 0 Critical, 5 High, 11 Medium, 2 Low                 | `CHANGELOG.md` (pending) |

The full audit trail lives in the `CHANGELOG.md` security sections of each
PATCH release.

## Out of Scope

The following are **not** considered vulnerabilities:

- **User-supplied tool functions** that themselves contain vulnerabilities
  — swarmline executes user-registered tools; user-tool security is the
  user's responsibility
- **LLM prompt injection** — swarmline provides input/output guardrail
  hooks (`InputGuardrail`, `OutputGuardrail`) that users wire to their
  own moderation/classifier; we do not ship a built-in classifier
- **Dependency vulnerabilities** in extras you did not install — report
  these to the upstream package
- **Self-hosted misconfigurations** — using `allow_unauthenticated_query=True`
  with a non-loopback host is refused by the framework; using
  `auth_token=...` with a weak token is the operator's responsibility

## Hall of Fame

Security researchers who have responsibly disclosed vulnerabilities will
be credited here (with their permission).

_No public credits yet — internal audits only._
