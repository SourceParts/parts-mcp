"""
Quality & Compliance Pipeline: operator-approved inspection & compliance.

Thin client MCP tools that upload photos/BOM/X-ray images to the
Source Parts API and return results for operator review. Every step
requires explicit approval before proceeding to the next.

Pipeline:
  1. quality_iqc_inspect      — incoming quality control inspection
  2. quality_xray_analyze     — X-ray solder joint analysis
  3. quality_fai_inspect      — first article inspection vs BOM
  4. quality_compliance_check — RoHS/REACH/conflict-minerals check
"""
import json
import logging
import os
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def register_quality_pipeline_tools(mcp: FastMCP) -> None:
    """Register Quality & Compliance Pipeline tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def quality_iqc_inspect(
        photos: list[str],
        part_number: str,
        expected_quantity: int,
        expected_date_code: str = "",
    ) -> dict[str, Any]:
        """Station 1: Incoming quality control inspection.

        Uploads component reel/packaging photos and PO reference data.
        Server validates label readability, checks date code freshness,
        verifies MPN, and checks MSL level.

        IMPORTANT: Review the inspection checks before accepting components
        into stock. Rejected components must not enter production.

        Args:
            photos: List of paths to component reel/packaging photos (JPEG/PNG)
            part_number: Expected manufacturer part number (MPN)
            expected_quantity: Expected quantity from PO
            expected_date_code: Expected date code (YYWW format, optional)

        Returns:
            Inspection report with checks, MSL level, moisture risk, and disposition.
        """
        try:
            client = get_client()

            for path in photos:
                if not os.path.exists(path):
                    return {"error": f"Photo not found: {path}"}

            import httpx
            from urllib.parse import urljoin

            base = client.base_url if client.base_url.endswith('/') else client.base_url + '/'
            url = urljoin(base, "quality/iqc/inspect")

            upload_headers = {
                "Authorization": f"Bearer {client.api_key}",
                "User-Agent": "PARTS-MCP/1.0",
            }

            files_list = []
            for photo_path in photos:
                with open(photo_path, "rb") as f:
                    photo_data = f.read()
                files_list.append(
                    ("photos", (os.path.basename(photo_path), photo_data, "image/jpeg"))
                )

            data = {
                "part_number": part_number,
                "expected_quantity": str(expected_quantity),
            }
            if expected_date_code:
                data["expected_date_code"] = expected_date_code

            response = httpx.request(
                method="POST",
                url=url,
                files=files_list,
                data=data,
                headers=upload_headers,
                timeout=120.0,
            )
            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict) and result.get("status") == "success" and "data" in result:
                result = result["data"]

            checks = result.get("checks", [])
            disposition = result.get("disposition", "unknown")
            msl_level = result.get("msl_level", "unknown")
            moisture_risk = result.get("moisture_exposure_risk", "unknown")

            summary_lines = [
                f"Inspection: {result.get('inspection_id', '')}",
                f"Part: {part_number}",
                f"Disposition: {disposition.upper()}",
                f"MSL: {msl_level} (moisture risk: {moisture_risk})",
            ]
            for check in checks:
                icon = "PASS" if check["pass"] else "FAIL"
                summary_lines.append(f"  [{icon}] {check['name']}: {check['detail']}")

            return {
                "success": True,
                "inspection_id": result.get("inspection_id", ""),
                "part_number": part_number,
                "disposition": disposition,
                "msl_level": msl_level,
                "moisture_exposure_risk": moisture_risk,
                "checks": checks,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Components accepted. Proceed to stock intake."
                    if disposition == "accept"
                    else "Components rejected or on hold. Review failed checks and contact supplier."
                    if disposition == "reject"
                    else "Components on hold. Investigate flagged checks before accepting."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def quality_xray_analyze(
        xray_images: list[str],
    ) -> dict[str, Any]:
        """Station 2: X-ray solder joint analysis for BGA/QFN packages.

        Uploads X-ray images of solder joints. Server analyzes void percentage,
        checks for solder bridges, head-in-pillow defects, and other anomalies
        per IPC-7095/IPC-A-610 standards.

        IMPORTANT: Review the defect report and void percentages before
        accepting the board. Joints exceeding 25% void require rework.

        Args:
            xray_images: List of paths to X-ray images (JPEG/PNG)

        Returns:
            Analysis report with joints analyzed, void %, defects, and disposition.
        """
        try:
            client = get_client()

            for path in xray_images:
                if not os.path.exists(path):
                    return {"error": f"X-ray image not found: {path}"}

            import httpx
            from urllib.parse import urljoin

            base = client.base_url if client.base_url.endswith('/') else client.base_url + '/'
            url = urljoin(base, "quality/xray/analyze")

            upload_headers = {
                "Authorization": f"Bearer {client.api_key}",
                "User-Agent": "PARTS-MCP/1.0",
            }

            files_list = []
            for image_path in xray_images:
                with open(image_path, "rb") as f:
                    image_data = f.read()
                files_list.append(
                    ("images", (os.path.basename(image_path), image_data, "image/jpeg"))
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

            joints = result.get("joints_analyzed", 0)
            void_pct = result.get("void_percentage", 0)
            void_pass = result.get("void_pass", True)
            defects = result.get("defects", [])
            disposition = result.get("disposition", "unknown")

            summary_lines = [
                f"Analysis: {result.get('analysis_id', '')}",
                f"Joints analyzed: {joints}",
                f"Void percentage: {void_pct}% (limit: {result.get('void_limit_pct', 25)}%)",
                f"Void check: {'PASS' if void_pass else 'FAIL'}",
                f"Defects: {len(defects)}",
                f"Disposition: {disposition.upper()}",
                f"Standard: {result.get('standard', 'IPC-7095')}",
            ]

            if defects:
                summary_lines.append("\nDefects found:")
                for d in defects[:10]:
                    summary_lines.append(
                        f"  [{d.get('severity', 'unknown').upper()}] "
                        f"{d.get('type', '')}: {d.get('location', '')}"
                    )

            return {
                "success": True,
                "analysis_id": result.get("analysis_id", ""),
                "joints_analyzed": joints,
                "void_percentage": void_pct,
                "void_pass": void_pass,
                "defects": defects,
                "disposition": disposition,
                "image_results": result.get("image_results", []),
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "X-ray analysis passed. Proceed to functional testing."
                    if disposition == "accept"
                    else "Defects found. Rework affected joints and re-inspect."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def quality_fai_inspect(
        board_photos: list[str],
        bom_path: str,
    ) -> dict[str, Any]:
        """Station 3: First Article Inspection — verify assembled board against BOM.

        Uploads assembled board photos and BOM file. Server cross-references
        each visible component against the BOM for presence, polarity,
        orientation, and correct value.

        IMPORTANT: Review flagged components manually. Vision-based checks
        should be confirmed by operator before accepting the first article.

        Args:
            board_photos: List of paths to assembled board photos (JPEG/PNG)
            bom_path: Path to BOM file (.csv or .json)

        Returns:
            Inspection report with component statuses, pass rate, and flagged items.
        """
        try:
            client = get_client()

            for path in board_photos:
                if not os.path.exists(path):
                    return {"error": f"Board photo not found: {path}"}
            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            import httpx
            from urllib.parse import urljoin

            base = client.base_url if client.base_url.endswith('/') else client.base_url + '/'
            url = urljoin(base, "quality/fai/inspect")

            upload_headers = {
                "Authorization": f"Bearer {client.api_key}",
                "User-Agent": "PARTS-MCP/1.0",
            }

            files_list = []
            for photo_path in board_photos:
                with open(photo_path, "rb") as f:
                    photo_data = f.read()
                files_list.append(
                    ("photos", (os.path.basename(photo_path), photo_data, "image/jpeg"))
                )

            with open(bom_path, "rb") as f:
                bom_data = f.read()
            files_list.append(
                ("bom", (os.path.basename(bom_path), bom_data, "application/octet-stream"))
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

            components = result.get("components", [])
            flagged = result.get("flagged", [])
            pass_rate = result.get("pass_rate", 0)
            total_refs = result.get("total_references", 0)

            summary_lines = [
                f"FAI: {result.get('fai_id', '')}",
                f"Photos: {result.get('total_photos', 0)}",
                f"BOM components: {result.get('total_bom_components', 0)}",
                f"References checked: {total_refs}",
                f"Pass rate: {pass_rate}%",
                f"Flagged: {len(flagged)}",
            ]

            if flagged:
                summary_lines.append("\nFlagged components:")
                for f_item in flagged[:15]:
                    summary_lines.append(
                        f"  {f_item['ref']}: {f_item['status']} "
                        f"(expected {f_item.get('expected_value', 'N/A')})"
                    )

            return {
                "success": True,
                "fai_id": result.get("fai_id", ""),
                "total_references": total_refs,
                "pass_rate": pass_rate,
                "flagged_count": len(flagged),
                "flagged": flagged,
                "components": components[:50],
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "All components verified. First article approved."
                    if not flagged
                    else "Review flagged components. Correct placement issues before production run."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def quality_compliance_check(
        bom_path: str,
        target_markets: list[str],
    ) -> dict[str, Any]:
        """Station 4: Check BOM regulatory compliance for target markets.

        Uploads BOM and checks every component against RoHS, REACH SVHC,
        conflict minerals (3TG), and market-specific requirements (CE/UL/CCC).

        IMPORTANT: Review non-compliant components and compliance summary
        per market before proceeding with production or export.

        Args:
            bom_path: Path to BOM file (.csv or .json)
            target_markets: List of target market codes (EU, US, CN)

        Returns:
            Compliance report per component and per market, with non-compliant list.
        """
        try:
            client = get_client()

            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            with open(bom_path, "rb") as f:
                bom_data = f.read()

            result = client._make_upload_request(
                "quality/compliance/check",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="application/octet-stream",
                form_fields={
                    "target_markets": ",".join(target_markets),
                },
            )

            components = result.get("components", [])
            compliance_summary = result.get("compliance_summary", {})
            non_compliant = result.get("non_compliant", [])
            report_ready = result.get("report_ready", False)

            summary_lines = [
                f"Compliance: {result.get('compliance_id', '')}",
                f"Markets: {', '.join(target_markets)}",
                f"Components checked: {result.get('total_components', 0)}",
                f"Non-compliant: {len(non_compliant)}",
                f"Report ready: {'Yes' if report_ready else 'No'}",
            ]

            for market, summary in compliance_summary.items():
                status = "COMPLIANT" if summary.get("compliant") else "ISSUES FOUND"
                summary_lines.append(f"\n  {market}: {status}")
                summary_lines.append(f"    Directives: {', '.join(summary.get('directives', []))}")
                summary_lines.append(f"    Marking: {summary.get('marking', 'N/A')}")
                if summary.get("issues"):
                    for issue in summary["issues"]:
                        summary_lines.append(f"    - {issue}")

            if non_compliant:
                summary_lines.append("\nNon-compliant components:")
                for nc in non_compliant[:10]:
                    summary_lines.append(
                        f"  {nc['ref']} ({nc['mpn']}): "
                        f"RoHS={nc['rohs']}, REACH={nc['reach']}"
                    )

            return {
                "success": True,
                "compliance_id": result.get("compliance_id", ""),
                "target_markets": target_markets,
                "total_components": result.get("total_components", 0),
                "components": components[:50],
                "compliance_summary": compliance_summary,
                "non_compliant": non_compliant,
                "non_compliant_count": len(non_compliant),
                "report_ready": report_ready,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "All components compliant. Compliance report is ready for export documentation."
                    if report_ready
                    else "Review non-compliant components. Source alternatives or obtain exemption certificates."
                ),
            }
        except Exception as e:
            return {"error": str(e)}
