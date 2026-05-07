"""
EDA file format conversion tools (Altium → KiCad, async).

Wraps the API's POST /v1/convert/altium → 202 + job_id flow plus the
GET /v1/convert/jobs/<id> status endpoint and POST /pin endpoint. KiCad 10
is the default target; pass target_version="7"|"8"|"9" to chain through
the same kicad-version downconverter that backs /v1/convert/kicad/version.
"""
import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsAPIError, get_client, with_user_context

logger = logging.getLogger(__name__)

# Match the API's MAX_FILE_SIZE (100 MB).
MAX_FILE_SIZE = 100 * 1024 * 1024

ALTIUM_EXTENSIONS = {
    ".prjpcb", ".schdoc", ".pcbdoc",
    ".intlib", ".pcblib", ".schlib",
    ".zip",
}

VALID_TARGET_VERSIONS = {"7", "8", "9", "10"}


def register_convert_tools(mcp: FastMCP, local_mode: bool = True) -> None:
    """Register conversion tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    async def convert_altium(
        file_path: str,
        target_version: str = "10",
        pin_project_id: str | None = None,
    ) -> dict[str, Any]:
        """Start an async Altium → KiCad conversion job.

        Returns immediately with a job_id. Poll convert_status to watch
        progress; once status=="succeeded" the response includes a
        presigned output_url valid for one hour. Pass pin_project_id to
        also request that the result be attached to a project on success.

        Args:
            file_path: Local path to an Altium project file or zip
                (.PrjPcb / .SchDoc / .PcbDoc / .IntLib / .PcbLib /
                .SchLib / .zip).
            target_version: KiCad major version. "10" (default), "9",
                "8", or "7". Versions <10 are produced by chaining
                through the kicad-version downconverter.
            pin_project_id: Optional. If supplied AND the conversion
                succeeds during this call (it usually won't —
                conversions are async), pin the output to the given
                project_id. Most callers should poll convert_status
                first and call convert_pin once succeeded.

        Returns:
            { success, job_id, status_url, target_version, ... }
        """
        if not local_mode:
            return {"success": False, "error": "convert_altium requires local_mode (file upload)"}

        if target_version not in VALID_TARGET_VERSIONS:
            return {
                "success": False,
                "error": f"target_version must be one of: {sorted(VALID_TARGET_VERSIONS)}",
            }

        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": f"File not found: {path}"}
        if not path.is_file():
            return {"success": False, "error": f"Not a file: {path}"}
        if path.suffix.lower() not in ALTIUM_EXTENSIONS:
            return {
                "success": False,
                "error": (
                    f"Expected an Altium project file (one of "
                    f"{sorted(ALTIUM_EXTENSIONS)}), got: {path.suffix}"
                ),
            }
        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            return {
                "success": False,
                "error": f"File too large: {size / 1024 / 1024:.1f} MB (max {MAX_FILE_SIZE / 1024 / 1024:.0f} MB)",
            }

        try:
            client = get_client()
            response = client.convert_altium_start(
                file_data=path.read_bytes(),
                filename=path.name,
                target_version=target_version,
            )
        except SourcePartsAPIError as e:
            return {"success": False, "error": f"API error: {e}"}
        except Exception as e:  # noqa: BLE001
            logger.exception("convert_altium upload failed")
            return {"success": False, "error": str(e)}

        data = response.get("data", {}) if isinstance(response, dict) else {}
        job_id = data.get("job_id")
        if not job_id:
            return {"success": False, "error": "API response missing job_id", "raw": response}

        out: dict[str, Any] = {
            "success": True,
            "job_id": job_id,
            "status_url": data.get("status_url"),
            "target_version": data.get("target_version", target_version),
        }
        if pin_project_id:
            out["pin_project_id"] = pin_project_id
            out["pin_hint"] = (
                "Conversions are async. Poll convert_status until status=='succeeded', "
                "then call convert_pin(job_id, project_id) to attach the output."
            )
        return out

    @mcp.tool()
    @with_user_context
    async def convert_status(job_id: str) -> dict[str, Any]:
        """Get the current state of an async convert job.

        Args:
            job_id: UUID returned by convert_altium.

        Returns:
            { success, status, progress_pct, kind, manifest?, output_url?,
              error?, pinned, pinned_to_project_id? } — output_url is
            populated only when status=='succeeded' and is a presigned
            URL valid for ~1 hour.
        """
        try:
            client = get_client()
            data = client.convert_job_status(job_id)
        except SourcePartsAPIError as e:
            return {"success": False, "error": f"API error: {e}"}
        except Exception as e:  # noqa: BLE001
            logger.exception("convert_status failed")
            return {"success": False, "error": str(e)}

        if not isinstance(data, dict):
            return {"success": False, "error": "Unexpected API response shape", "raw": data}

        return {
            "success": True,
            "job_id": data.get("job_id"),
            "kind": data.get("kind"),
            "status": data.get("status"),
            "progress_pct": data.get("progress_pct", 0),
            "target_version": data.get("target_version"),
            "output_url": data.get("output_url"),
            "manifest": data.get("manifest"),
            "error": data.get("error"),
            "pinned": data.get("pinned", False),
            "pinned_to_project_id": data.get("pinned_to_project_id"),
            "started_at": data.get("started_at"),
            "completed_at": data.get("completed_at"),
        }

    @mcp.tool()
    @with_user_context
    async def convert_pin(job_id: str, project_id: str) -> dict[str, Any]:
        """Pin a successful convert job's output to a project.

        Copies the temp output zip to
        parts-kicad/projects/<project_id>/imports/<job_id>.zip and
        sets pinned=true on the job row so the 30-day temp lifecycle
        sweep no longer touches it.

        Only succeeded jobs can be pinned (returns success=False with
        a 409-equivalent error otherwise).

        Args:
            job_id: UUID of a succeeded convert job.
            project_id: Target project to attach the output to.
        """
        if not job_id or not project_id:
            return {"success": False, "error": "job_id and project_id are required"}

        try:
            client = get_client()
            data = client.convert_job_pin(job_id, project_id)
        except SourcePartsAPIError as e:
            return {"success": False, "error": f"API error: {e}"}
        except Exception as e:  # noqa: BLE001
            logger.exception("convert_pin failed")
            return {"success": False, "error": str(e)}

        if not isinstance(data, dict):
            return {"success": False, "error": "Unexpected API response shape", "raw": data}

        return {
            "success": True,
            "job_id": data.get("job_id"),
            "pinned": data.get("pinned", False),
            "pinned_to_project_id": data.get("pinned_to_project_id"),
            "pinned_object_key": data.get("pinned_object_key"),
        }
