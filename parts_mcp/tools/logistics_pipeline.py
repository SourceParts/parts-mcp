"""
Logistics Pipeline: AOI-style operator-approved shipping & logistics.

Thin client MCP tools that upload data to the Source Parts API
and return results for operator review. Every step requires explicit
approval before proceeding to the next.

Pipeline:
  1. logistics_create_shipment      — create shipment with label + customs
  2. logistics_track_shipment       — track a shipment by ID or tracking number
  3. logistics_customs_declare      — map BOM to HS codes + declared values
  4. logistics_consignment_manifest — diff BOM vs inventory for CM shipment
  5. logistics_inventory_reconcile  — reconcile physical count vs system inventory
"""
import json
import logging
import os
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def register_logistics_pipeline_tools(mcp: FastMCP) -> None:
    """Register Logistics Pipeline tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def logistics_create_shipment(
        order_id: str,
        destination: dict[str, str],
        carrier: str = "dhl",
        weight_kg: float = 0.5,
    ) -> dict[str, Any]:
        """Station 1: Create a shipment with label, packing list, and customs docs.

        Creates a shipment for an order, generates shipping label data,
        packing list, and customs declaration for international shipments.

        IMPORTANT: Review shipment details and label before dispatching.

        Args:
            order_id: Order identifier (e.g. ORD-A1B2C3D4)
            destination: Destination address dict with keys: name, street, city, state, postal_code, country
            carrier: Preferred carrier (dhl, fedex, sf_express, usps)
            weight_kg: Package weight in kilograms

        Returns:
            Shipment data with label URL, packing list, and customs declaration.
        """
        try:
            client = get_client()

            json_data = {
                "order_id": order_id,
                "destination": destination,
                "carrier": carrier,
                "package": {"weight_kg": weight_kg},
            }

            result = client._make_request(
                "POST", "/v1/logistics/shipment/create", json_data=json_data
            )

            shipment_id = result.get("shipment_id", "")
            tracking = result.get("tracking_number", "")
            cost = result.get("estimated_cost", 0)
            delivery = result.get("estimated_delivery", "")
            international = result.get("international", False)

            summary_lines = [
                f"Shipment: {shipment_id}",
                f"Tracking: {tracking}",
                f"Carrier: {carrier.upper()}",
                f"Estimated cost: ${cost:.2f}",
                f"Estimated delivery: {delivery[:10] if delivery else 'N/A'}",
                f"International: {'Yes' if international else 'No'}",
            ]

            if result.get("customs_declaration"):
                summary_lines.append("Customs declaration generated.")

            return {
                "success": True,
                "shipment_id": shipment_id,
                "order_id": order_id,
                "tracking_number": tracking,
                "carrier": carrier,
                "label_url": result.get("label_url", ""),
                "packing_list": result.get("packing_list"),
                "customs_declaration": result.get("customs_declaration"),
                "estimated_cost": cost,
                "estimated_delivery": delivery,
                "international": international,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Review shipment details and label. Print label and attach to package. "
                    "Call logistics_track_shipment to monitor transit."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def logistics_track_shipment(
        shipment_id: str,
        carrier: str = "",
    ) -> dict[str, Any]:
        """Station 2: Track a shipment and get current status.

        Returns tracking events with timestamps, locations, and status updates.

        Args:
            shipment_id: Shipment identifier (e.g. SHP-A1B2C3D4)
            carrier: Carrier name (dhl, fedex, sf_express, usps)

        Returns:
            Tracking events array with current status and ETA.
        """
        try:
            client = get_client()

            json_data = {
                "shipment_id": shipment_id,
                "carrier": carrier,
            }

            result = client._make_request(
                "POST", "/v1/logistics/shipment/track", json_data=json_data
            )

            events = result.get("events", [])
            current_status = result.get("current_status", "unknown")
            eta = result.get("eta", "")

            summary_lines = [
                f"Shipment: {shipment_id}",
                f"Status: {current_status.upper()}",
                f"ETA: {eta[:10] if eta else 'N/A'}",
                f"Events: {len(events)}",
            ]
            for event in events[-5:]:
                summary_lines.append(
                    f"  [{event.get('timestamp', '')[:16]}] "
                    f"{event.get('location', '')}: {event.get('description', '')}"
                )

            return {
                "success": True,
                "shipment_id": shipment_id,
                "carrier": carrier,
                "current_status": current_status,
                "eta": eta,
                "events": events,
                "total_events": len(events),
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Shipment delivered. Confirm receipt with recipient."
                    if current_status == "delivered"
                    else "Track again later for updated status. Call logistics_track_shipment periodically."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def logistics_customs_declare(
        bom_path: str,
        invoice_amount: float,
        destination_country: str,
        origin_country: str = "CN",
    ) -> dict[str, Any]:
        """Station 3: Generate customs declaration from BOM with HS code mapping.

        Uploads BOM file and maps components to HS codes based on category.
        Calculates declared values for each line item.

        IMPORTANT: Review HS codes and declared values before submitting to customs.

        Args:
            bom_path: Path to BOM file (.csv or .json)
            invoice_amount: Total invoice amount in USD
            destination_country: Destination country code (e.g. US, DE, JP)
            origin_country: Origin country code (default CN)

        Returns:
            Customs declaration with HS-coded line items and total declared value.
        """
        try:
            client = get_client()

            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            with open(bom_path, "rb") as f:
                bom_data = f.read()

            result = client._make_upload_request(
                "logistics/customs/declare",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="application/octet-stream",
                form_fields={
                    "invoice_amount": str(invoice_amount),
                    "destination_country": destination_country,
                    "origin_country": origin_country,
                },
            )

            line_items = result.get("line_items", [])
            total_declared = result.get("total_declared_value", 0)
            declaration_id = result.get("declaration_id", "")

            summary_lines = [
                f"Declaration: {declaration_id}",
                f"Route: {origin_country.upper()} -> {destination_country.upper()}",
                f"Line items: {len(line_items)}",
                f"Total declared value: ${total_declared:.2f}",
                f"Invoice amount: ${invoice_amount:.2f}",
            ]

            # Show HS code breakdown
            hs_groups = {}
            for li in line_items:
                code = li.get("hs_code", "N/A")
                hs_groups[code] = hs_groups.get(code, 0) + 1
            for code, count in sorted(hs_groups.items()):
                summary_lines.append(f"  HS {code}: {count} item(s)")

            return {
                "success": True,
                "declaration_id": declaration_id,
                "destination_country": destination_country.upper(),
                "origin_country": origin_country.upper(),
                "total_line_items": len(line_items),
                "line_items": line_items,
                "total_declared_value": total_declared,
                "invoice_amount": invoice_amount,
                "currency": "USD",
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Review HS codes and declared values for accuracy. "
                    "Attach declaration to shipment. "
                    "Call logistics_create_shipment to generate labels."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def logistics_consignment_manifest(
        bom_path: str,
        inventory_levels: dict[str, int],
        cm_address: str,
    ) -> dict[str, Any]:
        """Station 4: Generate a consignment manifest by diffing BOM vs inventory.

        Uploads BOM and compares against current inventory levels to determine
        what needs to be shipped to the CM (contract manufacturer).

        IMPORTANT: Review the manifest before shipping. Verify short items.

        Args:
            bom_path: Path to BOM file (.csv or .json)
            inventory_levels: Dict mapping part_number to quantity on hand at CM
            cm_address: Contract manufacturer shipping address

        Returns:
            Manifest with items to ship, items on hand, and shortages.
        """
        try:
            client = get_client()

            if not os.path.exists(bom_path):
                return {"error": f"BOM file not found: {bom_path}"}

            with open(bom_path, "rb") as f:
                bom_data = f.read()

            result = client._make_upload_request(
                "logistics/consignment/manifest",
                file_data=bom_data,
                filename=os.path.basename(bom_path),
                content_type="application/octet-stream",
                form_fields={
                    "inventory_levels": json.dumps(inventory_levels),
                    "cm_address": cm_address,
                },
            )

            to_ship = result.get("items_to_ship", [])
            on_hand = result.get("items_on_hand", [])
            short = result.get("items_short", [])
            total_packages = result.get("total_packages", 0)
            weight_est = result.get("total_weight_estimate_kg", 0)

            summary_lines = [
                f"Manifest: {result.get('manifest_id', '')}",
                f"CM: {cm_address}",
                f"Items to ship: {len(to_ship)}",
                f"Items on hand at CM: {len(on_hand)}",
                f"Items short (need procurement): {len(short)}",
                f"Estimated packages: {total_packages}",
                f"Estimated weight: {weight_est:.3f} kg",
            ]

            if short:
                summary_lines.append("\nShort items:")
                for item in short[:10]:
                    summary_lines.append(
                        f"  {item['part_number']}: need {item['quantity_needed']}, "
                        f"have {item['quantity_on_hand']}, short {item.get('quantity_short', 0)}"
                    )

            return {
                "success": True,
                "manifest_id": result.get("manifest_id", ""),
                "cm_address": cm_address,
                "items_to_ship": to_ship,
                "items_on_hand": on_hand,
                "items_short": short,
                "total_packages": total_packages,
                "total_weight_estimate_kg": weight_est,
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Procure short items before shipping."
                    if short
                    else "All items accounted for. Call logistics_create_shipment to ship to CM."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    async def logistics_inventory_reconcile(
        physical_count_path: str,
        system_inventory_path: str,
    ) -> dict[str, Any]:
        """Station 5: Reconcile physical inventory count against system records.

        Uploads physical count CSV and system inventory CSV. Diffs quantities
        and reports matches, overages, and shortages.

        IMPORTANT: Review discrepancies and investigate before adjusting system records.

        Args:
            physical_count_path: Path to physical count CSV (columns: part_number, counted_quantity)
            system_inventory_path: Path to system inventory CSV (columns: part_number, system_quantity)

        Returns:
            Reconciliation report with matches, overages, shortages, and accuracy.
        """
        try:
            client = get_client()

            for path, label in [(physical_count_path, "Physical count"), (system_inventory_path, "System inventory")]:
                if not os.path.exists(path):
                    return {"error": f"{label} file not found: {path}"}

            with open(physical_count_path, "rb") as f:
                physical_data = f.read()
            with open(system_inventory_path, "rb") as f:
                system_data = f.read()

            from urllib.parse import urljoin

            import httpx

            base = client.base_url if client.base_url.endswith('/') else client.base_url + '/'
            url = urljoin(base, "logistics/inventory/reconcile")

            upload_headers = {
                "Authorization": f"Bearer {client.api_key}",
                "User-Agent": "PARTS-MCP/1.0",
            }

            files = {
                "physical_count": (os.path.basename(physical_count_path), physical_data, "text/csv"),
                "system_inventory": (os.path.basename(system_inventory_path), system_data, "text/csv"),
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

            matches = result.get("matches", [])
            overages = result.get("overages", [])
            shortages = result.get("shortages", [])
            accuracy = result.get("accuracy_pct", 0)
            total_checked = result.get("total_parts_checked", 0)

            summary_lines = [
                f"Parts checked: {total_checked}",
                f"Matches: {len(matches)}",
                f"Overages: {len(overages)}",
                f"Shortages: {len(shortages)}",
                f"Accuracy: {accuracy}%",
            ]

            if shortages:
                summary_lines.append("\nShortages:")
                for item in shortages[:10]:
                    summary_lines.append(
                        f"  {item['part_number']}: counted {item['counted_quantity']}, "
                        f"system {item['system_quantity']} (diff {item['difference']})"
                    )

            if overages:
                summary_lines.append("\nOverages:")
                for item in overages[:10]:
                    summary_lines.append(
                        f"  {item['part_number']}: counted {item['counted_quantity']}, "
                        f"system {item['system_quantity']} (diff +{item['difference']})"
                    )

            return {
                "success": True,
                "total_parts_checked": total_checked,
                "matches": matches,
                "overages": overages,
                "shortages": shortages,
                "accuracy_pct": accuracy,
                "total_discrepancies": result.get("total_discrepancies", 0),
                "summary": "\n".join(summary_lines),
                "next_step": (
                    "Inventory matches. No action needed."
                    if not overages and not shortages
                    else "Investigate discrepancies. Update system records after verification."
                ),
            }
        except Exception as e:
            return {"error": str(e)}
