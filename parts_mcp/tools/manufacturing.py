"""
Manufacturing and BOM tools for DFM analysis and BOM processing.
"""
import logging
import mimetypes
import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsAPIError, get_client, with_user_context

logger = logging.getLogger(__name__)

BOM_MIME_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".json": "application/json",
    ".xml": "application/xml",
}


def register_manufacturing_tools(mcp: FastMCP, local_mode: bool = True) -> None:
    """Register manufacturing and BOM tools with the MCP server.

    Args:
        mcp: The FastMCP server instance
        local_mode: If True, also register tools that need filesystem access
    """

    @mcp.tool()
    @with_user_context
    async def submit_dfm(
        project_id: str,
        bom_id: str | None = None,
        revision: str | None = None,
        notes: str | None = None,
        priority: str = "normal",
    ) -> dict[str, Any]:
        """Queue a DFM (Design for Manufacturability) analysis for a project.

        Args:
            project_id: Project ID to analyze
            bom_id: Optional BOM ID to include in analysis
            revision: Optional revision identifier
            notes: Optional notes for the analysis
            priority: Priority level ("low", "normal", "high")

        Returns:
            Submission result with job_id for tracking
        """
        try:
            client = get_client()
            result = client.submit_dfm(
                project_id=project_id,
                bom_id=bom_id,
                revision=revision,
                notes=notes,
                priority=priority,
            )

            return {
                "success": True,
                "job_id": result.get("job_id"),
                "status_url": result.get("status_url"),
                "message": "DFM analysis queued",
            }

        except SourcePartsAPIError as e:
            logger.error(f"DFM submission failed: {e}")
            return {
                "success": False,
                "project_id": project_id,
                "error": f"DFM submission failed: {e}",
            }

    @mcp.tool()
    @with_user_context
    async def check_dfm_status(job_id: str) -> dict[str, Any]:
        """Check the status of a DFM analysis job.

        Args:
            job_id: Job ID returned from submit_dfm

        Returns:
            Job status with progress and results when complete
        """
        try:
            client = get_client()
            status = client.get_manufacturing_status(job_id)

            response: dict[str, Any] = {
                "success": True,
                "job_id": job_id,
                "job_type": status.get("job_type"),
                "status": status.get("status"),
                "progress": status.get("progress"),
            }

            if status.get("status") == "complete":
                result = status.get("result", {})
                response["result"] = result
                response["message"] = "DFM analysis complete"

                issues = result.get("issues", [])
                warnings = result.get("warnings", [])
                if issues:
                    response["message"] = f"DFM analysis complete — {len(issues)} issue(s) found"
                elif warnings:
                    response["message"] = f"DFM analysis complete — {len(warnings)} warning(s)"
                else:
                    response["message"] = "DFM analysis complete — no issues found"

            elif status.get("status") == "failed":
                response["error"] = status.get("error", "Unknown error")
                response["message"] = "DFM analysis failed"

            else:
                pct = status.get("progress", 0)
                response["message"] = f"DFM analysis in progress ({pct}%)"

            return response

        except SourcePartsAPIError as e:
            logger.error(f"DFM status check failed: {e}")
            return {
                "success": False,
                "job_id": job_id,
                "error": f"Status check failed: {e}",
            }

    @mcp.tool()
    @with_user_context
    async def check_bom_status(job_id: str) -> dict[str, Any]:
        """Check BOM processing status and report unknown/unmatched parts.

        When processing is complete, automatically fetches the full BOM and
        separates parts into matched and unmatched lists. Unknown parts are
        highlighted so you can see which components need attention.

        Args:
            job_id: Job ID returned from upload_bom

        Returns:
            Processing status with matched/unmatched part breakdown when complete
        """
        try:
            client = get_client()
            status = client.get_bom_status(job_id)

            response: dict[str, Any] = {
                "success": True,
                "job_id": job_id,
                "status": status.get("status"),
                "progress": status.get("progress"),
            }

            if status.get("status") == "complete":
                bom_id = status.get("bom_id")
                response["bom_id"] = bom_id

                if bom_id:
                    bom_data = client.get_bom(bom_id)
                    lines = bom_data.get("lines", [])

                    matched = [ln for ln in lines if ln.get("matched")]
                    unmatched = [ln for ln in lines if not ln.get("matched")]

                    response["summary"] = {
                        "total_lines": len(lines),
                        "matched": len(matched),
                        "unmatched": len(unmatched),
                    }
                    response["matched_parts"] = matched
                    response["unknown_parts"] = [
                        {
                            "reference": ln.get("reference"),
                            "value": ln.get("value"),
                            "footprint": ln.get("footprint"),
                            "manufacturer": ln.get("manufacturer"),
                            "mpn": ln.get("mpn"),
                            "status": "unmatched",
                        }
                        for ln in unmatched
                    ]

                    if unmatched:
                        response["message"] = (
                            f"{len(unmatched)} of {len(lines)} parts are unknown "
                            "and being processed for addition to the database"
                        )
                    else:
                        response["message"] = f"All {len(lines)} parts matched successfully"
                else:
                    response["summary"] = status.get("summary", {})
                    response["message"] = "BOM processing complete"

            elif status.get("status") == "failed":
                response["error"] = status.get("error", "Unknown error")
                response["message"] = "BOM processing failed"

            else:
                pct = status.get("progress", 0)
                response["message"] = f"BOM processing in progress ({pct}%)"

            return response

        except SourcePartsAPIError as e:
            logger.error(f"BOM status check failed: {e}")
            return {
                "success": False,
                "job_id": job_id,
                "error": f"Status check failed: {e}",
            }

    # upload_bom needs filesystem access — only register in local mode
    if local_mode:
        @mcp.tool()
        @with_user_context
        async def upload_bom(file_path: str) -> dict[str, Any]:
            """Upload a BOM file for processing and part matching.

            Reads the file from the local filesystem, uploads it to the API for
            processing. Use check_bom_status with the returned job_id to track
            progress and see which parts are unknown.

            Supported formats: CSV, XLSX, XLS, JSON, XML.

            Args:
                file_path: Path to the BOM file on the local filesystem

            Returns:
                Upload result with job_id for tracking processing status
            """
            try:
                path = Path(file_path).expanduser().resolve()

                if not path.exists():
                    return {
                        "success": False,
                        "file_path": file_path,
                        "error": f"File not found: {path}",
                    }

                if not path.is_file():
                    return {
                        "success": False,
                        "file_path": file_path,
                        "error": f"Not a file: {path}",
                    }

                suffix = path.suffix.lower()
                content_type = BOM_MIME_TYPES.get(suffix)
                if not content_type:
                    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"

                file_data = path.read_bytes()
                client = get_client()
                result = client.upload_bom(
                    file_data=file_data,
                    filename=path.name,
                    content_type=content_type,
                )

                return {
                    "success": True,
                    "job_id": result.get("job_id"),
                    "status_url": result.get("status_url"),
                    "file": path.name,
                    "message": "BOM uploaded, processing started",
                }

            except SourcePartsAPIError as e:
                logger.error(f"BOM upload failed: {e}")
                return {
                    "success": False,
                    "file_path": file_path,
                    "error": f"BOM upload failed: {e}",
                }
            except OSError as e:
                logger.error(f"File read error: {e}")
                return {
                    "success": False,
                    "file_path": file_path,
                    "error": f"Could not read file: {e}",
                }

        logger.info("Registered upload_bom tool (local mode)")

    # =========================================================================
    # Fabrication Tools
    # =========================================================================

    @mcp.tool()
    @with_user_context
    async def quote_fabrication(
        project_id: str,
        quantity: int = 5,
        layers: int = 2,
        thickness: float = 1.6,
        surface_finish: str = "HASL",
        color: str = "green",
        priority: str = "normal",
    ) -> dict[str, Any]:
        """Get a fabrication quote for a project.

        Submits a fab quotation request using a project reference. Use
        upload_gerbers_for_quote to upload gerber files directly instead.

        Args:
            project_id: Project ID to quote
            quantity: Number of boards (default 5)
            layers: Number of PCB layers (default 2)
            thickness: Board thickness in mm (default 1.6)
            surface_finish: Surface finish (HASL, ENIG, OSP, etc.)
            color: Solder mask color (green, red, blue, black, white, yellow)
            priority: Priority level (low, normal, high)

        Returns:
            Quote result with job_id for tracking
        """
        try:
            client = get_client()
            result = client.create_fab_order(
                project_id=project_id,
                quantity=quantity,
                layers=layers,
                thickness=thickness,
                surface_finish=surface_finish,
                color=color,
                priority=priority,
            )

            return {
                "success": True,
                "job_id": result.get("job_id"),
                "status_url": result.get("status_url"),
                "message": "Fabrication quote submitted",
            }

        except SourcePartsAPIError as e:
            logger.error(f"Fab quote failed: {e}")
            return {
                "success": False,
                "project_id": project_id,
                "error": f"Fab quote failed: {e}",
            }

    @mcp.tool()
    @with_user_context
    async def check_manufacturing_status(job_id: str) -> dict[str, Any]:
        """Check the status of any manufacturing job (fab, DFM, AOI, QC).

        Args:
            job_id: Job ID returned from a manufacturing submission

        Returns:
            Job status with progress and results when complete
        """
        try:
            client = get_client()
            status = client.get_manufacturing_status(job_id)

            response: dict[str, Any] = {
                "success": True,
                "job_id": job_id,
                "job_type": status.get("job_type"),
                "status": status.get("status"),
                "progress": status.get("progress"),
            }

            if status.get("status") == "complete":
                response["result"] = status.get("result", {})
                response["message"] = f"{status.get('job_type', 'Job')} complete"
            elif status.get("status") == "failed":
                response["error"] = status.get("error", "Unknown error")
                response["message"] = f"{status.get('job_type', 'Job')} failed"
            else:
                pct = status.get("progress", 0)
                response["message"] = f"{status.get('job_type', 'Job')} in progress ({pct}%)"

            return response

        except SourcePartsAPIError as e:
            logger.error(f"Manufacturing status check failed: {e}")
            return {
                "success": False,
                "job_id": job_id,
                "error": f"Status check failed: {e}",
            }

    # =========================================================================
    # Cost Tools
    # =========================================================================

    @mcp.tool()
    @with_user_context
    async def estimate_cost(
        parts: list[dict[str, Any]],
        currency: str = "USD",
    ) -> dict[str, Any]:
        """Get a quick cost estimate for a list of parts.

        Each part should have at minimum a part_number and quantity field.

        Args:
            parts: List of parts, each with part_number and quantity
            currency: Currency code (default USD)

        Returns:
            Cost estimate with per-part and total breakdown
        """
        try:
            client = get_client()
            result = client.estimate_cost(parts=parts, currency=currency)

            return {
                "success": True,
                "estimate": result,
                "currency": currency,
                "message": f"Cost estimate for {len(parts)} part(s)",
            }

        except SourcePartsAPIError as e:
            logger.error(f"Cost estimation failed: {e}")
            return {
                "success": False,
                "error": f"Cost estimation failed: {e}",
            }

    # =========================================================================
    # Identification Tools
    # =========================================================================

    @mcp.tool()
    @with_user_context
    async def check_identification_status(job_id: str) -> dict[str, Any]:
        """Check the status of a PCB/component identification job.

        Args:
            job_id: Job ID returned from identify_pcb

        Returns:
            Status with identified items when complete
        """
        try:
            client = get_client()
            status = client.get_ingest_status(job_id)

            response: dict[str, Any] = {
                "success": True,
                "job_id": job_id,
                "status": status.get("status"),
                "progress": status.get("progress"),
            }

            if status.get("status") == "completed":
                response["items"] = status.get("items", [])
                response["message"] = f"Identification complete — {len(status.get('items', []))} item(s)"
            elif status.get("status") == "error":
                response["error"] = status.get("error", "Unknown error")
                response["message"] = "Identification failed"
            else:
                pct = status.get("progress", 0)
                response["message"] = f"Identification in progress ({pct}%)"

            return response

        except SourcePartsAPIError as e:
            logger.error(f"Identification status check failed: {e}")
            return {
                "success": False,
                "job_id": job_id,
                "error": f"Status check failed: {e}",
            }

    @mcp.tool()
    @with_user_context
    async def get_identified_item(short_code: str) -> dict[str, Any]:
        """Get details for an identified PCB/component by short code.

        Args:
            short_code: Item short code (e.g., SP-XXXXXX)

        Returns:
            Item details with barcodes, OCR text, and metadata
        """
        try:
            client = get_client()
            item = client.get_ingest_item(short_code)

            return {
                "success": True,
                "item": item,
                "short_code": short_code,
                "message": f"Item {short_code} retrieved",
            }

        except SourcePartsAPIError as e:
            logger.error(f"Get identified item failed: {e}")
            return {
                "success": False,
                "short_code": short_code,
                "error": f"Failed to get item: {e}",
            }

    # =========================================================================
    # Local-only Tools (filesystem access required)
    # =========================================================================

    if local_mode:
        @mcp.tool()
        @with_user_context
        async def upload_gerbers_for_quote(
            file_path: str,
            quantity: int = 5,
            layers: int = 2,
            thickness: float = 1.6,
            surface_finish: str = "HASL",
            color: str = "green",
            priority: str = "normal",
        ) -> dict[str, Any]:
            """Upload a gerber zip file to get a fabrication quote.

            Reads the gerber zip from disk and submits it for fabrication
            quotation. Use check_manufacturing_status with the returned job_id
            to track progress.

            Args:
                file_path: Path to the gerber zip file
                quantity: Number of boards (default 5)
                layers: Number of PCB layers (default 2)
                thickness: Board thickness in mm (default 1.6)
                surface_finish: Surface finish (HASL, ENIG, OSP, etc.)
                color: Solder mask color (green, red, blue, black, white, yellow)
                priority: Priority level (low, normal, high)

            Returns:
                Quote result with job_id for tracking
            """
            try:
                path = Path(file_path).expanduser().resolve()

                if not path.exists():
                    return {
                        "success": False,
                        "file_path": file_path,
                        "error": f"File not found: {path}",
                    }

                if not path.is_file():
                    return {
                        "success": False,
                        "file_path": file_path,
                        "error": f"Not a file: {path}",
                    }

                if path.suffix.lower() != ".zip":
                    return {
                        "success": False,
                        "file_path": file_path,
                        "error": f"Expected a .zip file, got: {path.suffix}",
                    }

                file_data = path.read_bytes()
                client = get_client()
                result = client.create_fab_order(
                    file_data=file_data,
                    filename=path.name,
                    content_type="application/zip",
                    quantity=quantity,
                    layers=layers,
                    thickness=thickness,
                    surface_finish=surface_finish,
                    color=color,
                    priority=priority,
                )

                return {
                    "success": True,
                    "job_id": result.get("job_id"),
                    "status_url": result.get("status_url"),
                    "file": path.name,
                    "message": "Gerbers uploaded, fabrication quote submitted",
                }

            except SourcePartsAPIError as e:
                logger.error(f"Gerber upload failed: {e}")
                return {
                    "success": False,
                    "file_path": file_path,
                    "error": f"Gerber upload failed: {e}",
                }
            except OSError as e:
                logger.error(f"File read error: {e}")
                return {
                    "success": False,
                    "file_path": file_path,
                    "error": f"Could not read file: {e}",
                }

        @mcp.tool()
        @with_user_context
        async def quote_assembly(
            gerber_path: str,
            bom_path: str,
            quantity: int = 5,
            layers: int = 2,
            thickness: float = 1.6,
            surface_finish: str = "HASL",
            color: str = "green",
            priority: str = "normal",
        ) -> dict[str, Any]:
            """Get a combined fabrication + assembly quote.

            Uploads gerbers for fab quotation and a BOM for assembly costing.
            Polls the BOM status to get a bom_id, then calculates COGS.

            Args:
                gerber_path: Path to the gerber zip file
                bom_path: Path to the BOM file (CSV, XLSX, etc.)
                quantity: Number of assemblies (default 5)
                layers: Number of PCB layers (default 2)
                thickness: Board thickness in mm (default 1.6)
                surface_finish: Surface finish (HASL, ENIG, OSP, etc.)
                color: Solder mask color
                priority: Priority level (low, normal, high)

            Returns:
                Combined quote with fab job_id, COGS breakdown, and totals
            """
            try:
                gerber = Path(gerber_path).expanduser().resolve()
                bom = Path(bom_path).expanduser().resolve()

                for p, label in [(gerber, "Gerber"), (bom, "BOM")]:
                    if not p.exists():
                        return {"success": False, "error": f"{label} file not found: {p}"}
                    if not p.is_file():
                        return {"success": False, "error": f"{label} path is not a file: {p}"}

                if gerber.suffix.lower() != ".zip":
                    return {"success": False, "error": f"Expected .zip for gerbers, got: {gerber.suffix}"}

                bom_suffix = bom.suffix.lower()
                bom_content_type = BOM_MIME_TYPES.get(bom_suffix)
                if not bom_content_type:
                    bom_content_type = mimetypes.guess_type(str(bom))[0] or "application/octet-stream"

                client = get_client()

                # Step 1: Upload gerbers for fab quote
                gerber_data = gerber.read_bytes()
                fab_result = client.create_fab_order(
                    file_data=gerber_data,
                    filename=gerber.name,
                    content_type="application/zip",
                    quantity=quantity,
                    layers=layers,
                    thickness=thickness,
                    surface_finish=surface_finish,
                    color=color,
                    priority=priority,
                )

                # Step 2: Upload BOM
                bom_data = bom.read_bytes()
                bom_result = client.upload_bom(
                    file_data=bom_data,
                    filename=bom.name,
                    content_type=bom_content_type,
                )

                bom_job_id = bom_result.get("job_id")

                # Step 3: Poll BOM status for bom_id (up to 60s)
                bom_id = None
                if bom_job_id:
                    for _ in range(30):
                        time.sleep(2)
                        bom_status = client.get_bom_status(bom_job_id)
                        if bom_status.get("status") == "complete":
                            bom_id = bom_status.get("bom_id")
                            break
                        elif bom_status.get("status") == "failed":
                            break

                response: dict[str, Any] = {
                    "success": True,
                    "fab_job_id": fab_result.get("job_id"),
                    "fab_status_url": fab_result.get("status_url"),
                    "bom_job_id": bom_job_id,
                    "gerber_file": gerber.name,
                    "bom_file": bom.name,
                }

                # Step 4: Calculate COGS if we have a bom_id
                if bom_id:
                    try:
                        cogs = client.calculate_cogs(
                            source_type="bom_id",
                            source_value=bom_id,
                            build_quantity=quantity,
                        )
                        response["bom_id"] = bom_id
                        response["cogs"] = cogs
                        response["message"] = "Assembly quote complete with COGS"
                    except SourcePartsAPIError as e:
                        response["bom_id"] = bom_id
                        response["cogs_error"] = str(e)
                        response["message"] = "Fab submitted, BOM processed, but COGS calculation failed"
                else:
                    response["message"] = (
                        "Fab submitted, BOM uploaded but still processing. "
                        "Use check_bom_status to track BOM, then calculate COGS manually."
                    )

                return response

            except SourcePartsAPIError as e:
                logger.error(f"Assembly quote failed: {e}")
                return {"success": False, "error": f"Assembly quote failed: {e}"}
            except OSError as e:
                logger.error(f"File read error: {e}")
                return {"success": False, "error": f"Could not read file: {e}"}

        @mcp.tool()
        @with_user_context
        async def identify_pcb(
            file_path: str,
            project_id: str | None = None,
            box_id: str | None = None,
        ) -> dict[str, Any]:
            """Identify a PCB or component from a photo.

            Uploads an image for barcode/QR code detection, OCR text extraction,
            and component identification.

            Args:
                file_path: Path to the image file (jpg, png, gif, heic, webp)
                project_id: Optional project ID to associate
                box_id: Optional box/shipment ID to associate

            Returns:
                Identification results with barcodes, OCR text, and metadata
            """
            valid_extensions = {".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp"}

            try:
                path = Path(file_path).expanduser().resolve()

                if not path.exists():
                    return {
                        "success": False,
                        "file_path": file_path,
                        "error": f"File not found: {path}",
                    }

                if not path.is_file():
                    return {
                        "success": False,
                        "file_path": file_path,
                        "error": f"Not a file: {path}",
                    }

                if path.suffix.lower() not in valid_extensions:
                    return {
                        "success": False,
                        "file_path": file_path,
                        "error": f"Unsupported image format: {path.suffix}. Use: {', '.join(sorted(valid_extensions))}",
                    }

                content_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
                file_data = path.read_bytes()

                client = get_client()
                result = client.upload_for_identification(
                    file_data=file_data,
                    filename=path.name,
                    content_type=content_type,
                    project_id=project_id,
                    box_id=box_id,
                )

                return {
                    "success": True,
                    "result": result,
                    "file": path.name,
                    "message": "Image uploaded for identification",
                }

            except SourcePartsAPIError as e:
                logger.error(f"PCB identification failed: {e}")
                return {
                    "success": False,
                    "file_path": file_path,
                    "error": f"Identification failed: {e}",
                }
            except OSError as e:
                logger.error(f"File read error: {e}")
                return {
                    "success": False,
                    "file_path": file_path,
                    "error": f"Could not read file: {e}",
                }

        logger.info("Registered local-mode manufacturing tools (upload_gerbers_for_quote, quote_assembly, identify_pcb)")
