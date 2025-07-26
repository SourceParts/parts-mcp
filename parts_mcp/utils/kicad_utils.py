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
    
    Returns:
        Path to kicad-cli or None if not found
    """
    system = platform.system()
    
    # Check environment variable first
    cli_path = os.environ.get("KICAD_CLI_PATH")
    if cli_path and os.path.exists(cli_path):
        return cli_path
    
    # Platform-specific paths
    if system == "Darwin":  # macOS
        paths = [
            "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
            "/Applications/KiCad.app/Contents/MacOS/kicad-cli",
        ]
    elif system == "Windows":
        paths = [
            r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
            r"C:\Program Files\KiCad\7.0\bin\kicad-cli.exe",
            r"C:\Program Files\KiCad\bin\kicad-cli.exe",
        ]
    else:  # Linux
        # Try to find in PATH
        cli_path = shutil.which("kicad-cli")
        if cli_path:
            return cli_path
        paths = [
            "/usr/bin/kicad-cli",
            "/usr/local/bin/kicad-cli",
        ]
    
    # Check each path
    for path in paths:
        if os.path.exists(path):
            return path
            
    # Try to find in PATH as last resort
    return shutil.which("kicad-cli")


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