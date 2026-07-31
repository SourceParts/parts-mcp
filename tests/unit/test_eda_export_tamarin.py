"""
Acceptance test for sch_export_bom against a real KiCad schematic.

This pins the exact failure the tool was built to prevent. Reading Tamarin C's
schematic with a hand-rolled regex parser reported two FUSB302 port controllers
and two R5524s, because a .kicad_sch begins with a lib_symbols block of symbol
*definitions* whose Reference fields are the unnumbered defaults "U", "J", "R",
"C". Counting those as placed components invents parts the board does not have,
and an architectural explanation was then built on the phantom.

The board has exactly one FUSB302 (U7), one R5524 (U1), four 74AVCH1T45
(U3-U6) and a Pico (U2) — 22 components, 11 non-passive.

Ground truth comes from kicad-cli itself, which is what the server runs, so this
skips rather than fails where kicad-cli or the fixture is unavailable.
"""
import asyncio
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "tamarin-c.kicad_sch"

pytestmark = [
    pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli not installed"),
    pytest.mark.skipif(not FIXTURE.exists(), reason=f"fixture missing: {FIXTURE}"),
]


class _CaptureMCP:
    def __init__(self):
        self._tools: dict = {}

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn
        return decorator


@pytest.fixture(scope="module")
def real_bom_csv(tmp_path_factory):
    """Run the same kicad-cli invocation the API's handler builds."""
    out = tmp_path_factory.mktemp("bom") / "bom.csv"
    subprocess.run(
        ["kicad-cli", "sch", "export", "bom",
         "--fields", "Reference,Value,Footprint",
         "--group-by", "Value",
         "--output", str(out), str(FIXTURE)],
        check=True, capture_output=True,
    )
    return out.read_text()


@pytest.fixture(scope="module")
def tool():
    from parts_mcp.tools.eda_export import register_eda_export_tools
    mcp = _CaptureMCP()
    register_eda_export_tools(mcp, local_mode=True)
    return mcp._tools["sch_export_bom"]


@pytest.fixture(scope="module")
def result(tool, real_bom_csv):
    """Resolve the coroutine once; the assertions below are plain sync checks."""
    client = MagicMock()
    client.upload_file.return_value = {
        "content": real_bom_csv,
        "filename": "bom.csv",
        "size_bytes": len(real_bom_csv),
    }
    with patch("parts_mcp.tools.eda_export.get_client", return_value=client):
        return asyncio.run(
            tool(
                schematic_path=str(FIXTURE),
                fields="Reference,Value,Footprint",
                group_by="Value",
            )
        )


def _values(result):
    return [c["Value"] for c in result["components"]]


class TestTamarinC:
    def test_exactly_one_fusb302(self, result):
        """The phantom second controller is the whole reason this test exists."""
        assert _values(result).count("FUSB302BMPX") == 1

    def test_exactly_one_r5524(self, result):
        assert _values(result).count("R5524") == 1

    def test_pico_is_a_placed_component(self, result):
        """U2 was shadowed by a lib_symbols definition in the broken parser."""
        assert "Pico" in _values(result)

    def test_four_level_shifters_in_one_grouped_row(self, result):
        """All four shifters group into a single row.

        The cell spelling is version-dependent — local kicad-cli 9.0.9 collapses
        to the range "U3-U6" while the deployed server returns "U3,U4,U5,U6" —
        so assert coverage, not the delimiter.
        """
        rows = [c for c in result["components"] if c["Value"] == "74AVCH1T45"]
        assert len(rows) == 1
        ref = rows[0]["Reference"]
        assert ref.startswith("U3") and ref.endswith("U6")

    def test_no_unnumbered_default_references(self, result):
        """"U", "J", "R", "C" are definition defaults, never placed parts."""
        refs = {c["Reference"] for c in result["components"]}
        assert not refs & {"U", "J", "R", "C"}

    def test_every_reference_carries_a_number(self, result):
        for c in result["components"]:
            assert any(ch.isdigit() for ch in c["Reference"]), c["Reference"]

    def test_footprints_survive_the_colon_in_the_value(self, result):
        """Footprints are "Lib:Name" — a naive split would truncate them."""
        u7 = next(c for c in result["components"] if c["Value"] == "FUSB302BMPX")
        assert u7["Footprint"].startswith("Package_DFN_QFN:")
