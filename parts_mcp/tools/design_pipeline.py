"""
Design & Engineering Pipeline: schematic review, impedance, thermal analysis.

Thin client MCP tools that upload data to the Source Parts API
and return results for engineer review. Every step requires explicit
approval before proceeding to the next.

Pipeline:
  1. design_schematic_review    — ERC-style schematic review
  2. design_impedance_calculate — controlled-impedance calculation
  3. design_thermal_analysis    — BOM-based thermal analysis
"""
import logging
import os
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def register_design_pipeline_tools(mcp: FastMCP) -> None:
    """Register Design & Engineering Pipeline tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def design_schematic_review(
        project_path: str,
    ) -> dict[str, Any]:
        """Review a KiCad schematic for common design issues.

        Uploads a .kicad_sch file and checks for: unconnected pins, missing
        decoupling capacitors (ICs without bypass caps within proximity),
        power domain analysis (voltage rails, current budget), and net
        naming conventions.

        IMPORTANT: Review all findings before proceeding with layout.

        Args:
            project_path: Path to the .kicad_sch schematic file

        Returns:
            Review findings with severity, score, and power domain analysis.
        """
        try:
            client = get_client()

            if not os.path.exists(project_path):
                return {"error": f"Schematic file not found: {project_path}"}

            if not project_path.endswith(".kicad_sch"):
                return {"error": "File must be a .kicad_sch schematic"}

            with open(project_path, "rb") as f:
                sch_data = f.read()

            result = client._make_upload_request(
                "design/schematic-review",
                file_data=sch_data,
                filename=os.path.basename(project_path),
                content_type="application/octet-stream",
            )

            findings = result.get("findings", [])
            score = result.get("score", 0)
            power_domains = result.get("power_domains", [])
            review_id = result.get("review_id", "")

            summary_lines = [
                f"Review: {review_id}",
                f"Score: {score}/100",
                f"Components: {result.get('total_components', 0)}",
                f"ICs: {result.get('total_ics', 0)}",
                f"Capacitors: {result.get('total_capacitors', 0)}",
                f"Nets: {result.get('total_nets', 0)}",
                f"Findings: {len(findings)}",
            ]

            # Summarize findings by severity
            severity_counts = {}
            for f_item in findings:
                sev = f_item.get("severity", "info")
                severity_counts[sev] = severity_counts.get(sev, 0) + 1
            for sev, count in sorted(severity_counts.items()):
                summary_lines.append(f"  {sev}: {count}")

            if power_domains:
                summary_lines.append(f"\nPower domains: {len(power_domains)}")
                for pd in power_domains:
                    v = pd.get("voltage_v")
                    summary_lines.append(
                        f"  {pd['rail_name']}: "
                        f"{f'{v}V' if v else 'unknown'}, "
                        f"~{pd.get('estimated_current_ma', 0):.0f}mA"
                    )

            return {
                "success": True,
                "review_id": review_id,
                "score": score,
                "total_components": result.get("total_components", 0),
                "total_ics": result.get("total_ics", 0),
                "total_nets": result.get("total_nets", 0),
                "findings": findings,
                "finding_count": len(findings),
                "power_domains": power_domains,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Address warnings and errors before layout. "
                    "Run design_impedance_calculate for high-speed traces. "
                    "Run design_thermal_analysis for power budget verification."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def design_impedance_calculate(
        stackup: dict[str, float],
        trace_width: float,
        trace_type: str = "microstrip",
        trace_spacing: float = 0.0,
        copper_weight_oz: float = 1.0,
    ) -> dict[str, Any]:
        """Calculate controlled impedance for a PCB trace.

        Computes characteristic impedance using standard formulas for
        microstrip, stripline, or differential pair configurations.

        Args:
            stackup: Dict with dielectric_height_mm and dielectric_constant (Er)
            trace_width: Trace width in mm
            trace_type: Type: microstrip, stripline, or differential
            trace_spacing: Trace spacing in mm (required for differential)
            copper_weight_oz: Copper weight in oz (default 1.0)

        Returns:
            Impedance, propagation delay, loss, and recommendation.
        """
        try:
            client = get_client()

            json_data = {
                "stackup": stackup,
                "trace_width_mm": trace_width,
                "trace_spacing_mm": trace_spacing,
                "copper_weight_oz": copper_weight_oz,
                "trace_type": trace_type,
            }

            result = client._make_request(
                "POST", "/v1/design/impedance", json_data=json_data
            )

            z = result.get("impedance_ohms", 0)
            delay = result.get("delay_ps_per_mm", 0)
            loss = result.get("loss_db_per_mm", 0)
            rec = result.get("recommendation", "")

            summary_lines = [
                f"Calculation: {result.get('calculation_id', '')}",
                f"Type: {trace_type}",
                f"Width: {trace_width} mm",
                f"Dielectric: Er={stackup.get('dielectric_constant', 0)}, "
                f"H={stackup.get('dielectric_height_mm', 0)} mm",
                "",
                f"Impedance: {z} ohm",
                f"Delay: {delay} ps/mm",
                f"Loss: {loss} dB/mm",
                "",
                f"Recommendation: {rec}",
            ]

            return {
                "success": True,
                "calculation_id": result.get("calculation_id", ""),
                "trace_type": trace_type,
                "impedance_ohms": z,
                "delay_ps_per_mm": delay,
                "loss_db_per_mm": loss,
                "effective_dielectric_constant": result.get("effective_dielectric_constant", 0),
                "recommendation": rec,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Verify impedance meets target for your interface. "
                    "Request stackup from fab house for accurate Er and height values. "
                    "Run design_schematic_review to check signal integrity constraints."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def design_thermal_analysis(
        bom_path: str,
        ambient_temp_c: float = 25.0,
    ) -> dict[str, Any]:
        """Estimate thermal dissipation from BOM and identify hot spots.

        Uploads a BOM file and estimates power dissipation per IC from
        typical values, identifies components exceeding thermal limits,
        and recommends thermal vias or heatsinking.

        IMPORTANT: Review thermal risks and recommendations before layout.

        Args:
            bom_path: Path to BOM file (.csv or .json)
            ambient_temp_c: Ambient temperature in Celsius (default 25)

        Returns:
            Thermal analysis with per-component power, hot spots, and recommendations.
        """
        try:
            client = get_client()

            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            with open(bom_path, "rb") as f:
                bom_data = f.read()

            result = client._make_upload_request(
                "design/thermal",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="application/octet-stream",
                form_fields={
                    "ambient_temp_c": str(ambient_temp_c),
                },
            )

            components = result.get("components", [])
            total_power = result.get("total_power_w", 0)
            hot_spots = result.get("hot_spots", [])
            recommendations = result.get("recommendations", [])
            analysis_id = result.get("analysis_id", "")

            summary_lines = [
                f"Analysis: {analysis_id}",
                f"Components: {len(components)}",
                f"Total power: {total_power:.3f} W",
                f"Ambient: {ambient_temp_c} C",
                f"Hot spots: {len(hot_spots)}",
            ]

            if hot_spots:
                summary_lines.append("\nHot spots:")
                for hs in hot_spots:
                    summary_lines.append(
                        f"  {hs['reference']} ({hs['description']}): "
                        f"{hs['power_w']}W, Tj={hs['junction_temp_c']}C "
                        f"[{hs['thermal_risk'].upper()}]"
                    )

            if recommendations:
                summary_lines.append("\nRecommendations:")
                for rec in recommendations:
                    summary_lines.append(f"  - {rec}")

            return {
                "success": True,
                "analysis_id": analysis_id,
                "total_components": len(components),
                "components": components,
                "total_power_w": total_power,
                "ambient_temp_c": ambient_temp_c,
                "hot_spots": hot_spots,
                "hot_spot_count": len(hot_spots),
                "recommendations": recommendations,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Address critical and high thermal risks in layout. "
                    "Add thermal vias under exposed pads. "
                    "Run design_schematic_review to verify power domains."
                    if hot_spots
                    else "Thermal profile is nominal. Proceed with layout."
                ),
            }
        except Exception as e:
            return {"error": str(e)}
