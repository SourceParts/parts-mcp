"""
Footprint/package matching utilities for electronic components.

Handles equivalence between imperial/metric sizes and package variations.
"""
import re
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# Imperial to metric size mappings (chip components)
IMPERIAL_TO_METRIC = {
    '0201': '0603',    # 0.6mm x 0.3mm
    '0402': '1005',    # 1.0mm x 0.5mm
    '0603': '1608',    # 1.6mm x 0.8mm
    '0805': '2012',    # 2.0mm x 1.25mm
    '1206': '3216',    # 3.2mm x 1.6mm
    '1210': '3225',    # 3.2mm x 2.5mm
    '1812': '4532',    # 4.5mm x 3.2mm
    '2010': '5025',    # 5.0mm x 2.5mm
    '2512': '6332',    # 6.3mm x 3.2mm
}

# Reverse mapping
METRIC_TO_IMPERIAL = {v: k for k, v in IMPERIAL_TO_METRIC.items()}


# Package family aliases (different names for same/compatible packages)
PACKAGE_ALIASES: Dict[str, Set[str]] = {
    'SOT-23': {'SOT23', 'SOT-23-3', 'TO-236', 'SC-59'},
    'SOT-23-5': {'SOT23-5', 'SOT-23-5L', 'SC-74A'},
    'SOT-23-6': {'SOT23-6', 'SOT-23-6L', 'SC-74'},
    'SOT-223': {'SOT223', 'SOT-223-4', 'TO-261AA'},
    'SOT-323': {'SOT323', 'SC-70', 'SC70'},
    'SOT-363': {'SOT363', 'SC-88', 'SC88'},
    'SOIC-8': {'SOIC8', 'SO-8', 'SO8', 'SOP-8', 'SOP8'},
    'SOIC-14': {'SOIC14', 'SO-14', 'SO14', 'SOP-14', 'SOP14'},
    'SOIC-16': {'SOIC16', 'SO-16', 'SO16', 'SOP-16', 'SOP16'},
    'TSSOP-8': {'TSSOP8', 'MSOP-8', 'MSOP8'},
    'TSSOP-14': {'TSSOP14'},
    'TSSOP-16': {'TSSOP16'},
    'TSSOP-20': {'TSSOP20'},
    'QFN-16': {'QFN16', 'VQFN-16', 'VQFN16'},
    'QFN-20': {'QFN20', 'VQFN-20', 'VQFN20'},
    'QFN-24': {'QFN24', 'VQFN-24', 'VQFN24'},
    'QFN-32': {'QFN32', 'VQFN-32', 'VQFN32'},
    'QFN-48': {'QFN48', 'VQFN-48', 'VQFN48'},
    'LQFP-32': {'LQFP32', 'TQFP-32', 'TQFP32'},
    'LQFP-48': {'LQFP48', 'TQFP-48', 'TQFP48'},
    'LQFP-64': {'LQFP64', 'TQFP-64', 'TQFP64'},
    'LQFP-100': {'LQFP100', 'TQFP-100', 'TQFP100'},
    'LQFP-144': {'LQFP144', 'TQFP-144', 'TQFP144'},
    'TO-220': {'TO220', 'TO-220-3', 'TO220-3'},
    'TO-252': {'TO252', 'DPAK', 'D-PAK'},
    'TO-263': {'TO263', 'D2PAK', 'D2-PAK', 'DDPAK'},
    'BGA-256': {'BGA256', 'FBGA-256'},
    'DIP-8': {'DIP8', 'PDIP-8', 'PDIP8'},
    'DIP-14': {'DIP14', 'PDIP-14', 'PDIP14'},
    'DIP-16': {'DIP16', 'PDIP-16', 'PDIP16'},
}

# Build reverse lookup for aliases
PACKAGE_ALIAS_LOOKUP: Dict[str, str] = {}
for canonical, aliases in PACKAGE_ALIASES.items():
    PACKAGE_ALIAS_LOOKUP[canonical.upper()] = canonical
    for alias in aliases:
        PACKAGE_ALIAS_LOOKUP[alias.upper()] = canonical


@dataclass
class ParsedFootprint:
    """Represents a parsed footprint/package."""
    original: str
    package_type: Optional[str]
    size_imperial: Optional[str]
    size_metric: Optional[str]
    pin_count: Optional[int]
    pitch: Optional[float]
    canonical: str

    def is_compatible(self, other: 'ParsedFootprint') -> bool:
        """Check if two footprints are compatible (can be substituted)."""
        # Same canonical name
        if self.canonical.upper() == other.canonical.upper():
            return True

        # Check size equivalence for chip components
        if self.size_imperial and other.size_metric:
            if IMPERIAL_TO_METRIC.get(self.size_imperial) == other.size_metric:
                return True
        if self.size_metric and other.size_imperial:
            if METRIC_TO_IMPERIAL.get(self.size_metric) == other.size_imperial:
                return True
        if self.size_imperial and other.size_imperial:
            if self.size_imperial == other.size_imperial:
                return True
        if self.size_metric and other.size_metric:
            if self.size_metric == other.size_metric:
                return True

        # Check package family aliases
        self_canonical = PACKAGE_ALIAS_LOOKUP.get(self.canonical.upper())
        other_canonical = PACKAGE_ALIAS_LOOKUP.get(other.canonical.upper())

        if self_canonical and other_canonical:
            return self_canonical == other_canonical

        return False


def parse_footprint(footprint_str: str) -> ParsedFootprint:
    """Parse a footprint/package string into structured data.

    Handles formats like:
    - 0603, 0805, 1206 (imperial chip sizes)
    - 1608, 2012, 3216 (metric chip sizes)
    - SOT-23, SOIC-8, LQFP-100
    - Package_QFP:LQFP-100_14x14mm_P0.5mm (KiCad format)

    Args:
        footprint_str: The footprint string to parse

    Returns:
        ParsedFootprint with parsed components
    """
    if not footprint_str:
        return ParsedFootprint(
            original="",
            package_type=None,
            size_imperial=None,
            size_metric=None,
            pin_count=None,
            pitch=None,
            canonical=""
        )

    original = footprint_str.strip()
    working = original

    # Handle KiCad-style footprints (Library:Footprint)
    if ':' in working:
        parts = working.split(':')
        working = parts[-1]  # Take the footprint name

    # Extract pitch if present (e.g., P0.5mm)
    pitch = None
    pitch_match = re.search(r'P(\d+(?:\.\d+)?)\s*mm', working, re.IGNORECASE)
    if pitch_match:
        pitch = float(pitch_match.group(1))
        working = working[:pitch_match.start()] + working[pitch_match.end():]

    # Extract dimensions if present (e.g., 14x14mm)
    dim_match = re.search(r'(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*mm', working, re.IGNORECASE)
    if dim_match:
        working = working[:dim_match.start()] + working[dim_match.end():]

    # Clean up working string
    working = re.sub(r'[_\-\s]+', '-', working.strip())
    working = working.strip('-')

    # Check for imperial chip sizes (4 digits, specific patterns)
    size_imperial = None
    size_metric = None
    imperial_match = re.match(r'^(0201|0402|0603|0805|1206|1210|1812|2010|2512)$', working)
    if imperial_match:
        size_imperial = imperial_match.group(1)
        size_metric = IMPERIAL_TO_METRIC.get(size_imperial)
        return ParsedFootprint(
            original=original,
            package_type="chip",
            size_imperial=size_imperial,
            size_metric=size_metric,
            pin_count=2,
            pitch=None,
            canonical=size_imperial
        )

    # Check for metric chip sizes
    metric_match = re.match(r'^(0603|1005|1608|2012|3216|3225|4532|5025|6332)$', working)
    if metric_match and metric_match.group(1) in METRIC_TO_IMPERIAL:
        size_metric = metric_match.group(1)
        size_imperial = METRIC_TO_IMPERIAL.get(size_metric)
        return ParsedFootprint(
            original=original,
            package_type="chip",
            size_imperial=size_imperial,
            size_metric=size_metric,
            pin_count=2,
            pitch=None,
            canonical=size_imperial or size_metric
        )

    # Extract pin count if present
    pin_count = None
    pin_match = re.search(r'[-_]?(\d+)$', working)
    if pin_match:
        pin_count = int(pin_match.group(1))

    # Look for package type
    package_type = None
    for pkg_family in ['LQFP', 'TQFP', 'QFN', 'VQFN', 'BGA', 'FBGA',
                       'SOIC', 'SOP', 'TSSOP', 'MSOP', 'SOT',
                       'TO', 'DIP', 'PDIP', 'QFP', 'PLCC']:
        if pkg_family.upper() in working.upper():
            package_type = pkg_family
            break

    # Determine canonical name
    canonical = working
    canonical_upper = canonical.upper()

    # Check for known aliases
    if canonical_upper in PACKAGE_ALIAS_LOOKUP:
        canonical = PACKAGE_ALIAS_LOOKUP[canonical_upper]

    return ParsedFootprint(
        original=original,
        package_type=package_type,
        size_imperial=size_imperial,
        size_metric=size_metric,
        pin_count=pin_count,
        pitch=pitch,
        canonical=canonical
    )


def footprints_compatible(fp1: str, fp2: str) -> bool:
    """Check if two footprint strings represent compatible packages.

    Args:
        fp1: First footprint string
        fp2: Second footprint string

    Returns:
        True if footprints are compatible
    """
    parsed1 = parse_footprint(fp1)
    parsed2 = parse_footprint(fp2)
    return parsed1.is_compatible(parsed2)


def normalize_footprint(footprint_str: str) -> str:
    """Normalize a footprint string to canonical form.

    Args:
        footprint_str: The footprint string to normalize

    Returns:
        Normalized/canonical footprint name
    """
    parsed = parse_footprint(footprint_str)
    return parsed.canonical


def get_equivalent_sizes(size: str) -> List[str]:
    """Get equivalent imperial/metric sizes for a chip component.

    Args:
        size: Imperial or metric size code (e.g., '0603' or '1608')

    Returns:
        List of equivalent size codes
    """
    equivalents = [size]

    # Check if it's imperial
    if size in IMPERIAL_TO_METRIC:
        metric = IMPERIAL_TO_METRIC[size]
        equivalents.append(metric)
        equivalents.append(f"{metric}_metric")

    # Check if it's metric
    if size in METRIC_TO_IMPERIAL:
        imperial = METRIC_TO_IMPERIAL[size]
        equivalents.append(imperial)

    return equivalents


def extract_footprint(component_data: dict) -> Optional[ParsedFootprint]:
    """Extract and parse footprint from component data dictionary.

    Args:
        component_data: Dictionary with component data

    Returns:
        ParsedFootprint or None if not found
    """
    footprint_fields = ['footprint', 'Footprint', 'FOOTPRINT',
                        'package', 'Package', 'PACKAGE',
                        'case', 'Case', 'CASE']

    for field in footprint_fields:
        if field in component_data and component_data[field]:
            return parse_footprint(str(component_data[field]))

    return None
