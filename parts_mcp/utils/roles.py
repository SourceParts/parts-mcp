"""
User role resolution and tool gating.

Roles are resolved from two sources:
1. JWT claims (hosted mode): Auth0 custom claims or API lookup by `sub`
2. Environment variable (local mode): PARTS_USER_ROLE=admin

Tool visibility:
- public:  All authenticated users (or anonymous in local mode)
- admin:   Source Parts team + authorized partners
- owner:   Super admins only (Source Parts internal)

The API endpoint GET /v1/users/me returns the user profile including role
and device preferences. Results are cached for the duration of the request.
"""
import logging
import os
from contextvars import ContextVar
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

# Ordered by privilege level (MCP simplified roles)
ROLES = ("public", "admin", "owner")

# Map MCP roles to the unified proxy/admin-api role system.
# When the proxy receives an X-MCP-User-Sub header, the user's actual role
# comes from the DB — this mapping is only for tool gating within the MCP.
MCP_TO_PROXY_ROLE = {
    "public": "customer",       # Customers, partners, external users
    "admin": "employee",        # Source Parts team, authorized partners
    "owner": "super_admin",     # Source Parts super admins only
}

# Reverse mapping: proxy roles → MCP role level for tool gating
PROXY_TO_MCP_ROLE = {
    "customer": "public",
    "partner": "public",
    "employee": "admin",
    "sales": "admin",
    "manager": "admin",
    "admin": "admin",
    "super_admin": "owner",
    "ceo": "owner",
    "consultant": "admin",
    "internal_consultant": "admin",
    "investor": "public",
    "analyst": "admin",
}

# Cache the user profile per-request to avoid repeated API calls
_cached_user_profile: ContextVar[dict[str, Any] | None] = ContextVar(
    "_cached_user_profile", default=None
)


def _role_rank(role: str) -> int:
    """Return numeric rank for a role. Higher = more privilege."""
    try:
        return ROLES.index(role)
    except ValueError:
        return 0


async def get_user_profile() -> dict[str, Any]:
    """Get the current user's profile with role and preferences.

    In hosted mode: calls GET /v1/users/me (cached per-request).
    In local mode: returns a synthetic profile from env vars.

    Returns:
        User profile dict with at least: role, preferences, devices
    """
    cached = _cached_user_profile.get()
    if cached is not None:
        return cached

    # Try API first
    try:
        from parts_mcp.utils.api_client import get_client
        client = get_client()
        profile = client._make_request(
            "GET", "users/me",
            base_url=client._project_base_url(),
        )
        _cached_user_profile.set(profile)
        return profile
    except Exception as e:
        logger.debug("Could not fetch user profile from API: %s", e)

    # Local fallback: synthetic profile from env
    role = os.environ.get("PARTS_USER_ROLE", "admin")  # local users default to admin
    profile = {
        "role": role,
        "preferences": {},
        "devices": {},
    }
    _cached_user_profile.set(profile)
    return profile


async def get_user_role() -> str:
    """Get the current user's MCP role (public/admin/owner).

    If the API returns a proxy-style role (e.g. 'employee', 'super_admin'),
    map it to the simplified MCP role for tool gating.
    """
    profile = await get_user_profile()
    raw_role = profile.get("role", "public")
    # If it's already an MCP role, return as-is
    if raw_role in ROLES:
        return raw_role
    # Map proxy role to MCP role
    return PROXY_TO_MCP_ROLE.get(raw_role, "public")


def require_role(minimum_role: str):
    """Decorator that gates a tool handler behind a minimum role.

    Usage:
        @mcp.tool()
        @with_user_context
        @require_role("admin")
        async def my_admin_tool(...) -> dict:
            ...
    """
    min_rank = _role_rank(minimum_role)

    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            role = await get_user_role()
            if _role_rank(role) < min_rank:
                return {
                    "error": f"Insufficient permissions. Requires '{minimum_role}' role, you have '{role}'.",
                    "hint": "Contact your Source Parts administrator to request elevated access.",
                }
            return await fn(*args, **kwargs)
        return wrapper
    return decorator


def clear_cached_profile():
    """Clear the cached user profile (call between requests if needed)."""
    _cached_user_profile.set(None)
