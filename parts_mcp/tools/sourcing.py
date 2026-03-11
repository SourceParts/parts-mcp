"""
Sourcing tools for price comparison and availability checking.
"""
import asyncio
import logging
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsAPIError, get_client, with_user_context
from parts_mcp.utils.cache import cache_pricing_data, cache_search_results

logger = logging.getLogger(__name__)


def register_sourcing_tools(mcp: FastMCP) -> None:
    """Register sourcing tools with the MCP server.

    Args:
        mcp: The FastMCP server instance
    """

    @mcp.tool()
    @cache_pricing_data()
    @with_user_context
    async def compare_prices(
        part_number: str,
        quantity: int = 1,
        suppliers: list[str] | None = None
    ) -> dict[str, Any]:
        """Compare prices for a part across multiple suppliers.

        Args:
            part_number: Part number to check
            quantity: Quantity needed
            suppliers: Optional list of suppliers to check

        Returns:
            Price comparison data
        """
        try:
            client = get_client()

            # Search for the part first
            search_results = client.search_parts(part_number, limit=1)

            if not search_results.get('results'):
                return {
                    "part_number": part_number,
                    "quantity": quantity,
                    "error": "Part not found",
                    "success": False
                }

            part_data = search_results['results'][0]
            sku = part_data.get('sku', part_data.get('part_number'))

            # Get pricing data from the API
            if sku:
                pricing_data = client.get_part_pricing(sku, quantity=quantity)
            else:
                pricing_data = {}

            # The API returns {"part_number": ..., "price_breaks": [...]}
            # Each price break is {"quantity": N, "unit_price": X}
            price_breaks = pricing_data.get('price_breaks', [])

            prices = []
            if price_breaks:
                # Find the best price break for the requested quantity
                unit_price = None
                for pb in sorted(price_breaks, key=lambda x: x.get('quantity', 0)):
                    if pb.get('quantity', 0) <= quantity:
                        unit_price = pb.get('unit_price')

                if unit_price is not None:
                    source = part_data.get('metadata', {}).get('external_source', 'Source Parts')
                    prices.append({
                        'supplier': source.upper() if source != 'Source Parts' else source,
                        'sku': sku,
                        'unit_price': unit_price,
                        'total_price': unit_price * quantity,
                        'stock': part_data.get('stock_quantity', 0),
                        'lead_time': f"{part_data.get('lead_time_days', 0)} days" if part_data.get('lead_time_days') else 'Check supplier'
                    })
            elif part_data.get('price') is not None:
                # Fallback: use price from search result directly
                base_price = float(part_data['price'])
                source = part_data.get('metadata', {}).get('external_source', 'Source Parts')
                prices.append({
                    'supplier': source.upper() if source != 'Source Parts' else source,
                    'sku': sku,
                    'unit_price': base_price,
                    'total_price': base_price * quantity,
                    'stock': part_data.get('stock_quantity', 0),
                    'lead_time': f"{part_data.get('lead_time_days', 0)} days" if part_data.get('lead_time_days') else 'Check supplier'
                })

            return {
                "part_number": part_number,
                "quantity": quantity,
                "suppliers_checked": len(prices),
                "prices": prices,
                "best_price": prices[0] if prices else None,
                "success": True
            }

        except SourcePartsAPIError as e:
            logger.error(f"Error comparing prices: {e}")
            return {
                "part_number": part_number,
                "quantity": quantity,
                "error": f"Price comparison failed: {str(e)}",
                "success": False
            }

    @mcp.tool()
    @with_user_context
    async def check_availability(
        part_numbers: list[str],
        quantities: list[int] | None = None
    ) -> dict[str, Any]:
        """Check availability for multiple parts.

        Args:
            part_numbers: List of part numbers
            quantities: Optional quantities needed for each part

        Returns:
            Availability information
        """
        if quantities and len(quantities) != len(part_numbers):
            return {"error": "Quantities list must match part_numbers length"}

        if not quantities:
            quantities = [1] * len(part_numbers)

        try:
            client = get_client()
            availability = []

            # Batch search if available
            if hasattr(client, 'batch_search'):
                batch_results = client.batch_search(part_numbers)
                parts_data = batch_results.get('results', {})
            else:
                parts_data = {}

            for i, part_number in enumerate(part_numbers):
                qty_needed = quantities[i]

                # Get part data from batch or individual search
                if part_number in parts_data:
                    part_data = parts_data[part_number]
                else:
                    search_results = client.search_parts(part_number, limit=1)
                    if search_results.get('results'):
                        part_data = search_results['results'][0]
                    else:
                        part_data = None

                if part_data:
                    sku = part_data.get('sku', part_data.get('part_number'))

                    # The API returns stock_quantity directly on the product,
                    # not a suppliers array. Read it from the search result.
                    total_stock = part_data.get('stock_quantity', 0) or 0
                    source = part_data.get('metadata', {}).get('external_source', 'Source Parts')

                    in_stock_suppliers = []
                    if total_stock >= qty_needed:
                        in_stock_suppliers.append({
                            'supplier': source.upper() if source != 'Source Parts' else source,
                            'stock': total_stock,
                            'sku': sku
                        })

                    availability.append({
                        'part_number': part_number,
                        'quantity_needed': qty_needed,
                        'available': total_stock >= qty_needed,
                        'total_stock': total_stock,
                        'in_stock_suppliers': in_stock_suppliers,
                        'manufacturer': part_data.get('manufacturer'),
                        'description': part_data.get('description')
                    })
                else:
                    availability.append({
                        'part_number': part_number,
                        'quantity_needed': qty_needed,
                        'available': False,
                        'error': 'Part not found'
                    })

            # Summary
            all_available = all(item['available'] for item in availability)

            return {
                "parts": part_numbers,
                "quantities": quantities,
                "availability": availability,
                "all_available": all_available,
                "success": True
            }

        except SourcePartsAPIError as e:
            logger.error(f"Error checking availability: {e}")
            return {
                "parts": part_numbers,
                "quantities": quantities,
                "error": f"Availability check failed: {str(e)}",
                "success": False
            }

    @mcp.tool()
    @cache_search_results()
    @with_user_context
    async def find_alternatives(
        part_number: str,
        parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Find alternative parts with similar specifications.

        Args:
            part_number: Original part number
            parameters: Optional key parameters to match

        Returns:
            Alternative parts suggestions
        """
        try:
            client = get_client()

            # Find alternatives
            alt_results = client.find_alternatives(
                part_number=part_number,
                match_parameters=list(parameters.keys()) if parameters else None
            )

            alternatives = alt_results.get('alternatives', [])

            # Filter by parameters if provided
            if parameters and alternatives:
                filtered = []
                for alt in alternatives:
                    match = True
                    for param, value in parameters.items():
                        alt_value = alt.get('parameters', {}).get(param)
                        if alt_value != value:
                            match = False
                            break
                    if match:
                        filtered.append(alt)
                alternatives = filtered

            return {
                "original_part": part_number,
                "match_parameters": parameters or {},
                "alternatives": alternatives,
                "total_alternatives": len(alternatives),
                "success": True
            }

        except SourcePartsAPIError as e:
            logger.error(f"Error finding alternatives: {e}")
            return {
                "original_part": part_number,
                "match_parameters": parameters or {},
                "error": f"Alternative search failed: {str(e)}",
                "success": False
            }

    @mcp.tool()
    @with_user_context
    async def calculate_bom_cost(
        bom: list[dict[str, Any]],
        quantity: int = 1,
        preferred_suppliers: list[str] | None = None
    ) -> dict[str, Any]:
        """Calculate total cost for a bill of materials.

        Args:
            bom: List of parts with quantities
            quantity: Number of boards/assemblies
            preferred_suppliers: Optional supplier preferences

        Returns:
            BOM cost analysis
        """
        try:
            client = get_client()
            cost_breakdown = []
            total_cost = 0.0
            errors = []

            async def _price_item(item: dict[str, Any]) -> tuple[dict | None, dict | None]:
                """Return (breakdown_entry, error_entry) for a single BOM line."""
                part_number = item.get('part_number', item.get('mpn', ''))
                part_qty = item.get('quantity', 1) * quantity

                if not part_number:
                    return None, {
                        'reference': item.get('reference', 'Unknown'),
                        'error': 'No part number specified'
                    }

                loop = asyncio.get_event_loop()
                try:
                    search_results = await loop.run_in_executor(
                        None, lambda: client.search_parts(part_number, limit=1)
                    )
                    if not search_results.get('results'):
                        return None, {
                            'reference': item.get('reference', ''),
                            'part_number': part_number,
                            'error': 'Part not found'
                        }

                    part_data = search_results['results'][0]
                    sku = part_data.get('sku', part_data.get('part_number'))

                    if not sku:
                        return None, {
                            'reference': item.get('reference', ''),
                            'part_number': part_number,
                            'error': 'No SKU found for part'
                        }

                    pricing_data = await loop.run_in_executor(
                        None, lambda: client.get_part_pricing(sku, quantity=part_qty)
                    )
                    price_breaks = pricing_data.get('price_breaks', [])

                    unit_price = None
                    for pb in sorted(price_breaks, key=lambda x: x.get('quantity', 0)):
                        if pb.get('quantity', 0) <= part_qty:
                            unit_price = pb.get('unit_price', pb.get('price'))

                    if unit_price is not None:
                        line_cost = unit_price * part_qty
                        return {
                            'reference': item.get('reference', ''),
                            'part_number': part_number,
                            'description': item.get('value', item.get('description', '')),
                            'quantity': part_qty,
                            'unit_price': unit_price,
                            'line_total': line_cost,
                            'supplier': 'Source Parts',
                            'sku': sku
                        }, None
                    else:
                        return None, {
                            'reference': item.get('reference', ''),
                            'part_number': part_number,
                            'error': 'No pricing available'
                        }

                except Exception as e:
                    return None, {
                        'reference': item.get('reference', ''),
                        'part_number': part_number,
                        'error': str(e)
                    }

            # Run all BOM item lookups concurrently (max 10 at a time to avoid hammering the API)
            semaphore = asyncio.Semaphore(10)

            async def _price_item_throttled(item: dict[str, Any]) -> tuple[dict | None, dict | None]:
                async with semaphore:
                    return await _price_item(item)

            results = await asyncio.gather(*[_price_item_throttled(item) for item in bom])

            for entry, error in results:
                if entry is not None:
                    cost_breakdown.append(entry)
                    total_cost += entry['line_total']
                elif error is not None:
                    errors.append(error)

            # Sort by line total (most expensive first)
            cost_breakdown.sort(key=lambda x: x['line_total'], reverse=True)

            return {
                "bom_items": len(bom),
                "priced_items": len(cost_breakdown),
                "quantity": quantity,
                "total_cost": round(total_cost, 2),
                "cost_breakdown": cost_breakdown,
                "errors": errors,
                "currency": "USD",
                "success": True
            }

        except Exception as e:
            logger.error(f"Error calculating BOM cost: {e}")
            return {
                "bom_items": len(bom),
                "quantity": quantity,
                "error": f"BOM cost calculation failed: {str(e)}",
                "success": False
            }
