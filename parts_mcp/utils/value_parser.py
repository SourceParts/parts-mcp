"""
Value parsing utilities for electronic component values.

Handles SI prefixes, resistor notation, and various value formats.
"""
import re
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# SI prefix multipliers (lowercase keys for lookup)
SI_PREFIXES_LOWER = {
    'p': 1e-12,   # pico
    'n': 1e-9,    # nano
    'u': 1e-6,    # micro
    'µ': 1e-6,    # micro (unicode)
    'm': 1e-3,    # milli
    'k': 1e3,     # kilo
    'g': 1e9,     # giga
    't': 1e12,    # tera
}

# SI prefix multipliers (uppercase - for M which is Mega, not milli)
SI_PREFIXES_UPPER = {
    'P': 1e-12,   # pico
    'N': 1e-9,    # nano
    'U': 1e-6,    # micro
    'M': 1e6,     # mega (uppercase M)
    'K': 1e3,     # kilo
    'G': 1e9,     # giga
    'T': 1e12,    # tera
}

# Unit suffixes for component types
UNIT_SUFFIXES = {
    'ohm': 'ohm',
    'ohms': 'ohm',
    'Ω': 'ohm',
    'r': 'ohm',
    'f': 'farad',
    'F': 'farad',
    'h': 'henry',
    'H': 'henry',
    'v': 'volt',
    'V': 'volt',
    'a': 'amp',
    'A': 'amp',
    'w': 'watt',
    'W': 'watt',
}


@dataclass
class ParsedValue:
    """Represents a parsed component value."""
    original: str
    numeric_value: Optional[float]
    unit: Optional[str]
    prefix: Optional[str]
    tolerance: Optional[float]
    formatted: str

    def __eq__(self, other):
        """Two values are equal if their numeric values match within tolerance."""
        if not isinstance(other, ParsedValue):
            return False
        if self.numeric_value is None or other.numeric_value is None:
            return self.original.upper() == other.original.upper()

        # Compare with 1% tolerance by default
        tolerance = max(self.tolerance or 0.01, other.tolerance or 0.01)
        if self.numeric_value == 0:
            return other.numeric_value == 0
        ratio = abs(self.numeric_value - other.numeric_value) / max(abs(self.numeric_value), abs(other.numeric_value))
        return ratio <= tolerance

    def is_compatible(self, other: 'ParsedValue', tolerance_pct: float = 5.0) -> bool:
        """Check if two values are compatible within a given tolerance percentage."""
        if self.numeric_value is None or other.numeric_value is None:
            return self.original.upper() == other.original.upper()

        if self.unit and other.unit and self.unit != other.unit:
            return False

        if self.numeric_value == 0:
            return other.numeric_value == 0

        tolerance = tolerance_pct / 100.0
        ratio = abs(self.numeric_value - other.numeric_value) / max(abs(self.numeric_value), abs(other.numeric_value))
        return ratio <= tolerance


def parse_value(value_str: str) -> ParsedValue:
    """Parse a component value string into a structured format.

    Supports:
    - SI prefixes: 10k, 100n, 4.7u, 1M
    - Resistor notation: 4R7 (4.7 ohms), 10k, 100R
    - Units: 10kOhm, 100nF, 4.7uH
    - Tolerances: 10k 1%, 100nF 10%

    Args:
        value_str: The value string to parse

    Returns:
        ParsedValue with parsed components
    """
    if not value_str:
        return ParsedValue(
            original="",
            numeric_value=None,
            unit=None,
            prefix=None,
            tolerance=None,
            formatted=""
        )

    original = value_str.strip()
    value_str = original.upper()

    # Extract tolerance if present
    tolerance = None
    tolerance_match = re.search(r'(\d+(?:\.\d+)?)\s*%', value_str)
    if tolerance_match:
        tolerance = float(tolerance_match.group(1)) / 100.0
        value_str = value_str[:tolerance_match.start()].strip()

    # Handle resistor R notation (e.g., 4R7 = 4.7 ohms, 10R = 10 ohms)
    r_notation_match = re.match(r'^(\d+)R(\d+)?$', value_str)
    if r_notation_match:
        whole = r_notation_match.group(1)
        decimal = r_notation_match.group(2) or "0"
        numeric_value = float(f"{whole}.{decimal}")
        return ParsedValue(
            original=original,
            numeric_value=numeric_value,
            unit="ohm",
            prefix=None,
            tolerance=tolerance,
            formatted=f"{numeric_value}Ω"
        )

    # Standard parsing with optional SI prefix
    # Pattern: number + optional prefix + optional unit
    pattern = r'^(\d+(?:\.\d+)?)\s*([PNUMKGpnumkg])?([OHMFARYVW]*)?\s*$'
    match = re.match(pattern, value_str)

    if match:
        number_str = match.group(1)
        prefix_char = match.group(2)
        unit_str = match.group(3) or ""

        numeric_value = float(number_str)

        # Apply SI prefix
        prefix = None
        if prefix_char:
            # Use uppercase lookup for M (Mega), lowercase for others
            if prefix_char == 'M':
                multiplier = SI_PREFIXES_UPPER.get('M', 1)
                prefix = 'M'
            else:
                prefix = prefix_char.lower()
                multiplier = SI_PREFIXES_LOWER.get(prefix, SI_PREFIXES_UPPER.get(prefix_char.upper(), 1))
            numeric_value *= multiplier

        # Determine unit
        unit = None
        unit_str_lower = unit_str.lower()
        if unit_str_lower:
            unit = UNIT_SUFFIXES.get(unit_str_lower)

        # Format output
        formatted = _format_value(numeric_value, unit, prefix)

        return ParsedValue(
            original=original,
            numeric_value=numeric_value,
            unit=unit,
            prefix=prefix,
            tolerance=tolerance,
            formatted=formatted
        )

    # Try parsing just a number
    try:
        numeric_value = float(value_str.replace(',', ''))
        return ParsedValue(
            original=original,
            numeric_value=numeric_value,
            unit=None,
            prefix=None,
            tolerance=tolerance,
            formatted=str(numeric_value)
        )
    except ValueError:
        pass

    # Could not parse - return original string only
    return ParsedValue(
        original=original,
        numeric_value=None,
        unit=None,
        prefix=None,
        tolerance=tolerance,
        formatted=original
    )


def _format_value(numeric_value: float, unit: Optional[str], prefix: Optional[str]) -> str:
    """Format a numeric value with appropriate prefix and unit."""
    if numeric_value == 0:
        return "0"

    # Find best prefix for display
    abs_value = abs(numeric_value)

    if abs_value >= 1e12:
        display_value = numeric_value / 1e12
        display_prefix = "T"
    elif abs_value >= 1e9:
        display_value = numeric_value / 1e9
        display_prefix = "G"
    elif abs_value >= 1e6:
        display_value = numeric_value / 1e6
        display_prefix = "M"
    elif abs_value >= 1e3:
        display_value = numeric_value / 1e3
        display_prefix = "k"
    elif abs_value >= 1:
        display_value = numeric_value
        display_prefix = ""
    elif abs_value >= 1e-3:
        display_value = numeric_value * 1e3
        display_prefix = "m"
    elif abs_value >= 1e-6:
        display_value = numeric_value * 1e6
        display_prefix = "µ"
    elif abs_value >= 1e-9:
        display_value = numeric_value * 1e9
        display_prefix = "n"
    else:
        display_value = numeric_value * 1e12
        display_prefix = "p"

    # Format number (remove trailing zeros)
    if display_value == int(display_value):
        formatted_number = str(int(display_value))
    else:
        formatted_number = f"{display_value:.3g}"

    # Add unit symbol
    unit_symbol = ""
    if unit == "ohm":
        unit_symbol = "Ω"
    elif unit == "farad":
        unit_symbol = "F"
    elif unit == "henry":
        unit_symbol = "H"
    elif unit == "volt":
        unit_symbol = "V"
    elif unit == "amp":
        unit_symbol = "A"
    elif unit == "watt":
        unit_symbol = "W"

    return f"{formatted_number}{display_prefix}{unit_symbol}"


def normalize_value(value_str: str) -> Tuple[Optional[float], str]:
    """Normalize a value string to a standard form for comparison.

    Args:
        value_str: The value string to normalize

    Returns:
        Tuple of (numeric_value, normalized_string)
    """
    parsed = parse_value(value_str)
    return parsed.numeric_value, parsed.formatted


def values_match(value1: str, value2: str, tolerance_pct: float = 5.0) -> bool:
    """Check if two value strings represent the same value within tolerance.

    Args:
        value1: First value string
        value2: Second value string
        tolerance_pct: Tolerance percentage for comparison

    Returns:
        True if values match within tolerance
    """
    parsed1 = parse_value(value1)
    parsed2 = parse_value(value2)

    return parsed1.is_compatible(parsed2, tolerance_pct)


def extract_component_value(component_data: dict) -> Optional[ParsedValue]:
    """Extract and parse the value from a component data dictionary.

    Looks for common field names like 'value', 'Value', 'comment', etc.

    Args:
        component_data: Dictionary with component data

    Returns:
        ParsedValue or None if no value found
    """
    # Common field names for component values
    value_fields = ['value', 'Value', 'VALUE', 'comment', 'Comment', 'COMMENT']

    for field in value_fields:
        if field in component_data and component_data[field]:
            return parse_value(str(component_data[field]))

    return None
