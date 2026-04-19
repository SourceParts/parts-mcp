"""MCP tools for document safelist management.

The safelist controls which file types Magika-scanned documents may have
when uploaded through the Source Parts API. An upload is accepted only if
Magika's detected MIME type is present in the safelist.

Commands follow the Parts CLI naming convention: lowercase single words.
  parts doc safelist          → list_doc_safelist
  parts doc safelist add      → add_doc_safelist
  parts doc safelist remove   → remove_doc_safelist
"""
from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsClient, with_user_context


def register_doc_safelist_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    @with_user_context
    async def list_doc_safelist() -> dict:
        """List all MIME types currently on the document upload safelist.

        Returns the full set of file types that are permitted for upload after
        Magika content-type scanning. Types not on this list will be rejected
        at the API boundary.
        """
        return SourcePartsClient()._make_request("GET", "/api/docs/safelist")

    @mcp.tool()
    @with_user_context
    async def add_doc_safelist(
        mime_type: str,
        label: str,
        description: str | None = None,
    ) -> dict:
        """Add a MIME type to the document upload safelist.

        Once added, files whose Magika-detected type matches this MIME type
        will be accepted for upload. Requires admin role.

        Args:
            mime_type: MIME type to allow, e.g. "application/pdf".
            label: Magika content label, e.g. "pdf". Run `parts doc scan`
                   against a sample file to find the correct label.
            description: Optional human-readable note about this entry.
        """
        return SourcePartsClient()._make_request(
            "POST",
            "/api/docs/safelist",
            json_data={
                "mimeType": mime_type,
                "label": label,
                "description": description,
            },
        )

    @mcp.tool()
    @with_user_context
    async def remove_doc_safelist(mime_type: str) -> dict:
        """Remove a MIME type from the document upload safelist.

        After removal, uploads whose Magika-detected type matches this MIME
        type will be rejected. Requires admin role.

        Args:
            mime_type: MIME type to remove, e.g. "application/pdf".
        """
        from urllib.parse import quote
        encoded = quote(mime_type, safe="")
        return SourcePartsClient()._make_request(
            "DELETE",
            f"/api/docs/safelist/{encoded}",
        )

    @mcp.tool()
    @with_user_context
    async def scan_doc(
        file_path: str,
    ) -> dict:
        """Scan a local file with Magika to detect its true content type.

        Uses the Source Parts document scanning API (backed by Google Magika)
        to identify what a file actually is, regardless of its extension.
        Useful for checking whether a file would be accepted by the safelist
        before uploading it.

        Args:
            file_path: Absolute path to the local file to scan.
        """
        import base64
        from pathlib import Path

        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}"}
        if not p.is_file():
            return {"error": f"Not a file: {file_path}"}

        # Read up to 4 MB — Magika only needs the first few KB for detection
        MAX_BYTES = 4 * 1024 * 1024
        data = p.read_bytes()[:MAX_BYTES]
        encoded = base64.b64encode(data).decode()

        return SourcePartsClient()._make_request(
            "POST",
            "/api/docs/scan",
            json_data={
                "filename": p.name,
                "dataBase64": encoded,
            },
        )
