"""
MCP server creation and configuration for parts sourcing.

Supports two transport modes:
- stdio (default): For local use with Claude Desktop / Claude Code
- streamable-http: For hosted deployment (e.g. claude.ai integration)

Set MCP_TRANSPORT=streamable-http to enable hosted mode with Auth0 OAuth.
"""
import logging
import os

from fastmcp import FastMCP

from parts_mcp.prompts.templates import register_prompts
from parts_mcp.resources.parts import register_parts_resources
from parts_mcp.resources.suppliers import register_supplier_resources
from parts_mcp.tools.search import register_search_tools
from parts_mcp.tools.sourcing import register_sourcing_tools

logger = logging.getLogger(__name__)


def _is_hosted() -> bool:
    """Check if server is running in hosted (HTTP) mode."""
    return os.getenv("MCP_TRANSPORT", "stdio") != "stdio"


def _create_auth():
    """Create Auth0 OAuth provider for hosted mode.

    Returns Auth0Provider if all required env vars are set, None otherwise.
    Auth0Provider reads FASTMCP_SERVER_AUTH_AUTH0_* env vars automatically.
    """
    try:
        from fastmcp.server.auth.providers.auth0 import Auth0Provider
        return Auth0Provider()
    except (ImportError, ValueError) as e:
        logger.warning("Auth0 not configured, running without auth: %s", e)
        return None


def create_server() -> FastMCP:
    """Create and configure the Parts MCP server."""
    logger.info("Initializing Parts MCP server")

    hosted = _is_hosted()
    auth = _create_auth() if hosted else None

    mcp = FastMCP("Parts MCP", auth=auth)
    logger.info("Created FastMCP server instance (hosted=%s, auth=%s)", hosted, auth is not None)

    # Register resources
    logger.info("Registering resources...")
    register_parts_resources(mcp)
    register_supplier_resources(mcp)

    # Register tools
    logger.info("Registering tools...")
    register_search_tools(mcp)
    register_sourcing_tools(mcp)

    # KiCad tools require local filesystem access — skip in hosted mode
    if not hosted:
        from parts_mcp.tools.kicad import register_kicad_tools
        register_kicad_tools(mcp)
        logger.info("Registered KiCad tools (local mode)")
    else:
        logger.info("Skipped KiCad tools (hosted mode)")

    # Register prompts
    logger.info("Registering prompts...")
    register_prompts(mcp)

    logger.info("Server initialization complete")
    return mcp


def setup_logging() -> None:
    """Configure logging for the server."""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def main() -> None:
    """Start the Parts MCP server."""
    setup_logging()

    transport = os.getenv("MCP_TRANSPORT", "stdio")
    logger.info("Starting Parts MCP server (transport=%s)...", transport)

    server = create_server()

    if transport == "stdio":
        try:
            server.run()
        except KeyboardInterrupt:
            logger.info("Server interrupted by user")
        except Exception as e:
            logger.error("Server error: %s", e)
            raise
        finally:
            logger.info("Server shutdown complete")
    else:
        _run_http(server, transport)


def _run_http(server: FastMCP, transport: str) -> None:
    """Run the server in HTTP mode with a health endpoint."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))
    path = os.getenv("MCP_PATH", "/mcp")

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "parts-mcp"})

    # Get the MCP ASGI app (includes OAuth endpoints when auth is configured)
    mcp_app = server.http_app(transport=transport, path=path)

    # Mount MCP app under a parent Starlette app that also has /health
    app = Starlette(
        routes=[Route("/api/health", health)],
        lifespan=mcp_app.router.lifespan_context,
    )
    app.mount("/", mcp_app)

    logger.info("Starting HTTP server on %s:%d (transport=%s, path=%s)", host, port, transport, path)
    uvicorn.run(app, host=host, port=port, log_level=os.getenv("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
