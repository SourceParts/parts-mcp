"""
Configuration management for Parts MCP server.
"""
import os
from pathlib import Path
from typing import List, Optional

# API Configuration
SOURCE_PARTS_API_KEY = os.getenv("SOURCE_PARTS_API_KEY", "")
SOURCE_PARTS_API_URL = os.getenv("SOURCE_PARTS_API_URL", "https://api.sourceparts.com/v1")

# Cache Configuration
CACHE_DIR = Path(os.getenv("PARTS_CACHE_DIR", "~/.cache/parts-mcp")).expanduser()
CACHE_EXPIRY_HOURS = int(os.getenv("CACHE_EXPIRY_HOURS", "24"))

# KiCad Configuration
KICAD_SEARCH_PATHS: List[str] = []
kicad_paths_env = os.getenv("KICAD_SEARCH_PATHS", "")
if kicad_paths_env:
    KICAD_SEARCH_PATHS = [
        Path(p.strip()).expanduser().resolve().as_posix() 
        for p in kicad_paths_env.split(",") 
        if p.strip()
    ]

# Default KiCad user directories by platform
if not KICAD_SEARCH_PATHS:
    home = Path.home()
    if os.name == "posix":
        if os.uname().sysname == "Darwin":  # macOS
            KICAD_SEARCH_PATHS = [
                (home / "Documents" / "KiCad").as_posix(),
                (home / "KiCad").as_posix(),
            ]
        else:  # Linux
            KICAD_SEARCH_PATHS = [
                (home / "Documents" / "KiCad").as_posix(),
                (home / "KiCad").as_posix(),
            ]
    elif os.name == "nt":  # Windows
        KICAD_SEARCH_PATHS = [
            (home / "Documents" / "KiCad").as_posix(),
            (Path(os.getenv("APPDATA", "")) / "KiCad").as_posix(),
        ]

# Search Configuration
DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", "20"))
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "100"))
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "30"))

# Ensure cache directory exists
CACHE_DIR.mkdir(parents=True, exist_ok=True)