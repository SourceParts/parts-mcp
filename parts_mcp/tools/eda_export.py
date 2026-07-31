"""
KiCad schematic export MCP tools.

Mirrors the `parts eda export sch <file> --format <fmt>` CLI surface, which has
long reached /v1/eda/sch/export/* while the MCP had no route to it at all.

  sch_export_bom      — components via /v1/eda/sch/export/bom
  sch_export_graphic  — pdf | dxf | hpgl | ps via the matching route

The server shells out to `kicad-cli sch export ...`, so results are KiCad's own,
not a re-implementation. That matters most for the BOM: a .kicad_sch holds a
lib_symbols block of symbol *definitions* whose Reference fields are the
unnumbered defaults ("U", "J", "R", "C"). Hand-rolled parsers that miss it
report parts the board does not have. Use this rather than reading the
s-expression directly.

The two tools are separate because their results differ in kind. The BOM is data
to reason about, returned parsed; the rest are opaque files to save, returned
base64 (and, for hpgl and ps, zipped because KiCad writes one file per page).

Registered in both hosted and local mode. The filesystem arguments are gated on
local_mode, not the tool itself, so hosted callers can still pass the schematic
inline instead of finding the tool simply absent.
"""
from __future__ import annotations

import base64
import csv
import io
import os
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP

from parts_mcp.utils.api_client import get_client, with_user_context

# The server allows kicad-cli 120s (_export_endpoint's default); the client's
# 30s search default would abort a large hierarchical export mid-flight.
EXPORT_TIMEOUT = 120

# Per-format default extension and whether the server returns an archive.
# Verified against kicad-cli directly: pdf is the only single-file export.
# dxf, hpgl and ps each plot one file per page into a directory, which the
# server zips — so the archive is what comes back whatever the format is named.
GRAPHIC_FORMATS: dict[str, tuple[str, bool]] = {
    "pdf": (".pdf", False),
    "dxf": (".zip", True),
    "hpgl": (".zip", True),
    "ps": (".zip", True),
}


def _parse_delimited(text: str, delimiter: str) -> list[dict[str, str]]:
    """Parse the exported table into row dicts, header-keyed."""
    return [dict(row) for row in csv.DictReader(io.StringIO(text), delimiter=delimiter)]


def _resolve_input(
    schematic_path: str | None,
    schematic_content: str | None,
    output_path: str | None,
    local_mode: bool,
) -> tuple[bytes | None, str, dict[str, Any] | None]:
    """Validate the input pair and load the schematic.

    Returns (data, filename, error). *error* is non-None when the caller should
    return it directly.
    """
    if schematic_path and schematic_content:
        return None, "", {
            "success": False,
            "error": "pass only one of schematic_path or schematic_content",
        }
    if not schematic_path and not schematic_content:
        return None, "", {
            "success": False,
            "error": "one of schematic_path or schematic_content is required",
        }
    if not local_mode and (schematic_path or output_path):
        return None, "", {
            "success": False,
            "error": (
                "schematic_path and output_path need filesystem access, which is "
                "unavailable in hosted mode. Pass the file text as "
                "schematic_content instead."
            ),
        }

    if schematic_path:
        p = Path(schematic_path)
        if not p.exists():
            return None, "", {"success": False, "error": f"not found: {schematic_path}"}
        return p.read_bytes(), p.name, None
    return schematic_content.encode("utf-8"), "schematic.kicad_sch", None


def _write(path: str, data: bytes | str) -> str:
    """Write *data* to *path*, creating parent directories."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    mode, payload = ("wb", data) if isinstance(data, bytes) else ("w", data)
    with open(path, mode) as f:
        f.write(payload)
    return path


def register_eda_export_tools(mcp: FastMCP, local_mode: bool = True) -> None:
    """Register KiCad export tools."""

    @mcp.tool()
    @with_user_context
    async def sch_export_bom(
        schematic_path: str | None = None,
        schematic_content: str | None = None,
        fields: str | None = None,
        group_by: str | None = None,
        sort_field: str | None = None,
        sort_desc: bool = False,
        format_preset: str = "CSV",
        exclude_dnp: bool = False,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Extract the bill of materials from a KiCad schematic.

        Uploads to /v1/eda/sch/export/bom, which runs `kicad-cli sch export bom`
        server-side, and returns the components both parsed and raw. Prefer this
        over reading a .kicad_sch yourself — the file's lib_symbols block holds
        symbol definitions that are easily miscounted as placed parts.

        Supply exactly one of schematic_path or schematic_content.

        Args:
            schematic_path: Path to a .kicad_sch (local mode only)
            schematic_content: Schematic file text, for hosted mode
            fields: Comma-separated fields to emit, e.g. "Reference,Value,Footprint"
            group_by: Comma-separated fields to group identical parts by, e.g. "Value"
            sort_field: Field to sort on
            sort_desc: Sort descending instead of ascending
            format_preset: "CSV" or "TSV"
            exclude_dnp: Drop components marked Do-Not-Populate
            output_path: Write the raw export here as well (local mode only)

        Returns:
            components (list of row dicts), component_count, content (raw text),
            filename, size_bytes, output_path
        """
        try:
            data, name, error = _resolve_input(
                schematic_path, schematic_content, output_path, local_mode
            )
            if error:
                return error

            is_tsv = format_preset.upper() == "TSV"

            form_fields = {"format_preset": "TSV" if is_tsv else "CSV"}
            if fields:
                form_fields["fields"] = fields
            if group_by:
                form_fields["group_by"] = group_by
            if sort_field:
                form_fields["sort_field"] = sort_field
            if sort_desc:
                form_fields["sort_asc"] = "false"
            if exclude_dnp:
                form_fields["exclude_dnp"] = "true"

            client = get_client()
            result = client.upload_file(
                "eda/sch/export/bom",
                file_data=data,
                filename=name,
                options=form_fields,
                timeout=EXPORT_TIMEOUT,
            )

            content = result.get("content", "")
            filename = result.get("filename", "bom.tsv" if is_tsv else "bom.csv")

            # A parse failure must not lose the export — the raw text is the
            # ground truth and the caller can still work from it.
            components: list[dict[str, str]] = []
            parse_error: str | None = None
            try:
                components = _parse_delimited(content, "\t" if is_tsv else ",")
            except Exception as e:
                parse_error = str(e)

            written = _write(output_path, content) if output_path else None

            response: dict[str, Any] = {
                "success": True,
                "components": components,
                "component_count": len(components),
                "content": content,
                "filename": filename,
                "size_bytes": result.get("size_bytes", len(content)),
                "output_path": written,
                "summary": f"{len(components)} components from {name}",
            }
            if parse_error:
                response["parse_error"] = parse_error
                response["summary"] = f"exported {name}, but the table could not be parsed"
            return response

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"API error {e.response.status_code}: {e.response.text[:300]}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    @with_user_context
    async def sch_export_graphic(
        format: str,
        schematic_path: str | None = None,
        schematic_content: str | None = None,
        output_path: str | None = None,
        pages: str | None = None,
        black_and_white: bool = False,
        pen_size: str | None = None,
    ) -> dict[str, Any]:
        """Plot a KiCad schematic to PDF, DXF, HPGL or PostScript.

        Runs `kicad-cli sch export <format>` server-side. For a bill of
        materials use sch_export_bom instead — it returns parsed components
        rather than an opaque file.

        hpgl and ps are plotted one file per page, so those come back as a ZIP
        archive whatever output_path is named. is_archive says which you got.

        Supply exactly one of schematic_path or schematic_content. In hosted
        mode the file is returned base64 in content_base64, since there is no
        filesystem to write to.

        Args:
            format: "pdf", "dxf", "hpgl" or "ps"
            schematic_path: Path to a .kicad_sch (local mode only)
            schematic_content: Schematic file text, for hosted mode
            output_path: Where to write the result (local mode only). Defaults
                to the schematic's own directory when a path was given.
            pages: Comma-separated page numbers; all pages when omitted
            black_and_white: Monochrome output (pdf, dxf, ps)
            pen_size: Pen width in mm (hpgl only, server default 0.5)

        Returns:
            format, filename, size_bytes, is_archive, output_path, and
            content_base64 when nothing was written to disk
        """
        try:
            fmt = format.lower().strip()
            if fmt not in GRAPHIC_FORMATS:
                return {
                    "success": False,
                    "error": (
                        f"unsupported format {format!r}; expected one of "
                        f"{', '.join(sorted(GRAPHIC_FORMATS))}. For a BOM use "
                        "sch_export_bom."
                    ),
                }
            ext, is_archive = GRAPHIC_FORMATS[fmt]

            data, name, error = _resolve_input(
                schematic_path, schematic_content, output_path, local_mode
            )
            if error:
                return error

            form_fields: dict[str, str] = {}
            if pages:
                form_fields["pages"] = pages
            if black_and_white:
                form_fields["black_and_white"] = "true"
            if pen_size and fmt == "hpgl":
                form_fields["pen_size"] = pen_size

            client = get_client()
            result = client.upload_file(
                f"eda/sch/export/{fmt}",
                file_data=data,
                filename=name,
                options=form_fields,
                timeout=EXPORT_TIMEOUT,
            )

            encoded = result.get("file_base64", "")
            payload = base64.b64decode(encoded) if encoded else b""
            filename = result.get("filename") or f"{Path(name).stem}{ext}"
            # The server zips whenever it plots per page; trust what it sent
            # over the table, which only predicts the usual case.
            archive = is_archive or filename.endswith(".zip")

            target = output_path
            if target is None and schematic_path:
                target = str(Path(schematic_path).with_suffix("")) + ext
            written = _write(target, payload) if target and local_mode else None

            response: dict[str, Any] = {
                "success": True,
                "format": fmt,
                "filename": filename,
                "size_bytes": result.get("size_bytes", len(payload)),
                "is_archive": archive,
                "output_path": written,
                "summary": f"exported {name} as {fmt}"
                + (f" to {written}" if written else ""),
            }
            if written is None:
                response["content_base64"] = encoded
            return response

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"API error {e.response.status_code}: {e.response.text[:300]}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
