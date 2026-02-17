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
from mcp.types import Icon

from parts_mcp.prompts.templates import register_prompts
from parts_mcp.resources.parts import register_parts_resources
from parts_mcp.resources.suppliers import register_supplier_resources
from parts_mcp.tools.search import register_search_tools
from parts_mcp.tools.sourcing import register_sourcing_tools

logger = logging.getLogger(__name__)

# Module-level reference so the JWKS route handler can access it
_jwt_issuer = None


def _is_hosted() -> bool:
    """Check if server is running in hosted (HTTP) mode."""
    return os.getenv("MCP_TRANSPORT", "stdio") != "stdio"


def _create_auth():
    """Create OAuth provider for hosted mode.

    Uses SourcePartsOIDCProxy with RS256 JWT signing when MCP_JWT_RSA_PRIVATE_KEY
    is set (required for Claude.ai). Falls back to Auth0Provider (HS256) otherwise.
    """
    global _jwt_issuer

    rsa_key_b64 = os.getenv("MCP_JWT_RSA_PRIVATE_KEY")
    if rsa_key_b64:
        try:
            from parts_mcp.auth import RS256JWTIssuer, SourcePartsOIDCProxy, load_rsa_private_key
            from fastmcp.server.auth.providers.auth0 import Auth0ProviderSettings

            rsa_pem = load_rsa_private_key(rsa_key_b64)

            # Read Auth0 settings from FASTMCP_SERVER_AUTH_AUTH0_* env vars
            settings = Auth0ProviderSettings()
            if not all([settings.config_url, settings.client_id, settings.client_secret, settings.audience, settings.base_url]):
                raise ValueError("Missing required Auth0 env vars")

            proxy = SourcePartsOIDCProxy(
                rsa_private_key_pem=rsa_pem,
                valid_scopes=["openid", "profile", "email", "offline_access"],
                config_url=settings.config_url,
                client_id=settings.client_id,
                client_secret=settings.client_secret.get_secret_value(),
                audience=settings.audience,
                base_url=settings.base_url,
                issuer_url=settings.issuer_url,
                redirect_path=settings.redirect_path,
                required_scopes=settings.required_scopes or ["openid"],
                allowed_client_redirect_uris=settings.allowed_client_redirect_uris,
                jwt_signing_key=settings.jwt_signing_key,
            )

            # Store reference for JWKS endpoint — the actual RS256JWTIssuer is
            # created later in set_mcp_path(), but we can create a temporary one
            # now just for JWKS (same key, issuer/audience don't affect JWKS).
            _jwt_issuer = RS256JWTIssuer(
                issuer="",
                audience="",
                rsa_private_key_pem=rsa_pem,
            )

            logger.info("Created SourcePartsOIDCProxy with RS256 JWT signing")
            return proxy
        except Exception as e:
            logger.error("Failed to create RS256 auth provider: %s", e)
            raise

    # Fallback: standard Auth0Provider (HS256, no JWKS endpoint)
    try:
        from fastmcp.server.auth.providers.auth0 import Auth0Provider
        logger.info("No RSA key configured, using standard Auth0Provider (HS256)")
        return Auth0Provider()
    except (ImportError, ValueError) as e:
        logger.warning("Auth0 not configured, running without auth: %s", e)
        return None


def create_server() -> FastMCP:
    """Create and configure the Parts MCP server."""
    logger.info("Initializing Parts MCP server")

    hosted = _is_hosted()
    auth = _create_auth() if hosted else None

    mcp = FastMCP(
        "Parts MCP",
        auth=auth,
        icons=[Icon(src="https://source.parts/favicon-310x310.png", mimeType="image/png")],
    )
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
    """Run the server in HTTP mode with health and JWKS endpoints."""
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

    async def jwks(request: Request) -> JSONResponse:
        if _jwt_issuer is None:
            return JSONResponse({"keys": []}, status_code=404)
        return JSONResponse(
            _jwt_issuer.get_jwks(),
            headers={"Cache-Control": "public, max-age=3600"},
        )

    # Get the MCP ASGI app (includes OAuth endpoints when auth is configured)
    # Enable event_store so SSE connections get priming events — required for
    # Cloudflare-proxied deployments where unbuffered SSE would otherwise hang.
    from parts_mcp.events import InMemoryEventStore
    event_store = InMemoryEventStore()

    mcp_app = server.http_app(transport=transport, path=path, event_store=event_store)

    # Mount MCP app under a parent Starlette app that also has /health and /jwks
    app = Starlette(
        routes=[
            Route("/api/health", health),
            Route("/.well-known/jwks.json", jwks),
        ],
        lifespan=mcp_app.router.lifespan_context,
    )
    app.mount("/", mcp_app)

    logger.info("Starting HTTP server on %s:%d (transport=%s, path=%s)", host, port, transport, path)
    uvicorn.run(app, host=host, port=port, log_level=os.getenv("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
