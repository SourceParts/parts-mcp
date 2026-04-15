"""
Assembly Pipeline: AOI-style operator-approved SMT assembly pipeline.

Thin client MCP tools that upload BOM/gerber/position/photo files to the
Source Parts API and return results for operator review. Every step requires
explicit approval before proceeding to the next.

Pipeline:
  1. assembly_readiness_check  — pre-assembly readiness checklist
  2. assembly_feeder_setup     — optimal feeder slot assignment
  3. assembly_reflow_profile   — reflow profile recommendation
  4. assembly_aoi_inspect      — automated optical inspection
  5. assembly_functional_test  — functional test validation + yield
"""
import json
import logging
import os
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def register_assembly_pipeline_tools(mcp: FastMCP) -> None:
    """Register Assembly Pipeline tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def assembly_readiness_check(
        bom_path: str,
        gerber_path: str,
        position_path: str,
    ) -> dict[str, Any]:
        """Station 1: Pre-assembly readiness checklist.

        Uploads BOM, gerber ZIP, and position CSV to the API. Server checks:
        all parts parseable? stencil layer present? positions match BOM?

        IMPORTANT: Review the checklist before proceeding to feeder setup.

        Args:
            bom_path: Path to BOM CSV file
            gerber_path: Path to gerber ZIP file
            position_path: Path to position/placement CSV file

        Returns:
            Readiness checklist with pass/fail per item.
        """
        try:
            client = get_client()

            for path, label in [(bom_path, "BOM"), (gerber_path, "Gerbers"), (position_path, "Positions")]:
                if not os.path.exists(path):
                    return {"error": f"{label} file not found: {path}"}

            with open(bom_path, "rb") as f:
                bom_data = f.read()
            with open(gerber_path, "rb") as f:
                gerber_data = f.read()
            with open(position_path, "rb") as f:
                position_data = f.read()

            result = client._make_upload_request(
                "assembly/readiness",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="text/csv",
                form_fields=None,
            )

            # The readiness endpoint needs all three files — use httpx directly
            import httpx
            from urllib.parse import urljoin

            base = client.base_url if client.base_url.endswith('/') else client.base_url + '/'
            url = urljoin(base, "assembly/readiness")

            upload_headers = {
                "Authorization": f"Bearer {client.api_key}",
                "User-Agent": "PARTS-MCP/1.0",
            }

            files = {
                "bom": (os.path.basename(bom_path), bom_data, "text/csv"),
                "gerbers": (os.path.basename(gerber_path), gerber_data, "application/zip"),
                "positions": (os.path.basename(position_path), position_data, "text/csv"),
            }

            response = httpx.request(
                method="POST",
                url=url,
                files=files,
                headers=upload_headers,
                timeout=120.0,
            )
            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict) and result.get("status") == "success" and "data" in result:
                result = result["data"]

            checklist = result.get("checklist", [])
            overall = result.get("overall_status", "unknown")

            summary_lines = [f"Overall: {overall.upper()}"]
            for item in checklist:
                icon = "PASS" if item["status"] == "pass" else (
                    "WARN" if item["status"] == "warn" else "FAIL"
                )
                summary_lines.append(f"  [{icon}] {item['label']}: {item.get('detail', '')}")

            return {
                "success": True,
                "overall_status": overall,
                "checklist": checklist,
                "bom_line_items": result.get("bom_line_items", 0),
                "position_placements": result.get("position_placements", 0),
                "summary": "\n".join(summary_lines),
                "next_step": "Review the checklist. If all items pass, call assembly_feeder_setup to generate feeder slot assignments."
                if overall == "pass"
                else "Address failing items before proceeding. Re-run assembly_readiness_check after fixes.",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def assembly_feeder_setup(
        bom_path: str,
        position_path: str,
        machine: str = "neoden",
    ) -> dict[str, Any]:
        """Station 2: Generate optimal feeder slot assignment.

        Uploads BOM and position CSV. Server groups components and assigns
        feeder slots to minimize changeover time.

        IMPORTANT: Review the feeder map before loading the machine.

        Args:
            bom_path: Path to BOM CSV file
            position_path: Path to position/placement CSV file
            machine: Machine type (e.g. "neoden", "juki", "yamaha")

        Returns:
            Feeder map JSON + CSV with slot assignments.
        """
        try:
            client = get_client()

            for path, label in [(bom_path, "BOM"), (position_path, "Positions")]:
                if not os.path.exists(path):
                    return {"error": f"{label} file not found: {path}"}

            with open(bom_path, "rb") as f:
                bom_data = f.read()
            with open(position_path, "rb") as f:
                position_data = f.read()

            import httpx
            from urllib.parse import urljoin

            base = client.base_url if client.base_url.endswith('/') else client.base_url + '/'
            url = urljoin(base, "assembly/feeder-setup")

            upload_headers = {
                "Authorization": f"Bearer {client.api_key}",
                "User-Agent": "PARTS-MCP/1.0",
            }

            files = {
                "bom": (os.path.basename(bom_path), bom_data, "text/csv"),
                "positions": (os.path.basename(position_path), position_data, "text/csv"),
            }

            response = httpx.request(
                method="POST",
                url=url,
                files=files,
                data={"machine_type": machine},
                headers=upload_headers,
                timeout=120.0,
            )
            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict) and result.get("status") == "success" and "data" in result:
                result = result["data"]

            feeder_map = result.get("feeder_map", [])
            total_feeders = result.get("total_feeders", 0)
            total_placements = result.get("total_placements", 0)

            # Save feeder CSV locally
            csv_path = None
            feeder_csv = result.get("feeder_csv")
            if feeder_csv:
                csv_path = os.path.join(os.path.dirname(bom_path), f"feeder_setup_{machine}.csv")
                with open(csv_path, "w") as f:
                    f.write(feeder_csv)

            summary_lines = [
                f"Machine: {machine}",
                f"Total feeders: {total_feeders}",
                f"Total placements: {total_placements}",
            ]
            for entry in feeder_map[:10]:
                summary_lines.append(
                    f"  Slot {entry['slot']}: {entry['value']} ({entry['footprint']}) x{entry['count']}"
                )
            if total_feeders > 10:
                summary_lines.append(f"  ... and {total_feeders - 10} more")

            return {
                "success": True,
                "machine": machine,
                "total_feeders": total_feeders,
                "total_placements": total_placements,
                "feeder_map": feeder_map,
                "feeder_csv_path": csv_path,
                "summary": "\n".join(summary_lines),
                "next_step": "Review feeder assignments. Load the machine per the map, then call assembly_reflow_profile to check thermal specs.",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def assembly_reflow_profile(
        bom_path: str,
    ) -> dict[str, Any]:
        """Station 3: Analyze BOM thermal specs and recommend reflow profile.

        Uploads BOM CSV. Server analyzes MSL levels, peak reflow temps,
        and soak times across all components.

        IMPORTANT: Review thermal constraints and MSL warnings before reflowing.

        Args:
            bom_path: Path to BOM CSV file (with optional MSL, Peak_Temp columns)

        Returns:
            Recommended reflow profile + thermal constraint summary.
        """
        try:
            client = get_client()

            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            with open(bom_path, "rb") as f:
                bom_data = f.read()

            result = client._make_upload_request(
                "assembly/reflow-profile",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="text/csv",
            )

            profile = result.get("recommended_profile", {})
            msl_warnings = result.get("msl_warnings", [])
            constraints = result.get("thermal_constraints", [])

            summary_lines = [
                f"Solder: {profile.get('solder_type', 'N/A')}",
                f"Peak temp: {profile.get('peak_temp', 'N/A')}°C",
                f"Soak: {profile.get('soak_start', 'N/A')}–{profile.get('soak_end', 'N/A')}°C for {profile.get('soak_time_seconds', 'N/A')}s",
                f"Time above liquidus ({profile.get('liquidus_temp', 217)}°C): {profile.get('time_above_liquidus', 'N/A')}s",
            ]

            if msl_warnings:
                summary_lines.append("\nMSL Warnings:")
                for w in msl_warnings:
                    summary_lines.append(f"  {w['action']} ({w['count']} components)")

            if constraints:
                summary_lines.append("\nThermal Constraints:")
                for c in constraints:
                    summary_lines.append(f"  {c['detail']}")

            return {
                "success": True,
                "recommended_profile": profile,
                "msl_summary": result.get("msl_summary", {}),
                "msl_warnings": msl_warnings,
                "thermal_constraints": constraints,
                "summary": "\n".join(summary_lines),
                "next_step": "Review reflow profile and MSL warnings. Set oven profile accordingly, then run assembly. After assembly, call assembly_aoi_inspect.",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def assembly_aoi_inspect(
        board_photos: list[str],
        reference_image: str | None = None,
    ) -> dict[str, Any]:
        """Station 4: Automated optical inspection.

        Uploads board photos and optional golden reference image. Server
        compares placement quality and flags defects.

        IMPORTANT: Review the defect report and manually verify flagged items.

        Args:
            board_photos: List of paths to board photos (JPEG/PNG)
            reference_image: Optional path to golden reference image

        Returns:
            Defect report with flagged items per category.
        """
        try:
            client = get_client()

            for path in board_photos:
                if not os.path.exists(path):
                    return {"error": f"Photo not found: {path}"}
            if reference_image and not os.path.exists(reference_image):
                return {"error": f"Reference image not found: {reference_image}"}

            import httpx
            from urllib.parse import urljoin

            base = client.base_url if client.base_url.endswith('/') else client.base_url + '/'
            url = urljoin(base, "assembly/aoi")

            upload_headers = {
                "Authorization": f"Bearer {client.api_key}",
                "User-Agent": "PARTS-MCP/1.0",
            }

            # Build multipart files list
            files_list = []
            for photo_path in board_photos:
                with open(photo_path, "rb") as f:
                    photo_data = f.read()
                files_list.append(
                    ("photos", (os.path.basename(photo_path), photo_data, "image/jpeg"))
                )

            if reference_image:
                with open(reference_image, "rb") as f:
                    ref_data = f.read()
                files_list.append(
                    ("reference", (os.path.basename(reference_image), ref_data, "image/jpeg"))
                )

            response = httpx.request(
                method="POST",
                url=url,
                files=files_list,
                headers=upload_headers,
                timeout=120.0,
            )
            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict) and result.get("status") == "success" and "data" in result:
                result = result["data"]

            inspections = result.get("inspections", [])
            total_defects = result.get("total_defects_found", 0)

            summary_lines = [
                f"Inspected {len(inspections)} photo(s)",
                f"Total defects flagged: {total_defects}",
            ]
            for insp in inspections:
                defect_count = len(insp.get("defects", []))
                summary_lines.append(
                    f"  {insp['photo']}: {insp['status']} ({defect_count} issues)"
                )

            return {
                "success": True,
                "total_photos": len(inspections),
                "total_defects": total_defects,
                "inspections": inspections,
                "defect_categories": result.get("defect_categories", []),
                "summary": "\n".join(summary_lines),
                "next_step": "Review flagged defects visually. Rework any confirmed issues, then call assembly_functional_test."
                if total_defects > 0
                else "No defects flagged. Proceed to assembly_functional_test for electrical validation.",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def assembly_functional_test(
        results_path: str,
        criteria: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Station 5: Validate functional test results against pass/fail criteria.

        Uploads test results CSV and criteria JSON. Server validates each unit
        against specs and calculates yield.

        IMPORTANT: Review yield and outliers before lot disposition.

        Args:
            results_path: Path to test results CSV file
            criteria: Pass/fail criteria dict, e.g. {"Vout": {"min": 3.2, "max": 3.4}}

        Returns:
            Test report with yield %, outliers, and lot disposition.
        """
        try:
            client = get_client()

            if not os.path.exists(results_path):
                return {"error": f"Results file not found: {results_path}"}

            with open(results_path, "rb") as f:
                results_data = f.read()

            form_fields = {}
            if criteria:
                form_fields["criteria"] = json.dumps(criteria)

            result = client._make_upload_request(
                "assembly/functional-test",
                file_data=results_data,
                filename=os.path.basename(results_path),
                content_type="text/csv",
                form_fields=form_fields,
            )

            yield_pct = result.get("yield_percent", 0)
            disposition = result.get("disposition", "unknown")
            passed = result.get("passed", 0)
            failed = result.get("failed", 0)
            total = result.get("total_units", 0)
            outliers = result.get("outliers", [])

            summary_lines = [
                f"Yield: {yield_pct:.1f}% ({passed}/{total} pass)",
                f"Disposition: {disposition.upper()}",
            ]
            if failed > 0:
                summary_lines.append(f"Failed units: {failed}")
            if outliers:
                summary_lines.append(f"Outliers: {len(outliers)}")
                for o in outliers[:5]:
                    summary_lines.append(f"  {o['unit']}: {o['test']} = {o['value']}")

            return {
                "success": True,
                "yield_percent": yield_pct,
                "disposition": disposition,
                "total_units": total,
                "passed": passed,
                "failed": failed,
                "outliers": outliers,
                "test_details": result.get("test_details", [])[:20],
                "summary": "\n".join(summary_lines),
                "next_step": "Lot accepted. Package and ship."
                if disposition == "accept"
                else "Review failed units. Rework or scrap per disposition policy.",
            }
        except Exception as e:
            return {"error": str(e)}
