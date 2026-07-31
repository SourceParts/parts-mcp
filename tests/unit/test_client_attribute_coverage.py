"""
Guard: every client method a tool module calls must exist on SourcePartsClient.

kicad_ctrl.py called upload_file, upload_files and upload_file_raw, none of
which were defined. Each call raised AttributeError straight into a bare
`except Exception`, so all seven kicad_ctrl_* tools returned an error dict on
every invocation and nothing failed loudly enough to notice.

A static scan catches that class of rot without needing the network or a live
API key, which is why it lives here rather than in an integration test.
"""
import ast
from pathlib import Path

import pytest

from parts_mcp.utils.api_client import SourcePartsClient

TOOLS_DIR = Path(__file__).parent.parent.parent / "parts_mcp" / "tools"


def _called_client_methods(path: Path) -> set[str]:
    """Names invoked as client.<name>(...) or self.client.<name>(...)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        obj = func.value
        if isinstance(obj, ast.Name) and obj.id == "client":
            found.add(func.attr)
        elif (
            isinstance(obj, ast.Attribute)
            and obj.attr == "client"
            and isinstance(obj.value, ast.Name)
            and obj.value.id == "self"
        ):
            found.add(func.attr)
    return found


TOOL_MODULES = sorted(p for p in TOOLS_DIR.glob("*.py") if p.name != "__init__.py")


@pytest.mark.parametrize("module", TOOL_MODULES, ids=lambda p: p.name)
def test_every_called_client_method_exists(module):
    missing = sorted(
        name for name in _called_client_methods(module)
        if not hasattr(SourcePartsClient, name)
    )
    assert not missing, (
        f"{module.name} calls client methods that do not exist: {missing}"
    )
