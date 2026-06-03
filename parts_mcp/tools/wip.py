"""
Work-in-Progress (WiP) engineering report MCP tools.

Mirrors the `parts doc wip` CLI surface:

  doc_wip_new      — scaffold a new WiP report from the template (local)
  doc_wip_preview  — audit a report for IP-leak / style issues (local)
  doc_wip_send     — render PDF + email via /api/pdf/doc/wip/send
  doc_wip_history  — list past deliveries via /api/pdf/doc/wip/history

The `new` and `preview` paths are pure-local and replicate the same
template + audit-rule set as the Go CLI in
parts.sh/parts-cli/commands/doc_wip*.go. Keep them in sync when the
CLI's template evolves.

The `send` and `history` paths talk to the landing-page deployment
(source.parts/api/pdf/...) via the vercel.json rewrite to
pdf-api-five.vercel.app. They use httpx directly because the
shared api_client is pinned to api.source.parts.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP


LANDING_PAGE_BASE = os.environ.get(
    "PARTS_LANDING_URL", "https://source.parts"
).rstrip("/")


# ----- template + audit (mirror parts-cli/commands/doc_wip*.go) -----


WIP_REPORT_TEMPLATE = """# [REV / MILESTONE] — [Subject]

| Field      | Value                                |
|------------|--------------------------------------|
| Project    | {project}                            |
| Report     | {slug}                               |
| Date       | {date}                               |
| Prepared by| Source Parts Inc.                    |
| Status     | Engineering work in progress         |

## Executive summary

[2-5 sentences. What changed since the last touchpoint, what's the
single most important thing the reader needs to know, what's the
overall posture (on-track / blocked / decision-needed). Keep it
scannable — the reader may not read past this.]

## [Current state — by area]

[Pick the structure that fits the engagement. Common patterns:

- "Filed ECO status" table for hardware rev work
- "Open issues" table for software / firmware bugs
- "Test results" table for QA / characterization work
- "Milestones" timeline for project management updates

Use tables for status; reserve prose for explanation.]

## Recommended but not yet filed

[Items that became apparent during the period — recommendations the
client should consider. Always include reasoning ("Why") not just
the recommendation. This is where you add value beyond status.]

## Remaining work

[Concrete punch list. If a phase has many items, sub-section by phase
or area. Each item should be actionable.]

## Suggested next steps

[Sequenced priority list. Ground it in cost/impact tradeoffs so the
client can re-sequence if their priorities differ from ours.]

Next snapshot will be issued after [milestone] or at the next client
checkpoint, whichever is sooner.

---

<!--
Template notes for the author — DELETE before sending.

CHECKLIST before delivery:
  [ ] Absolute filepaths to internal IP repos removed
  [ ] No internal hostnames, credentials, or IPs leaked
  [ ] No "AI", "Claude", "ChatGPT", "LLM", "AI assistant" references
  [ ] No "client-facing", "client-visible", "customer-facing" phrasing
  [ ] Executive summary scannable in <30 seconds
  [ ] Recommendations include reasoning, not just verdicts
  [ ] Date in front-matter matches today

Run the audit before delivery: doc_wip_preview <this-file>
-->
"""


# Audit rules — must stay in sync with
# parts.sh/parts-cli/commands/doc_wip_audit.go
_AUDIT_RULES = [
    {
        "name": "absolute-filepath-internal",
        "pattern": re.compile(
            r"(^|[^A-Za-z0-9_/-])(/run/media/|/home/[A-Za-z0-9_-]+/|/Users/[A-Za-z0-9_-]+/|/mnt/[A-Za-z0-9_-]+/)",
            re.MULTILINE,
        ),
        "severity": "error",
        "message": "absolute filesystem path to a user/dev location — strip or replace with a relative or symbolic reference",
        "skip_in_code": True,
    },
    {
        "name": "ai-attribution",
        "pattern": re.compile(
            r"\b(claude|chatgpt|gpt-?\d|copilot|ai assistant|llm)\b",
            re.IGNORECASE,
        ),
        "severity": "error",
        "message": "AI / LLM attribution in body text — work is attributed to Source Parts Inc.",
        "skip_in_code": False,
    },
    {
        "name": "client-facing-meta",
        "pattern": re.compile(
            r"\b(client-facing|client-visible|customer-facing)\b",
            re.IGNORECASE,
        ),
        "severity": "warning",
        "message": "meta phrasing about audience — the report IS the client-facing artifact, no need to comment on that",
        "skip_in_code": False,
    },
    {
        "name": "template-author-checklist",
        "pattern": re.compile(r"Template notes for the author — DELETE before sending"),
        "severity": "error",
        "message": "template author-checklist comment block is still in the file — delete it before sending",
        "skip_in_code": False,
    },
]

_FRONT_MATTER_DATE_RE = re.compile(
    r"^\|\s*Date\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|",
    re.IGNORECASE | re.MULTILINE,
)


def _sanitize_slug(s: str) -> str:
    """Filesystem-safe version of input. A-Z a-z 0-9 hyphen only."""
    out = []
    prev_hyphen = False
    for ch in s:
        if ch.isalnum() and ord(ch) < 128:
            out.append(ch)
            prev_hyphen = False
        elif not prev_hyphen and out:
            out.append("-")
            prev_hyphen = True
    return "".join(out).strip("-")


def _run_audit(markdown: str) -> list[dict]:
    """Return list of {severity, rule, line, match, message} findings."""
    findings: list[dict] = []
    in_code = False
    lines = markdown.split("\n")

    for line_no, line in enumerate(lines, 1):
        trimmed = line.lstrip()
        if trimmed.startswith("```"):
            in_code = not in_code
            continue
        for rule in _AUDIT_RULES:
            if in_code and rule["skip_in_code"]:
                continue
            m = rule["pattern"].search(line)
            if not m:
                continue
            match_text = m.group(0)
            if len(match_text) > 80:
                match_text = match_text[:80] + "..."
            findings.append(
                {
                    "severity": rule["severity"],
                    "rule": rule["name"],
                    "line": line_no,
                    "match": match_text,
                    "message": rule["message"],
                }
            )

    # Front-matter check
    fm = _FRONT_MATTER_DATE_RE.search(markdown)
    if fm is None:
        findings.append(
            {
                "severity": "warning",
                "rule": "front-matter-missing",
                "line": 0,
                "match": "",
                "message": "canonical front-matter table (with Date row) not found",
            }
        )
    else:
        try:
            from datetime import date, datetime

            fm_date = datetime.strptime(fm.group(1), "%Y-%m-%d").date()
            age_days = (date.today() - fm_date).days
            if age_days > 7:
                findings.append(
                    {
                        "severity": "warning",
                        "rule": "stale-date",
                        "line": 0,
                        "match": fm.group(1),
                        "message": f"front-matter Date is {age_days} days old; update to today before delivery",
                    }
                )
        except ValueError:
            pass

    return findings


# ----- HTTP helper for landing-page endpoints -----


def _landing_post(
    path: str,
    json_payload: dict | None = None,
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
    data: dict | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """POST to the landing-page deployment (source.parts/api/pdf/...).

    Uses httpx directly because the shared api_client is pinned to
    api.source.parts.
    """
    url = f"{LANDING_PAGE_BASE}{path}"
    headers = {"User-Agent": "PARTS-MCP/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if files:
        response = httpx.post(
            url, files=files, data=data, headers=headers, timeout=60.0
        )
    elif json_payload is not None:
        headers["Content-Type"] = "application/json"
        response = httpx.post(url, json=json_payload, headers=headers, timeout=60.0)
    else:
        response = httpx.post(url, data=data or {}, headers=headers, timeout=60.0)
    response.raise_for_status()
    return response.json()


def _landing_get(
    path: str,
    params: dict | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    url = f"{LANDING_PAGE_BASE}{path}"
    headers = {"User-Agent": "PARTS-MCP/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = httpx.get(url, params=params or {}, headers=headers, timeout=30.0)
    response.raise_for_status()
    return response.json()


# ----- MCP tool registration -----


def register_wip_tools(mcp: FastMCP) -> None:
    """Register parts doc wip tools."""

    @mcp.tool()
    async def doc_wip_new(
        project: str,
        out_path: str | None = None,
        slug: str | None = None,
    ) -> dict[str, Any]:
        """Scaffold a new WiP engineering report from the standard template.

        Writes a markdown file at out_path (or Reports/<slug>.md by
        default). Refuses to overwrite an existing file.

        Args:
            project: Short project slug (e.g. "capstone-rev-b")
            out_path: Output path (default: Reports/<slug>.md)
            slug: Override the auto-generated slug (default: WiP-<today>-<project>)
        """
        try:
            project = project.strip()
            if not project:
                return {"success": False, "error": "project slug required"}

            today = time.strftime("%Y-%m-%d")
            real_slug = slug or f"WiP-{today}-{_sanitize_slug(project)}"
            real_out = out_path or os.path.join("Reports", f"{real_slug}.md")

            p = Path(real_out)
            if p.exists():
                return {
                    "success": False,
                    "error": f"output file already exists: {real_out}",
                }
            p.parent.mkdir(parents=True, exist_ok=True)
            body = WIP_REPORT_TEMPLATE.format(
                project=project, slug=real_slug, date=today
            )
            p.write_text(body)
            return {
                "success": True,
                "path": str(p),
                "slug": real_slug,
                "next_step": "Edit the file, then run doc_wip_preview to validate before sending.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def doc_wip_preview(report_path: str) -> dict[str, Any]:
        """Audit a WiP report for IP-leak / formatting issues.

        Checks for:
          - Absolute filesystem paths to user/dev locations (error)
          - AI / LLM attribution in body text (error)
          - "Client-facing" meta phrasing (warning)
          - Template author-checklist not removed (error)
          - Front-matter table missing or with stale Date (warning)

        Returns findings list; agent should resolve all errors before
        calling doc_wip_send.

        Args:
            report_path: Path to the .md file to audit
        """
        try:
            p = Path(report_path)
            if not p.exists():
                return {"success": False, "error": f"file not found: {report_path}"}
            findings = _run_audit(p.read_text())
            errors = [f for f in findings if f["severity"] == "error"]
            return {
                "success": True,
                "findings": findings,
                "error_count": len(errors),
                "warning_count": len(findings) - len(errors),
                "ready_to_send": len(errors) == 0,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def doc_wip_send(
        report_path: str,
        to: list[str],
        project_name: str,
        client_name: str,
        client_email: str,
        subject: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """Send a WiP report — server renders PDF and emails it.

        Runs the audit in strict mode first; aborts if any errors.

        Args:
            report_path: Path to the .md file
            to: List of recipient email addresses (≥1)
            project_name: Project name for the email + DB row
            client_name: Recipient display name
            client_email: Primary client email (for DB row)
            subject: Email subject (default: derived from filename)
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            api_key: Optional Bearer token for the landing-page API
        """
        try:
            p = Path(report_path)
            if not p.exists():
                return {"success": False, "error": f"file not found: {report_path}"}
            markdown = p.read_text()

            findings = _run_audit(markdown)
            errors = [f for f in findings if f["severity"] == "error"]
            if errors:
                return {
                    "success": False,
                    "error": "audit has errors — fix them before sending",
                    "findings": errors,
                }

            if not to:
                return {"success": False, "error": "'to' must contain ≥1 recipient"}
            real_subject = subject or f"WiP report — {p.stem}"

            payload = {
                "project_name": project_name,
                "client_name": client_name,
                "client_email": client_email,
                "to": to,
                "subject": real_subject,
                "markdown": markdown,
                "file_name": p.name,
                "file_path": str(p),
            }
            if cc:
                payload["cc"] = cc
            if bcc:
                payload["bcc"] = bcc

            result = _landing_post(
                "/api/pdf/doc/wip/send", json_payload=payload, api_key=api_key
            )
            return {
                "success": True,
                "id": result.get("id"),
                "status": result.get("status"),
                "email_id": result.get("email_id"),
                "recipients": result.get("recipients", []),
                "pdf_bytes": result.get("pdf_bytes", 0),
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"API error {e.response.status_code}: {e.response.text[:300]}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def doc_wip_history(
        project: str | None = None,
        client: str | None = None,
        limit: int = 50,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """Show past WiP report deliveries for a project or client.

        Exactly one of project or client must be provided.

        Args:
            project: Filter by project name
            client: Filter by client email or name
            limit: Max rows (default 50, max 200)
            api_key: Optional Bearer token for the landing-page API
        """
        try:
            if not project and not client:
                return {
                    "success": False,
                    "error": "one of 'project' or 'client' is required",
                }
            params: dict = {"limit": min(max(limit, 1), 200)}
            if project:
                params["project"] = project
            if client:
                params["client"] = client
            result = _landing_get(
                "/api/pdf/doc/wip/history", params=params, api_key=api_key
            )
            return {
                "success": True,
                "rows": result.get("rows", []),
                "count": result.get("count", 0),
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"API error {e.response.status_code}: {e.response.text[:300]}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
