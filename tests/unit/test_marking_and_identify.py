"""
Unit tests for search_by_marking and the identify_pcb mode split fix.

Two defects from the gap log (§17) are pinned here:

1. There was no marking→part resolver anywhere in the surface. search_by_marking
   is the new resolver; these tests pin its response shape and its 404 guidance.
2. identify_pcb was registered local-mode only while its consumers
   (check_identification_status, get_identified_item) registered in both modes,
   leaving hosted callers a pipeline with no entry point. It must now register
   in BOTH modes, with only the filesystem argument gated — the same pattern as
   sch_export_bom.
"""
import base64

from unittest.mock import MagicMock, patch

import pytest


class _CaptureMCP:
    """Stub FastMCP that captures registered tool callables by name."""

    def __init__(self):
        self._tools: dict = {}

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn
        return decorator


def _search_tools():
    from parts_mcp.tools.search import register_search_tools
    mcp = _CaptureMCP()
    register_search_tools(mcp)
    return mcp._tools


def _manufacturing_tools(local_mode: bool):
    from parts_mcp.tools.manufacturing import register_manufacturing_tools
    mcp = _CaptureMCP()
    register_manufacturing_tools(mcp, local_mode=local_mode)
    return mcp._tools


@pytest.fixture(scope="module")
def search_tools():
    return _search_tools()


@pytest.fixture(scope="module")
def local_tools():
    return _manufacturing_tools(local_mode=True)


@pytest.fixture(scope="module")
def hosted_tools():
    return _manufacturing_tools(local_mode=False)


# ---------------------------------------------------------------------------
# search_by_marking
# ---------------------------------------------------------------------------

def _marking_client(candidates):
    client = MagicMock()
    client.search_by_marking.return_value = {
        "code": "F407VG",
        "candidates": candidates,
        "counts": {"catalog": 0, "identified": 0, "mpn": len(candidates)},
    }
    return client


class TestSearchByMarking:
    @pytest.mark.asyncio
    async def test_candidates_pass_through_with_match_lane(self, search_tools):
        client = _marking_client([
            {"match": "mpn", "sku": "SP-1", "part_number": "STM32F407VGT6"}
        ])
        with patch("parts_mcp.tools.search.get_client", return_value=client):
            result = await search_tools["search_by_marking"](code="F407VG")

        assert result["success"] is True
        assert result["total_candidates"] == 1
        assert result["candidates"][0]["match"] == "mpn"
        client.search_by_marking.assert_called_once_with(code="F407VG", limit=10)

    @pytest.mark.asyncio
    async def test_404_names_identify_pcb_as_the_way_forward(self, search_tools):
        from parts_mcp.utils.api_client import SourcePartsAPIError

        client = MagicMock()
        client.search_by_marking.side_effect = SourcePartsAPIError(
            "API error 404: no candidates"
        )
        with patch("parts_mcp.tools.search.get_client", return_value=client):
            result = await search_tools["search_by_marking"](code="UADD")

        assert result["success"] is False
        assert result["candidates"] == []
        assert "identify_pcb" in result["message"]


# ---------------------------------------------------------------------------
# identify_pcb — mode split
# ---------------------------------------------------------------------------

class TestIdentifyPcbRegistration:
    def test_registered_in_hosted_mode(self, hosted_tools):
        """The §17 defect: the job creator was invisible exactly where its
        pollers were visible. It must register in both modes."""
        assert "identify_pcb" in hosted_tools

    def test_registered_in_local_mode(self, local_tools):
        assert "identify_pcb" in local_tools

    def test_pollers_and_creator_travel_together(self, hosted_tools):
        for name in ("identify_pcb", "check_identification_status", "get_identified_item"):
            assert name in hosted_tools, f"{name} missing from hosted surface"


class TestIdentifyPcbInputs:
    @pytest.mark.asyncio
    async def test_both_inputs_rejected(self, local_tools, tmp_path):
        img = tmp_path / "a.jpg"
        img.write_bytes(b"\xff\xd8jpeg")
        result = await local_tools["identify_pcb"](
            file_path=str(img), image_base64="aGk="
        )
        assert result["success"] is False
        assert "only one" in result["error"]

    @pytest.mark.asyncio
    async def test_neither_input_rejected(self, local_tools):
        result = await local_tools["identify_pcb"]()
        assert result["success"] is False
        assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_hosted_path_rejected_and_names_the_alternative(
        self, hosted_tools, tmp_path
    ):
        img = tmp_path / "a.jpg"
        img.write_bytes(b"\xff\xd8jpeg")
        result = await hosted_tools["identify_pcb"](file_path=str(img))
        assert result["success"] is False
        assert "image_base64" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_base64_reported(self, hosted_tools):
        result = await hosted_tools["identify_pcb"](image_base64="not@base64!!")
        assert result["success"] is False
        assert "base64" in result["error"]

    @pytest.mark.asyncio
    async def test_bad_extension_via_filename_rejected(self, hosted_tools):
        payload = base64.b64encode(b"\xff\xd8jpeg").decode()
        result = await hosted_tools["identify_pcb"](
            image_base64=payload, filename="photo.tiff"
        )
        assert result["success"] is False
        assert "Unsupported image format" in result["error"]


class TestIdentifyPcbUpload:
    @pytest.mark.asyncio
    async def test_hosted_base64_uploads_decoded_bytes(self, hosted_tools):
        raw = b"\xff\xd8\xff\xe0fakejpeg"
        payload = base64.b64encode(raw).decode()
        client = MagicMock()
        client.upload_for_identification.return_value = {"job_id": "job-1"}

        with patch("parts_mcp.tools.manufacturing.get_client", return_value=client):
            result = await hosted_tools["identify_pcb"](image_base64=payload)

        assert result["success"] is True
        kwargs = client.upload_for_identification.call_args.kwargs
        assert kwargs["file_data"] == raw
        assert kwargs["filename"] == "photo.jpg"
        assert kwargs["content_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_local_file_path_still_works(self, local_tools, tmp_path):
        raw = b"\x89PNG\r\n\x1a\nfakepng"
        img = tmp_path / "board.png"
        img.write_bytes(raw)
        client = MagicMock()
        client.upload_for_identification.return_value = {"job_id": "job-2"}

        with patch("parts_mcp.tools.manufacturing.get_client", return_value=client):
            result = await local_tools["identify_pcb"](file_path=str(img))

        assert result["success"] is True
        kwargs = client.upload_for_identification.call_args.kwargs
        assert kwargs["file_data"] == raw
        assert kwargs["filename"] == "board.png"
        assert kwargs["content_type"] == "image/png"
