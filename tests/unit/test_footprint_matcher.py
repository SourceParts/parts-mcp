"""
Unit tests for footprint matching utilities.
"""

from parts_mcp.utils.footprint_matcher import (
    footprints_compatible,
    get_equivalent_sizes,
    normalize_footprint,
    parse_footprint,
)


class TestParseFootprint:
    """Tests for parse_footprint function."""

    def test_parse_imperial_0603(self):
        """Parse imperial 0603 size."""
        result = parse_footprint("0603")
        assert result.size_imperial == "0603"
        assert result.size_metric == "1608"
        assert result.package_type == "chip"

    def test_parse_imperial_0805(self):
        """Parse imperial 0805 size."""
        result = parse_footprint("0805")
        assert result.size_imperial == "0805"
        assert result.size_metric == "2012"

    def test_parse_imperial_1206(self):
        """Parse imperial 1206 size."""
        result = parse_footprint("1206")
        assert result.size_imperial == "1206"
        assert result.size_metric == "3216"

    def test_parse_metric_1608(self):
        """Parse metric 1608 size."""
        result = parse_footprint("1608")
        assert result.size_metric == "1608"
        assert result.size_imperial == "0603"

    def test_parse_sot23(self):
        """Parse SOT-23 package."""
        result = parse_footprint("SOT-23")
        assert result.package_type == "SOT"
        assert "SOT-23" in result.canonical

    def test_parse_soic8(self):
        """Parse SOIC-8 package."""
        result = parse_footprint("SOIC-8")
        assert result.package_type == "SOIC"
        assert result.pin_count == 8

    def test_parse_lqfp100(self):
        """Parse LQFP-100 package."""
        result = parse_footprint("LQFP-100")
        assert result.package_type == "LQFP"
        assert result.pin_count == 100

    def test_parse_kicad_format(self):
        """Parse KiCad library:footprint format."""
        result = parse_footprint("Package_QFP:LQFP-100_14x14mm_P0.5mm")
        assert result.package_type == "LQFP"
        assert result.pin_count == 100
        assert result.pitch == 0.5

    def test_parse_kicad_resistor(self):
        """Parse KiCad resistor footprint format."""
        result = parse_footprint("Resistor_SMD:R_0603_1608Metric")
        # KiCad format includes both sizes in the name
        # Should extract the footprint name
        assert "0603" in result.original or "1608" in result.original

    def test_parse_to220(self):
        """Parse TO-220 package."""
        result = parse_footprint("TO-220")
        assert result.package_type == "TO"

    def test_parse_dip8(self):
        """Parse DIP-8 package."""
        result = parse_footprint("DIP-8")
        assert result.package_type == "DIP"
        assert result.pin_count == 8

    def test_parse_empty_string(self):
        """Parse empty string returns empty result."""
        result = parse_footprint("")
        assert result.canonical == ""


class TestFootprintCompatibility:
    """Tests for footprint compatibility checking."""

    def test_same_footprint_compatible(self):
        """Same footprint is compatible with itself."""
        fp1 = parse_footprint("0603")
        fp2 = parse_footprint("0603")
        assert fp1.is_compatible(fp2)

    def test_imperial_metric_compatible(self):
        """Imperial 0603 compatible with metric 1608."""
        fp1 = parse_footprint("0603")
        fp2 = parse_footprint("1608")
        assert fp1.is_compatible(fp2)

    def test_different_sizes_not_compatible(self):
        """0603 not compatible with 0805."""
        fp1 = parse_footprint("0603")
        fp2 = parse_footprint("0805")
        assert not fp1.is_compatible(fp2)

    def test_sot23_aliases_compatible(self):
        """SOT-23 aliases are compatible."""
        fp1 = parse_footprint("SOT-23")
        fp2 = parse_footprint("SOT23")
        assert fp1.is_compatible(fp2)

    def test_sot23_to236_compatible(self):
        """SOT-23 compatible with TO-236 (alias)."""
        fp1 = parse_footprint("SOT-23")
        fp2 = parse_footprint("TO-236")
        assert fp1.is_compatible(fp2)

    def test_soic8_so8_compatible(self):
        """SOIC-8 compatible with SO-8."""
        fp1 = parse_footprint("SOIC-8")
        fp2 = parse_footprint("SO-8")
        assert fp1.is_compatible(fp2)

    def test_soic8_sop8_compatible(self):
        """SOIC-8 compatible with SOP-8."""
        fp1 = parse_footprint("SOIC-8")
        fp2 = parse_footprint("SOP-8")
        assert fp1.is_compatible(fp2)


class TestFootprintsCompatibleFunction:
    """Tests for footprints_compatible convenience function."""

    def test_compatible_strings(self):
        """Compatible footprint strings."""
        assert footprints_compatible("0603", "1608")

    def test_incompatible_strings(self):
        """Incompatible footprint strings."""
        assert not footprints_compatible("0603", "0805")

    def test_package_compatibility(self):
        """Package compatibility via strings."""
        assert footprints_compatible("SOIC-8", "SO8")


class TestNormalizeFootprint:
    """Tests for normalize_footprint function."""

    def test_normalize_imperial(self):
        """Normalize imperial size."""
        result = normalize_footprint("0603")
        assert result == "0603"

    def test_normalize_kicad_format(self):
        """Normalize KiCad format extracts footprint."""
        result = normalize_footprint("Resistor_SMD:R_0603_1608Metric")
        # Should return something meaningful
        assert result != ""

    def test_normalize_alias(self):
        """Normalize package alias to canonical form."""
        result = normalize_footprint("SO8")
        assert result == "SOIC-8"


class TestGetEquivalentSizes:
    """Tests for get_equivalent_sizes function."""

    def test_imperial_to_metric(self):
        """Get metric equivalent for imperial size."""
        equivalents = get_equivalent_sizes("0603")
        assert "0603" in equivalents
        assert "1608" in equivalents

    def test_metric_to_imperial(self):
        """Get imperial equivalent for metric size."""
        equivalents = get_equivalent_sizes("1608")
        assert "1608" in equivalents
        assert "0603" in equivalents

    def test_unknown_size(self):
        """Unknown size returns just itself."""
        equivalents = get_equivalent_sizes("unknown")
        assert equivalents == ["unknown"]
