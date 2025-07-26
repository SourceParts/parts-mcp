"""
Sourcing tools for price comparison and availability checking.
"""
import logging
from typing import Dict, Any, List, Optional
from fastmcp import FastMCP

from parts_mcp.utils.api_client import (
    get_client,
    SourcePartsAPIError
)
from parts_mcp.utils.cache import cache_pricing_data, cache_search_results

logger = logging.getLogger(__name__)


def register_sourcing_tools(mcp: FastMCP) -> None:
    """Register sourcing tools with the MCP server.
    
    Args:
        mcp: The FastMCP server instance
    """
    
    @mcp.tool()
    @cache_pricing_data()
    async def compare_prices(
        part_number: str,
        quantity: int = 1,
        suppliers: Optional[List[str]] = None
    ) -> Dict[str, Any]:
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
            search_results = client.search_parts(part_number, page_size=1)
            
            if not search_results.get('results'):
                return {
                    "part_number": part_number,
                    "quantity": quantity,
                    "error": "Part not found",
                    "success": False
                }
                
            part_data = search_results['results'][0]
            part_id = part_data.get('id', part_data.get('part_id'))
            
            # Get pricing data
            if part_id:
                pricing_data = client.get_part_pricing(part_id, quantity=quantity)
            else:
                # Use pricing from search results if available
                pricing_data = {'suppliers': part_data.get('suppliers', [])}
            
            # Format pricing comparison
            prices = []
            for supplier in pricing_data.get('suppliers', []):
                supplier_name = supplier.get('name', supplier.get('supplier'))
                
                # Filter by requested suppliers if specified
                if suppliers and supplier_name not in suppliers:
                    continue
                    
                # Find appropriate price break
                price = None
                price_breaks = supplier.get('price_breaks', supplier.get('pricing', []))
                
                for pb in sorted(price_breaks, key=lambda x: x.get('quantity', 0)):
                    if pb.get('quantity', 0) <= quantity:
                        price = pb.get('price', pb.get('unit_price'))
                        
                if price is not None:
                    prices.append({
                        'supplier': supplier_name,
                        'sku': supplier.get('sku', supplier.get('part_number')),
                        'unit_price': price,
                        'total_price': price * quantity,
                        'stock': supplier.get('stock', supplier.get('quantity_available', 0)),
                        'lead_time': supplier.get('lead_time', 'Check supplier')
                    })
                    
            # Sort by total price
            prices.sort(key=lambda x: x['total_price'])
            
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
    async def check_availability(
        part_numbers: List[str],
        quantities: Optional[List[int]] = None
    ) -> Dict[str, Any]:
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
                    search_results = client.search_parts(part_number, page_size=1)
                    if search_results.get('results'):
                        part_data = search_results['results'][0]
                    else:
                        part_data = None
                        
                if part_data:
                    # Get availability info
                    part_id = part_data.get('id', part_data.get('part_id'))
                    
                    if part_id:
                        avail_data = client.get_part_availability(part_id)
                    else:
                        avail_data = {'suppliers': part_data.get('suppliers', [])}
                        
                    # Check stock levels
                    in_stock_suppliers = []
                    total_stock = 0
                    
                    for supplier in avail_data.get('suppliers', []):
                        stock = supplier.get('stock', supplier.get('quantity_available', 0))
                        if stock >= qty_needed:
                            in_stock_suppliers.append({
                                'supplier': supplier.get('name', supplier.get('supplier')),
                                'stock': stock,
                                'sku': supplier.get('sku')
                            })
                        total_stock += stock
                        
                    availability.append({
                        'part_number': part_number,
                        'quantity_needed': qty_needed,
                        'available': len(in_stock_suppliers) > 0,
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
    async def find_alternatives(
        part_number: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
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
    async def calculate_bom_cost(
        bom: List[Dict[str, Any]],
        quantity: int = 1,
        preferred_suppliers: Optional[List[str]] = None
    ) -> Dict[str, Any]:
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
            
            for item in bom:
                part_number = item.get('part_number', item.get('mpn', ''))
                part_qty = item.get('quantity', 1) * quantity
                
                if not part_number:
                    errors.append({
                        'reference': item.get('reference', 'Unknown'),
                        'error': 'No part number specified'
                    })
                    continue
                    
                # Get pricing for this part
                try:
                    pricing = await compare_prices(
                        part_number=part_number,
                        quantity=part_qty,
                        suppliers=preferred_suppliers
                    )
                    
                    if pricing.get('success') and pricing.get('best_price'):
                        best = pricing['best_price']
                        line_cost = best['total_price']
                        
                        cost_breakdown.append({
                            'reference': item.get('reference', ''),
                            'part_number': part_number,
                            'description': item.get('value', item.get('description', '')),
                            'quantity': part_qty,
                            'unit_price': best['unit_price'],
                            'line_total': line_cost,
                            'supplier': best['supplier'],
                            'sku': best['sku']
                        })
                        
                        total_cost += line_cost
                    else:
                        errors.append({
                            'reference': item.get('reference', ''),
                            'part_number': part_number,
                            'error': pricing.get('error', 'No pricing found')
                        })
                        
                except Exception as e:
                    errors.append({
                        'reference': item.get('reference', ''),
                        'part_number': part_number,
                        'error': str(e)
                    })
                    
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