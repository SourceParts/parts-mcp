"""
ECN (Engineering Change Notice) tools for managing ECNs via the Source Parts API.

Remote-only: The API clones project repos, reads/writes ECN files, and can
push commits or create PRs. For local operations, use the `parts` CLI directly:

    parts project ecn list
    parts project ecn get ECN-006
    parts project ecn create --id ECN-021 --title "..." --type "BOM Change" --severity HIGH --disposition REQUIRED
    parts project ecn validate
"""
import logging
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsAPIError, get_client, with_user_context

logger = logging.getLogger(__name__)

# --- Constants ---

VALID_TYPES = {
    "Design Constraint",
    "Assembly Note",
    "BOM Change",
    "Schematic Change",
    "Process Change",
}

VALID_DISPOSITIONS = {"REQUIRED", "RECOMMENDED", "OPTIONAL"}

VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}

VALID_STATUSES = {"OPEN", "IN REVIEW", "APPROVED", "IMPLEMENTED", "CLOSED"}


# --- Tool registration ---


def register_ecn_tools(mcp: FastMCP) -> None:
    """Register ECN management tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    async def ecn_list(
        project_id: str,
        severity: str | None = None,
        status: str | None = None,
        ecn_type: str | None = None,
    ) -> dict[str, Any]:
        """List all Engineering Change Notices (ECNs) in a project.

        The API clones the project repo and reads ECO/ECN-*.md files.
        For local projects, use the `parts` CLI: `parts project ecn list`

        Args:
            project_id: Source Parts project ID or git repo URL
            severity: Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)
            status: Filter by status (OPEN, IN REVIEW, APPROVED, IMPLEMENTED, CLOSED)
            ecn_type: Filter by type (Design Constraint, Assembly Note, BOM Change, Schematic Change, Process Change)

        Returns:
            List of ECN summaries with counts by severity and status
        """
        try:
            client = get_client()
            params: dict[str, Any] = {}
            if severity:
                params["severity"] = severity
            if status:
                params["status"] = status
            if ecn_type:
                params["type"] = ecn_type

            return client._make_request(
                "GET", f"projects/{project_id}/ecns",
                params=params or None,
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECN list failed: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def ecn_get(
        project_id: str,
        ecn_id: str,
    ) -> dict[str, Any]:
        """Get the full content of a specific ECN by ID.

        Returns both structured metadata and the full markdown body.
        For local projects, use: `parts project ecn get <ECN-ID>`

        Args:
            project_id: Source Parts project ID or git repo URL
            ecn_id: ECN identifier (e.g. 'ECN-006')

        Returns:
            ECN metadata and full body content
        """
        try:
            client = get_client()
            return client._make_request(
                "GET", f"projects/{project_id}/ecns/{ecn_id}",
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECN get failed: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def ecn_create(
        project_id: str,
        ecn_id: str,
        title: str,
        ecn_type: str,
        severity: str,
        disposition: str,
        category: str = "",
        author: str = "",
        source: str = "",
        affected: str = "",
        body: str = "",
        create_pr: bool = False,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Engineering Change Notice (ECN).

        The API clones the repo, creates the ECN file in ECO/, commits,
        and optionally pushes to a branch or creates a PR.
        For local projects, use: `parts project ecn create --id ECN-021 ...`

        Args:
            project_id: Source Parts project ID or git repo URL
            ecn_id: ECN identifier (e.g. 'ECN-021')
            title: ECN title describing the issue
            ecn_type: One of: Design Constraint, Assembly Note, BOM Change, Schematic Change, Process Change
            severity: One of: CRITICAL, HIGH, MEDIUM, LOW
            disposition: One of: REQUIRED, RECOMMENDED, OPTIONAL
            category: Optional category (e.g. Electrical, Mechanical, Thermal)
            author: Author name (defaults to 'Unknown')
            source: Source reference
            affected: Affected components
            body: ECN body content (markdown). If empty, a template is used.
            create_pr: If True, create a pull request with the change
            branch: Target branch for the commit (default: main)

        Returns:
            Created ECN metadata, file path, and optional PR URL
        """
        if ecn_type not in VALID_TYPES:
            return {"error": f"Invalid type {ecn_type!r}. Must be one of: {', '.join(sorted(VALID_TYPES))}"}
        if severity not in VALID_SEVERITIES:
            return {"error": f"Invalid severity {severity!r}. Must be one of: {', '.join(sorted(VALID_SEVERITIES))}"}
        if disposition not in VALID_DISPOSITIONS:
            return {"error": f"Invalid disposition {disposition!r}. Must be one of: {', '.join(sorted(VALID_DISPOSITIONS))}"}

        try:
            client = get_client()
            json_data: dict[str, Any] = {
                "id": ecn_id,
                "title": title,
                "type": ecn_type,
                "severity": severity,
                "disposition": disposition,
                "category": category,
                "author": author or "Unknown",
                "source": source,
                "affected": affected,
            }
            if body:
                json_data["body"] = body
            if create_pr:
                json_data["create_pr"] = True
            if branch:
                json_data["branch"] = branch

            return client._make_request(
                "POST", f"projects/{project_id}/ecns",
                json_data=json_data,
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECN create failed: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def ecn_update(
        project_id: str,
        ecn_id: str,
        status: str | None = None,
        severity: str | None = None,
        disposition: str | None = None,
        title: str | None = None,
        category: str | None = None,
        affected: str | None = None,
        source: str | None = None,
        body: str | None = None,
        create_pr: bool = False,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Update metadata or body of an existing ECN.

        The API clones the repo, modifies the ECN file, commits, and optionally
        creates a PR. Only the fields you provide will be changed.
        For local projects, use: `parts project ecn update ECN-006 --status CLOSED`

        Args:
            project_id: Source Parts project ID or git repo URL
            ecn_id: ECN identifier (e.g. 'ECN-006')
            status: New status (OPEN, IN REVIEW, APPROVED, IMPLEMENTED, CLOSED)
            severity: New severity (CRITICAL, HIGH, MEDIUM, LOW)
            disposition: New disposition (REQUIRED, RECOMMENDED, OPTIONAL)
            title: New title
            category: New category
            affected: New affected components
            source: New source reference
            body: New body content (replaces entire body)
            create_pr: If True, create a PR with the change
            branch: Target branch for the commit

        Returns:
            Updated metadata and optional PR URL
        """
        if status is not None and status not in VALID_STATUSES:
            return {"error": f"Invalid status {status!r}. Must be one of: {', '.join(sorted(VALID_STATUSES))}"}
        if severity is not None and severity not in VALID_SEVERITIES:
            return {"error": f"Invalid severity {severity!r}. Must be one of: {', '.join(sorted(VALID_SEVERITIES))}"}
        if disposition is not None and disposition not in VALID_DISPOSITIONS:
            return {"error": f"Invalid disposition {disposition!r}. Must be one of: {', '.join(sorted(VALID_DISPOSITIONS))}"}

        try:
            client = get_client()
            json_data: dict[str, Any] = {}
            if status is not None:
                json_data["status"] = status
            if severity is not None:
                json_data["severity"] = severity
            if disposition is not None:
                json_data["disposition"] = disposition
            if title is not None:
                json_data["title"] = title
            if category is not None:
                json_data["category"] = category
            if affected is not None:
                json_data["affected"] = affected
            if source is not None:
                json_data["source"] = source
            if body is not None:
                json_data["body"] = body
            if create_pr:
                json_data["create_pr"] = True
            if branch:
                json_data["branch"] = branch

            return client._make_request(
                "PATCH", f"projects/{project_id}/ecns/{ecn_id}",
                json_data=json_data,
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECN update failed: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def ecn_validate(
        project_id: str,
    ) -> dict[str, Any]:
        """Validate all ECN files for correct frontmatter schema.

        The API clones the repo and checks all ECO/ECN-*.md files for required
        fields, valid enum values, and filename/ID consistency.
        For local projects, use: `parts project ecn validate`

        Args:
            project_id: Source Parts project ID or git repo URL

        Returns:
            Validation results with error count and per-file details
        """
        try:
            client = get_client()
            return client._make_request(
                "POST", f"projects/{project_id}/ecns/validate",
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECN validate failed: %s", e)
            return {"error": str(e)}
