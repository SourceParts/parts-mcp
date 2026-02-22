"""
Project context tools for reading .parts/config.yaml and bridging with the Source Parts API.
"""
import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from parts_mcp.internal.project_config import (
    find_config_file,
    find_git_root,
    parse_config,
    resolve_file_paths,
)
from parts_mcp.utils.api_client import SourcePartsAPIError, get_client, with_user_context

logger = logging.getLogger(__name__)


def register_project_tools(mcp: FastMCP) -> None:
    """Register project context tools with the MCP server.

    Args:
        mcp: The FastMCP server instance
    """

    @mcp.tool()
    @with_user_context
    async def get_project_context(
        project_path: str | None = None,
        include_api_context: bool = True,
        include_file_listing: bool = False,
    ) -> dict[str, Any]:
        """Get project context from .parts/config.yaml and the Source Parts API.

        Reads the local .parts/config.yaml for project metadata, BOM locations,
        fabrication settings, and DFM rules. Optionally enriches with API data
        (BOMs, activity) if the project is linked to Source Parts.

        Args:
            project_path: Directory to search from (defaults to cwd)
            include_api_context: Fetch project data from the Source Parts API
            include_file_listing: Resolve and check referenced file paths

        Returns:
            Project context with local config and optional API data
        """
        start = Path(project_path) if project_path else Path.cwd()
        if not start.is_dir():
            return {"error": f"Not a directory: {start}"}

        # Find git root for context
        git_root = find_git_root(start)

        # Find and parse config
        config_path = find_config_file(start)
        if config_path is None:
            return {
                "error": "No .parts/config.yaml found",
                "searched_from": str(start),
                "git_root": str(git_root) if git_root else None,
                "hint": "Create a .parts/config.yaml in your project root",
            }

        config = parse_config(config_path)
        project_root = config_path.parent.parent  # .parts/ is one level down

        result: dict[str, Any] = {
            "config_path": str(config_path),
            "project_root": str(project_root),
            "git_root": str(git_root) if git_root else None,
            "config": config,
        }

        # Resolve file paths if requested
        if include_file_listing:
            result["files"] = resolve_file_paths(config, project_root)

        # Fetch API context if requested
        if include_api_context:
            api_context = await _fetch_api_context(config)
            if api_context:
                result["api"] = api_context

        return result


async def _fetch_api_context(config: dict[str, Any]) -> dict[str, Any] | None:
    """Fetch project data from the Source Parts API.

    Looks up by config.project.id (direct) or config.project.name (search).
    Returns None if no project info is in config or API is unavailable.
    """
    project_config = config.get("project", {})
    if not isinstance(project_config, dict):
        return None

    project_id = project_config.get("id")
    project_name = project_config.get("name")

    if not project_id and not project_name:
        return None

    try:
        client = get_client()
    except Exception:
        logger.debug("API client unavailable, skipping API context")
        return None

    api_data: dict[str, Any] = {}

    try:
        # Look up by ID first, fall back to name search
        if project_id:
            api_data["project"] = client.get_project(project_id)
        elif project_name:
            projects_resp = client.list_projects(search=project_name)
            projects = (
                projects_resp
                if isinstance(projects_resp, list)
                else projects_resp.get("projects", [])
            )
            if projects:
                api_data["project"] = projects[0]
                project_id = projects[0].get("id")

        # Fetch BOMs and activity if we have a project ID
        if project_id or (api_data.get("project") and api_data["project"].get("id")):
            pid = project_id or api_data["project"]["id"]
            try:
                api_data["boms"] = client.get_project_boms(pid)
            except SourcePartsAPIError as e:
                api_data["boms_error"] = str(e)

            try:
                api_data["activity"] = client.get_project_activity(pid)
            except SourcePartsAPIError as e:
                api_data["activity_error"] = str(e)

    except SourcePartsAPIError as e:
        api_data["error"] = str(e)
    except Exception as e:
        logger.warning(f"Unexpected error fetching API context: {e}")
        api_data["error"] = str(e)

    return api_data if api_data else None
