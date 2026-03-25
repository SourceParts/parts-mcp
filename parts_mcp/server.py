"""
MCP server creation and configuration for parts sourcing.

Supports two transport modes:
- stdio (default): For local use with Claude Desktop / Claude Code
- streamable-http: For hosted deployment (e.g. claude.ai integration)

Set MCP_TRANSPORT=streamable-http to enable hosted mode with Auth0 OAuth.
"""
import logging

from fastmcp import FastMCP
from mcp.types import Icon

from parts_mcp.config import (
    AuthConfig,
    ServerConfig,
    StorageConfig,
    load_auth_config,
    load_server_config,
    load_storage_config,
)
from parts_mcp.prompts.templates import register_prompts
from parts_mcp.resources.parts import register_parts_resources
from parts_mcp.resources.suppliers import register_supplier_resources
from parts_mcp.tools.datasheet import register_datasheet_tools
from parts_mcp.tools.docs import register_docs_tools
from parts_mcp.tools.manufacturing import register_manufacturing_tools
from parts_mcp.tools.search import register_search_tools
from parts_mcp.tools.sourcing import register_sourcing_tools
from parts_mcp.utils.api_client import _mcp_user_sub

logger = logging.getLogger(__name__)

# Module-level reference so the JWKS route handler can access it
_jwt_issuer = None


def _create_storage(storage_cfg: StorageConfig, client_secret: str):
    """Create OAuth state storage backend.

    - redis_url set: use RedisStore (production — Valkey on Docker network)
    - storage_dir set: use encrypted DiskStore at that path (self-hosting with volume mount)
    - Neither: let OAuthProxy use its default (encrypted DiskStore in temp dir)
    """
    if storage_cfg.redis_url:
        from key_value.aio.stores.redis import RedisStore
        logger.info("Using Redis storage backend for OAuth state")
        return RedisStore(url=storage_cfg.redis_url)

    if storage_cfg.storage_dir:
        from pathlib import Path

        from cryptography.fernet import Fernet
        from fastmcp.server.auth.jwt_issuer import derive_jwt_key
        from key_value.aio.stores.disk import DiskStore
        from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

        jwt_key = derive_jwt_key(high_entropy_material=client_secret, salt="fastmcp-jwt-signing-key")
        encryption_key = derive_jwt_key(high_entropy_material=jwt_key.decode(), salt="fastmcp-storage-encryption-key")

        logger.info("Using encrypted disk storage at %s for OAuth state", storage_cfg.storage_dir)
        return FernetEncryptionWrapper(
            key_value=DiskStore(directory=Path(storage_cfg.storage_dir)),
            fernet=Fernet(key=encryption_key),
        )

    return None


def _create_auth(auth_cfg: AuthConfig, storage_cfg: StorageConfig):
    """Create OAuth provider for hosted mode.

    Uses SourcePartsOIDCProxy with RS256 JWT signing when MCP_JWT_RSA_PRIVATE_KEY
    is set (required for Claude.ai). Falls back to Auth0Provider (HS256) otherwise.
    """
    global _jwt_issuer

    if auth_cfg.has_rsa_key:
        try:
            from parts_mcp.auth import RS256JWTIssuer, SourcePartsOIDCProxy, load_rsa_private_key

            rsa_pem = load_rsa_private_key(auth_cfg.rsa_private_key_b64)

            if not auth_cfg.has_required_auth0:
                raise ValueError("Missing required Auth0 env vars")

            client_storage = _create_storage(storage_cfg, auth_cfg.client_secret)

            proxy = SourcePartsOIDCProxy(
                rsa_private_key_pem=rsa_pem,
                valid_scopes=["openid", "profile", "email", "offline_access"],
                config_url=auth_cfg.config_url,
                client_id=auth_cfg.client_id,
                client_secret=auth_cfg.client_secret,
                audience=auth_cfg.audience,
                base_url=auth_cfg.base_url,
                issuer_url=auth_cfg.issuer_url,
                redirect_path=auth_cfg.redirect_path,
                required_scopes=["openid"],
                jwt_signing_key=auth_cfg.jwt_signing_key,
                client_storage=client_storage,
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

        if auth_cfg.has_required_auth0:
            logger.info("No RSA key configured, using standard Auth0Provider (HS256)")
            return Auth0Provider(
                config_url=auth_cfg.config_url,
                client_id=auth_cfg.client_id,
                client_secret=auth_cfg.client_secret,
                audience=auth_cfg.audience,
                base_url=auth_cfg.base_url,
                issuer_url=auth_cfg.issuer_url,
                redirect_path=auth_cfg.redirect_path,
                jwt_signing_key=auth_cfg.jwt_signing_key,
            )

        logger.warning("Auth0 not configured, running without auth")
        return None
    except (ImportError, ValueError) as e:
        logger.warning("Auth0 not configured, running without auth: %s", e)
        return None


def create_server(server_cfg: ServerConfig, auth_cfg: AuthConfig, storage_cfg: StorageConfig) -> FastMCP:
    """Create and configure the Parts MCP server."""
    logger.info("Initializing Parts MCP server")

    hosted = server_cfg.is_hosted
    auth = _create_auth(auth_cfg, storage_cfg) if hosted else None

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
    register_manufacturing_tools(mcp, local_mode=not hosted)
    register_datasheet_tools(mcp, local_mode=not hosted)
    register_docs_tools(mcp)

    # Render pipeline tools (Blender headless render)
    from parts_mcp.tools.render import register_render_tools
    register_render_tools(mcp)
    logger.info("Registered render pipeline tools")

    # ECN + ECO tools are remote-only (API-backed). For local operations,
    # clients should use the `parts` CLI directly.
    from parts_mcp.tools.ecn import register_ecn_tools
    from parts_mcp.tools.eco import register_eco_tools
    register_ecn_tools(mcp)
    register_eco_tools(mcp)

    # User profile, preferences, and device management
    from parts_mcp.tools.preferences import register_preference_tools
    register_preference_tools(mcp)
    logger.info("Registered ECN + ECO + preference tools")

    # Local-only tools require filesystem access — skip in hosted mode
    if not hosted:
        from parts_mcp.tools.cli import register_cli_tools
        from parts_mcp.tools.kicad import register_kicad_tools
        from parts_mcp.tools.project import register_project_tools
        register_cli_tools(mcp)
        register_kicad_tools(mcp)
        register_project_tools(mcp)
        logger.info("Registered local tools (CLI, KiCad, project)")
    else:
        logger.info("Skipped local-only tools (hosted mode)")

    # Register prompts
    logger.info("Registering prompts...")
    register_prompts(mcp)

    logger.info("Server initialization complete")
    return mcp


def setup_logging(server_cfg: ServerConfig) -> None:
    """Configure logging for the server."""
    level = server_cfg.log_level.upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def main() -> None:
    """Start the Parts MCP server."""
    server_cfg = load_server_config()
    auth_cfg = load_auth_config()
    storage_cfg = load_storage_config()

    setup_logging(server_cfg)

    logger.info("Starting Parts MCP server (transport=%s)...", server_cfg.transport)

    server = create_server(server_cfg, auth_cfg, storage_cfg)

    if not server_cfg.is_hosted:
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
        _run_http(server, server_cfg)


def _extract_sub_from_bearer(auth_header: str) -> str | None:
    """Extract 'sub' claim from a Bearer JWT without signature verification."""
    if not auth_header.startswith("Bearer "):
        return None
    try:
        import base64
        import json
        segment = auth_header[7:].split(".")[1]
        segment += "=" * (4 - len(segment) % 4)
        return json.loads(base64.urlsafe_b64decode(segment)).get("sub")
    except Exception:
        return None


def _run_http(server: FastMCP, server_cfg: ServerConfig) -> None:
    """Run the server in HTTP mode with health and JWKS endpoints."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "parts-mcp"})

    async def jwks(request: Request) -> JSONResponse:
        if _jwt_issuer is None:
            return JSONResponse({"keys": []}, status_code=404)
        return JSONResponse(
            _jwt_issuer.get_jwks(),
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def docs(request: Request) -> JSONResponse:
        """Proxy CLI docs from the Source Parts API with user context from JWT."""
        from parts_mcp.utils.api_client import SourcePartsClient
        sub = _extract_sub_from_bearer(request.headers.get("Authorization", ""))
        reset = _mcp_user_sub.set(sub)
        try:
            section = request.query_params.get("section")
            data = SourcePartsClient().get_cli_docs(section=section)
            return JSONResponse(data)
        finally:
            _mcp_user_sub.reset(reset)

    # Get the MCP ASGI app (includes OAuth endpoints when auth is configured)
    # Use stateless_http so each request gets a fresh transport — no session
    # tracking. This makes redeploys transparent: there are no in-memory
    # sessions to lose, so clients never get "Session not found" errors.
    #
    # Re-evaluate once upstream fixes land (all open as of 2026-03-09):
    #   - modelcontextprotocol/python-sdk#880  (session persistence / horizontal scaling)
    #   - anthropics/claude-code#30224         (auto-reconnect SSE MCP after restart)
    #   - anthropics/claude-code#10129         (auto-reconnect for MCP servers)
    #   - PrefectHQ/fastmcp#831               (client errors on server restart)
    #   - PrefectHQ/fastmcp#1572              (OAuth proxy session state persistence)
    #   - PrefectHQ/fastmcp#485               (stale session reuse after restart)
    mcp_app = server.http_app(
        transport=server_cfg.transport,
        path=server_cfg.path,
        stateless_http=True,
    )

    # Mount MCP app under a parent Starlette app that also has /health and /jwks
    app = Starlette(
        routes=[
            Route("/v1/health", health),
            Route("/v1/docs", docs),
            Route("/.well-known/jwks.json", jwks),
        ],
        lifespan=mcp_app.router.lifespan_context,
    )
    app.mount("/", mcp_app)

    logger.info("Starting HTTP server on %s:%d (transport=%s, path=%s)",
                 server_cfg.host, server_cfg.port, server_cfg.transport, server_cfg.path)
    uvicorn.run(app, host=server_cfg.host, port=server_cfg.port, log_level=server_cfg.log_level.lower())


if __name__ == "__main__":
    main()
