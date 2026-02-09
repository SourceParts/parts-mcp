"""
MCP server creation and configuration for parts sourcing.
"""
import logging

from fastmcp import FastMCP

from parts_mcp.prompts.templates import register_prompts
from parts_mcp.resources.parts import register_parts_resources
from parts_mcp.resources.suppliers import register_supplier_resources
from parts_mcp.tools.kicad import register_kicad_tools
from parts_mcp.tools.search import register_search_tools
from parts_mcp.tools.sourcing import register_sourcing_tools

logger = logging.getLogger(__name__)


def create_server() -> FastMCP:
    """Create and configure the Parts MCP server."""
    logger.info("Initializing Parts MCP server")

    # Initialize FastMCP server
    mcp = FastMCP("Parts MCP")
    logger.info("Created FastMCP server instance")

    # Register resources
    logger.info("Registering resources...")
    register_parts_resources(mcp)
    register_supplier_resources(mcp)

    # Register tools
    logger.info("Registering tools...")
    register_search_tools(mcp)
    register_sourcing_tools(mcp)
    register_kicad_tools(mcp)

    # Register prompts
    logger.info("Registering prompts...")
    register_prompts(mcp)

    logger.info("Server initialization complete")
    return mcp


def setup_logging() -> None:
    """Configure logging for the server."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def main() -> None:
    """Start the Parts MCP server."""
    setup_logging()
    logger.info("Starting Parts MCP server...")

    server = create_server()

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        logger.info("Server shutdown complete")


if __name__ == "__main__":
    main()
