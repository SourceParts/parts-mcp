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

## Resolved

Entries below were previously suppressed and have since been eliminated
from the dependency tree. Kept here as an audit trail.

- **CVE-2025-64340, CVE-2026-27124 (`fastmcp`)** — resolved by the
  2.14.5 → 3.2.4 migration ([issue #1](https://github.com/SourceParts/parts-mcp/issues/1)).
- **CVE-2026-34444 (`lupa`)** — resolved as a side effect of the
  fastmcp 3.x migration; `fastmcp` 3.x no longer pulls in `pydocket`,
  so `fakeredis[lua]` and `lupa` are no longer in the tree.
