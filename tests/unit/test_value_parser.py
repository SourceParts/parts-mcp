"""
Unit tests for value parsing utilities.
"""
import pytest

from parts_mcp.utils.value_parser import normalize_value, parse_value, values_match


class TestParseValue:
    """Tests for parse_value function."""

    def test_parse_simple_number(self):
        """Parse simple numeric value."""
        result = parse_value("100")
        assert result.numeric_value == 100
        assert result.prefix is None

    def test_parse_kilo_prefix(self):
        """Parse value with kilo prefix."""
        result = parse_value("10k")
        assert result.numeric_value == 10000
        assert result.prefix == "k"

    def test_parse_mega_prefix(self):
        """Parse value with mega prefix."""
        result = parse_value("1M")
        assert result.numeric_value == 1000000
        assert result.prefix == "M"

    def test_parse_micro_prefix(self):
        """Parse value with micro prefix."""
        result = parse_value("4.7u")
        assert result.numeric_value == pytest.approx(4.7e-6)
        assert result.prefix == "u"

    def test_parse_nano_prefix(self):
        """Parse value with nano prefix."""
        result = parse_value("100n")
        assert result.numeric_value == pytest.approx(100e-9)
        assert result.prefix == "n"

    def test_parse_pico_prefix(self):
        """Parse value with pico prefix."""
        result = parse_value("22p")
        assert result.numeric_value == pytest.approx(22e-12)
        assert result.prefix == "p"

    def test_parse_r_notation_whole(self):
        """Parse R notation with whole number (10R = 10 ohms)."""
        result = parse_value("10R")
        assert result.numeric_value == 10
        assert result.unit == "ohm"

    def test_parse_r_notation_decimal(self):
        """Parse R notation with decimal (4R7 = 4.7 ohms)."""
        result = parse_value("4R7")
        assert result.numeric_value == 4.7
        assert result.unit == "ohm"

    def test_parse_r_notation_small(self):
        """Parse R notation for small values (0R1 = 0.1 ohms)."""
        result = parse_value("0R1")
        assert result.numeric_value == 0.1
        assert result.unit == "ohm"

    def test_parse_with_ohm_unit(self):
        """Parse value with Ohm unit."""
        result = parse_value("10kOhm")
        assert result.numeric_value == 10000
        assert result.unit == "ohm"

    def test_parse_with_farad_unit(self):
        """Parse value with Farad unit."""
        result = parse_value("100nF")
        assert result.numeric_value == pytest.approx(100e-9)
        assert result.unit == "farad"

    def test_parse_with_tolerance(self):
        """Parse value with tolerance percentage."""
        result = parse_value("10k 1%")
        assert result.numeric_value == 10000
        assert result.tolerance == 0.01

    def test_parse_with_tolerance_10_percent(self):
        """Parse value with 10% tolerance."""
        result = parse_value("100nF 10%")
        assert result.numeric_value == pytest.approx(100e-9)
        assert result.tolerance == 0.10

    def test_parse_empty_string(self):
        """Parse empty string returns empty result."""
        result = parse_value("")
        assert result.numeric_value is None
        assert result.original == ""

    def test_parse_unparseable_string(self):
        """Parse unparseable string preserves original."""
        result = parse_value("DNP")
        assert result.numeric_value is None
        assert result.original == "DNP"


class TestParsedValueEquality:
    """Tests for ParsedValue equality."""

    def test_equal_values(self):
        """Two identical values are equal."""
        v1 = parse_value("10k")
        v2 = parse_value("10k")
        assert v1 == v2

    def test_equal_different_notation(self):
        """Same value in different notations are equal."""
        v1 = parse_value("10000")
        v2 = parse_value("10k")
        assert v1 == v2

    def test_not_equal_different_values(self):
        """Different values are not equal."""
        v1 = parse_value("10k")
        v2 = parse_value("20k")
        assert v1 != v2


class TestParsedValueCompatibility:
    """Tests for ParsedValue compatibility checks."""

    def test_compatible_within_tolerance(self):
        """Values within tolerance are compatible."""
        v1 = parse_value("10k")
        v2 = parse_value("10.2k")
        assert v1.is_compatible(v2, tolerance_pct=5.0)

    def test_not_compatible_outside_tolerance(self):
        """Values outside tolerance are not compatible."""
        v1 = parse_value("10k")
        v2 = parse_value("15k")
        assert not v1.is_compatible(v2, tolerance_pct=5.0)

    def test_compatible_different_units_same_value(self):
        """Same value in different formats are compatible."""
        v1 = parse_value("1000")
        v2 = parse_value("1k")
        assert v1.is_compatible(v2)


class TestNormalizeValue:
    """Tests for normalize_value function."""

    def test_normalize_kilo(self):
        """Normalize kilo value."""
        numeric, formatted = normalize_value("10k")
        assert numeric == 10000
        assert "10k" in formatted.lower()

    def test_normalize_micro(self):
        """Normalize micro value."""
        numeric, formatted = normalize_value("4.7u")
        assert numeric == pytest.approx(4.7e-6)


class TestValuesMatch:
    """Tests for values_match function."""

    def test_exact_match(self):
        """Exact values match."""
        assert values_match("10k", "10k")

    def test_notation_match(self):
        """Different notations for same value match."""
        assert values_match("10000", "10k")

    def test_tolerance_match(self):
        """Values within tolerance match."""
        assert values_match("10k", "10.5k", tolerance_pct=10.0)

    def test_no_match_outside_tolerance(self):
        """Values outside tolerance don't match."""
        assert not values_match("10k", "20k", tolerance_pct=5.0)

    def test_r_notation_match(self):
        """R notation matches standard notation."""
        assert values_match("4R7", "4.7")
