"""
KiCad-specific utility functions for parts-mcp.
"""
import os
import json
import logging
import subprocess
import platform
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional

from parts_mcp.config import KICAD_SEARCH_PATHS

logger = logging.getLogger(__name__)

# KiCad file extensions
KICAD_EXTENSIONS = {
    "project": ".kicad_pro",
    "pcb": ".kicad_pcb", 
    "schematic": ".kicad_sch",
    "design_rules": ".kicad_dru",
    "worksheet": ".kicad_wks",
    "footprint": ".kicad_mod",
    "netlist": "_netlist.net",
}

# Data file extensions
DATA_EXTENSIONS = [
    ".csv",  # BOM or other data
    ".pos",  # Component position file
    ".net",  # Netlist files
    ".zip",  # Gerber files and other archives
    ".drl",  # Drill files
]


def find_kicad_projects() -> List[Dict[str, Any]]:
    """Find KiCad projects in configured search paths.
    
    Returns:
        List of dictionaries with project information
    """
    projects = []
    logger.info("Searching for KiCad projects...")
    
    # Expand and validate search paths
    expanded_search_dirs = []
    for raw_dir in KICAD_SEARCH_PATHS:
        expanded_dir = Path(raw_dir).expanduser().resolve()
        if expanded_dir.exists() and expanded_dir not in expanded_search_dirs:
            expanded_search_dirs.append(expanded_dir)
            
    logger.info(f"Searching in {len(expanded_search_dirs)} directories")
    
    for search_dir in expanded_search_dirs:
        logger.debug(f"Scanning directory: {search_dir}")
        
        # Find all .kicad_pro files
        try:
            for proj_file in search_dir.rglob("*.kicad_pro"):
                try:
                    # Get modification time
                    mod_time = proj_file.stat().st_mtime
                    rel_path = proj_file.relative_to(search_dir)
                    
                    projects.append({
                        "name": proj_file.stem,
                        "path": str(proj_file),
                        "relative_path": str(rel_path),
                        "directory": str(proj_file.parent),
                        "modified": mod_time
                    })
                    
                except OSError as e:
                    logger.error(f"Error accessing project file {proj_file}: {e}")
                    
        except Exception as e:
            logger.error(f"Error scanning directory {search_dir}: {e}")
    
    logger.info(f"Found {len(projects)} KiCad projects")
    return projects


def get_project_files(project_path: str) -> Dict[str, str]:
    """Get all files related to a KiCad project.
    
    Args:
        project_path: Path to the .kicad_pro file
        
    Returns:
        Dictionary mapping file types to file paths
    """
    project_dir = Path(project_path).parent
    project_name = Path(project_path).stem
    
    files = {}
    
    # Check for standard KiCad files
    for file_type, extension in KICAD_EXTENSIONS.items():
        if file_type == "project":
            files[file_type] = project_path
            continue
            
        file_path = project_dir / f"{project_name}{extension}"
        if file_path.exists():
            files[file_type] = str(file_path)
    
    # Check for data files
    try:
        for file_path in project_dir.iterdir():
            if file_path.is_file() and file_path.suffix in DATA_EXTENSIONS:
                # Determine file type from name
                file_name = file_path.stem.lower()
                
                if "bom" in file_name:
                    file_type = "bom"
                elif "pos" in file_name or "position" in file_name:
                    file_type = "position"
                elif file_path.suffix == ".net":
                    file_type = "netlist_data"
                else:
                    file_type = file_path.suffix[1:]  # Remove dot
                    
                # Add suffix to avoid key conflicts
                if file_type in files:
                    file_type = f"{file_type}_{file_path.suffix[1:]}"
                    
                files[file_type] = str(file_path)
                
    except (OSError, FileNotFoundError):
        pass
        
    return files


def load_project_json(project_path: str) -> Optional[Dict[str, Any]]:
    """Load and parse a KiCad project file.
    
    Args:
        project_path: Path to the .kicad_pro file
        
    Returns:
        Parsed JSON data or None if parsing failed
    """
    try:
        with open(project_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading project file {project_path}: {e}")
        return None


def extract_project_info(project_path: str) -> Dict[str, Any]:
    """Extract information from a KiCad project file.
    
    Args:
        project_path: Path to the .kicad_pro file
        
    Returns:
        Dictionary with project information
    """
    info = {
        "path": project_path,
        "name": Path(project_path).stem,
        "directory": str(Path(project_path).parent),
        "files": get_project_files(project_path),
        "metadata": {},
        "settings": {}
    }
    
    # Load project JSON
    project_data = load_project_json(project_path)
    if project_data:
        # Extract metadata
        if "meta" in project_data:
            info["metadata"] = project_data["meta"]
            
        # Extract board settings
        if "board" in project_data:
            board = project_data["board"]
            info["settings"]["board"] = {
                "thickness": board.get("thickness"),
                "copper_layers": board.get("copper_layer_count"),
            }
            
        # Extract text variables
        if "text_variables" in project_data:
            info["text_variables"] = project_data["text_variables"]
            
    return info


def find_kicad_cli() -> Optional[str]:
    """Find the KiCad CLI executable.

    Searches in the following order:
    1. KICAD_CLI_PATH environment variable
    2. System PATH
    3. Platform-specific default locations
    4. Flatpak/Snap installations (Linux)

    Returns:
        Path to kicad-cli or None if not found
    """
    system = platform.system()

    # Check environment variable first
    cli_path = os.environ.get("KICAD_CLI_PATH")
    if cli_path and os.path.exists(cli_path):
        return cli_path

    # Try to find in PATH first (works across platforms)
    cli_path = shutil.which("kicad-cli")
    if cli_path:
        return cli_path

    # Platform-specific paths
    if system == "Darwin":  # macOS
        paths = [
            # KiCad 9.x
            "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
            # KiCad 8.x and earlier
            "/Applications/KiCad.app/Contents/MacOS/kicad-cli",
            # Homebrew installation
            "/usr/local/bin/kicad-cli",
            "/opt/homebrew/bin/kicad-cli",
            # User-specific installations
            str(Path.home() / "Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"),
            str(Path.home() / "Applications/KiCad.app/Contents/MacOS/kicad-cli"),
        ]
    elif system == "Windows":
        # Check common installation paths for KiCad 7, 8, 9
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

        paths = []
        for version in ["9.0", "8.0", "7.0", ""]:
            if version:
                paths.append(os.path.join(program_files, "KiCad", version, "bin", "kicad-cli.exe"))
                paths.append(os.path.join(program_files_x86, "KiCad", version, "bin", "kicad-cli.exe"))
            else:
                paths.append(os.path.join(program_files, "KiCad", "bin", "kicad-cli.exe"))
                paths.append(os.path.join(program_files_x86, "KiCad", "bin", "kicad-cli.exe"))

    else:  # Linux
        paths = [
            # Standard installations
            "/usr/bin/kicad-cli",
            "/usr/local/bin/kicad-cli",
            # Flatpak installation
            "/var/lib/flatpak/exports/bin/org.kicad.KiCad.kicad-cli",
            str(Path.home() / ".local/share/flatpak/exports/bin/org.kicad.KiCad.kicad-cli"),
            # Snap installation
            "/snap/bin/kicad.kicad-cli",
            "/snap/kicad/current/usr/bin/kicad-cli",
        ]

    # Check each path
    for path in paths:
        if os.path.exists(path):
            return path

    return None


def run_kicad_cli(args: List[str], timeout: int = 30) -> Dict[str, Any]:
    """Run a KiCad CLI command.
    
    Args:
        args: Command arguments (excluding 'kicad-cli')
        timeout: Command timeout in seconds
        
    Returns:
        Dictionary with command results
    """
    cli_path = find_kicad_cli()
    if not cli_path:
        return {
            "success": False,
            "error": "KiCad CLI not found. Please install KiCad."
        }
    
    cmd = [cli_path] + args
    
    try:
        logger.info(f"Running KiCad CLI: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "command": ' '.join(cmd)
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Command timed out after {timeout} seconds",
            "command": ' '.join(cmd)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": ' '.join(cmd)
        }


def open_kicad_project(project_path: str) -> Dict[str, Any]:
    """Open a KiCad project in the KiCad application.
    
    Args:
        project_path: Path to the .kicad_pro file
        
    Returns:
        Dictionary with result information
    """
    if not os.path.exists(project_path):
        return {"success": False, "error": f"Project not found: {project_path}"}
    
    system = platform.system()
    
    try:
        if system == "Darwin":  # macOS
            cmd = ["open", "-a", "KiCad", project_path]
        elif system == "Windows":
            cmd = ["start", "", project_path]
            # Use shell=True for Windows 'start' command
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            return {
                "success": result.returncode == 0,
                "command": ' '.join(cmd),
                "error": result.stderr if result.returncode != 0 else None
            }
        else:  # Linux
            cmd = ["xdg-open", project_path]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        return {
            "success": result.returncode == 0,
            "command": ' '.join(cmd),
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_kicad_version() -> Optional[Dict[str, Any]]:
    """Get KiCad CLI version information.

    Returns:
        Dictionary with version info or None if CLI not found
    """
    cli_path = find_kicad_cli()
    if not cli_path:
        return None

    try:
        result = subprocess.run(
            [cli_path, "version"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            version_str = result.stdout.strip()
            # Parse version string (e.g., "8.0.4" or "9.0.0-rc1")
            import re
            match = re.match(r"(\d+)\.(\d+)\.?(\d+)?", version_str)

            version_info = {
                "full_version": version_str,
                "cli_path": cli_path
            }

            if match:
                version_info["major"] = int(match.group(1))
                version_info["minor"] = int(match.group(2))
                version_info["patch"] = int(match.group(3)) if match.group(3) else 0

            return version_info

    except Exception as e:
        logger.error(f"Error getting KiCad version: {e}")

    return None


def generate_bom_from_schematic(
    schematic_path: str,
    output_path: Optional[str] = None,
    format: str = "csv",
    fields: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Generate a BOM from a KiCad schematic using kicad-cli.

    Args:
        schematic_path: Path to the .kicad_sch file
        output_path: Output file path (auto-generated if None)
        format: Output format ('csv', 'xml', or 'grouped')
        fields: List of fields to include (None for defaults)

    Returns:
        Dictionary with result information and BOM path
    """
    if not os.path.exists(schematic_path):
        return {"success": False, "error": f"Schematic not found: {schematic_path}"}

    cli_path = find_kicad_cli()
    if not cli_path:
        return {"success": False, "error": "KiCad CLI not found"}

    # Generate output path if not provided
    if output_path is None:
        schematic_dir = Path(schematic_path).parent
        schematic_name = Path(schematic_path).stem
        ext = ".xml" if format == "xml" else ".csv"
        output_path = str(schematic_dir / f"{schematic_name}_bom{ext}")

    # Build command
    cmd = [cli_path, "sch", "export", "bom"]

    # Add output path
    cmd.extend(["-o", output_path])

    # Add format-specific options
    if format == "xml":
        cmd.append("--format-preset")
        cmd.append("xml")
    elif format == "grouped":
        cmd.append("--group-by")
        cmd.append("Value,Footprint")

    # Add custom fields if specified
    if fields:
        cmd.append("--fields")
        cmd.append(",".join(fields))

    # Add schematic path
    cmd.append(schematic_path)

    try:
        logger.info(f"Generating BOM: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            return {
                "success": True,
                "bom_path": output_path,
                "format": format,
                "command": ' '.join(cmd)
            }
        else:
            return {
                "success": False,
                "error": result.stderr or "BOM generation failed",
                "command": ' '.join(cmd),
                "stdout": result.stdout
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "BOM generation timed out",
            "command": ' '.join(cmd)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": ' '.join(cmd)
        }


def generate_netlist(
    schematic_path: str,
    output_path: Optional[str] = None,
    format: str = "kicad"
) -> Dict[str, Any]:
    """Generate a netlist from a KiCad schematic using kicad-cli.

    Args:
        schematic_path: Path to the .kicad_sch file
        output_path: Output file path (auto-generated if None)
        format: Output format ('kicad', 'cadstar', 'orcadpcb2', 'spice')

    Returns:
        Dictionary with result information and netlist path
    """
    if not os.path.exists(schematic_path):
        return {"success": False, "error": f"Schematic not found: {schematic_path}"}

    cli_path = find_kicad_cli()
    if not cli_path:
        return {"success": False, "error": "KiCad CLI not found"}

    # Generate output path if not provided
    if output_path is None:
        schematic_dir = Path(schematic_path).parent
        schematic_name = Path(schematic_path).stem
        ext = ".net" if format == "kicad" else f".{format}"
        output_path = str(schematic_dir / f"{schematic_name}_netlist{ext}")

    # Build command
    cmd = [cli_path, "sch", "export", "netlist"]

    # Add format
    cmd.extend(["--format", format])

    # Add output path
    cmd.extend(["-o", output_path])

    # Add schematic path
    cmd.append(schematic_path)

    try:
        logger.info(f"Generating netlist: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            return {
                "success": True,
                "netlist_path": output_path,
                "format": format,
                "command": ' '.join(cmd)
            }
        else:
            return {
                "success": False,
                "error": result.stderr or "Netlist generation failed",
                "command": ' '.join(cmd),
                "stdout": result.stdout
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Netlist generation timed out",
            "command": ' '.join(cmd)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": ' '.join(cmd)
        }


def export_schematic_pdf(
    schematic_path: str,
    output_path: Optional[str] = None
) -> Dict[str, Any]:
    """Export a schematic to PDF using kicad-cli.

    Args:
        schematic_path: Path to the .kicad_sch file
        output_path: Output PDF path (auto-generated if None)

    Returns:
        Dictionary with result information
    """
    if not os.path.exists(schematic_path):
        return {"success": False, "error": f"Schematic not found: {schematic_path}"}

    cli_path = find_kicad_cli()
    if not cli_path:
        return {"success": False, "error": "KiCad CLI not found"}

    # Generate output path if not provided
    if output_path is None:
        schematic_dir = Path(schematic_path).parent
        schematic_name = Path(schematic_path).stem
        output_path = str(schematic_dir / f"{schematic_name}.pdf")

    cmd = [cli_path, "sch", "export", "pdf", "-o", output_path, schematic_path]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            return {
                "success": True,
                "pdf_path": output_path,
                "command": ' '.join(cmd)
            }
        else:
            return {
                "success": False,
                "error": result.stderr or "PDF export failed",
                "command": ' '.join(cmd)
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


def validate_kicad_installation() -> Dict[str, Any]:
    """Validate KiCad installation and capabilities.

    Returns:
        Dictionary with installation status and capabilities
    """
    result = {
        "installed": False,
        "cli_available": False,
        "cli_path": None,
        "version": None,
        "capabilities": []
    }

    # Check CLI availability
    cli_path = find_kicad_cli()
    if cli_path:
        result["cli_available"] = True
        result["cli_path"] = cli_path
        result["installed"] = True

        # Get version
        version_info = get_kicad_version()
        if version_info:
            result["version"] = version_info

            # Determine capabilities based on version
            major = version_info.get("major", 0)

            if major >= 7:
                result["capabilities"].extend([
                    "bom_export",
                    "netlist_export",
                    "pdf_export",
                    "svg_export"
                ])

            if major >= 8:
                result["capabilities"].extend([
                    "drc",
                    "erc",
                    "pcb_export"
                ])

            if major >= 9:
                result["capabilities"].append("advanced_bom_options")

    return result