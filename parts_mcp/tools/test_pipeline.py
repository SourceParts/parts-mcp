"""
Test & Validation + Post-Production Pipeline: operator-approved test, provisioning,
reliability, RMA, failure analysis, and ECO feedback tools.

Thin client MCP tools that upload data to the Source Parts API
and return results for operator review. Every step requires explicit
approval before proceeding to the next.

Test & Validation Pipeline:
  1. test_coverage_analysis     — test point coverage + probe accessibility
  2. test_provision_devices     — per-device provisioning packages
  3. test_reliability_predict   — MTBF prediction (MIL-HDBK-217F)

Post-Production Pipeline:
  4. rma_process                — RMA categorization + disposition
  5. failure_analysis           — Pareto analysis + lot correlation
  6. eco_feedback               — ECN suggestions from failure patterns
"""
import logging
import os
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def register_test_pipeline_tools(mcp: FastMCP) -> None:
    """Register Test & Validation + Post-Production Pipeline tools with the MCP server."""

    # =========================================================================
    # Test & Validation Tools
    # =========================================================================

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def test_coverage_analysis(
        test_points_path: str,
        pcb_path: str,
    ) -> dict[str, Any]:
        """Station 1: Analyze test point coverage and probe accessibility.

        Uploads test points CSV and PCB file. Server checks probe spacing
        (min 1.27mm), keep-out violations, and ICT fixture clearance.

        IMPORTANT: Review blocked points before committing to fixture design.

        Args:
            test_points_path: Path to test points CSV (columns: ref, net_name, x, y, side)
            pcb_path: Path to .kicad_pcb file

        Returns:
            Coverage report with accessible/blocked points and coverage percentage.
        """
        try:
            client = get_client()

            for path, label in [(test_points_path, "Test points"), (pcb_path, "PCB file")]:
                if not os.path.exists(path):
                    return {"error": f"{label} file not found: {path}"}

            with open(test_points_path, "rb") as f:
                tp_data = f.read()
            with open(pcb_path, "rb") as f:
                pcb_data = f.read()

            from urllib.parse import urljoin

            import httpx

            base = client.base_url if client.base_url.endswith('/') else client.base_url + '/'
            url = urljoin(base, "test/coverage")

            upload_headers = {
                "Authorization": f"Bearer {client.api_key}",
                "User-Agent": "PARTS-MCP/1.0",
            }

            files = {
                "test_points": (os.path.basename(test_points_path), tp_data, "text/csv"),
                "pcb_file": (os.path.basename(pcb_path), pcb_data, "application/octet-stream"),
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

            total = result.get("total_points", 0)
            accessible = result.get("accessible", 0)
            blocked = result.get("blocked", 0)
            coverage = result.get("coverage_percentage", 0)

            summary_lines = [
                f"Total test points: {total}",
                f"Accessible: {accessible}",
                f"Blocked: {blocked}",
                f"Coverage: {coverage}%",
            ]

            blocked_details = result.get("blocked_details", [])
            if blocked_details:
                summary_lines.append("\nBlocked points:")
                for bp in blocked_details[:10]:
                    summary_lines.append(
                        f"  {bp.get('ref', 'N/A')} ({bp.get('net_name', '')}): "
                        f"{bp.get('reason', 'unknown')}"
                    )

            return {
                "success": True,
                "total_points": total,
                "accessible": accessible,
                "blocked": blocked,
                "coverage_percentage": coverage,
                "blocked_details": blocked_details,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "All points accessible. Proceed with fixture design."
                    if blocked == 0
                    else "Review blocked points. Relocate test points or adjust fixture design."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def test_provision_devices(
        firmware_url: str,
        device_ids: list[str],
        cert_template: str = "production",
    ) -> dict[str, Any]:
        """Station 2: Generate per-device provisioning packages.

        Creates unique keys, certificates, and serial numbers for each device.
        Returns provisioning packages for flashing during production test.

        IMPORTANT: Verify firmware URL and device list before provisioning.

        Args:
            firmware_url: URL to firmware binary
            device_ids: List of device identifiers to provision
            cert_template: Certificate template ("production" or "development")

        Returns:
            Provisioning data with per-device keys, certs, and package URL.
        """
        try:
            client = get_client()

            json_data = {
                "firmware_url": firmware_url,
                "device_ids": device_ids,
                "certificate_template": cert_template,
            }

            result = client._make_request(
                "POST", "/v1/test/provision", json_data=json_data
            )

            devices = result.get("devices", [])
            provision_id = result.get("provision_id", "")
            package_url = result.get("provision_package_url", "")

            summary_lines = [
                f"Provision ID: {provision_id}",
                f"Firmware: {firmware_url}",
                f"Template: {cert_template}",
                f"Devices provisioned: {len(devices)}",
                f"Package URL: {package_url}",
            ]

            for dev in devices[:5]:
                summary_lines.append(
                    f"  {dev.get('device_id', 'N/A')} -> Serial: {dev.get('serial', '')}, "
                    f"Key: {dev.get('key_id', '')}"
                )
            if len(devices) > 5:
                summary_lines.append(f"  ... and {len(devices) - 5} more")

            return {
                "success": True,
                "provision_id": provision_id,
                "firmware_url": firmware_url,
                "certificate_template": cert_template,
                "total_devices": len(devices),
                "devices": devices,
                "provision_package_url": package_url,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Download provisioning package and flash devices during production test. "
                    "Verify each device's serial and certificate after flashing."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def test_reliability_predict(
        bom_path: str,
        ambient_temp: float = 25.0,
        environment: str = "ground_benign",
        duty_cycle: float = 1.0,
    ) -> dict[str, Any]:
        """Station 3: Calculate MTBF using MIL-HDBK-217F simplified method.

        Uploads BOM file and calculates per-component failure rates,
        total MTBF, and identifies weakest components.

        IMPORTANT: Review weakest links and consider derating or alternatives.

        Args:
            bom_path: Path to BOM file (.csv or .json)
            ambient_temp: Ambient operating temperature in Celsius (default 25)
            environment: Operating environment (ground_benign, ground_fixed, airborne, etc.)
            duty_cycle: Operating duty cycle 0.0-1.0 (default 1.0)

        Returns:
            MTBF prediction with component-level breakdown and weakest links.
        """
        try:
            client = get_client()

            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            with open(bom_path, "rb") as f:
                bom_data = f.read()

            result = client._make_upload_request(
                "test/reliability",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="application/octet-stream",
                form_fields={
                    "ambient_temp_c": str(ambient_temp),
                    "duty_cycle": str(duty_cycle),
                    "environment": environment,
                },
            )

            mtbf = result.get("mtbf_hours", 0)
            fit = result.get("fit_rate", 0)
            reliability_1yr = result.get("reliability_at_1year", 0)
            weakest = result.get("weakest_links", [])
            conditions = result.get("operating_conditions", {})

            # Format MTBF in human-readable terms
            mtbf_years = round(mtbf / 8760, 1) if mtbf and mtbf != float("inf") else "N/A"

            summary_lines = [
                f"MTBF: {mtbf:,.0f} hours ({mtbf_years} years)",
                f"FIT rate: {fit} failures/billion hours",
                f"Reliability at 1 year: {reliability_1yr * 100:.2f}%",
                f"Environment: {environment}",
                f"Ambient temp: {ambient_temp}C",
                f"Duty cycle: {duty_cycle * 100:.0f}%",
            ]

            if weakest:
                summary_lines.append("\nWeakest links:")
                for w in weakest:
                    summary_lines.append(
                        f"  {w.get('ref', 'N/A')}: {w.get('contribution_pct', 0):.1f}% "
                        f"of total failure rate"
                    )

            return {
                "success": True,
                "mtbf_hours": mtbf,
                "mtbf_years": mtbf_years,
                "fit_rate": fit,
                "reliability_at_1year": reliability_1yr,
                "weakest_links": weakest,
                "operating_conditions": conditions,
                "standard": "MIL-HDBK-217F (simplified)",
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Review weakest links. Consider component derating, alternative parts, "
                    "or design changes to improve reliability."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # Post-Production Tools
    # =========================================================================

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def rma_process(
        order_id: str,
        failure_description: str,
        serial_number: str,
    ) -> dict[str, Any]:
        """Station 4: Process an RMA request with failure categorization and disposition.

        Categorizes failure mode (DOA, wear-out, damage, no-fault-found),
        checks warranty status, and generates RMA number with disposition.

        IMPORTANT: Review disposition before confirming with customer.

        Args:
            order_id: Original order identifier
            failure_description: Description of the failure
            serial_number: Device serial number

        Returns:
            RMA data with failure category, warranty status, and disposition.
        """
        try:
            client = get_client()

            json_data = {
                "order_id": order_id,
                "failure_description": failure_description,
                "serial_number": serial_number,
            }

            result = client._make_request(
                "POST", "/v1/post-production/rma/process", json_data=json_data
            )

            rma_number = result.get("rma_number", "")
            category = result.get("failure_category", "")
            warranty = result.get("warranty_status", "")
            disposition = result.get("disposition", "")
            instructions = result.get("return_instructions", {})

            summary_lines = [
                f"RMA: {rma_number}",
                f"Order: {order_id}",
                f"Serial: {serial_number}",
                f"Failure: {failure_description}",
                f"Category: {category.upper()}",
                f"Warranty: {warranty}",
                f"Disposition: {disposition.upper()}",
            ]

            if instructions.get("action"):
                summary_lines.append(f"\nAction: {instructions['action']}")
            if instructions.get("reason"):
                summary_lines.append(f"Reason: {instructions['reason']}")

            return {
                "success": True,
                "rma_number": rma_number,
                "order_id": order_id,
                "serial_number": serial_number,
                "failure_category": category,
                "warranty_status": warranty,
                "disposition": disposition,
                "return_instructions": instructions,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    f"RMA {rma_number} created. Communicate disposition to customer. "
                    f"{'Provide return shipping label.' if disposition in ('replace', 'repair', 'refund') else 'No further action required.'}"
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def failure_analysis(
        failure_data_path: str,
    ) -> dict[str, Any]:
        """Station 5: Run Pareto analysis on failure data with lot correlation.

        Uploads failure data CSV and identifies top failure modes, correlates
        with production lots, and provides actionable recommendations.

        IMPORTANT: Review Pareto chart and lot correlation before taking action.

        Args:
            failure_data_path: Path to failure data CSV (columns: serial, failure_mode, date, lot_number)

        Returns:
            Failure analysis with Pareto chart, lot correlation, and recommendations.
        """
        try:
            client = get_client()

            if not os.path.exists(failure_data_path):
                return {"error": f"Failure data file not found: {failure_data_path}"}

            with open(failure_data_path, "rb") as f:
                failure_data = f.read()

            result = client._make_upload_request(
                "post-production/failure-analysis",
                file_data=failure_data,
                filename=os.path.basename(failure_data_path),
                content_type="text/csv",
            )

            total = result.get("total_failures", 0)
            pareto = result.get("pareto", [])
            lots = result.get("lot_correlation", [])
            recommendations = result.get("recommendations", [])
            analysis_id = result.get("analysis_id", "")

            summary_lines = [
                f"Analysis ID: {analysis_id}",
                f"Total failures: {total}",
                f"Unique failure modes: {result.get('unique_failure_modes', 0)}",
                f"Unique lots: {result.get('unique_lots', 0)}",
            ]

            if pareto:
                summary_lines.append("\nPareto (top failure modes):")
                for p in pareto[:5]:
                    summary_lines.append(
                        f"  {p['failure_mode']}: {p['count']} ({p['percentage']}%, "
                        f"cumulative {p['cumulative_pct']}%)"
                    )

            if lots:
                summary_lines.append("\nLot correlation:")
                for lot in lots[:5]:
                    summary_lines.append(
                        f"  Lot {lot['lot']}: {lot['failures']} failures "
                        f"({lot['failure_rate']}% rate)"
                    )

            if recommendations:
                summary_lines.append("\nRecommendations:")
                for rec in recommendations:
                    summary_lines.append(f"  - {rec}")

            return {
                "success": True,
                "analysis_id": analysis_id,
                "total_failures": total,
                "pareto": pareto,
                "lot_correlation": lots,
                "recommendations": recommendations,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Review recommendations and implement corrective actions. "
                    "Call eco_feedback with this analysis_id to generate ECN suggestions."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def eco_feedback(
        failure_analysis_id: str = "",
        top_failures: list[dict] | None = None,
        lot_correlation: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Station 6: Generate ECN suggestions based on failure patterns.

        Uses failure analysis data to suggest engineering change notices
        (e.g., paste aperture changes, AVL updates, design modifications).

        IMPORTANT: Review ECN suggestions before creating formal ECNs.

        Args:
            failure_analysis_id: Reference to a prior failure analysis
            top_failures: Optional list of failure summaries [{failure_mode, count, percentage}]
            lot_correlation: Optional list of lot data [{lot, failure_rate}]

        Returns:
            Suggested ECNs with severity, rationale, and affected designators.
        """
        try:
            client = get_client()

            json_data = {
                "failure_analysis_id": failure_analysis_id,
                "failure_data": {},
            }
            if top_failures:
                json_data["failure_data"]["top_failures"] = top_failures
            if lot_correlation:
                json_data["failure_data"]["lot_correlation"] = lot_correlation

            result = client._make_request(
                "POST", "/v1/post-production/eco-feedback", json_data=json_data
            )

            ecns = result.get("suggested_ecns", [])
            priority = result.get("priority_score", 0)
            feedback_id = result.get("feedback_id", "")

            summary_lines = [
                f"Feedback ID: {feedback_id}",
                f"Analysis ref: {failure_analysis_id or 'N/A'}",
                f"Suggested ECNs: {len(ecns)}",
                f"Priority score: {priority}/100",
            ]

            if ecns:
                summary_lines.append("\nSuggested ECNs:")
                for ecn in ecns:
                    summary_lines.append(
                        f"  [{ecn.get('severity', '').upper()}] {ecn.get('title', '')}"
                    )
                    summary_lines.append(
                        f"    Type: {ecn.get('type', '')} | "
                        f"Affected: {', '.join(ecn.get('affected_designators', []))}"
                    )

            return {
                "success": True,
                "feedback_id": feedback_id,
                "failure_analysis_id": failure_analysis_id,
                "suggested_ecns": ecns,
                "priority_score": priority,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Review suggested ECNs and create formal change requests for approved items. "
                    "Use ecn_create to formalize each approved change."
                ),
            }
        except Exception as e:
            return {"error": str(e)}
