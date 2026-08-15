#!/usr/bin/env python3
"""End-to-end check of sch_export_bom's real HTTP path, without credentials.

The unit tests mock get_client, so they assert what the tool *intends* to send
and never exercise _make_upload_request itself. This runs the genuine client
against a throwaway local server and inspects the request that actually arrives:
the multipart field name, the form fields, and the envelope unwrapping.

What it does not cover: authentication and the real endpoint's behaviour. Those
are verified separately through the public CLI, which carries its own auth.

Usage:  python3 scripts/verify_sch_export_wire.py
"""

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

BOM = (
    '"Reference","Value"\n'
    '"U7","FUSB302BMPX"\n'
    '"U3,U4,U5,U6","74AVCH1T45"\n'
)

received: dict = {}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received["path"] = self.path
        received["body"] = body
        received["content_type"] = self.headers.get("Content-Type", "")
        received["auth"] = self.headers.get("Authorization", "")
        payload = json.dumps({
            "status": "success",
            "data": {"content": BOM, "filename": "bom.csv", "size_bytes": len(BOM)},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    import os
    os.environ["SOURCE_PARTS_API_URL"] = f"http://127.0.0.1:{port}/v1/"
    os.environ.setdefault("SOURCE_PARTS_API_KEY", "wire-test-key")

    from parts_mcp.tools.eda_export import register_eda_export_tools

    class _CaptureMCP:
        def __init__(self):
            self._tools = {}

        def tool(self):
            def deco(fn):
                self._tools[fn.__name__] = fn
                return fn
            return deco

    mcp = _CaptureMCP()
    register_eda_export_tools(mcp, local_mode=True)

    result = asyncio.run(mcp._tools["sch_export_bom"](
        schematic_content="(kicad_sch)",
        fields="Reference,Value",
        group_by="Value",
        sort_desc=True,
        exclude_dnp=True,
    ))
    server.shutdown()

    failures = []

    def check(name, cond, detail=""):
        print(f"  {'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
        if not cond:
            failures.append(name)

    body = received.get("body", b"")
    print(f"request: POST {received.get('path')}\n")

    check("hits the bom export route", received.get("path") == "/v1/eda/sch/export/bom",
          str(received.get("path")))
    check("sends multipart", received.get("content_type", "").startswith("multipart/form-data"))
    check("file is under field name 'file'", b'name="file"' in body)
    check("schematic bytes present", b"(kicad_sch)" in body)
    check("sends Authorization header", received.get("auth", "").startswith("Bearer "))

    check("form field fields", b'name="fields"' in body and b"Reference,Value" in body)
    check("form field group_by", b'name="group_by"' in body)
    check("sort_desc becomes sort_asc=false",
          b'name="sort_asc"' in body and b"false" in body)
    check("exclude_dnp sent", b'name="exclude_dnp"' in body)
    check("format_preset sent", b'name="format_preset"' in body)

    check("envelope unwrapped", result.get("success") is True, str(result.get("error", "")))
    check("components parsed", result.get("component_count") == 2,
          str(result.get("component_count")))
    check("one FUSB302",
          [c["Value"] for c in result.get("components", [])].count("FUSB302BMPX") == 1)
    check("raw content preserved", result.get("content") == BOM)

    print(f"\n{len(failures)} failure(s)" if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
