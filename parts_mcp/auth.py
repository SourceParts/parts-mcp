"""RS256 JWT signing and OIDC proxy for Claude.ai MCP OAuth.

FastMCP's built-in JWTIssuer uses HS256 (symmetric). Claude.ai expects to
validate tokens by fetching /.well-known/jwks.json, which requires asymmetric
signing (RS256). This module provides:

- RS256JWTIssuer: Drop-in replacement for JWTIssuer that signs with an RSA key
  and exposes the public key as a JWKS endpoint.
- SourcePartsOIDCProxy: OIDCProxy subclass that injects valid_scopes (omitted
  by upstream OIDCProxy) and uses RS256JWTIssuer.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from fastmcp.server.auth.oidc_proxy import OIDCProxy

logger = logging.getLogger(__name__)


class RS256JWTIssuer:
    """Drop-in replacement for FastMCP's JWTIssuer that uses RS256.

    Signs tokens with an RSA private key and exposes the public key via
    get_jwks() for the /.well-known/jwks.json endpoint.

    Implements the same interface as JWTIssuer: issue_access_token,
    issue_refresh_token, verify_token.
    """

    def __init__(
        self,
        issuer: str,
        audience: str,
        rsa_private_key_pem: bytes,
    ):
        self.issuer = issuer
        self.audience = audience

        # Load the RSA private key
        private_key = load_pem_private_key(rsa_private_key_pem, password=None)
        public_key = private_key.public_key()

        # Public key PEM for verification
        self._public_pem = public_key.public_bytes(
            encoding=Encoding.PEM,
            format=PublicFormat.SubjectPublicKeyInfo,
        )

        # Build the JWK for the public key (used in JWKS endpoint)
        jwk = JsonWebKey.import_key(self._public_pem, {"kty": "RSA"})
        self._jwk_dict = jwk.as_dict()
        self._jwk_dict.update({"alg": "RS256", "use": "sig"})
        self._kid = self._jwk_dict.get("kid", "")

        # Private key PEM for signing
        self._private_pem = private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

        self._jwt = JsonWebToken(["RS256"])

    def issue_access_token(
        self,
        client_id: str,
        scopes: list[str],
        jti: str,
        expires_in: int = 3600,
    ) -> str:
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT", "kid": self._kid}
        payload = {
            "iss": self.issuer,
            "aud": self.audience,
            "client_id": client_id,
            "scope": " ".join(scopes),
            "exp": now + expires_in,
            "iat": now,
            "jti": jti,
        }
        token_bytes = self._jwt.encode(header, payload, self._private_pem)
        token = token_bytes.decode("utf-8")
        logger.debug(
            "Issued RS256 access token for client=%s jti=%s exp=%d",
            client_id,
            jti[:8],
            payload["exp"],
        )
        return token

    def issue_refresh_token(
        self,
        client_id: str,
        scopes: list[str],
        jti: str,
        expires_in: int,
    ) -> str:
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT", "kid": self._kid}
        payload = {
            "iss": self.issuer,
            "aud": self.audience,
            "client_id": client_id,
            "scope": " ".join(scopes),
            "exp": now + expires_in,
            "iat": now,
            "jti": jti,
            "token_use": "refresh",
        }
        token_bytes = self._jwt.encode(header, payload, self._private_pem)
        token = token_bytes.decode("utf-8")
        logger.debug(
            "Issued RS256 refresh token for client=%s jti=%s exp=%d",
            client_id,
            jti[:8],
            payload["exp"],
        )
        return token

    def verify_token(self, token: str) -> dict[str, Any]:
        try:
            payload = self._jwt.decode(token, self._public_pem)
            logger.debug("RS256 JWT decoded successfully, claims: iss=%s aud=%s jti=%s",
                         payload.get("iss"), payload.get("aud"), str(payload.get("jti", ""))[:8])

            exp = payload.get("exp")
            if exp and exp < time.time():
                logger.debug("Token expired: exp=%s now=%s", exp, time.time())
                raise JoseError("Token has expired")

            if payload.get("iss") != self.issuer:
                logger.debug("Issuer mismatch: token=%r expected=%r", payload.get("iss"), self.issuer)
                raise JoseError("Invalid token issuer")

            if payload.get("aud") != self.audience:
                logger.debug("Audience mismatch: token=%r expected=%r", payload.get("aud"), self.audience)
                raise JoseError("Invalid token audience")

            logger.debug("RS256 JWT verified successfully")
            return payload
        except JoseError:
            raise
        except Exception as e:
            logger.error("Unexpected error in verify_token: %s", e)
            raise

    def get_jwks(self) -> dict:
        """Return JWKS document for /.well-known/jwks.json."""
        return {"keys": [self._jwk_dict]}


def load_rsa_private_key(env_value: str) -> bytes:
    """Decode a base64-encoded PEM private key from an env var value."""
    return base64.b64decode(env_value)


def _create_consent_html(
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    txn_id: str,
    csrf_token: str,
    client_name: str | None = None,
    server_name: str | None = None,
    server_icon_url: str | None = None,
    server_website_url: str | None = None,
    client_website_url: str | None = None,
    csp_policy: str | None = None,
) -> str:
    """Create consent HTML with Source Parts branding instead of FastMCP."""
    import html as html_module
    from urllib.parse import urlparse

    from fastmcp.server.auth.oauth_proxy import (
        BUTTON_STYLES,
        DETAILS_STYLES,
        DETAIL_BOX_STYLES,
        INFO_BOX_STYLES,
        REDIRECT_SECTION_STYLES,
        TOOLTIP_STYLES,
        create_logo,
        create_page,
    )

    client_display = html_module.escape(client_name or client_id)
    server_name_escaped = html_module.escape(server_name or "Source Parts")

    if server_website_url:
        website_url_escaped = html_module.escape(server_website_url)
        server_display = f'<a href="{website_url_escaped}" target="_blank" rel="noopener noreferrer" class="server-name-link">{server_name_escaped}</a>'
    else:
        server_display = server_name_escaped

    intro_box = f"""
        <div class="info-box">
            <p>The application <strong>{client_display}</strong> wants to access the MCP server <strong>{server_display}</strong>. Please ensure you recognize the callback address below.</p>
        </div>
    """

    redirect_uri_escaped = html_module.escape(redirect_uri)
    redirect_section = f"""
        <div class="redirect-section">
            <span class="label">Credentials will be sent to:</span>
            <div class="value">{redirect_uri_escaped}</div>
        </div>
    """

    detail_rows = [
        ("Application Name", html_module.escape(client_name or client_id)),
        ("Application Website", html_module.escape(client_website_url or "N/A")),
        ("Application ID", client_id),
        ("Redirect URI", redirect_uri_escaped),
        (
            "Requested Scopes",
            ", ".join(html_module.escape(s) for s in scopes) if scopes else "None",
        ),
    ]

    detail_rows_html = "\n".join(
        f"""
        <div class="detail-row">
            <div class="detail-label">{label}:</div>
            <div class="detail-value">{value}</div>
        </div>
        """
        for label, value in detail_rows
    )

    advanced_details = f"""
        <details>
            <summary>Advanced Details</summary>
            <div class="detail-box">
                {detail_rows_html}
            </div>
        </details>
    """

    form = f"""
        <form id="consentForm" method="POST" action="">
            <input type="hidden" name="txn_id" value="{txn_id}" />
            <input type="hidden" name="csrf_token" value="{csrf_token}" />
            <input type="hidden" name="submit" value="true" />
            <div class="button-group">
                <button type="submit" name="action" value="approve" class="btn-approve">Allow Access</button>
                <button type="submit" name="action" value="deny" class="btn-deny">Deny</button>
            </div>
        </form>
    """

    help_link = """
        <div class="help-link-container">
            <span class="help-link">
                Why am I seeing this?
                <span class="tooltip">
                    This server requires your consent before allowing a new
                    application to connect. This protects you from unauthorized
                    access where a malicious application could impersonate you.<br><br>
                    If you did not initiate this request, click Deny and close
                    this window.
                </span>
            </span>
        </div>
    """

    content = f"""
        <div class="container">
            {create_logo(icon_url=server_icon_url, alt_text=server_name or "Source Parts")}
            <h1>Application Access Request</h1>
            {intro_box}
            {redirect_section}
            {advanced_details}
            {form}
        </div>
        {help_link}
    """

    additional_styles = (
        INFO_BOX_STYLES
        + REDIRECT_SECTION_STYLES
        + DETAILS_STYLES
        + DETAIL_BOX_STYLES
        + BUTTON_STYLES
        + TOOLTIP_STYLES
    )

    if csp_policy is None:
        parsed_redirect = urlparse(redirect_uri)
        redirect_scheme = parsed_redirect.scheme.lower()
        form_action_schemes = ["https:", "http:"]
        if redirect_scheme and redirect_scheme not in ("http", "https"):
            form_action_schemes.append(f"{redirect_scheme}:")
        form_action_directive = " ".join(form_action_schemes)
        csp_policy = f"default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; base-uri 'none'; form-action {form_action_directive}"

    return create_page(
        content=content,
        title="Application Access Request",
        additional_styles=additional_styles,
        csp_policy=csp_policy,
    )


class SourcePartsOIDCProxy(OIDCProxy):
    """OIDCProxy subclass that uses RS256 JWT signing and passes valid_scopes.

    Fixes three issues with the base OIDCProxy:
    1. OIDCProxy.__init__ does not pass valid_scopes to OAuthProxy, so DCR
       registrations with custom scopes (like "claudeai") may be rejected.
    2. FastMCP's JWTIssuer uses HS256, but Claude.ai needs RS256 + JWKS.
    3. OAuth metadata is missing jwks_uri, which Claude.ai needs.
    """

    def __init__(
        self,
        *,
        rsa_private_key_pem: bytes,
        valid_scopes: list[str] | None = None,
        **kwargs,
    ):
        self._rsa_private_key_pem = rsa_private_key_pem
        super().__init__(**kwargs)

        # OIDCProxy doesn't pass valid_scopes to OAuthProxy, so
        # client_registration_options falls back to required_scopes only.
        # Patch it after init so the /.well-known endpoints advertise all
        # scopes and DCR accepts them.
        if valid_scopes and self.client_registration_options:
            self.client_registration_options.valid_scopes = valid_scopes

    def set_mcp_path(self, mcp_path: str | None) -> None:
        """Override to create RS256JWTIssuer instead of HS256 JWTIssuer."""
        # Call the grandparent (OAuthProvider) set_mcp_path to set _resource_url
        # without creating the HS256 JWTIssuer
        from fastmcp.server.auth.auth import OAuthProvider
        OAuthProvider.set_mcp_path(self, mcp_path)

        # Create our RS256 issuer instead
        self._jwt_issuer = RS256JWTIssuer(
            issuer=str(self.base_url),
            audience=str(self._resource_url),
            rsa_private_key_pem=self._rsa_private_key_pem,
        )
        logger.info(
            "Configured RS256 OAuth proxy for resource URL: %s", self._resource_url
        )

    def get_routes(self, mcp_path: str | None = None):
        """Override to replace the metadata route with one that includes jwks_uri."""
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        routes = super().get_routes(mcp_path)
        jwks_uri = str(self.base_url).rstrip("/") + "/.well-known/jwks.json"

        # Build the metadata dict ourselves by reading from the existing
        # provider state — this avoids trying to call a CORS-wrapped ASGI app.
        scopes = (
            self.client_registration_options.valid_scopes
            if self.client_registration_options and self.client_registration_options.valid_scopes
            else self.required_scopes
        )
        base = str(self.base_url).rstrip("/")
        metadata_dict = {
            "issuer": str(self.issuer_url) if self.issuer_url else base + "/",
            "authorization_endpoint": base + "/authorize",
            "token_endpoint": base + "/token",
            "registration_endpoint": base + "/register",
            "jwks_uri": jwks_uri,
            "scopes_supported": scopes,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "revocation_endpoint": base + "/revoke",
            "revocation_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "code_challenge_methods_supported": ["S256"],
        }

        async def metadata_handler(request: Request) -> JSONResponse:
            return JSONResponse(
                content=metadata_dict,
                headers={"Cache-Control": "public, max-age=3600"},
            )

        patched = []
        for route in routes:
            if (
                isinstance(route, Route)
                and route.path == "/.well-known/oauth-authorization-server"
            ):
                patched.append(Route(
                    path="/.well-known/oauth-authorization-server",
                    endpoint=metadata_handler,
                    methods=["GET", "OPTIONS"],
                ))
            else:
                patched.append(route)
        return patched

    async def _show_consent_page(self, request):
        """Override to use Source Parts branded consent page."""
        import secrets as secrets_module

        from fastmcp.server.server import FastMCP
        from fastmcp.utilities.ui import create_secure_html_response

        txn_id = request.query_params.get("txn_id")
        if not txn_id:
            return create_secure_html_response(
                "<h1>Error</h1><p>Invalid or expired transaction</p>", status_code=400
            )

        txn_model = await self._transaction_store.get(key=txn_id)
        if not txn_model:
            return create_secure_html_response(
                "<h1>Error</h1><p>Invalid or expired transaction</p>", status_code=400
            )

        txn = txn_model.model_dump()
        client_key = self._make_client_key(txn["client_id"], txn["client_redirect_uri"])

        approved = set(self._decode_list_cookie(request, "MCP_APPROVED_CLIENTS"))
        denied = set(self._decode_list_cookie(request, "MCP_DENIED_CLIENTS"))

        if client_key in approved:
            from starlette.responses import RedirectResponse
            upstream_url = self._build_upstream_authorize_url(txn_id, txn)
            return RedirectResponse(url=upstream_url, status_code=302)

        if client_key in denied:
            from starlette.responses import RedirectResponse
            from urllib.parse import urlencode
            callback_params = {
                "error": "access_denied",
                "state": txn.get("client_state") or "",
            }
            sep = "&" if "?" in txn["client_redirect_uri"] else "?"
            return RedirectResponse(
                url=f"{txn['client_redirect_uri']}{sep}{urlencode(callback_params)}",
                status_code=302,
            )

        # Need consent: issue CSRF token and show HTML
        csrf_token = secrets_module.token_urlsafe(32)
        csrf_expires_at = time.time() + 15 * 60

        txn_model.csrf_token = csrf_token
        txn_model.csrf_expires_at = csrf_expires_at
        await self._transaction_store.put(key=txn_id, value=txn_model, ttl=15 * 60)

        txn["csrf_token"] = csrf_token
        txn["csrf_expires_at"] = csrf_expires_at

        client = await self.get_client(txn["client_id"])
        client_name = getattr(client, "client_name", None) if client else None

        fastmcp = getattr(request.app.state, "fastmcp_server", None)
        if isinstance(fastmcp, FastMCP):
            server_name = fastmcp.name
            icons = fastmcp.icons
            server_icon_url = icons[0].src if icons else None
            server_website_url = fastmcp.website_url
        else:
            server_name = None
            server_icon_url = None
            server_website_url = None

        html = _create_consent_html(
            client_id=txn["client_id"],
            redirect_uri=txn["client_redirect_uri"],
            scopes=txn.get("scopes") or [],
            txn_id=txn_id,
            csrf_token=csrf_token,
            client_name=client_name,
            server_name=server_name,
            server_icon_url=server_icon_url,
            server_website_url=server_website_url,
            csp_policy=self._consent_csp_policy,
        )
        response = create_secure_html_response(html)
        self._set_list_cookie(
            response,
            "MCP_CONSENT_STATE",
            self._encode_list_cookie([csrf_token]),
            max_age=15 * 60,
        )
        return response

    async def load_access_token(self, token: str):
        """Override to add step-by-step debug logging for token validation."""
        try:
            # Step 1: Verify our RS256 JWT
            logger.info("load_access_token: Step 1 - verifying RS256 JWT")
            payload = self.jwt_issuer.verify_token(token)
            jti = payload["jti"]
            logger.info("load_access_token: Step 1 OK - jti=%s", jti[:8])

            # Step 2: Look up JTI mapping
            logger.info("load_access_token: Step 2 - looking up JTI mapping")
            jti_mapping = await self._jti_mapping_store.get(key=jti)
            if not jti_mapping:
                logger.error("load_access_token: Step 2 FAILED - JTI mapping not found for jti=%s", jti[:8])
                return None
            logger.info("load_access_token: Step 2 OK - upstream_token_id=%s", jti_mapping.upstream_token_id[:8])

            # Step 3: Look up upstream tokens
            logger.info("load_access_token: Step 3 - looking up upstream tokens")
            upstream_token_set = await self._upstream_token_store.get(key=jti_mapping.upstream_token_id)
            if not upstream_token_set:
                logger.error("load_access_token: Step 3 FAILED - upstream token not found")
                return None
            upstream_access = upstream_token_set.access_token
            logger.info("load_access_token: Step 3 OK - got upstream token (%d chars, starts=%s)",
                        len(upstream_access), upstream_access[:20])

            # Step 4: Validate upstream token
            logger.info("load_access_token: Step 4 - validating upstream token with %s",
                        type(self._token_validator).__name__)
            validated = await self._token_validator.verify_token(upstream_access)
            if not validated:
                logger.error("load_access_token: Step 4 FAILED - upstream validation returned None")
                return None
            logger.info("load_access_token: Step 4 OK - upstream token validated, scopes=%s",
                        getattr(validated, 'scopes', 'unknown'))
            return validated

        except Exception as e:
            logger.error("load_access_token: EXCEPTION at some step: %s: %s", type(e).__name__, e)
            return None
