"""
Unit tests for MPN match verification (field-test report 2026-08-08).

The report's core defect class: search_parts is fuzzy, and every tool that
took its top hit silently acted on it — 13/26 BOM rows matched a different
component, compare_prices priced a 10uH inductor as a $3.24 tactile switch,
and pricing 404s hard-errored. These tests pin the fixes:

  - verify_mpn_match strictness (real wrong-match pairs from the report)
  - search_parts annotates match_verified + warns on fuzzy top hits
  - compare_prices refuses to price a fuzzy match, degrades pricing 404s to
    "no pricing data", and warns that `suppliers` is not honored
  - calculate_bom_cost reports fuzzy lines as errors instead of costing them
"""
from unittest.mock import MagicMock, patch

import pytest

from parts_mcp.utils.api_client import SourcePartsAPIError
from parts_mcp.utils.matching import (
    describe_candidate,
    normalize_mpn,
    verify_mpn_match,
)


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
def sourcing_tools():
    from parts_mcp.tools.sourcing import register_sourcing_tools
    mcp = _CaptureMCP()
    register_sourcing_tools(mcp)
    return mcp._tools


@pytest.fixture(scope="module")
def search_tools():
    from parts_mcp.tools.search import register_search_tools
    mcp = _CaptureMCP()
    register_search_tools(mcp)
    return mcp._tools


# ---------------------------------------------------------------------------
# verify_mpn_match — pairs straight from the field report
# ---------------------------------------------------------------------------

class TestVerifyMpnMatch:
    def test_different_ldo_is_not_a_match(self):
        """TLV75533PDBVR vs TLV70233PDBVR — one digit apart, different part."""
        assert not verify_mpn_match(
            "TLV75533PDBVR", {"part_number": "TLV70233PDBVR"}
        )

    def test_resistor_vs_inductor_is_not_a_match(self):
        """0603WAF5101T5E (5.1k resistor) matched AIML-0603-180K-T (inductor)."""
        assert not verify_mpn_match(
            "0603WAF5101T5E", {"name": "ABRACON AIML-0603-180K-T"}
        )

    def test_suffix_variant_is_not_verified(self):
        """BSS138 vs BSS138LT1G: almost-right is the failure mode."""
        assert not verify_mpn_match("BSS138", {"part_number": "BSS138LT1G"})

    def test_exact_part_number_matches(self):
        assert verify_mpn_match("BSS138", {"part_number": "BSS138"})

    def test_mpn_embedded_in_name_matches(self):
        """Catalog rows carry the MPN inside name ('BRAND MPN')."""
        assert verify_mpn_match(
            "TS3USB221RSER-TP", {"name": "TECH PUBLIC TS3USB221RSER-TP"}
        )

    def test_metadata_mpn_matches_case_and_separator_insensitively(self):
        assert verify_mpn_match(
            "erj 3rqjr47v",
            {"metadata": {"manufacturer_part_number": "ERJ-3RQJR47V"}},
        )

    def test_sku_query_matches(self):
        assert verify_mpn_match("SP-IC-2026-05865", {"sku": "SP-IC-2026-05865"})

    def test_empty_query_never_matches(self):
        assert not verify_mpn_match("", {"part_number": ""})

    def test_normalize_strips_separators_only(self):
        assert normalize_mpn("ERJ-3RQJR47V") == "ERJ3RQJR47V"
        assert normalize_mpn("era50v2200m16x30") == "ERA50V2200M16X30"

    def test_describe_candidate_prefers_part_number_then_metadata(self):
        d = describe_candidate(
            {"sku": "SP-1", "metadata": {"manufacturer_part_number": "X1"}}
        )
        assert d["part_number"] == "X1" and d["sku"] == "SP-1"


# ---------------------------------------------------------------------------
# search_parts annotation
# ---------------------------------------------------------------------------

class TestSearchAnnotation:
    @pytest.mark.asyncio
    async def test_fuzzy_top_hit_flags_and_warns(self, search_tools):
        client = MagicMock()
        client.search_parts.return_value = {
            "results": [{"sku": "SP-9", "name": "ABRACON AIML-0603-180K-T"}],
            "total": 1,
        }
        with patch("parts_mcp.tools.search.get_client", return_value=client):
            result = await search_tools["search_parts"](query="0603WAF5101T5E")

        assert result["success"] is True
        assert result["match_verified"] is False
        assert result["results"][0]["match_verified"] is False
        assert "fuzzy" in result["match_warning"]

    @pytest.mark.asyncio
    async def test_exact_hit_is_verified_without_warning(self, search_tools):
        client = MagicMock()
        client.search_parts.return_value = {
            "results": [{"sku": "SP-8", "name": "onsemi BSS138"}],
            "total": 1,
        }
        with patch("parts_mcp.tools.search.get_client", return_value=client):
            result = await search_tools["search_parts"](query="BSS138")

        assert result["match_verified"] is True
        assert "match_warning" not in result


# ---------------------------------------------------------------------------
# compare_prices
# ---------------------------------------------------------------------------

def _client_with(part, pricing=None, pricing_error=None):
    client = MagicMock()
    client.search_parts.return_value = {"results": [part], "total": 1}
    if pricing_error is not None:
        client.get_part_pricing.side_effect = pricing_error
    else:
        client.get_part_pricing.return_value = pricing or {}
    return client


class TestComparePrices:
    @pytest.mark.asyncio
    async def test_refuses_to_price_a_fuzzy_match(self, sourcing_tools):
        """The inductor-priced-as-tactile-switch case: no exact match, no price."""
        client = _client_with(
            {"sku": "SP-SW-1", "name": "E-Switch KAC02LGGR", "price": 3.24}
        )
        with patch("parts_mcp.tools.sourcing.get_client", return_value=client):
            result = await sourcing_tools["compare_prices"](
                part_number="SWPA252012S100MT"
            )

        assert result["success"] is False
        assert result["match_verified"] is False
        assert result["closest_match"]["sku"] == "SP-SW-1"
        client.get_part_pricing.assert_not_called()

    @pytest.mark.asyncio
    async def test_pricing_404_degrades_to_no_pricing_data(self, sourcing_tools):
        client = _client_with(
            {"sku": "SP-C-1", "name": "Murata GRM21BR61H106KE43L"},
            pricing_error=SourcePartsAPIError("API error 404: Part not found"),
        )
        with patch("parts_mcp.tools.sourcing.get_client", return_value=client):
            result = await sourcing_tools["compare_prices"](
                part_number="GRM21BR61H106KE43L"
            )

        assert result["success"] is True
        assert result["prices"] == []
        assert "No pricing data" in result["message"]

    @pytest.mark.asyncio
    async def test_suppliers_parameter_warns_instead_of_silently_ignoring(
        self, sourcing_tools
    ):
        client = _client_with(
            {"sku": "SP-F-1", "name": "onsemi BSS138", "price": 0.11},
        )
        with patch("parts_mcp.tools.sourcing.get_client", return_value=client):
            result = await sourcing_tools["compare_prices"](
                part_number="BSS138",
                suppliers=["DigiKey", "Mouser", "LCSC"],
            )

        assert result["success"] is True
        assert result["price_source"] == "source_parts_catalog"
        assert result["suppliers_requested"] == ["DigiKey", "Mouser", "LCSC"]
        assert "not supported" in result["warning"]

    @pytest.mark.asyncio
    async def test_exact_match_prices_normally(self, sourcing_tools):
        client = _client_with(
            {"sku": "SP-F-2", "name": "onsemi BSS138", "stock_quantity": 100},
            pricing={"price_breaks": [{"quantity": 1, "unit_price": 0.03}]},
        )
        with patch("parts_mcp.tools.sourcing.get_client", return_value=client):
            result = await sourcing_tools["compare_prices"](part_number="BSS138")

        assert result["success"] is True
        assert result["match_verified"] is True
        assert result["best_price"]["unit_price"] == 0.03


# ---------------------------------------------------------------------------
# calculate_bom_cost
# ---------------------------------------------------------------------------

class TestBomCostMatchGate:
    @pytest.mark.asyncio
    async def test_fuzzy_line_is_an_error_not_a_cost(self, sourcing_tools):
        client = MagicMock()
        client.search_parts.return_value = {
            "results": [{"sku": "SP-SW-1", "name": "E-Switch KAC02LGGR"}],
            "total": 1,
        }
        with patch("parts_mcp.tools.sourcing.get_client", return_value=client):
            result = await sourcing_tools["calculate_bom_cost"](
                bom=[{"reference": "L1", "part_number": "SWPA252012S100MT",
                      "quantity": 2}]
            )

        assert result["success"] is True
        assert result.get("cost_breakdown", []) == []
        errors = result.get("errors") or result.get("unmatched_parts") or []
        assert errors and errors[0]["match_verified"] is False
        assert "not priced" in errors[0]["error"]
        client.get_part_pricing.assert_not_called()

    @pytest.mark.asyncio
    async def test_pricing_404_line_reports_no_pricing_data(self, sourcing_tools):
        client = MagicMock()
        client.search_parts.return_value = {
            "results": [{"sku": "SP-C-2", "name": "Murata GRM21BR61H106KE43L"}],
            "total": 1,
        }
        client.get_part_pricing.side_effect = SourcePartsAPIError(
            "API error 404: Part 'SP-C-2' not found"
        )
        with patch("parts_mcp.tools.sourcing.get_client", return_value=client):
            result = await sourcing_tools["calculate_bom_cost"](
                bom=[{"reference": "C1", "part_number": "GRM21BR61H106KE43L",
                      "quantity": 1}]
            )

        errors = result.get("errors") or result.get("unmatched_parts") or []
        assert errors and errors[0]["error"] == "No pricing data"
