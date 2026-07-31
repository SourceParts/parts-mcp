#!/usr/bin/env python3
"""Prove test_client_attribute_coverage is not vacuous.

A guard that passes against both the broken and the fixed tree tests nothing.
This re-runs its scan against the committed (pre-fix) SourcePartsClient and
asserts it *would* have flagged kicad_ctrl.py, then confirms the current tree
is clean.

Usage:  python3 scripts/verify_attribute_guard.py
"""

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.unit.test_client_attribute_coverage import (  # noqa: E402
    TOOL_MODULES,
    _called_client_methods,
)


def committed_client_methods() -> set[str]:
    """Method names on SourcePartsClient as of git HEAD."""
    src = subprocess.run(
        ["git", "-C", str(REPO), "show", "HEAD:parts_mcp/utils/api_client.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    tree = ast.parse(src)
    cls = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "SourcePartsClient"
    )
    return {
        n.name for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def main() -> int:
    before = committed_client_methods()

    would_flag = {}
    for module in TOOL_MODULES:
        missing = sorted(n for n in _called_client_methods(module) if n not in before)
        if missing:
            would_flag[module.name] = missing

    print("Against committed HEAD, the guard would flag:")
    for name, missing in sorted(would_flag.items()):
        print(f"  {name}: {missing}")

    if "kicad_ctrl.py" not in would_flag:
        print("\nFAIL: guard would not have caught the kicad_ctrl breakage")
        return 1

    expected = {"upload_file", "upload_files", "upload_file_raw"}
    got = set(would_flag["kicad_ctrl.py"])
    if got != expected:
        print(f"\nFAIL: expected {sorted(expected)}, got {sorted(got)}")
        return 1

    print("\nOK: guard catches the real defect, and the current tree is clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
