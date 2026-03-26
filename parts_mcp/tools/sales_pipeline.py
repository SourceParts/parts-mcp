"""
Sales Pipeline: AOI-style operator-approved quoting and invoicing.

Thin client MCP tools that upload data to the Source Parts API
and return results for operator review. Every step requires explicit
approval before proceeding to the next.

Pipeline:
  1. sales_quote_build          — price a BOM and generate a quote
  2. sales_quote_negotiate      — revise quantities/pricing on a quote
  3. sales_order_convert        — validate stock and convert quote to order
  4. sales_invoice_generate     — generate invoice data from an order
  5. sales_commission_calculate — calculate sales commission on an order
"""
import logging
import os
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def register_sales_pipeline_tools(mcp: FastMCP) -> None:
    """Register Sales pipeline tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def sales_quote_build(
        bom_path: str,
        quantity: int,
        customer_name: str,
    ) -> dict[str, Any]:
        """Station 1: Price a BOM and generate a quote breakdown.

        Uploads the BOM file to the API, which prices all components using
        the internal DB, adds fab + assembly + margin, and returns a full
        quote breakdown for operator review.

        IMPORTANT: Review the quote before sending to the customer or
        proceeding to negotiation.

        Args:
            bom_path: Path to BOM file (.csv or .json)
            quantity: Build quantity (number of units)
            customer_name: Customer name or identifier

        Returns:
            Quote breakdown with line items, subtotals, and margin analysis.
        """
        try:
            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            client = get_client()

            with open(bom_path, "rb") as f:
                bom_data = f.read()

            result = client._make_upload_request(
                "v1/sales/quote/build",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="application/octet-stream",
                form_fields={
                    "quantity": str(quantity),
                    "customer_name": customer_name,
                },
            )

            quote_id = result.get("quote_id", "")
            line_count = result.get("line_item_count", 0)
            total = result.get("total_cost", 0)
            margin = result.get("margin_analysis", {})

            return {
                "success": True,
                "quote_id": quote_id,
                "customer_name": customer_name,
                "build_quantity": quantity,
                "line_item_count": line_count,
                "component_subtotal": result.get("component_subtotal", 0),
                "fab_cost": result.get("fab_cost", 0),
                "assembly_cost": result.get("assembly_cost", 0),
                "total_cost": total,
                "margin_analysis": margin,
                "line_items": result.get("line_items", []),
                "summary": (
                    f"Quote {quote_id}: {line_count} line items, "
                    f"${total:.2f} total cost, "
                    f"{margin.get('margin_pct', 0) * 100:.0f}% margin "
                    f"(${margin.get('selling_price', 0):.2f} selling price)."
                ),
                "next_step": (
                    "Review line items and margin. If adjustments needed, "
                    "call sales_quote_negotiate. Otherwise, call "
                    "sales_order_convert to validate stock and create an order."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def sales_quote_negotiate(
        quote_id: str,
        revised_quantity: int | None = None,
        revised_margin_pct: float | None = None,
    ) -> dict[str, Any]:
        """Station 2: Revise quantities or pricing on an existing quote.

        Recalculates the quote at new terms and shows the margin delta
        compared to the original quote.

        IMPORTANT: Review margin impact before accepting revised terms.

        Args:
            quote_id: Existing quote identifier (e.g. QUO-A1B2C3D4)
            revised_quantity: New build quantity (optional)
            revised_margin_pct: New margin percentage as decimal (optional, e.g. 0.20 for 20%)

        Returns:
            Revised quote with margin delta vs. original.
        """
        try:
            client = get_client()

            json_data = {"quote_id": quote_id}
            if revised_quantity is not None:
                json_data["revised_quantity"] = revised_quantity
            if revised_margin_pct is not None:
                json_data["revised_margin_pct"] = revised_margin_pct

            result = client._make_request(
                "POST", "/v1/sales/quote/negotiate", json_data=json_data
            )

            margin_delta = result.get("margin_delta", 0)
            price_delta = result.get("price_delta", 0)
            direction = "increase" if margin_delta >= 0 else "decrease"

            return {
                "success": True,
                "quote_id": quote_id,
                "revised_quantity": result.get("revised_quantity"),
                "original_margin": result.get("original_margin", {}),
                "revised_margin": result.get("revised_margin", {}),
                "margin_delta": margin_delta,
                "price_delta": price_delta,
                "summary": (
                    f"Quote {quote_id} revised: "
                    f"margin {direction} of ${abs(margin_delta):.2f}, "
                    f"price {direction} of ${abs(price_delta):.2f}."
                ),
                "next_step": (
                    "If terms are acceptable, call sales_order_convert "
                    "to validate stock and create the order."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def sales_order_convert(
        quote_id: str,
    ) -> dict[str, Any]:
        """Station 3: Validate stock/lead times and convert quote to order.

        Checks inventory for all line items in the quote and flags any
        shortages or long lead times. If all clear, creates the order.

        IMPORTANT: Review items at risk before confirming the order.

        Args:
            quote_id: Quote identifier to convert (e.g. QUO-A1B2C3D4)

        Returns:
            Order readiness report (all clear or items at risk).
        """
        try:
            client = get_client()

            result = client._make_request(
                "POST", "/v1/sales/order/convert", json_data={"quote_id": quote_id}
            )

            order_id = result.get("order_id", "")
            all_clear = result.get("all_clear", False)
            at_risk = result.get("items_at_risk_count", 0)

            status_msg = "ALL CLEAR" if all_clear else f"{at_risk} ITEMS AT RISK"

            return {
                "success": True,
                "quote_id": quote_id,
                "order_id": order_id,
                "all_clear": all_clear,
                "items_at_risk": result.get("items_at_risk", []),
                "items_at_risk_count": at_risk,
                "summary": f"Order {order_id} from quote {quote_id}: {status_msg}.",
                "next_step": (
                    "Call sales_invoice_generate to create an invoice."
                    if all_clear
                    else "Review at-risk items. Resolve shortages, then retry sales_order_convert."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def sales_invoice_generate(
        order_id: str,
        payment_terms: str = "net30",
        tax_rate: float = 0.0,
    ) -> dict[str, Any]:
        """Station 4: Generate invoice data from an order.

        Creates a draft invoice with line items, tax calculation,
        totals, and due date based on payment terms.

        IMPORTANT: Review invoice details before sending to customer.

        Args:
            order_id: Order identifier (e.g. ORD-A1B2C3D4)
            payment_terms: Payment terms (net30, net60, due_on_receipt, etc.)
            tax_rate: Decimal tax rate (e.g. 0.0875 for 8.75%)

        Returns:
            Invoice data with line items, tax, totals, and due date.
        """
        try:
            client = get_client()

            result = client._make_request(
                "POST",
                "/v1/sales/invoice/generate",
                json_data={
                    "order_id": order_id,
                    "payment_terms": payment_terms,
                    "tax_rate": tax_rate,
                },
            )

            invoice_id = result.get("invoice_id", "")
            total = result.get("total", 0)
            due_date = result.get("due_date", "")

            return {
                "success": True,
                "invoice_id": invoice_id,
                "order_id": order_id,
                "payment_terms": payment_terms,
                "subtotal": result.get("subtotal", 0),
                "tax_rate": tax_rate,
                "tax_amount": result.get("tax_amount", 0),
                "total": total,
                "due_date": due_date,
                "line_items": result.get("line_items", []),
                "summary": (
                    f"Invoice {invoice_id}: ${total:.2f} total, "
                    f"due {due_date[:10] if due_date else 'N/A'} ({payment_terms})."
                ),
                "next_step": (
                    "Review invoice details. If correct, send to customer. "
                    "Call sales_commission_calculate to compute sales commission."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def sales_commission_calculate(
        order_id: str,
        commission_rate: float,
        commission_type: str = "percentage",
    ) -> dict[str, Any]:
        """Station 5: Calculate sales commission on an order.

        Computes commission payout based on order total and the given
        commission structure (percentage or flat amount).

        Args:
            order_id: Order identifier (e.g. ORD-A1B2C3D4)
            commission_rate: Commission rate — decimal for percentage (e.g. 0.05 for 5%)
                            or dollar amount for flat
            commission_type: "percentage" (default) or "flat"

        Returns:
            Commission breakdown with net revenue.
        """
        try:
            client = get_client()

            result = client._make_request(
                "POST",
                "/v1/sales/commission/calculate",
                json_data={
                    "order_id": order_id,
                    "commission_rate": commission_rate,
                    "commission_type": commission_type,
                },
            )

            commission_amount = result.get("commission_amount", 0)
            order_total = result.get("order_total", 0)
            net_revenue = result.get("net_revenue", 0)

            rate_display = (
                f"{commission_rate * 100:.1f}%"
                if commission_type == "percentage"
                else f"${commission_rate:.2f} flat"
            )

            return {
                "success": True,
                "order_id": order_id,
                "order_total": order_total,
                "commission_type": commission_type,
                "commission_rate": commission_rate,
                "commission_amount": commission_amount,
                "net_revenue": net_revenue,
                "summary": (
                    f"Commission on order {order_id}: "
                    f"${commission_amount:.2f} ({rate_display}), "
                    f"net revenue ${net_revenue:.2f}."
                ),
                "next_step": (
                    "Commission calculated. Review and approve payout."
                ),
            }
        except Exception as e:
            return {"error": str(e)}
