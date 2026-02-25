"""MCP tools for CLI documentation."""
from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsClient, with_user_context


def register_docs_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    @with_user_context
    async def get_cli_documentation(section: str | None = None) -> dict:
        """Get documentation for the Source Parts CLI tool.

        Returns usage guides, command reference, and examples for the `parts`
        CLI. The content returned is automatically tailored to your account.

        Args:
            section: Optional topic to focus on (e.g. "auth", "search", "bom",
                     "manufacturing", "project"). Omit for full documentation.
        """
        return SourcePartsClient().get_cli_docs(section=section)
