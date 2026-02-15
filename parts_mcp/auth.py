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
        header = {"alg": "RS256", "typ": "JWT"}
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
        header = {"alg": "RS256", "typ": "JWT"}
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

            exp = payload.get("exp")
            if exp and exp < time.time():
                raise JoseError("Token has expired")

            if payload.get("iss") != self.issuer:
                raise JoseError("Invalid token issuer")

            if payload.get("aud") != self.audience:
                raise JoseError("Invalid token audience")

            return payload
        except JoseError:
            raise

    def get_jwks(self) -> dict:
        """Return JWKS document for /.well-known/jwks.json."""
        return {"keys": [self._jwk_dict]}


def load_rsa_private_key(env_value: str) -> bytes:
    """Decode a base64-encoded PEM private key from an env var value."""
    return base64.b64decode(env_value)


class SourcePartsOIDCProxy(OIDCProxy):
    """OIDCProxy subclass that uses RS256 JWT signing and passes valid_scopes.

    Fixes two issues with the base OIDCProxy:
    1. OIDCProxy.__init__ does not pass valid_scopes to OAuthProxy, so DCR
       registrations with custom scopes (like "claudeai") may be rejected.
    2. FastMCP's JWTIssuer uses HS256, but Claude.ai needs RS256 + JWKS.
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
