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

## Resolved

Entries below were previously suppressed and have since been eliminated
from the dependency tree. Kept here as an audit trail.

- **CVE-2025-64340, CVE-2026-27124 (`fastmcp`)** — resolved by the
  2.14.5 → 3.2.4 migration ([issue #1](https://github.com/SourceParts/parts-mcp/issues/1)).
- **CVE-2026-34444 (`lupa`)** — resolved as a side effect of the
  fastmcp 3.x migration; `fastmcp` 3.x no longer pulls in `pydocket`,
  so `fakeredis[lua]` and `lupa` are no longer in the tree.
- **CVE-2025-69872 (`diskcache`)** — resolved by replacing `diskcache`
  with an in-process TTL cache (`parts_mcp/utils/_ttl_cache.py`).
  `diskcache` is no longer a dependency.
