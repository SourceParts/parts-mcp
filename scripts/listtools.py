"""List every MCP tool the server registers, by module.

Static AST scan: finds async functions decorated with @mcp.tool() inside each
tools module, and notes whether the registration sits under an `if local_mode:`
block (best-effort: checks enclosing If nodes' source segment).

Usage: python scripts/listtools.py
"""
import ast
import pathlib

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1] / "parts_mcp" / "tools"


def tool_names(path: pathlib.Path) -> list[tuple[str, bool]]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    found: list[tuple[str, bool]] = []

    def walk(node, in_local: bool):
        for child in ast.iter_child_nodes(node):
            local = in_local
            if isinstance(child, ast.If):
                test_src = ast.get_source_segment(src, child.test) or ""
                if "local_mode" in test_src:
                    local = True
            if isinstance(child, (ast.AsyncFunctionDef, ast.FunctionDef)):
                for dec in child.decorator_list:
                    d = ast.get_source_segment(src, dec) or ""
                    if d.startswith("mcp.tool"):
                        found.append((child.name, local))
                        break
            walk(child, local)

    walk(tree, False)
    return found


def main():
    total = 0
    for path in sorted(TOOLS_DIR.glob("*.py")):
        names = tool_names(path)
        if not names:
            continue
        total += len(names)
        print(f"\n{path.stem} ({len(names)}):")
        for name, local in names:
            print(f"  {name}{'  [local-mode only]' if local else ''}")
    print(f"\nTOTAL: {total}")


if __name__ == "__main__":
    main()
