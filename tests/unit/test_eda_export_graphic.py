"""
Unit tests for sch_export_graphic (pdf / dxf / hpgl / ps).

These endpoints differ from the BOM one in two ways that are easy to get wrong:
they answer with base64 under `file_base64` rather than text under `content`,
and everything except pdf plots one file per page, so the server returns a ZIP
whatever the nominal format was.

That last point was got wrong here first: dxf was assumed to be a single file
by both this module and the API handler, which made the route answer HTTP 500
("[Errno 21] Is a directory") until a live call exposed it. `kicad-cli sch
export dxf --output <path>` creates a *directory* at that path.
"""
import base64
from unittest.mock import MagicMock, patch

import pytest

from parts_mcp.utils.api_client import SourcePartsAPIError

PDF = b"%PDF-1.4 fake"
ZIP = b"PK\x03\x04fake"


class _CaptureMCP:
    def __init__(self):
        self._tools: dict = {}

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn
        return decorator


def _tools(local_mode: bool = True):
    from parts_mcp.tools.eda_export import register_eda_export_tools
    mcp = _CaptureMCP()
    register_eda_export_tools(mcp, local_mode=local_mode)
    return mcp._tools


@pytest.fixture(scope="module")
def tool():
    return _tools(True)["sch_export_graphic"]


@pytest.fixture(scope="module")
def hosted_tool():
    return _tools(False)["sch_export_graphic"]


def _client(payload=PDF, filename="schematic.pdf"):
    client = MagicMock()
    client.upload_file.return_value = {
        "file_base64": base64.b64encode(payload).decode(),
        "filename": filename,
        "size_bytes": len(payload),
    }
    return client


def _patch(client):
    return patch("parts_mcp.tools.eda_export.get_client", return_value=client)


class TestFormatValidation:
    @pytest.mark.asyncio
    async def test_unknown_format_rejected(self, tool):
        result = await tool(format="svg", schematic_content="(kicad_sch)")
        assert result["success"] is False
        assert "svg" in result["error"]

    @pytest.mark.asyncio
    async def test_bom_redirected_to_the_right_tool(self, tool):
        """bom is not a plot format — the message must say where to go."""
        result = await tool(format="bom", schematic_content="(kicad_sch)")
        assert result["success"] is False
        assert "sch_export_bom" in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fmt", ["pdf", "dxf", "hpgl", "ps"])
    async def test_each_format_hits_its_own_route(self, tool, fmt):
        client = _client()
        with _patch(client):
            await tool(format=fmt, schematic_content="(kicad_sch)")
        assert client.upload_file.call_args.args[0] == f"eda/sch/export/{fmt}"

    @pytest.mark.asyncio
    async def test_format_is_case_insensitive(self, tool):
        client = _client()
        with _patch(client):
            result = await tool(format="  PDF ", schematic_content="(kicad_sch)")
        assert result["success"] is True
        assert client.upload_file.call_args.args[0] == "eda/sch/export/pdf"


class TestBinaryHandling:
    @pytest.mark.asyncio
    async def test_base64_decoded_to_disk(self, tool, tmp_path):
        out = tmp_path / "out.pdf"
        with _patch(_client()):
            result = await tool(
                format="pdf", schematic_content="(kicad_sch)", output_path=str(out)
            )
        assert out.read_bytes() == PDF
        assert result["output_path"] == str(out)

    @pytest.mark.asyncio
    async def test_no_base64_returned_when_written(self, tool, tmp_path):
        with _patch(_client()):
            result = await tool(
                format="pdf",
                schematic_content="(kicad_sch)",
                output_path=str(tmp_path / "o.pdf"),
            )
        assert "content_base64" not in result

    @pytest.mark.asyncio
    async def test_defaults_output_beside_the_schematic(self, tool, tmp_path):
        sch = tmp_path / "board.kicad_sch"
        sch.write_text("(kicad_sch)")
        with _patch(_client()):
            result = await tool(format="pdf", schematic_path=str(sch))
        assert result["output_path"] == str(tmp_path / "board.pdf")
        assert (tmp_path / "board.pdf").read_bytes() == PDF


class TestArchiveFormats:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("fmt", ["dxf", "hpgl", "ps"])
    async def test_per_page_formats_flagged_as_archive(self, tool, fmt):
        """Verified against kicad-cli: only pdf is a single file."""
        with _patch(_client(ZIP, "schematic.zip")):
            result = await tool(format=fmt, schematic_content="(kicad_sch)")
        assert result["is_archive"] is True

    @pytest.mark.asyncio
    async def test_pdf_not_an_archive(self, tool):
        with _patch(_client()):
            result = await tool(format="pdf", schematic_content="(kicad_sch)")
        assert result["is_archive"] is False

    @pytest.mark.asyncio
    async def test_server_zip_overrides_the_table(self, tool):
        """If the server zips a pdf, believe the server, not our lookup."""
        with _patch(_client(ZIP, "schematic.zip")):
            result = await tool(format="pdf", schematic_content="(kicad_sch)")
        assert result["is_archive"] is True

    @pytest.mark.asyncio
    async def test_archive_extension_used_for_default_path(self, tool, tmp_path):
        sch = tmp_path / "board.kicad_sch"
        sch.write_text("(kicad_sch)")
        with _patch(_client(ZIP, "schematic.zip")):
            result = await tool(format="ps", schematic_path=str(sch))
        assert result["output_path"].endswith(".zip")


class TestFormFields:
    async def _fields(self, tool, **kwargs):
        client = _client()
        with _patch(client):
            await tool(schematic_content="(kicad_sch)", **kwargs)
        return client.upload_file.call_args.kwargs["options"]

    @pytest.mark.asyncio
    async def test_black_and_white_sent_when_set(self, tool):
        assert (await self._fields(tool, format="pdf", black_and_white=True))[
            "black_and_white"
        ] == "true"

    @pytest.mark.asyncio
    async def test_black_and_white_omitted_by_default(self, tool):
        assert "black_and_white" not in await self._fields(tool, format="pdf")

    @pytest.mark.asyncio
    async def test_pages_passed_through(self, tool):
        assert (await self._fields(tool, format="pdf", pages="1,3"))["pages"] == "1,3"

    @pytest.mark.asyncio
    async def test_pen_size_only_for_hpgl(self, tool):
        """The pdf handler does not read pen_size; sending it would be noise."""
        assert "pen_size" not in await self._fields(tool, format="pdf", pen_size="0.3")
        assert (await self._fields(tool, format="hpgl", pen_size="0.3"))["pen_size"] == "0.3"

    @pytest.mark.asyncio
    async def test_export_timeout_applied(self, tool):
        client = _client()
        with _patch(client):
            await tool(format="pdf", schematic_content="(kicad_sch)")
        assert client.upload_file.call_args.kwargs["timeout"] == 120


class TestHostedMode:
    @pytest.mark.asyncio
    async def test_returns_base64_with_no_filesystem(self, hosted_tool):
        with _patch(_client()):
            result = await hosted_tool(format="pdf", schematic_content="(kicad_sch)")
        assert result["success"] is True
        assert result["output_path"] is None
        assert base64.b64decode(result["content_base64"]) == PDF

    @pytest.mark.asyncio
    async def test_path_rejected(self, hosted_tool, tmp_path):
        sch = tmp_path / "a.kicad_sch"
        sch.write_text("(kicad_sch)")
        result = await hosted_tool(format="pdf", schematic_path=str(sch))
        assert result["success"] is False
        assert "schematic_content" in result["error"]


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_neither_input_rejected(self, tool):
        result = await tool(format="pdf")
        assert result["success"] is False
        assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_both_inputs_rejected(self, tool, tmp_path):
        sch = tmp_path / "a.kicad_sch"
        sch.write_text("(kicad_sch)")
        result = await tool(
            format="pdf", schematic_path=str(sch), schematic_content="(kicad_sch)"
        )
        assert result["success"] is False
        assert "only one" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_file_reported(self, tool, tmp_path):
        result = await tool(format="pdf", schematic_path=str(tmp_path / "nope.kicad_sch"))
        assert result["success"] is False
        assert "not found" in result["error"]


class TestErrors:
    @pytest.mark.asyncio
    async def test_api_error_surfaced(self, tool):
        client = MagicMock()
        client.upload_file.side_effect = SourcePartsAPIError("kicad-cli not found")
        with _patch(client):
            result = await tool(format="pdf", schematic_content="(kicad_sch)")
        assert result["success"] is False
        assert "kicad-cli not found" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_payload_does_not_crash(self, tool):
        client = MagicMock()
        client.upload_file.return_value = {"filename": "schematic.pdf", "size_bytes": 0}
        with _patch(client):
            result = await tool(format="pdf", schematic_content="(kicad_sch)")
        assert result["success"] is True
        assert result["size_bytes"] == 0
