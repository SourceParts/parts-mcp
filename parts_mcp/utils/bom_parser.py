"""
BOM (Bill of Materials) parsing utilities for KiCad projects.
"""
import csv
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def parse_bom_file(file_path: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a BOM file and detect its format.

    Args:
        file_path: Path to the BOM file

    Returns:
        Tuple containing:
            - List of component dictionaries
            - Dictionary with format information
    """
    logger.info(f"Parsing BOM file: {file_path}")

    file_path = Path(file_path)
    if not file_path.exists():
        return [], {"error": "File not found"}

    ext = file_path.suffix.lower()

    # Format detection info
    format_info = {
        "file_type": ext,
        "detected_format": "unknown",
        "header_fields": []
    }

    components = []

    try:
        if ext == '.csv':
            components, format_info = _parse_csv_bom(file_path)
        elif ext == '.tsv':
            components, format_info = _parse_csv_bom(file_path, delimiter='\t')
        elif ext == '.json':
            components, format_info = _parse_json_bom(file_path)
        elif ext == '.xml':
            components, format_info = _parse_xml_bom(file_path)
        else:
            # Try CSV as fallback
            components, format_info = _parse_csv_bom(file_path)

    except Exception as e:
        logger.error(f"Error parsing BOM file: {e}")
        return [], {"error": str(e)}

    logger.info(f"Parsed {len(components)} components from BOM")
    return components, format_info


def _parse_csv_bom(file_path: Path, delimiter: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a CSV/TSV BOM file.

    Args:
        file_path: Path to the CSV file
        delimiter: CSV delimiter (auto-detected if None)

    Returns:
        Tuple of components list and format info
    """
    format_info = {
        "file_type": file_path.suffix,
        "detected_format": "unknown",
        "header_fields": []
    }

    components = []

    with open(file_path, encoding='utf-8-sig') as f:
        # Auto-detect delimiter if not specified
        if delimiter is None:
            sample = f.read(1024)
            f.seek(0)

            if '\t' in sample:
                delimiter = '\t'
            elif ';' in sample:
                delimiter = ';'
            else:
                delimiter = ','

        format_info["delimiter"] = delimiter

        # Read CSV
        reader = csv.DictReader(f, delimiter=delimiter)
        format_info["header_fields"] = list(reader.fieldnames) if reader.fieldnames else []

        # Detect format based on headers
        headers_lower = [h.lower() for h in format_info["header_fields"]]

        if 'reference' in headers_lower and 'value' in headers_lower:
            format_info["detected_format"] = "kicad"
        elif 'designator' in headers_lower:
            format_info["detected_format"] = "altium"
        elif 'part number' in headers_lower or 'mpn' in headers_lower:
            format_info["detected_format"] = "generic"

        # Read all components
        for row in reader:
            # Clean up row - remove empty values
            cleaned_row = {k: v for k, v in row.items() if v and v.strip()}
            if cleaned_row:  # Only add non-empty rows
                components.append(cleaned_row)

    return components, format_info


def _parse_json_bom(file_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a JSON BOM file.

    Args:
        file_path: Path to the JSON file

    Returns:
        Tuple of components list and format info
    """
    format_info = {
        "file_type": ".json",
        "detected_format": "json",
        "header_fields": []
    }

    with open(file_path) as f:
        data = json.load(f)

    # Try to find components in common structures
    if isinstance(data, list):
        components = data
    elif isinstance(data, dict):
        # Look for common keys
        for key in ['components', 'parts', 'items', 'bom']:
            if key in data and isinstance(data[key], list):
                components = data[key]
                break
        else:
            # If no standard key found, assume the dict contains components
            components = [data]
    else:
        components = []

    # Extract header fields from first component
    if components:
        format_info["header_fields"] = list(components[0].keys())

    return components, format_info


def _parse_xml_bom(file_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse an XML BOM file.

    Args:
        file_path: Path to the XML file

    Returns:
        Tuple of components list and format info
    """
    from defusedxml.ElementTree import parse as safe_parse

    format_info = {
        "file_type": ".xml",
        "detected_format": "xml",
        "header_fields": []
    }

    components = []

    try:
        tree = safe_parse(file_path)
        root = tree.getroot()

        # Try common XML structures
        # Look for component/part elements
        for tag in ['component', 'Component', 'part', 'Part', 'item', 'Item']:
            elements = root.findall(f'.//{tag}')
            if elements:
                for elem in elements:
                    component = {}

                    # Get attributes
                    component.update(elem.attrib)

                    # Get child elements
                    for child in elem:
                        if child.text:
                            component[child.tag] = child.text.strip()

                    if component:
                        components.append(component)
                break

        # Extract header fields
        if components:
            all_keys = set()
            for comp in components:
                all_keys.update(comp.keys())
            format_info["header_fields"] = sorted(all_keys)

    except Exception as e:
        logger.error(f"Error parsing XML: {e}")

    return components, format_info


def analyze_bom_data(components: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze BOM data to extract insights.

    Args:
        components: List of component dictionaries

    Returns:
        Dictionary with analysis results
    """
    analysis = {
        "total_components": 0,
        "unique_components": 0,
        "categories": {},
        "most_common_values": [],
        "has_pricing": False,
        "missing_data": {
            "value": 0,
            "footprint": 0,
            "manufacturer": 0
        }
    }

    if not components:
        return analysis

    try:
        df = pd.DataFrame(components)

        # Normalize column names
        df.columns = [col.strip().lower() for col in df.columns]

        # Find key columns
        ref_col = _find_column(df, ['reference', 'ref', 'designator', 'refdes'])
        value_col = _find_column(df, ['value', 'part', 'component'])
        qty_col = _find_column(df, ['quantity', 'qty', 'count'])
        footprint_col = _find_column(df, ['footprint', 'package', 'case'])
        mfr_col = _find_column(df, ['manufacturer', 'mfr', 'mfg'])

        # Count components
        if qty_col and qty_col in df.columns:
            df[qty_col] = pd.to_numeric(df[qty_col], errors='coerce').fillna(1)
            analysis["total_components"] = int(df[qty_col].sum())
        else:
            analysis["total_components"] = len(df)

        analysis["unique_components"] = len(df)

        # Analyze categories from reference designators
        if ref_col and ref_col in df.columns:
            categories = _extract_categories_from_refs(df[ref_col])
            analysis["categories"] = categories

        # Find most common values
        if value_col and value_col in df.columns:
            value_counts = df[value_col].value_counts().head(10)
            analysis["most_common_values"] = [
                {"value": str(val), "count": int(count)}
                for val, count in value_counts.items()
            ]

        # Check for pricing data
        price_cols = ['price', 'cost', 'unit price', 'unit cost', 'extended price']
        for col in price_cols:
            if col in df.columns:
                analysis["has_pricing"] = True
                break

        # Check for missing data
        if value_col and value_col in df.columns:
            analysis["missing_data"]["value"] = int(df[value_col].isna().sum())
        if footprint_col and footprint_col in df.columns:
            analysis["missing_data"]["footprint"] = int(df[footprint_col].isna().sum())
        if mfr_col and mfr_col in df.columns:
            analysis["missing_data"]["manufacturer"] = int(df[mfr_col].isna().sum())

    except Exception as e:
        logger.error(f"Error analyzing BOM data: {e}")

    return analysis


def _find_column(df: pd.DataFrame, possible_names: list[str]) -> str | None:
    """Find a column by trying multiple possible names.

    Args:
        df: DataFrame to search
        possible_names: List of possible column names

    Returns:
        Found column name or None
    """
    for name in possible_names:
        if name in df.columns:
            return name
        # Also try with spaces
        name_with_space = name.replace('_', ' ')
        if name_with_space in df.columns:
            return name_with_space
    return None


def _extract_categories_from_refs(ref_series: pd.Series) -> dict[str, int]:
    """Extract component categories from reference designators.

    Args:
        ref_series: Series of reference designators

    Returns:
        Dictionary of category counts
    """
    import re

    # Component type mapping
    ref_mapping = {
        'R': 'Resistors',
        'C': 'Capacitors',
        'L': 'Inductors',
        'D': 'Diodes',
        'Q': 'Transistors',
        'U': 'ICs',
        'J': 'Connectors',
        'SW': 'Switches',
        'F': 'Fuses',
        'T': 'Transformers',
        'Y': 'Crystals',
        'TP': 'Test Points',
        'M': 'Mechanical',
        'BT': 'Batteries',
        'LED': 'LEDs'
    }

    categories = {}

    for refs in ref_series.dropna():
        # Handle multiple references in one cell (e.g., "R1, R2, R3")
        if isinstance(refs, str):
            ref_list = [r.strip() for r in refs.split(',')]
        else:
            ref_list = [str(refs)]

        for ref in ref_list:
            # Extract prefix
            match = re.match(r'^([A-Za-z]+)', ref)
            if match:
                prefix = match.group(1).upper()

                # Map to category
                category = ref_mapping.get(prefix, f"Other ({prefix})")
                categories[category] = categories.get(category, 0) + 1

    return categories


def export_bom_summary(components: list[dict[str, Any]], output_path: str) -> bool:
    """Export a BOM summary in a standard format.

    Args:
        components: List of components
        output_path: Path to save summary

    Returns:
        True if successful
    """
    try:
        output_path = Path(output_path)

        # Create summary
        analysis = analyze_bom_data(components)

        summary = {
            "total_components": analysis["total_components"],
            "unique_components": analysis["unique_components"],
            "categories": analysis["categories"],
            "components": components
        }

        # Save based on extension
        if output_path.suffix.lower() == '.json':
            with open(output_path, 'w') as f:
                json.dump(summary, f, indent=2)
        else:
            # Default to CSV
            df = pd.DataFrame(components)
            df.to_csv(output_path, index=False)

        logger.info(f"Exported BOM summary to {output_path}")
        return True

    except Exception as e:
        logger.error(f"Error exporting BOM summary: {e}")
        return False
