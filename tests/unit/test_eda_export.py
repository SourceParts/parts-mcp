"""
Unit tests for the KiCad export MCP tools (sch_export_bom).

Extracts registered tool functions from a stub FastMCP and calls them
directly to test business logic without running a live MCP server.

The fixtures use real kicad-cli output shape — every field quoted, grouped
references collapsed into one cell ("U3-U6") — because that grouping is what
makes naive parsing of a .kicad_sch go wrong, and it is the reason this tool
exists.
"""
from unittest.mock import MagicMock, patch

import pytest

from parts_mcp.utils.api_client import SourcePartsAPIError


class _CaptureMCP:
    """Stub FastMCP that captures registered tool callables by name."""

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
def export_tools():
    return _tools(local_mode=True)


@pytest.fixture(scope="module")
def hosted_tools():
    return _tools(local_mode=False)


BOM_CSV = (
    '"Reference","Value","Footprint"\n'
    '"U7","FUSB302BMPX","Package_DFN_QFN:WQFN-14"\n'
    '"U3-U6","74AVCH1T45","Package_TO_SOT_SMD:SOT-23-6"\n'
    '"C1,C2","470pF","Capacitor_SMD:C_0603"\n'
)

BOM_TSV = (
    "Reference\tValue\n"
    "U7\tFUSB302BMPX\n"
    "U3-U6\t74AVCH1T45\n"
)


def _client(content=BOM_CSV, filename="bom.csv"):
    client = MagicMock()
    client.upload_file.return_value = {
        "content": content,
        "filename": filename,
        "size_bytes": len(content),
    }
    return client


def _patch(client):
    return patch("parts_mcp.tools.eda_export.get_client", return_value=client)


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_both_inputs_rejected(self, export_tools, tmp_path):
        sch = tmp_path / "a.kicad_sch"
        sch.write_text("(kicad_sch)")
        result = await export_tools["sch_export_bom"](
            schematic_path=str(sch), schematic_content="(kicad_sch)"
        )
        assert result["success"] is False
        assert "only one" in result["error"]

    @pytest.mark.asyncio
    async def test_neither_input_rejected(self, export_tools):
        result = await export_tools["sch_export_bom"]()
        assert result["success"] is False
        assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_file_reported(self, export_tools, tmp_path):
        result = await export_tools["sch_export_bom"](
            schematic_path=str(tmp_path / "nope.kicad_sch")
        )
        assert result["success"] is False
        assert "not found" in result["error"]


class TestHostedMode:
    @pytest.mark.asyncio
    async def test_path_rejected_and_names_the_alternative(self, hosted_tools, tmp_path):
        sch = tmp_path / "a.kicad_sch"
        sch.write_text("(kicad_sch)")
        result = await hosted_tools["sch_export_bom"](schematic_path=str(sch))
        assert result["success"] is False
        assert "schematic_content" in result["error"]

    @pytest.mark.asyncio
    async def test_output_path_rejected(self, hosted_tools, tmp_path):
        result = await hosted_tools["sch_export_bom"](
            schematic_content="(kicad_sch)", output_path=str(tmp_path / "o.csv")
        )
        assert result["success"] is False
        assert "hosted mode" in result["error"]

    @pytest.mark.asyncio
    async def test_inline_content_works(self, hosted_tools):
        client = _client()
        with _patch(client):
            result = await hosted_tools["sch_export_bom"](schematic_content="(kicad_sch)")
        assert result["success"] is True
        assert result["component_count"] == 3
        assert client.upload_file.call_args.kwargs["file_data"] == b"(kicad_sch)"


class TestParsing:
    @pytest.mark.asyncio
    async def test_parses_csv_into_rows(self, export_tools):
        with _patch(_client()):
            result = await export_tools["sch_export_bom"](schematic_content="(kicad_sch)")
        assert result["success"] is True
        assert result["components"][0] == {
            "Reference": "U7",
            "Value": "FUSB302BMPX",
            "Footprint": "Package_DFN_QFN:WQFN-14",
        }

    @pytest.mark.asyncio
    async def test_grouped_reference_cell_not_split(self, export_tools):
        """"C1,C2" holds the delimiter — it must stay one field."""
        with _patch(_client()):
            result = await export_tools["sch_export_bom"](schematic_content="(kicad_sch)")
        refs = [c["Reference"] for c in result["components"]]
        assert "C1,C2" in refs
        assert len(result["components"]) == 3

    @pytest.mark.asyncio
    async def test_parses_tsv_with_tab_delimiter(self, export_tools):
        with _patch(_client(BOM_TSV, "bom.tsv")):
            result = await export_tools["sch_export_bom"](
                schematic_content="(kicad_sch)", format_preset="TSV"
            )
        assert result["component_count"] == 2
        assert result["components"][0]["Value"] == "FUSB302BMPX"

    @pytest.mark.asyncio
    async def test_raw_content_always_returned(self, export_tools):
        with _patch(_client()):
            result = await export_tools["sch_export_bom"](schematic_content="(kicad_sch)")
        assert result["content"] == BOM_CSV

    @pytest.mark.asyncio
    async def test_empty_export_is_not_an_error(self, export_tools):
        with _patch(_client("", "bom.csv")):
            result = await export_tools["sch_export_bom"](schematic_content="(kicad_sch)")
        assert result["success"] is True
        assert result["components"] == []


class TestFormFields:
    async def _fields(self, tools, **kwargs):
        client = _client()
        with _patch(client):
            await tools["sch_export_bom"](schematic_content="(kicad_sch)", **kwargs)
        return client.upload_file.call_args.kwargs["options"]

    @pytest.mark.asyncio
    async def test_sort_desc_sends_sort_asc_false(self, export_tools):
        assert (await self._fields(export_tools, sort_desc=True))["sort_asc"] == "false"

    @pytest.mark.asyncio
    async def test_sort_asc_omitted_by_default(self, export_tools):
        assert "sort_asc" not in await self._fields(export_tools)

    @pytest.mark.asyncio
    async def test_exclude_dnp_omitted_when_false(self, export_tools):
        assert "exclude_dnp" not in await self._fields(export_tools)

    @pytest.mark.asyncio
    async def test_optional_fields_passed_through(self, export_tools):
        fields = await self._fields(
            export_tools, fields="Reference,Value", group_by="Value", sort_field="Reference"
        )
        assert fields["fields"] == "Reference,Value"
        assert fields["group_by"] == "Value"
        assert fields["sort_field"] == "Reference"

    @pytest.mark.asyncio
    async def test_format_preset_normalised(self, export_tools):
        assert (await self._fields(export_tools, format_preset="tsv"))["format_preset"] == "TSV"

    @pytest.mark.asyncio
    async def test_export_timeout_beats_search_default(self, export_tools):
        """A 30s search timeout would abort a large export the server completes."""
        client = _client()
        with _patch(client):
            await export_tools["sch_export_bom"](schematic_content="(kicad_sch)")
        assert client.upload_file.call_args.kwargs["timeout"] == 120


class TestFileHandling:
    @pytest.mark.asyncio
    async def test_reads_from_path(self, export_tools, tmp_path):
        sch = tmp_path / "board.kicad_sch"
        sch.write_text("(kicad_sch)")
        client = _client()
        with _patch(client):
            result = await export_tools["sch_export_bom"](schematic_path=str(sch))
        assert result["success"] is True
        assert client.upload_file.call_args.kwargs["filename"] == "board.kicad_sch"

    @pytest.mark.asyncio
    async def test_output_path_written_and_echoed(self, export_tools, tmp_path):
        out = tmp_path / "nested" / "bom.csv"
        with _patch(_client()):
            result = await export_tools["sch_export_bom"](
                schematic_content="(kicad_sch)", output_path=str(out)
            )
        assert result["output_path"] == str(out)
        assert out.read_text() == BOM_CSV

    @pytest.mark.asyncio
    async def test_output_path_none_when_not_requested(self, export_tools):
        with _patch(_client()):
            result = await export_tools["sch_export_bom"](schematic_content="(kicad_sch)")
        assert result["output_path"] is None


class TestErrors:
    @pytest.mark.asyncio
    async def test_api_error_surfaced(self, export_tools):
        client = MagicMock()
        client.upload_file.side_effect = SourcePartsAPIError("kicad-cli not found")
        with _patch(client):
            result = await export_tools["sch_export_bom"](schematic_content="(kicad_sch)")
        assert result["success"] is False
        assert "kicad-cli not found" in result["error"]

    @pytest.mark.asyncio
    async def test_parse_failure_keeps_content(self, export_tools):
        """The raw export is ground truth; a parse problem must not discard it."""
        client = _client()
        with _patch(client), patch(
            "parts_mcp.tools.eda_export._parse_delimited",
            side_effect=ValueError("bad table"),
        ):
            result = await export_tools["sch_export_bom"](schematic_content="(kicad_sch)")
        assert result["success"] is True
        assert result["parse_error"] == "bad table"
        assert result["content"] == BOM_CSV
        assert result["components"] == []
