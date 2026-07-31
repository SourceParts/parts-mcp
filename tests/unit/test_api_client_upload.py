"""
Unit tests for SourcePartsClient's public upload surface.

upload_file / upload_files / upload_file_raw are called from
parts_mcp.tools.kicad_ctrl but had no implementation, so all seven
kicad_ctrl_* tools raised AttributeError into a bare except and returned an
error dict on every invocation. These tests pin the call shapes those sites
use — particularly the `options=` keyword, which is not `form_fields=`.
"""
from unittest.mock import MagicMock, patch

import pytest

from parts_mcp.config import SEARCH_TIMEOUT
from parts_mcp.utils.api_client import SourcePartsClient


@pytest.fixture
def client():
    c = SourcePartsClient(api_key="test-key")
    c._rate_limit = MagicMock()
    return c


def _response(payload=None, content=b"", status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload if payload is not None else {"status": "success", "data": {}}
    r.content = content
    r.raise_for_status.return_value = None
    return r


class TestUploadFile:
    def test_sends_single_file_under_field_name_file(self, client):
        with patch("httpx.request", return_value=_response()) as req:
            client.upload_file("eda/drc", file_data=b"pcb", filename="b.kicad_pcb")
        assert list(req.call_args.kwargs["files"]) == ["file"]
        assert req.call_args.kwargs["files"]["file"][0] == "b.kicad_pcb"

    def test_options_becomes_form_fields(self, client):
        """The call sites spell it `options=`; it must reach the multipart body."""
        with patch("httpx.request", return_value=_response()) as req:
            client.upload_file(
                "eda/analyze",
                file_data=b"pcb",
                filename="b.kicad_pcb",
                options={"net_names_json": "[]"},
            )
        assert req.call_args.kwargs["data"] == {"net_names_json": "[]"}

    def test_unwraps_success_envelope(self, client):
        payload = {"status": "success", "data": {"error_count": 0}}
        with patch("httpx.request", return_value=_response(payload)):
            result = client.upload_file("eda/drc", file_data=b"x", filename="b.kicad_pcb")
        assert result == {"error_count": 0}

    def test_default_timeout_is_search_timeout(self, client):
        with patch("httpx.request", return_value=_response()) as req:
            client.upload_file("eda/drc", file_data=b"x", filename="b.kicad_pcb")
        assert req.call_args.kwargs["timeout"] == SEARCH_TIMEOUT

    def test_timeout_override_honoured(self, client):
        with patch("httpx.request", return_value=_response()) as req:
            client.upload_file(
                "eda/sch/export/bom", file_data=b"x", filename="a.kicad_sch", timeout=120
            )
        assert req.call_args.kwargs["timeout"] == 120

    def test_content_type_passed_through(self, client):
        with patch("httpx.request", return_value=_response()) as req:
            client.upload_file(
                "eda/erc", file_data=b"x", filename="a.kicad_sch", content_type="text/plain"
            )
        assert req.call_args.kwargs["files"]["file"][2] == "text/plain"


class TestUploadFiles:
    def test_sends_every_field(self, client):
        """/v1/eda/netlist/diff reads old_file and new_file, not 'file'."""
        files = {
            "old_file": ("old.kicad_sch", b"old", "application/octet-stream"),
            "new_file": ("new.kicad_sch", b"new", "application/octet-stream"),
        }
        with patch("httpx.request", return_value=_response()) as req:
            client.upload_files("eda/netlist/diff", files=files)
        sent = req.call_args.kwargs["files"]
        assert set(sent) == {"old_file", "new_file"}
        assert sent["new_file"][1] == b"new"

    def test_unwraps_success_envelope(self, client):
        payload = {"status": "success", "data": {"nets": {}}}
        with patch("httpx.request", return_value=_response(payload)):
            result = client.upload_files("eda/netlist/diff", files={})
        assert result == {"nets": {}}


class TestUploadFileRaw:
    def test_returns_bytes_not_dict(self, client):
        """/v1/eda/export answers with a ZIP, so the body must not be parsed."""
        with patch("httpx.request", return_value=_response(content=b"PK\x03\x04zip")):
            result = client.upload_file_raw(
                "eda/export", file_data=b"pcb", filename="b.kicad_pcb"
            )
        assert result == b"PK\x03\x04zip"

    def test_default_timeout_suits_long_conversions(self, client):
        with patch("httpx.request", return_value=_response(content=b"z")) as req:
            client.upload_file_raw("eda/export", file_data=b"x", filename="b.kicad_pcb")
        assert req.call_args.kwargs["timeout"] == 300

    def test_options_becomes_form_data(self, client):
        with patch("httpx.request", return_value=_response(content=b"z")) as req:
            client.upload_file_raw(
                "eda/export", file_data=b"x", filename="b.kicad_pcb", options={"layers": "F.Cu"}
            )
        assert req.call_args.kwargs["data"] == {"layers": "F.Cu"}


class TestCallSiteCompatibility:
    """Every shape kicad_ctrl.py actually uses must bind without TypeError."""

    @pytest.mark.parametrize(
        "method,kwargs",
        [
            ("upload_file", {"file_data": b"x", "filename": "f",
                             "content_type": "application/octet-stream"}),
            ("upload_file", {"file_data": b"x", "filename": "f",
                             "content_type": "application/octet-stream",
                             "options": {"net_names_json": "[]"}}),
            ("upload_file_raw", {"file_data": b"x", "filename": "f",
                                 "content_type": "application/octet-stream"}),
        ],
    )
    def test_binds(self, client, method, kwargs):
        with patch("httpx.request", return_value=_response(content=b"z")):
            getattr(client, method)("eda/erc", **kwargs)

    def test_upload_files_binds(self, client):
        with patch("httpx.request", return_value=_response()):
            client.upload_files(
                "eda/netlist/diff",
                files={"old_file": ("o", b"o", "application/octet-stream")},
            )
