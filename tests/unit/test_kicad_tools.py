"""
Unit tests for the KiCad MCP tools (convert_allegro et al.).

Extracts registered tool functions from a stub FastMCP and calls them
directly to test business logic without running a live MCP server.
"""
import zipfile
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from parts_mcp.utils.api_client import SourcePartsAPIError


# ---------------------------------------------------------------------------
# Minimal FastMCP stub — captures @mcp.tool() registrations
# ---------------------------------------------------------------------------

class _CaptureMCP:
    """Stub FastMCP that captures registered tool callables by name."""

    def __init__(self):
        self._tools: dict = {}

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn
        return decorator


@pytest.fixture(scope="module")
def kicad_tools():
    """Register all kicad tools into a stub MCP and return the tool map."""
    from parts_mcp.tools.kicad import register_kicad_tools
    mcp = _CaptureMCP()
    register_kicad_tools(mcp)
    return mcp._tools


def _make_zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("board.kicad_pcb", b"(kicad_pcb)")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# convert_allegro tool
# ---------------------------------------------------------------------------

class TestConvertAllegroTool:
    """Tests for the convert_allegro MCP tool."""

    @pytest.mark.asyncio
    async def test_file_not_found(self, kicad_tools):
        """Returns error dict when the source file does not exist."""
        fn = kicad_tools["convert_allegro"]
        result = await fn("/nonexistent/path/board.brd")
        assert result["success"] is False
        assert "File not found" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_extension(self, kicad_tools, tmp_path):
        """Returns error dict for unsupported file extensions."""
        bad_file = tmp_path / "board.txt"
        bad_file.write_bytes(b"not a brd file")
        fn = kicad_tools["convert_allegro"]
        result = await fn(str(bad_file))
        assert result["success"] is False
        assert ".txt" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_conversion_default_output(self, kicad_tools, tmp_path):
        """Successful conversion writes <stem>_kicad.zip next to the input."""
        brd_file = tmp_path / "board.brd"
        brd_file.write_bytes(b"fake allegro data")
        fake_zip = _make_zip_bytes()

        mock_client = MagicMock()
        mock_client.convert_allegro.return_value = fake_zip

        fn = kicad_tools["convert_allegro"]
        with patch("parts_mcp.tools.kicad.get_client", return_value=mock_client):
            result = await fn(str(brd_file))

        assert result["success"] is True
        assert result["output_path"].endswith("board_kicad.zip")
        assert result["output_size_bytes"] == len(fake_zip)
        assert result["source_file"] == str(brd_file)
        # Output file must be written to disk
        assert Path(result["output_path"]).read_bytes() == fake_zip

    @pytest.mark.asyncio
    async def test_successful_conversion_custom_output(self, kicad_tools, tmp_path):
        """Conversion respects an explicit output_path argument."""
        brd_file = tmp_path / "design.brd"
        brd_file.write_bytes(b"fake allegro data")
        custom_out = str(tmp_path / "output.zip")
        fake_zip = _make_zip_bytes()

        mock_client = MagicMock()
        mock_client.convert_allegro.return_value = fake_zip

        fn = kicad_tools["convert_allegro"]
        with patch("parts_mcp.tools.kicad.get_client", return_value=mock_client):
            result = await fn(str(brd_file), output_path=custom_out)

        assert result["success"] is True
        assert result["output_path"] == custom_out
        assert Path(custom_out).read_bytes() == fake_zip

    @pytest.mark.asyncio
    async def test_api_error_propagates(self, kicad_tools, tmp_path):
        """SourcePartsAPIError from the client surfaces as error dict."""
        brd_file = tmp_path / "board.brd"
        brd_file.write_bytes(b"fake allegro data")

        mock_client = MagicMock()
        mock_client.convert_allegro.side_effect = SourcePartsAPIError("Allegro conversion failed (503): pcbnew unavailable")

        fn = kicad_tools["convert_allegro"]
        with patch("parts_mcp.tools.kicad.get_client", return_value=mock_client):
            result = await fn(str(brd_file))

        assert result["success"] is False
        assert "Allegro conversion failed" in result["error"]

    @pytest.mark.asyncio
    async def test_zip_input_accepted(self, kicad_tools, tmp_path):
        """A .zip containing .brd files is a valid input."""
        zip_file = tmp_path / "boards.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("board.brd", b"fake allegro data")
        zip_file.write_bytes(buf.getvalue())

        fake_zip = _make_zip_bytes()
        mock_client = MagicMock()
        mock_client.convert_allegro.return_value = fake_zip

        fn = kicad_tools["convert_allegro"]
        with patch("parts_mcp.tools.kicad.get_client", return_value=mock_client):
            result = await fn(str(zip_file))

        assert result["success"] is True
        # Client was called with the raw zip bytes
        call_kwargs = mock_client.convert_allegro.call_args
        assert call_kwargs.kwargs["filename"] == "boards.zip"

    @pytest.mark.asyncio
    async def test_client_receives_correct_filename(self, kicad_tools, tmp_path):
        """The original filename is forwarded to the API client."""
        brd_file = tmp_path / "my_design_rev3.brd"
        brd_file.write_bytes(b"fake allegro data")

        mock_client = MagicMock()
        mock_client.convert_allegro.return_value = _make_zip_bytes()

        fn = kicad_tools["convert_allegro"]
        with patch("parts_mcp.tools.kicad.get_client", return_value=mock_client):
            await fn(str(brd_file))

        call_kwargs = mock_client.convert_allegro.call_args
        assert call_kwargs.kwargs["filename"] == "my_design_rev3.brd"
