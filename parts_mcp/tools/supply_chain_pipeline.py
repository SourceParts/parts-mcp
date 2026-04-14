"""
Supply Chain Pipeline: AOI-style operator-approved procurement, AVL
qualification, and obsolescence management.

Thin client MCP tools that upload data to the Source Parts API
and return results for operator review. Every step requires explicit
approval before proceeding to the next.

Pipeline:
  1. supply_chain_procurement_approve — group BOM by vendor, check MOQs, price breaks
  2. supply_chain_avl_qualify         — check components against AVL rules + counterfeit risk
  3. supply_chain_obsolescence_check  — lifecycle status + alternative suggestions
"""
import logging
import os
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def register_supply_chain_pipeline_tools(mcp: FastMCP) -> None:
    """Register Supply Chain pipeline tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def supply_chain_procurement_approve(
        bom_path: str,
        quantity: int,
        target_date: str,
    ) -> dict[str, Any]:
        """Station 1: Group BOM by vendor, check MOQs, calculate price breaks, estimate lead times.

        Uploads the BOM file to the API, which groups components by vendor,
        validates minimum order quantities, applies price-break discounts,
        and estimates lead times for each purchase order.

        IMPORTANT: Review the purchase orders before placing with vendors.

        Args:
            bom_path: Path to BOM file (.csv or .json)
            quantity: Build quantity (number of units)
            target_date: Target delivery date (ISO 8601, e.g. 2026-04-15)

        Returns:
            Purchase orders grouped by vendor with MOQ status, price breaks, and lead times.
        """
        try:
            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            client = get_client()

            with open(bom_path, "rb") as f:
                bom_data = f.read()

            result = client._make_upload_request(
                "v1/supply-chain/procurement/approve",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="application/octet-stream",
                form_fields={
                    "quantity": str(quantity),
                    "target_date": target_date,
                },
            )

            po_count = result.get("purchase_order_count", 0)
            total_cost = result.get("total_cost", 0)
            longest_lt = result.get("longest_lead_time", 0)
            component_count = result.get("component_count", 0)

            return {
                "success": True,
                "build_quantity": quantity,
                "target_date": target_date,
                "purchase_orders": result.get("purchase_orders", []),
                "purchase_order_count": po_count,
                "total_cost": total_cost,
                "longest_lead_time": longest_lt,
                "component_count": component_count,
                "summary": (
                    f"Procurement plan: {component_count} components across "
                    f"{po_count} vendor PO(s), ${total_cost:.2f} total cost, "
                    f"longest lead time {longest_lt} days."
                ),
                "next_step": (
                    "Review purchase orders and MOQ status. If all MOQs are met "
                    "and lead times fit the target date, approve for ordering. "
                    "Run supply_chain_avl_qualify to verify authorized sources."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def supply_chain_avl_qualify(
        bom_path: str,
    ) -> dict[str, Any]:
        """Station 2: Check components against AVL rules and score counterfeit risk.

        Uploads the BOM file to the API, which checks each component against
        the Approved Vendor List (AVL): authorized distributors, source control
        requirements (e.g. SI1304BDL), and counterfeit risk scoring based on
        component age, popularity, and price anomalies.

        IMPORTANT: Review flagged components before proceeding with procurement.

        Args:
            bom_path: Path to BOM file (.csv or .json)

        Returns:
            Component-level AVL status (approved/flagged/rejected) with risk scores.
        """
        try:
            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            client = get_client()

            with open(bom_path, "rb") as f:
                bom_data = f.read()

            result = client._make_upload_request(
                "v1/supply-chain/avl/qualify",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="application/octet-stream",
            )

            component_count = result.get("component_count", 0)
            flagged = result.get("flagged_count", 0)
            rejected = result.get("rejected_count", 0)
            approved = result.get("approved_count", 0)

            if flagged == 0 and rejected == 0:
                status_msg = f"ALL CLEAR: {approved} components approved"
            else:
                status_msg = (
                    f"{approved} approved, {flagged} flagged, {rejected} rejected"
                )

            return {
                "success": True,
                "components": result.get("components", []),
                "component_count": component_count,
                "flagged_count": flagged,
                "rejected_count": rejected,
                "approved_count": approved,
                "summary": f"AVL qualification: {status_msg}.",
                "next_step": (
                    "All components cleared. Run supply_chain_obsolescence_check "
                    "to verify lifecycle status."
                    if flagged == 0 and rejected == 0
                    else "Review flagged/rejected components. Ensure source-controlled "
                    "parts are sourced from authorized distributors only."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def supply_chain_obsolescence_check(
        bom_path: str,
    ) -> dict[str, Any]:
        """Station 3: Check lifecycle status for each part and suggest alternatives.

        Uploads the BOM file to the API, which checks each component's lifecycle
        status (active, NRND, obsolete, EOL, unknown) and suggests drop-in
        alternatives for at-risk parts.

        IMPORTANT: Review at-risk components and alternatives before design freeze.

        Args:
            bom_path: Path to BOM file (.csv or .json)

        Returns:
            Lifecycle status per component with alternative suggestions for at-risk parts.
        """
        try:
            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            client = get_client()

            with open(bom_path, "rb") as f:
                bom_data = f.read()

            result = client._make_upload_request(
                "v1/supply-chain/obsolescence/check",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="application/octet-stream",
            )

            component_count = result.get("component_count", 0)
            at_risk = result.get("at_risk_count", 0)
            active = result.get("active_count", 0)
            recommendations = result.get("recommendations", [])

            if at_risk == 0:
                status_msg = f"ALL CLEAR: {active} components active"
            else:
                status_msg = f"{active} active, {at_risk} AT RISK"

            return {
                "success": True,
                "components": result.get("components", []),
                "component_count": component_count,
                "at_risk_count": at_risk,
                "active_count": active,
                "recommendations": recommendations,
                "summary": f"Obsolescence check: {status_msg}.",
                "next_step": (
                    "All components have active lifecycle status."
                    if at_risk == 0
                    else "Review at-risk components and evaluate suggested alternatives "
                    "before design freeze. Consider last-time-buy for EOL parts."
                ),
            }
        except Exception as e:
            return {"error": str(e)}
