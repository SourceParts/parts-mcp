"""
Shared utilities for discovering and parsing .parts/config.yaml project configuration.

These are separated from the project tool so other tools (e.g. KiCad, manufacturing)
can also discover project context without circular imports.
"""
import logging
import subprocess
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def find_git_root(start_path: Path) -> Path | None:
    """Find the git repository root from a starting path.

    Args:
        start_path: Directory to start searching from

    Returns:
        Path to git root, or None if not in a git repo
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start_path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def find_config_file(start_path: Path) -> Path | None:
    """Walk from start_path up to git root looking for .parts/config.yaml.

    Args:
        start_path: Directory to start searching from

    Returns:
        Path to config file, or None if not found
    """
    git_root = find_git_root(start_path)
    if git_root is None:
        # Not in a git repo — just check start_path
        config = start_path / ".parts" / "config.yaml"
        return config if config.is_file() else None

    current = start_path.resolve()
    git_root = git_root.resolve()

    while True:
        config = current / ".parts" / "config.yaml"
        if config.is_file():
            return config
        if current == git_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def parse_config(config_path: Path) -> dict[str, Any]:
    """Parse a .parts/config.yaml file.

    Args:
        config_path: Path to the config file

    Returns:
        Parsed config dict
    """
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def resolve_file_paths(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Walk config dict and resolve relative file paths, checking existence.

    Looks for string values that look like file paths (contain '/' or '\\' or
    end with common file extensions) and resolves them relative to project_root.

    Handles directory-context conventions: if a dict has a ``directory`` key,
    its value is used as a prefix when resolving sibling file paths.  Strings
    nested under a ``contents`` key are treated as references to files *inside*
    an archive and are flagged with ``inside_archive: True`` instead of being
    checked on disk.

    Args:
        config: Parsed config dict
        project_root: Root directory to resolve paths against

    Returns:
        Dict mapping config keys to file info with resolved paths and existence
    """
    file_extensions = {
        ".csv", ".xlsx", ".xls", ".json", ".xml", ".yaml", ".yml",
        ".zip", ".kicad_pro", ".kicad_sch", ".kicad_pcb",
        ".gbr", ".drl", ".pos", ".net", ".bom",
    }
    resolved: dict[str, Any] = {}

    def _walk(obj: Any, prefix: str = "", context_dir: str = "", in_contents: bool = False) -> None:
        if isinstance(obj, dict):
            # If this dict has a "directory" key, use it as context for children
            child_context = obj.get("directory", context_dir)
            for key, value in obj.items():
                if key == "directory":
                    continue  # skip the directory key itself
                path_key = f"{prefix}.{key}" if prefix else key
                child_in_contents = in_contents or key == "contents"
                _walk(value, path_key, child_context, child_in_contents)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{prefix}[{i}]", context_dir, in_contents)
        elif isinstance(obj, str):
            path = Path(obj)
            is_path = (
                "/" in obj
                or "\\" in obj
                or path.suffix.lower() in file_extensions
            )
            if is_path:
                if in_contents:
                    resolved[prefix] = {
                        "original": obj,
                        "inside_archive": True,
                        "exists": None,
                    }
                else:
                    base = project_root / context_dir if context_dir else project_root
                    resolved_path = (base / path).resolve() if not path.is_absolute() else path
                    resolved[prefix] = {
                        "original": obj,
                        "resolved": str(resolved_path),
                        "exists": resolved_path.exists(),
                    }

    _walk(config)
    return resolved
