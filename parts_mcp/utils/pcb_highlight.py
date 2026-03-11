"""
Thin client for PCB net trace highlighting.

Finds the .kicad_pcb file, uploads it to the Source Parts API,
and saves the returned PDF(s) to disk.
"""

import logging
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from parts_mcp.utils.api_client import SourcePartsAPIError, get_client
from parts_mcp.utils.kicad_utils import get_project_files

logger = logging.getLogger(__name__)


def _find_pcb_file(project_path: str) -> Path | None:
    """Find the .kicad_pcb file for a project.

    Args:
        project_path: Path to .kicad_pro file or project directory

    Returns:
        Path to .kicad_pcb file, or None if not found
    """
    path = Path(project_path)

    # If it's a .kicad_pcb file directly, use it
    if path.is_file() and path.suffix == ".kicad_pcb":
        return path

    # If it's a .kicad_pro file, look for matching .kicad_pcb
    if path.is_file() and path.suffix == ".kicad_pro":
        files = get_project_files(str(path))
        pcb_path = files.get("pcb")
        if pcb_path:
            return Path(pcb_path)
        return None

    # If it's a directory, search for .kicad_pcb files
    if path.is_dir():
        # Check for .kicad_pro first
        pro_files = list(path.glob("*.kicad_pro"))
        if pro_files:
            files = get_project_files(str(pro_files[0]))
            pcb_path = files.get("pcb")
            if pcb_path:
                return Path(pcb_path)

        # Direct search for .kicad_pcb
        pcb_files = list(path.glob("*.kicad_pcb"))
        if pcb_files:
            return pcb_files[0]

        # Search subdirectories
        pcb_files = list(path.rglob("*.kicad_pcb"))
        if pcb_files:
            # Return most recently modified
            return max(pcb_files, key=lambda p: p.stat().st_mtime)

    return None


async def highlight_nets(
    project_path: str,
    net_names: list[str],
    colors: dict[str, str] | None = None,
    mode: str = "both",
    layers: str = "",
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Highlight net traces on a PCB and save PDF(s).

    Args:
        project_path: Path to KiCad project directory or .kicad_pro/.kicad_pcb file
        net_names: Net names to highlight
        colors: Optional color mapping {"net_name": "#rrggbb"}
        mode: "overlay", "traces_only", or "both"
        layers: Comma-separated copper layer filter
        output_dir: Where to save PDFs (defaults to project dir)

    Returns:
        Dict with success status, file paths, and metadata
    """
    # Find PCB file
    pcb_file = _find_pcb_file(project_path)
    if pcb_file is None:
        return {
            "success": False,
            "error": f"No .kicad_pcb file found in {project_path}",
        }

    if not pcb_file.exists():
        return {
            "success": False,
            "error": f"PCB file not found: {pcb_file}",
        }

    logger.info(f"Using PCB file: {pcb_file}")

    # Read file
    file_data = pcb_file.read_bytes()
    filename = pcb_file.name

    # Call API
    try:
        client = get_client()
        content_bytes, content_type, meta = client.highlight_pcb_nets(
            file_data=file_data,
            filename=filename,
            net_names=net_names,
            colors=colors,
            mode=mode,
            layers=layers,
        )
    except SourcePartsAPIError as e:
        return {
            "success": False,
            "error": str(e),
        }

    # Determine output directory
    out_dir = Path(output_dir) if output_dir else pcb_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pcb_file.stem

    files: dict[str, str] = {}

    if "application/zip" in content_type:
        # Unpack ZIP into individual PDFs
        with zipfile.ZipFile(BytesIO(content_bytes)) as zf:
            for name in zf.namelist():
                if name.endswith(".pdf"):
                    pdf_name = Path(name).stem  # "overlay" or "traces_only"
                    out_path = out_dir / f"{stem}_{pdf_name}.pdf"
                    out_path.write_bytes(zf.read(name))
                    files[pdf_name] = str(out_path)
                    logger.info(f"Saved: {out_path}")
    elif "application/pdf" in content_type:
        out_path = out_dir / f"{stem}_{mode}.pdf"
        out_path.write_bytes(content_bytes)
        files[mode] = str(out_path)
        logger.info(f"Saved: {out_path}")
    else:
        # Unknown content type — save raw
        out_path = out_dir / f"{stem}_highlight.bin"
        out_path.write_bytes(content_bytes)
        files["raw"] = str(out_path)

    return {
        "success": True,
        "pcb_file": str(pcb_file),
        "files": files,
        **meta,
    }
