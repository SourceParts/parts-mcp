"""
Render pipeline MCP tools.

Provides trigger_part_render and check_render_status for the headless
Blender render pipeline. All renders are parametric — no LCSC assets.
"""
import logging
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsAPIError, get_client, with_user_context
from parts_mcp.utils.template_router import resolve_template

logger = logging.getLogger(__name__)


def register_render_tools(mcp: FastMCP) -> None:
    """Register render pipeline tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    async def trigger_part_render(
        sku: str | None = None,
        part_id: str | None = None,
        force: bool = False,
        template_override: str | None = None,
    ) -> dict[str, Any]:
        """Queue a Blender render job for an electronic component.

        Every image is generated from parametric .blend templates — no supplier
        assets. Pass either sku or part_id. The system will match the part to
        the correct Blender template based on category, package, and MPN suffix.

        Args:
            sku: Source Parts SKU (required if no part_id)
            part_id: Internal part ID (required if no sku)
            force: If false (default), skip if a render already exists
            template_override: Force a specific .blend template file

        Returns:
            Job ID and status, or existing render URL if short-circuited
        """
        if not sku and not part_id:
            return {"error": "Either sku or part_id is required"}

        try:
            client = get_client()

            # Step 1: Resolve SKU → part details
            if sku and not part_id:
                resolve_data = client._make_request("GET", "/renders/resolve", params={"sku": sku})
                if not resolve_data.get("part_id"):
                    return {"error": f"Part not found for SKU: {sku}"}
                part_id = resolve_data["part_id"]
                part_info = resolve_data
            else:
                part_info = client.get_part_details(part_id)

            # Step 2: Short-circuit if render exists and force=false
            if not force:
                render_url = part_info.get("render_url") or part_info.get("render_image_url")
                render_status = part_info.get("render_status")
                if render_url and render_status == "complete":
                    return {
                        "job_id": None,
                        "render_status": "complete",
                        "render_url": render_url,
                        "message": "Render already exists. Pass force: true to re-render.",
                    }

            # Step 3: Route to template
            if template_override:
                template = template_override
                blender_params = {}
            else:
                part_record = {
                    "category": part_info.get("category"),
                    "package": part_info.get("package")
                        or (part_info.get("parameters", {}) or part_info.get("specifications", {})).get("package"),
                    "mpn": part_info.get("mpn")
                        or (part_info.get("parameters", {}) or part_info.get("specifications", {})).get("mpn", ""),
                    "parameters": part_info.get("parameters") or part_info.get("specifications") or {},
                }
                route = resolve_template(part_record)
                if route is None:
                    return {"error": f"No template matched for category={part_record['category']}, package={part_record['package']}"}
                template = route["template"]
                blender_params = route["blender_params"]

            # Step 4: Create the render job via API
            result = client._make_request("POST", "/renders/trigger", json_data={
                "part_id": part_id,
                "template": template,
                "blender_params": blender_params,
                "force": force,
            })

            return {
                "job_id": result.get("job_id"),
                "render_status": result.get("render_status", "queued"),
                "message": result.get("message", f"Render job queued: {template}"),
            }

        except SourcePartsAPIError as e:
            logger.error("trigger_part_render failed: %s", e)
            return {"error": str(e)}
        except Exception as e:
            logger.error("trigger_part_render unexpected error: %s", e)
            return {"error": f"Unexpected error: {e}"}

    @mcp.tool()
    @with_user_context
    async def check_render_status(
        job_id: str,
    ) -> dict[str, Any]:
        """Check the status of a Blender render job.

        Returns the CDN URL when the render is complete, or the error
        message if it failed.

        Args:
            job_id: The render job UUID from trigger_part_render

        Returns:
            Job status with render_url (when complete) or error (when failed)
        """
        if not job_id:
            return {"error": "job_id is required"}

        try:
            client = get_client()
            result = client._make_request("GET", f"/renders/status/{job_id}")

            return {
                "job_id": result.get("job_id", job_id),
                "render_status": result.get("render_status"),
                "render_url": result.get("render_url"),
                "error": result.get("error"),
                "elapsed_seconds": result.get("elapsed_seconds"),
            }

        except SourcePartsAPIError as e:
            logger.error("check_render_status failed: %s", e)
            return {"error": str(e)}
        except Exception as e:
            logger.error("check_render_status unexpected error: %s", e)
            return {"error": f"Unexpected error: {e}"}
