"""
Datasheet tools for reading and chunking PDF datasheets.
"""
import logging
import re
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import SourcePartsAPIError, get_client, with_user_context

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_RESPONSE_CHARS = 30_000  # Keep response within MCP context limits
DEFAULT_MAX_CHUNKS = 5
MAX_SECTIONS = 200  # Cap for list_datasheet_sections


def _tokenize_query(query: str) -> list[str]:
    """Split query into lowercase keyword tokens."""
    return [t.lower() for t in re.findall(r'\w+', query) if len(t) >= 2]


def _score_text(text: str, keywords: list[str]) -> int:
    """Count keyword occurrences in text."""
    text_lower = text.lower()
    return sum(text_lower.count(kw) for kw in keywords)


def _filter_chunks(
    chunks: list[dict],
    toc: list[dict],
    query: str,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    max_chars: int = MAX_RESPONSE_CHARS,
) -> tuple[list[dict], dict]:
    """Filter chunks by query relevance, return matching chunks and savings stats.

    Chunks are scored by keyword occurrence, sorted by relevance, then capped
    by both max_chunks and max_chars to stay within MCP response limits.
    """
    keywords = _tokenize_query(query)
    if not keywords:
        return _cap_chunks(chunks, max_chunks, max_chars)

    scored = []
    total_chars = 0
    for chunk in chunks:
        text = chunk.get("text", "")
        total_chars += len(text)
        score = _score_text(text, keywords)

        # Boost score if TOC entry for this chunk's pages matches
        chunk_pages = set(range(chunk.get("start_page", 0), chunk.get("end_page", 0) + 1))
        for entry in toc:
            if entry.get("page") in chunk_pages:
                score += _score_text(entry.get("title", ""), keywords) * 3

        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    filtered = [chunk for _, chunk in scored]

    # Apply caps
    truncated = False
    pre_cap_count = len(filtered)
    if len(filtered) > max_chunks:
        filtered = filtered[:max_chunks]
        truncated = True

    # Enforce character limit
    capped: list[dict] = []
    running_chars = 0
    for chunk in filtered:
        chunk_len = len(chunk.get("text", ""))
        if running_chars + chunk_len > max_chars and capped:
            truncated = True
            break
        capped.append(chunk)
        running_chars += chunk_len
    filtered = capped

    filtered_chars = sum(len(c.get("text", "")) for c in filtered)
    savings = {
        "total_chunks": len(chunks),
        "matched_chunks": pre_cap_count,
        "returned_chunks": len(filtered),
        "total_chars": total_chars,
        "returned_chars": filtered_chars,
        "reduction_pct": round((1 - filtered_chars / total_chars) * 100, 1) if total_chars else 0,
        "truncated": truncated,
    }

    return filtered, savings


def _cap_chunks(
    chunks: list[dict],
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    max_chars: int = MAX_RESPONSE_CHARS,
) -> tuple[list[dict], dict]:
    """Cap chunks by count and character limit (no query filtering)."""
    original_count = len(chunks)
    total_chars = sum(len(c.get("text", "")) for c in chunks)
    truncated = False

    limited = chunks[:max_chunks] if len(chunks) > max_chunks else chunks
    if len(limited) < original_count:
        truncated = True

    capped: list[dict] = []
    running_chars = 0
    for chunk in limited:
        chunk_len = len(chunk.get("text", ""))
        if running_chars + chunk_len > max_chars and capped:
            truncated = True
            break
        capped.append(chunk)
        running_chars += chunk_len

    capped_chars = sum(len(c.get("text", "")) for c in capped)
    savings = {
        "total_chunks": original_count,
        "returned_chunks": len(capped),
        "total_chars": total_chars,
        "returned_chars": capped_chars,
        "reduction_pct": round((1 - capped_chars / total_chars) * 100, 1) if total_chars else 0,
        "truncated": truncated,
    }

    return capped, savings


def register_datasheet_tools(mcp: FastMCP, local_mode: bool = True) -> None:
    """Register datasheet tools with the MCP server."""

    @mcp.tool()
    @with_user_context
    async def read_datasheet(
        file_path: str | None = None,
        sku: str | None = None,
        query: str | None = None,
        chunk_pages: int = 5,
        max_chunks: int = DEFAULT_MAX_CHUNKS,
    ) -> dict[str, Any]:
        """Read and chunk a datasheet PDF for analysis.

        Two input modes:
        - file_path: Upload a local PDF file for chunking
        - sku: Fetch cached chunks from CDN by part number

        If query is provided, only chunks matching the query keywords are
        returned, reducing context usage. Use list_datasheet_sections first
        to discover what's in a datasheet before reading specific chunks.

        Args:
            file_path: Path to a local PDF datasheet
            sku: Part SKU to fetch cached chunks for
            query: Optional keywords to filter chunks (e.g. "maximum input voltage")
            chunk_pages: Pages per chunk (default 5)
            max_chunks: Maximum chunks to return (default 5). Increase for broader results.

        Returns:
            Chunked datasheet text with TOC and metadata
        """
        if not file_path and not sku:
            return {
                "success": False,
                "error": "Provide either file_path or sku",
            }

        # Normalize SKU to lowercase for case-insensitive CDN lookup
        if sku:
            sku = sku.lower()

        try:
            client = get_client()

            if file_path:
                if not local_mode:
                    return {"success": False, "error": "file_path not available in hosted mode — use sku instead"}
                path = Path(file_path).expanduser().resolve()

                if not path.exists():
                    return {"success": False, "error": f"File not found: {path}"}
                if not path.is_file():
                    return {"success": False, "error": f"Not a file: {path}"}
                if path.suffix.lower() != ".pdf":
                    return {"success": False, "error": f"Expected a .pdf file, got: {path.suffix}"}

                file_size = path.stat().st_size
                if file_size > MAX_FILE_SIZE:
                    return {
                        "success": False,
                        "error": f"File too large: {file_size / 1024 / 1024:.1f} MB (max {MAX_FILE_SIZE / 1024 / 1024:.0f} MB)",
                    }

                file_data = path.read_bytes()
                result = client.chunk_datasheet(
                    file_data=file_data,
                    filename=path.name,
                    chunk_pages=chunk_pages,
                    sku=sku,
                )
                source = path.name
            else:
                result = client.get_datasheet_chunks(
                    sku=sku,
                    chunk_pages=chunk_pages,
                )
                source = sku

            chunks = result.get("chunks", [])
            toc = result.get("toc", [])

            response: dict[str, Any] = {
                "success": True,
                "source": source,
                "total_pages": result.get("total_pages"),
                "method": result.get("method"),
                "toc": toc,
            }

            if query:
                filtered, savings = _filter_chunks(
                    chunks, toc, query,
                    max_chunks=max_chunks,
                    max_chars=MAX_RESPONSE_CHARS,
                )
                response["chunks"] = filtered
                response["query"] = query
                response["context_savings"] = savings
                msg = (
                    f"{savings['returned_chunks']} of {savings['total_chunks']} chunks "
                    f"match query ({savings['reduction_pct']}% reduction)"
                )
                if savings.get("truncated"):
                    msg += (
                        f". Results were truncated to stay within response limits "
                        f"(matched {savings.get('matched_chunks', '?')} chunks). "
                        f"Narrow your query or increase max_chunks for different results."
                    )
                response["message"] = msg
            else:
                capped, savings = _cap_chunks(
                    chunks,
                    max_chunks=max_chunks,
                    max_chars=MAX_RESPONSE_CHARS,
                )
                response["chunks"] = capped
                response["context_savings"] = savings
                msg = f"{savings['returned_chunks']} of {savings['total_chunks']} chunks from {source}"
                if savings.get("truncated"):
                    msg += (
                        ". Results were truncated to stay within response limits. "
                        "Use a query to filter for specific content, or increase max_chunks."
                    )
                response["message"] = msg

            return response

        except SourcePartsAPIError as e:
            logger.error(f"Datasheet read failed: {e}")
            return {"success": False, "error": f"Datasheet read failed: {e}"}
        except OSError as e:
            logger.error(f"File read error: {e}")
            return {"success": False, "error": f"Could not read file: {e}"}

    @mcp.tool()
    @with_user_context
    async def list_datasheet_sections(
        file_path: str | None = None,
        sku: str | None = None,
    ) -> dict[str, Any]:
        """List table-of-contents sections from a datasheet PDF.

        A lightweight way to discover what's in a datasheet before reading
        specific chunks with read_datasheet. Returns only section titles
        and page numbers, no chunk text.

        Two input modes:
        - file_path: Upload a local PDF file
        - sku: Fetch cached data from CDN by part number

        Args:
            file_path: Path to a local PDF datasheet
            sku: Part SKU to fetch cached data for

        Returns:
            TOC entries with section titles and page numbers
        """
        if not file_path and not sku:
            return {
                "success": False,
                "error": "Provide either file_path or sku",
            }

        # Normalize SKU to lowercase for case-insensitive CDN lookup
        if sku:
            sku = sku.lower()

        try:
            client = get_client()

            if file_path:
                if not local_mode:
                    return {"success": False, "error": "file_path not available in hosted mode — use sku instead"}

                path = Path(file_path).expanduser().resolve()

                if not path.exists():
                    return {"success": False, "error": f"File not found: {path}"}
                if not path.is_file():
                    return {"success": False, "error": f"Not a file: {path}"}
                if path.suffix.lower() != ".pdf":
                    return {"success": False, "error": f"Expected a .pdf file, got: {path.suffix}"}

                file_size = path.stat().st_size
                if file_size > MAX_FILE_SIZE:
                    return {
                        "success": False,
                        "error": f"File too large: {file_size / 1024 / 1024:.1f} MB (max {MAX_FILE_SIZE / 1024 / 1024:.0f} MB)",
                    }

                file_data = path.read_bytes()
                result = client.chunk_datasheet(
                    file_data=file_data,
                    filename=path.name,
                    chunk_pages=1,
                    sku=sku,
                )
                source = path.name
            else:
                result = client.get_datasheet_chunks(
                    sku=sku,
                    chunk_pages=1,
                )
                source = sku

            toc = result.get("toc", [])
            total_sections = len(toc)
            truncated = False

            if total_sections > MAX_SECTIONS:
                toc = toc[:MAX_SECTIONS]
                truncated = True

            msg = f"{total_sections} sections found in {source}" if toc else f"No TOC detected in {source}"
            if truncated:
                msg += f" (showing first {MAX_SECTIONS} of {total_sections})"

            return {
                "success": True,
                "source": source,
                "total_pages": result.get("total_pages"),
                "sections": toc,
                "section_count": total_sections,
                "returned_sections": len(toc),
                "truncated": truncated,
                "message": msg,
            }

        except SourcePartsAPIError as e:
            logger.error(f"Datasheet sections failed: {e}")
            return {"success": False, "error": f"Datasheet sections failed: {e}"}
        except OSError as e:
            logger.error(f"File read error: {e}")
            return {"success": False, "error": f"Could not read file: {e}"}

    logger.info("Registered datasheet tools (read_datasheet, list_datasheet_sections)")
