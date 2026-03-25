"""
ECO (Engineering Change Order) tools for managing ECOs via the Source Parts API.

ECOs bundle related ECNs and gate build readiness. The build button on
source.parts/build stays locked until every ECN under every ECO reaches
CLOSED or IMPLEMENTED status.

Remote-only: The API clones project repos, reads/writes ECO files, and can
push commits or create PRs. For local operations, use the `parts` CLI:

    parts project eco list
    parts project eco get ECO-001
    parts project eco create --id ECO-002 --title "..." --revision "EVT2"
    parts project eco approve ECO-001
    parts project eco build-status
"""
import logging
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsAPIError, get_client, with_user_context

logger = logging.getLogger(__name__)

# --- Constants ---

VALID_ECO_STATUSES = {
    "PENDING CLIENT AUTHORIZATION",
    "AUTHORIZED",
    "IN PROGRESS",
    "COMPLETED",
    "REJECTED",
}


# --- Tool registration ---


def register_eco_tools(mcp: FastMCP) -> None:
    """Register ECO management tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    async def eco_list(
        project_id: str,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List all Engineering Change Orders (ECOs) in a project.

        Returns each ECO with its bundled ECN IDs, status, and a summary
        of how many ECNs are resolved vs blocking.

        Args:
            project_id: Source Parts project ID or git repo URL
            status: Filter by ECO status (e.g. AUTHORIZED, PENDING CLIENT AUTHORIZATION)

        Returns:
            List of ECO summaries with per-ECO resolution counts
        """
        try:
            client = get_client()
            params: dict[str, Any] = {}
            if status:
                params["status"] = status

            return client._make_request(
                "GET", f"projects/{project_id}/ecos",
                params=params or None,
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECO list failed: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def eco_get(
        project_id: str,
        eco_id: str,
    ) -> dict[str, Any]:
        """Get full details of a specific ECO including all its ECNs.

        Returns the ECO metadata, full markdown body, and the complete list
        of bundled ECNs with their current statuses.

        Args:
            project_id: Source Parts project ID or git repo URL
            eco_id: ECO identifier (e.g. 'ECO-001')

        Returns:
            ECO metadata, body content, and nested ECN list with statuses
        """
        try:
            client = get_client()
            return client._make_request(
                "GET", f"projects/{project_id}/ecos/{eco_id}",
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECO get failed: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def eco_create(
        project_id: str,
        eco_id: str,
        title: str,
        revision: str,
        ecn_ids: list[str] | None = None,
        author: str = "",
        body: str = "",
        create_pr: bool = False,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Engineering Change Order (ECO) that bundles ECNs.

        The API clones the repo, creates the ECO file in ECO/, commits,
        and optionally creates a PR.

        Args:
            project_id: Source Parts project ID or git repo URL
            eco_id: ECO identifier (e.g. 'ECO-003')
            title: ECO title describing the change scope
            revision: Revision identifier (e.g. 'EVT1 → EVT2', 'DVT updates')
            ecn_ids: List of ECN IDs to bundle (e.g. ['ECN-041', 'ECN-042'])
            author: Author name
            body: ECO body content (markdown)
            create_pr: If True, create a pull request with the change
            branch: Target branch for the commit

        Returns:
            Created ECO metadata and optional PR URL
        """
        try:
            client = get_client()
            json_data: dict[str, Any] = {
                "id": eco_id,
                "title": title,
                "revision": revision,
                "author": author or "Unknown",
            }
            if ecn_ids:
                json_data["ecn_ids"] = ecn_ids
            if body:
                json_data["body"] = body
            if create_pr:
                json_data["create_pr"] = True
            if branch:
                json_data["branch"] = branch

            return client._make_request(
                "POST", f"projects/{project_id}/ecos",
                json_data=json_data,
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECO create failed: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def eco_update(
        project_id: str,
        eco_id: str,
        status: str | None = None,
        title: str | None = None,
        revision: str | None = None,
        ecn_ids: list[str] | None = None,
        body: str | None = None,
        create_pr: bool = False,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing ECO's metadata or status.

        Only the fields you provide will be changed. Use this to authorize
        an ECO, update its ECN list, or change its status.

        Args:
            project_id: Source Parts project ID or git repo URL
            eco_id: ECO identifier (e.g. 'ECO-001')
            status: New status (PENDING CLIENT AUTHORIZATION, AUTHORIZED, IN PROGRESS, COMPLETED, REJECTED)
            title: New title
            revision: New revision string
            ecn_ids: Updated list of bundled ECN IDs
            body: New body content (replaces entire body)
            create_pr: If True, create a PR with the change
            branch: Target branch for the commit

        Returns:
            Updated ECO metadata and optional PR URL
        """
        if status is not None and status not in VALID_ECO_STATUSES:
            return {"error": f"Invalid status {status!r}. Must be one of: {', '.join(sorted(VALID_ECO_STATUSES))}"}

        try:
            client = get_client()
            json_data: dict[str, Any] = {}
            if status is not None:
                json_data["status"] = status
            if title is not None:
                json_data["title"] = title
            if revision is not None:
                json_data["revision"] = revision
            if ecn_ids is not None:
                json_data["ecn_ids"] = ecn_ids
            if body is not None:
                json_data["body"] = body
            if create_pr:
                json_data["create_pr"] = True
            if branch:
                json_data["branch"] = branch

            return client._make_request(
                "PATCH", f"projects/{project_id}/ecos/{eco_id}",
                json_data=json_data,
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECO update failed: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def eco_approve(
        project_id: str,
        eco_id: str,
        approved_ecn_ids: list[str] | None = None,
        note: str = "",
        create_pr: bool = False,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Approve an ECO and optionally batch-approve its ECNs.

        Sets the ECO status to AUTHORIZED. If approved_ecn_ids is provided,
        those ECNs are also moved to APPROVED status. If omitted, all ECNs
        under the ECO are approved.

        Args:
            project_id: Source Parts project ID or git repo URL
            eco_id: ECO identifier (e.g. 'ECO-001')
            approved_ecn_ids: Specific ECN IDs to approve (default: all ECNs in this ECO)
            note: Optional approval note or comment
            create_pr: If True, create a PR with the changes
            branch: Target branch for the commit

        Returns:
            Approval result with list of ECNs that were approved
        """
        try:
            client = get_client()
            json_data: dict[str, Any] = {}
            if approved_ecn_ids is not None:
                json_data["approved_ecn_ids"] = approved_ecn_ids
            if note:
                json_data["note"] = note
            if create_pr:
                json_data["create_pr"] = True
            if branch:
                json_data["branch"] = branch

            return client._make_request(
                "POST", f"projects/{project_id}/ecos/{eco_id}/approve",
                json_data=json_data,
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECO approve failed: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def eco_build_status(
        project_id: str,
    ) -> dict[str, Any]:
        """Check build readiness — are all ECOs/ECNs resolved?

        Returns a summary of every ECO and its ECNs, with counts of how many
        are blocking the build. The build is ready only when every ECN across
        all ECOs has reached CLOSED or IMPLEMENTED status.

        This powers the locked/unlocked state of the Build button on
        source.parts/build.

        Args:
            project_id: Source Parts project ID or git repo URL

        Returns:
            Build readiness status with per-ECO breakdown:
            - build_ready: bool
            - total_ecns: int
            - resolved_ecns: int
            - blocking_ecns: int
            - critical_blocking: int
            - ecos: list of ECO summaries with nested ECN statuses
        """
        try:
            client = get_client()
            return client._make_request(
                "GET", f"projects/{project_id}/ecos/build-status",
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ECO build-status failed: %s", e)
            return {"error": str(e)}
