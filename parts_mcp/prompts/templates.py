"""
Prompt templates for common parts sourcing workflows.
"""
import logging
from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_prompts(mcp: FastMCP) -> None:
    """Register prompt templates with the MCP server.
    
    Args:
        mcp: The FastMCP server instance
    """
    
    @mcp.prompt()
    async def find_resistor() -> str:
        """Help finding the right resistor."""
        return """I need help finding a resistor with the following specifications:
- Resistance value: [specify value, e.g., 10kΩ]
- Tolerance: [specify tolerance, e.g., 1%, 5%]
- Power rating: [specify power, e.g., 1/4W, 1/2W]
- Package type: [specify package, e.g., 0805, through-hole]
- Quantity needed: [specify quantity]

Please search for suitable resistors and compare prices across suppliers."""

    @mcp.prompt()
    async def source_bom() -> str:
        """Help sourcing a complete bill of materials."""
        return """I need help sourcing components for my project. 

Please help me:
1. Extract the BOM from my KiCad project at: [project path]
2. Find suitable parts for each component
3. Check availability across suppliers
4. Compare total costs
5. Suggest alternatives for any out-of-stock items

My preferences:
- Preferred suppliers: [list suppliers or "any"]
- Target quantity: [number of boards]
- Budget constraints: [if any]"""

    @mcp.prompt()
    async def find_alternative() -> str:
        """Help finding alternative parts."""
        return """I need to find an alternative for this part:
- Part number: [original part number]
- Manufacturer: [original manufacturer]
- Reason for alternative: [e.g., out of stock, too expensive, obsolete]

Critical parameters to match:
- [List the parameters that must match]

Flexible parameters:
- [List parameters that can vary]

Please find suitable alternatives and compare them."""

    @mcp.prompt()
    async def parametric_search() -> str:
        """Help with parametric component search."""
        return """I need to find a component with these specifications:
- Component type: [e.g., voltage regulator, op-amp, MCU]
- Key parameters:
  - [Parameter 1]: [value/range]
  - [Parameter 2]: [value/range]
  - [Add more as needed]
- Package preferences: [if any]
- Other requirements: [temperature range, certifications, etc.]

Please search for matching components and provide a comparison."""

    @mcp.prompt()
    async def quick_availability() -> str:
        """Quick availability check for parts."""
        return """Please check the availability of these parts:
- [Part number 1]
- [Part number 2]
- [Add more parts]

I need:
- Current stock levels
- Lead times if out of stock
- Pricing for quantity: [specify]
- Alternative suggestions if unavailable"""