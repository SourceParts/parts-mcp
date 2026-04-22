# Security Policy

## Reporting a Vulnerability

Please report security issues privately via GitHub:

https://github.com/SourceParts/parts-mcp/security/advisories/new

Do not open a public issue for suspected vulnerabilities. We will acknowledge
receipt within a few business days.

## Dependency Scanning

`parts-mcp` dependencies are audited in CI with
[`pip-audit`](https://github.com/pypa/pip-audit) against the resolved
`uv.lock`. To reproduce the scan locally:

```bash
uv sync --all-extras --frozen
uv export --no-hashes --format requirements-txt --all-extras \
  | grep -v "^-e" > /tmp/reqs.txt
uvx pip-audit -r /tmp/reqs.txt --disable-pip --no-deps
```

## Known Non-Exploitable CVEs

The CVEs listed here are flagged by `pip-audit` but are not exploitable in
`parts-mcp`'s configuration. They are suppressed in CI via
`--ignore-vuln` flags in `.github/workflows/ci.yml`. Each entry below
documents the reasoning; remove the suppression once an upstream patch
lands and the dependency is bumped.

### CVE-2025-69872 — `diskcache`

- **Issue:** Unsafe pickle deserialization (CWE-94) in the default `Disk`
  backend. CVSS 5.2, local attack vector.
- **Why it does not apply:** `parts_mcp/utils/cache.py` initializes the
  cache with `disk=diskcache.JSONDisk`, so cached values are serialized as
  JSON, not pickle. Pickle is never invoked. All cached payloads are
  JSON-safe API response dicts.
- **Mitigation location:** `parts_mcp/utils/cache.py` (search for
  `JSONDisk`).
- **Upstream tracking:**
  https://github.com/grantjenks/python-diskcache/issues/357

### CVE-2026-34444 — `lupa`

- **Issue:** Sandbox escape in `LuaRuntime` via `getattr`/`setattr`
  bypassing `attribute_filter`. CVSS 7.9, remote attack vector where the
  server runs attacker-supplied Lua code.
- **Why it does not apply:** `parts-mcp` never imports `lupa` and never
  instantiates a `LuaRuntime`. Confirm with
  `grep -r "lupa\|LuaRuntime" parts_mcp/` (expected: no matches). The
  package is present transitively because of the chain
  `fastmcp` → `pydocket` → `fakeredis[lua]` → `lupa`, where `fakeredis`
  uses Lua only inside its own internal `EVAL` simulation during tests.
  No attacker-controlled Lua reaches any runtime in our process.
- **Upstream tracking:** https://github.com/advisories/GHSA-69v7-xpr6-6gjm

## Accepted Risk — Pending Migration

The CVEs below have upstream patches but those patches live in a major
version we have not migrated to yet. They are suppressed in CI to keep
the `security` job actionable; remove each suppression as part of the
migration PR.

### CVE-2025-64340, CVE-2026-27124 — `fastmcp`

- **Status:** Patched in `fastmcp 3.2.0`. Our `pyproject.toml` pins
  `fastmcp>=2.13.0,<3.0.0` because the 2.x → 3.x jump has breaking
  changes (the `fastmcp.utilities.ui` import path moved and the
  decorator / registration API was refactored).
- **Plan:** Tracked in
  [issue #1](https://github.com/SourceParts/parts-mcp/issues/1) with a
  researched migration checklist. Once `fastmcp 3.x` is adopted, bump
  the pin, run the full test suite, and remove both `--ignore-vuln`
  flags for these IDs from `.github/workflows/ci.yml`.
