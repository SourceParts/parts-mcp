"""
User preference tools — get/set per-user and per-device preferences.

Preferences are stored in the Source Parts API and scoped by:
- User (Auth0 sub): global defaults for the user
- Device (device_id): overrides per MCP client (e.g. "macbook", "claude-desktop", "ci")

Preference keys are namespaced by feature:
- ecn.*         ECN workflow preferences
- fab.*         Fabrication output preferences
- tools.*       Tool visibility and behavior
- notify.*      Notification preferences

Example preference document:
{
  "tools.cli_enabled": true,
  "tools.visible_categories": ["search", "sourcing", "ecn", "fab", "cli"],
  "ecn.default_author": "José Angel Torres",
  "ecn.default_severity": "HIGH",
  "fab.default_scale": 3,
  "fab.board_name": "nRF54H20 Main V1.03",
  "notify.ecn_thread": true
}
"""
import logging
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsAPIError, get_client, with_user_context
from parts_mcp.utils.roles import require_role

logger = logging.getLogger(__name__)


def register_preference_tools(mcp: FastMCP) -> None:
    """Register user preference tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    async def user_profile() -> dict[str, Any]:
        """Get the current user's profile, role, and preferences.

        Returns the authenticated user's profile including their role level
        (public, admin, owner), global preferences, and per-device overrides.

        Returns:
            User profile with role, preferences, and device list
        """
        from parts_mcp.utils.roles import get_user_profile
        try:
            return await get_user_profile()
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def get_preferences(
        device_id: str | None = None,
    ) -> dict[str, Any]:
        """Get user preferences, optionally for a specific device.

        Preferences are merged: global user defaults are overridden by
        device-specific values when a device_id is provided.

        Args:
            device_id: Optional device identifier (e.g. "macbook", "claude-desktop").
                       If omitted, returns global user preferences only.

        Returns:
            Merged preference key-value pairs
        """
        try:
            client = get_client()
            params: dict[str, Any] = {}
            if device_id:
                params["device_id"] = device_id

            return client._make_request(
                "GET", "users/me/preferences",
                params=params or None,
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("Failed to get preferences: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def set_preferences(
        preferences: dict[str, Any],
        device_id: str | None = None,
    ) -> dict[str, Any]:
        """Set user preferences, optionally for a specific device.

        Merges the provided key-value pairs into existing preferences.
        To delete a key, set its value to null.

        Args:
            preferences: Key-value pairs to set. Keys use dot notation
                         (e.g. "ecn.default_author", "fab.default_scale").
            device_id: Optional device identifier. If provided, preferences
                       are stored as device-specific overrides.

        Returns:
            Updated preferences
        """
        try:
            client = get_client()
            json_data: dict[str, Any] = {"preferences": preferences}
            if device_id:
                json_data["device_id"] = device_id

            return client._make_request(
                "PATCH", "users/me/preferences",
                json_data=json_data,
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("Failed to set preferences: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    async def list_devices() -> dict[str, Any]:
        """List all devices registered for the current user.

        Each device has an ID, name, last-seen timestamp, and any
        device-specific preference overrides.

        Returns:
            List of devices with their preferences
        """
        try:
            client = get_client()
            return client._make_request(
                "GET", "users/me/devices",
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("Failed to list devices: %s", e)
            return {"error": str(e)}

    # --- Admin-only tools ---

    @mcp.tool()
    @with_user_context
    @require_role("owner")
    async def admin_set_user_role(
        user_id: str,
        role: str,
    ) -> dict[str, Any]:
        """Set a user's role level. Owner-only.

        Args:
            user_id: Target user's Auth0 sub or Source Parts user ID
            role: New role: public, admin, or owner

        Returns:
            Updated user profile
        """
        if role not in ("public", "admin", "owner"):
            return {"error": f"Invalid role {role!r}. Must be: public, admin, owner"}

        try:
            client = get_client()
            return client._make_request(
                "PATCH", f"users/{user_id}/role",
                json_data={"role": role},
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("Failed to set user role: %s", e)
            return {"error": str(e)}

    @mcp.tool()
    @with_user_context
    @require_role("owner")
    async def admin_list_users(
        role: str | None = None,
    ) -> dict[str, Any]:
        """List all users. Owner-only.

        Args:
            role: Optional filter by role (public, admin, owner)

        Returns:
            List of users with their roles and preferences
        """
        try:
            client = get_client()
            params: dict[str, Any] = {}
            if role:
                params["role"] = role

            return client._make_request(
                "GET", "users",
                params=params or None,
                base_url=client._project_base_url(),
            )
        except SourcePartsAPIError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("Failed to list users: %s", e)
            return {"error": str(e)}
