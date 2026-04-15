"""
DFM (Design for Manufacturability) Pipeline: tiered review service.

Thin client MCP tools that upload design files to the Source Parts API
and return complexity scoring, pricing, review status, and report delivery.

Customer-facing tools (public):
  1. dfm_estimate         — upload design files, get pricing + complexity
  2. dfm_submit           — submit for review with payment
  3. dfm_check_status     — poll review status

Admin-only tools:
  4. dfm_add_findings     — add review findings to a request
  5. dfm_generate_report  — generate PDF report + email
  6. dfm_deliver_report   — re-send report to customer
"""
import json
import logging
import os
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def register_dfm_pipeline_tools(mcp: FastMCP) -> None:
    """Register DFM Pipeline tools with the MCP server."""

    # ------------------------------------------------------------------
    # Public tools (customer-facing)
    # ------------------------------------------------------------------

    @mcp.tool()
    @with_user_context
    @require_role("public")
    async def dfm_estimate(
        design_path: str,
        tier: str = "",
    ) -> dict[str, Any]:
        """Analyze design file complexity and get DFM review pricing.

        Uploads a design file (Gerber ZIP, .kicad_pcb, or CAD file) to
        the Source Parts API, which analyzes layer count, component density,
        HDI features, and blind/buried vias to produce a complexity score
        and pricing estimate.

        Tiers:
          - basic:         $97  (3-5 day turnaround)
          - comprehensive: $297 (1-2 day turnaround)

        If tier is omitted, the API auto-recommends based on complexity.

        Args:
            design_path: Path to design file (Gerber .zip or .kicad_pcb)
            tier: Optional tier selection (basic or comprehensive)

        Returns:
            Pricing, turnaround, complexity score, and design analysis.
        """
        try:
            client = get_client()

            if not os.path.exists(design_path):
                return {"error": f"Design file not found: {design_path}"}

            with open(design_path, "rb") as f:
                file_data = f.read()

            form_fields = {}
            if tier:
                form_fields["tier"] = tier

            result = client._make_upload_request(
                "v1/dfm/estimate",
                file_data=file_data,
                filename=os.path.basename(design_path),
                content_type="application/octet-stream",
                form_fields=form_fields if form_fields else None,
            )

            score = result.get("complexity_score", 0)
            layers = result.get("layer_count", 0)
            price = result.get("price", 0)
            tier_label = result.get("tier_label", "")
            rec = result.get("recommendation")

            summary_lines = [
                f"Tier: {tier_label} (${price:.2f})",
                f"Turnaround: {result.get('turnaround_days', 0)} business days",
                f"Complexity: {score}/10",
                f"Layers: {layers}",
                f"Components: ~{result.get('component_estimate', 0)}",
                f"Board area: {result.get('board_area_mm2', 0):.1f} mm2",
                f"HDI: {'yes' if result.get('has_hdi') else 'no'}",
                f"Blind/buried vias: {'yes' if result.get('has_blind_vias') else 'no'}",
            ]
            if rec:
                summary_lines.append(f"\nRecommendation: {rec}")

            return {
                "success": True,
                "tier": result.get("tier", ""),
                "tier_label": tier_label,
                "price": price,
                "turnaround_days": result.get("turnaround_days", 0),
                "complexity_score": score,
                "layer_count": layers,
                "component_estimate": result.get("component_estimate", 0),
                "board_area_mm2": result.get("board_area_mm2", 0),
                "has_hdi": result.get("has_hdi", False),
                "has_blind_vias": result.get("has_blind_vias", False),
                "recommendation": rec,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Review the complexity analysis and pricing. "
                    "Run dfm_submit to submit the design for review with payment."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("public")
    async def dfm_submit(
        design_path: str,
        tier: str,
        customer_name: str,
        customer_email: str,
        promo_code: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Submit a DFM review request with design files and customer info.

        Uploads the design file, creates a review request in the database,
        and triggers a Stripe payment intent. Returns a payment URL if
        payment is required.

        Tiers:
          - basic:         $97  (3-5 day turnaround)
          - comprehensive: $297 (1-2 day turnaround)

        Promo codes: LAUNCH99 ($99 basic), PARTNER199 ($199 comprehensive)

        Args:
            design_path: Path to design file (Gerber .zip or .kicad_pcb)
            tier: Review tier (basic or comprehensive)
            customer_name: Customer's full name
            customer_email: Customer's email address
            promo_code: Optional promotional code
            notes: Optional notes or requirements

        Returns:
            Request ID, status, payment URL, and estimated completion date.
        """
        try:
            client = get_client()

            if not os.path.exists(design_path):
                return {"error": f"Design file not found: {design_path}"}

            with open(design_path, "rb") as f:
                file_data = f.read()

            form_fields = {
                "tier": tier,
                "customer_name": customer_name,
                "customer_email": customer_email,
            }
            if promo_code:
                form_fields["promo_code"] = promo_code
            if notes:
                form_fields["notes"] = notes

            result = client._make_upload_request(
                "v1/dfm/submit",
                file_data=file_data,
                filename=os.path.basename(design_path),
                content_type="application/octet-stream",
                form_fields=form_fields,
            )

            request_id = result.get("request_id", "")
            price = result.get("price", 0)
            status = result.get("status", "")
            completion = result.get("estimated_completion", "")

            summary_lines = [
                f"Request: {request_id}",
                f"Status: {status}",
                f"Tier: {result.get('tier_label', '')} (${price:.2f})",
                f"Customer: {customer_name} <{customer_email}>",
                f"Complexity: {result.get('complexity_score', 0)}/10",
                f"Estimated completion: {completion}",
            ]

            if result.get("promo_applied"):
                summary_lines.append(f"Promo applied: {result['promo_applied']}")
            if result.get("promo_warning"):
                summary_lines.append(f"Promo warning: {result['promo_warning']}")
            if result.get("payment_url"):
                summary_lines.append(f"\nPayment URL: {result['payment_url']}")

            return {
                "success": True,
                "request_id": request_id,
                "status": status,
                "tier": result.get("tier", ""),
                "price": price,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "complexity_score": result.get("complexity_score", 0),
                "payment_url": result.get("payment_url"),
                "estimated_completion": completion,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    f"Share the payment URL with the customer. "
                    f"Once payment is confirmed, use dfm_check_status('{request_id}') "
                    f"to monitor review progress."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("public")
    async def dfm_check_status(
        request_id: str,
    ) -> dict[str, Any]:
        """Check the current status of a DFM review request.

        Polls the API for the latest status, progress percentage,
        findings count, and estimated completion date.

        Status flow:
          submitted -> payment_pending -> in_review -> findings_ready ->
          report_sent -> complete

        Args:
            request_id: DFM review request ID (e.g. DFM-A1B2C3D4)

        Returns:
            Current status, progress, findings count, and estimated completion.
        """
        try:
            client = get_client()

            result = client._make_request(
                "GET", f"/v1/dfm/status/{request_id}"
            )

            status = result.get("status", "unknown")
            progress = result.get("progress", 0)
            findings = result.get("findings_count", 0)
            completion = result.get("estimated_completion", "")

            summary_lines = [
                f"Request: {request_id}",
                f"Status: {status}",
                f"Progress: {progress}%",
                f"Findings: {findings}",
                f"Est. completion: {completion}",
            ]

            # Determine next step based on status
            if status == "payment_pending":
                next_step = "Payment is pending. Share the payment URL with the customer."
            elif status == "in_review":
                next_step = "Review is in progress. Check back later for updates."
            elif status == "findings_ready":
                next_step = "Findings are ready. Use dfm_generate_report to create the PDF."
            elif status == "report_sent":
                next_step = "Report has been sent. Use dfm_deliver_report to re-send if needed."
            elif status == "complete":
                next_step = "Review is complete. No further action needed."
            else:
                next_step = "Waiting for review to begin. Check back later."

            return {
                "success": True,
                "request_id": request_id,
                "status": status,
                "progress": progress,
                "findings_count": findings,
                "estimated_completion": completion,
                "summary": "\n".join(summary_lines),
                "next_step": next_step,
            }
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Admin-only tools
    # ------------------------------------------------------------------

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def dfm_add_findings(
        request_id: str,
        findings: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Add review findings to a DFM request (admin-only).

        Each finding should include category, severity, description,
        recommendation, and affected_area. The API validates all fields
        and stores them in the dfm_review_findings table.

        IMPORTANT: Review all findings before generating the customer report.

        Args:
            request_id: DFM review request ID (e.g. DFM-A1B2C3D4)
            findings: List of finding dicts, each with:
                - category: e.g. design_issue, manufacturability, material
                - severity: info, low, medium, high, or critical
                - description: What the issue is
                - recommendation: How to fix it
                - affected_area: Which part of the design is affected
                - image_ref: (optional) reference to annotated image

        Returns:
            Confirmation with findings count.
        """
        try:
            client = get_client()

            json_data = {
                "findings": findings,
            }

            result = client._make_request(
                "POST", f"/v1/dfm/findings/{request_id}", json_data=json_data
            )

            count = result.get("findings_count", 0)
            stored = result.get("findings", [])

            summary_lines = [
                f"Request: {request_id}",
                f"Findings added: {count}",
            ]
            for f in stored:
                summary_lines.append(
                    f"  [{f.get('severity', '').upper()}] {f.get('category', '')}: "
                    f"{f.get('description', '')[:80]}"
                )

            return {
                "success": True,
                "request_id": request_id,
                "findings_count": count,
                "findings": stored,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    f"Findings recorded. Use dfm_generate_report('{request_id}') "
                    f"to generate the PDF report and email it to the customer."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def dfm_generate_report(
        request_id: str,
    ) -> dict[str, Any]:
        """Generate a PDF report and email it to the customer (admin-only).

        Triggers the existing PDF generation service, uploads the report
        to storage, and sends it via Resend to the customer on file.

        IMPORTANT: Ensure all findings have been added before generating.

        Args:
            request_id: DFM review request ID (e.g. DFM-A1B2C3D4)

        Returns:
            Report URL and email delivery confirmation.
        """
        try:
            client = get_client()

            result = client._make_request(
                "POST", f"/v1/dfm/report/{request_id}/generate"
            )

            report_url = result.get("report_url", "")
            email_sent = result.get("email_sent", False)
            recipient = result.get("recipient", "")

            summary_lines = [
                f"Request: {request_id}",
                f"Report: {report_url}",
                f"Email sent: {'yes' if email_sent else 'no'}",
                f"Recipient: {recipient}",
            ]

            return {
                "success": True,
                "request_id": request_id,
                "report_url": report_url,
                "email_sent": email_sent,
                "recipient": recipient,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    f"Report generated and sent to {recipient}. "
                    f"Use dfm_deliver_report('{request_id}') to re-send "
                    f"to a different email if needed."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def dfm_deliver_report(
        request_id: str,
        email: str = "",
        message: str = "",
    ) -> dict[str, Any]:
        """Re-send or deliver the DFM report to a specific email (admin-only).

        Sends the previously generated PDF report to the specified email,
        or re-sends to the original customer if no email override is given.

        Args:
            request_id: DFM review request ID (e.g. DFM-A1B2C3D4)
            email: Optional override recipient email address
            message: Optional custom note to include in the email

        Returns:
            Email delivery confirmation.
        """
        try:
            client = get_client()

            json_data = {}
            if email:
                json_data["email"] = email
            if message:
                json_data["message"] = message

            result = client._make_request(
                "POST",
                f"/v1/dfm/report/{request_id}/deliver",
                json_data=json_data if json_data else None,
            )

            report_url = result.get("report_url", "")
            email_sent = result.get("email_sent", False)
            recipient = result.get("recipient", "")

            summary_lines = [
                f"Request: {request_id}",
                f"Report: {report_url}",
                f"Email sent: {'yes' if email_sent else 'no'}",
                f"Recipient: {recipient}",
            ]
            if result.get("custom_message"):
                summary_lines.append(f"Custom message: {result['custom_message']}")

            return {
                "success": True,
                "request_id": request_id,
                "report_url": report_url,
                "email_sent": email_sent,
                "recipient": recipient,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Report delivered. Review is complete."
                    if email_sent
                    else "Delivery failed. Check the email address and try again."
                ),
            }
        except Exception as e:
            return {"error": str(e)}
