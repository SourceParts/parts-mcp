"""
Unit tests for BOM parsing utilities.
"""
import pytest
import json
from pathlib import Path

from parts_mcp.utils.bom_parser import (
    parse_bom_file,
    analyze_bom_data,
    _parse_csv_bom,
    _parse_json_bom,
    _extract_categories_from_refs,
    export_bom_summary
)


class TestParseBomFile:
    """Tests for parse_bom_file function."""

    def test_parse_csv_bom(self, sample_csv_bom):
        """Parse a CSV BOM file."""
        components, format_info = parse_bom_file(str(sample_csv_bom))

        assert len(components) == 5
        assert format_info["file_type"] == ".csv"
        assert format_info["detected_format"] == "kicad"
        assert "Reference" in format_info["header_fields"]

    def test_parse_json_bom(self, sample_json_bom):
        """Parse a JSON BOM file."""
        components, format_info = parse_bom_file(str(sample_json_bom))

        assert len(components) == 2
        assert format_info["file_type"] == ".json"
        assert format_info["detected_format"] == "json"

    def test_parse_xml_bom(self, sample_xml_bom):
        """Parse an XML BOM file."""
        components, format_info = parse_bom_file(str(sample_xml_bom))

        assert len(components) == 2
        assert format_info["file_type"] == ".xml"
        assert format_info["detected_format"] == "xml"

    def test_parse_nonexistent_file(self):
        """Handle non-existent file gracefully."""
        components, format_info = parse_bom_file("/nonexistent/path/bom.csv")

        assert components == []
        assert "error" in format_info

    def test_parse_empty_file(self, tmp_path):
        """Handle empty file gracefully."""
        empty_file = tmp_path / "empty.csv"
        empty_file.write_text("")

        components, format_info = parse_bom_file(str(empty_file))

        assert components == []


class TestCSVParsing:
    """Tests for CSV-specific parsing."""

    def test_delimiter_autodetection_comma(self, tmp_path):
        """Auto-detect comma delimiter."""
        csv_content = "Reference,Value,Footprint\nR1,10k,0603"
        csv_file = tmp_path / "comma.csv"
        csv_file.write_text(csv_content)

        components, format_info = _parse_csv_bom(csv_file)

        assert format_info["delimiter"] == ","
        assert len(components) == 1

    def test_delimiter_autodetection_semicolon(self, tmp_path):
        """Auto-detect semicolon delimiter."""
        csv_content = "Reference;Value;Footprint\nR1;10k;0603"
        csv_file = tmp_path / "semicolon.csv"
        csv_file.write_text(csv_content)

        components, format_info = _parse_csv_bom(csv_file)

        assert format_info["delimiter"] == ";"
        assert len(components) == 1

    def test_delimiter_autodetection_tab(self, tmp_path):
        """Auto-detect tab delimiter."""
        csv_content = "Reference\tValue\tFootprint\nR1\t10k\t0603"
        csv_file = tmp_path / "tab.tsv"
        csv_file.write_text(csv_content)

        components, format_info = _parse_csv_bom(csv_file, delimiter='\t')

        assert format_info["delimiter"] == "\t"
        assert len(components) == 1

    def test_format_detection_kicad(self, tmp_path):
        """Detect KiCad format from headers."""
        csv_content = "Reference,Value,Footprint,Quantity\nR1,10k,0603,1"
        csv_file = tmp_path / "kicad.csv"
        csv_file.write_text(csv_content)

        components, format_info = _parse_csv_bom(csv_file)

        assert format_info["detected_format"] == "kicad"

    def test_format_detection_altium(self, tmp_path):
        """Detect Altium format from headers."""
        csv_content = "Designator,Comment,Footprint,Quantity\nR1,10k,0603,1"
        csv_file = tmp_path / "altium.csv"
        csv_file.write_text(csv_content)

        components, format_info = _parse_csv_bom(csv_file)

        assert format_info["detected_format"] == "altium"

    def test_format_detection_generic(self, tmp_path):
        """Detect generic format from headers."""
        csv_content = "Part Number,MPN,Description\nRC0603,RC0603FR-0710KL,10k Resistor"
        csv_file = tmp_path / "generic.csv"
        csv_file.write_text(csv_content)

        components, format_info = _parse_csv_bom(csv_file)

        assert format_info["detected_format"] == "generic"

    def test_empty_rows_filtered(self, tmp_path):
        """Empty rows are filtered out."""
        csv_content = "Reference,Value,Footprint\nR1,10k,0603\n,,\nR2,20k,0603"
        csv_file = tmp_path / "with_empty.csv"
        csv_file.write_text(csv_content)

        components, format_info = _parse_csv_bom(csv_file)

        assert len(components) == 2


class TestJSONParsing:
    """Tests for JSON-specific parsing."""

    def test_parse_components_array(self, tmp_path):
        """Parse JSON with components array."""
        json_data = {"components": [{"ref": "R1", "value": "10k"}]}
        json_file = tmp_path / "components.json"
        json_file.write_text(json.dumps(json_data))

        components, format_info = _parse_json_bom(json_file)

        assert len(components) == 1

    def test_parse_parts_array(self, tmp_path):
        """Parse JSON with parts array."""
        json_data = {"parts": [{"ref": "R1", "value": "10k"}]}
        json_file = tmp_path / "parts.json"
        json_file.write_text(json.dumps(json_data))

        components, format_info = _parse_json_bom(json_file)

        assert len(components) == 1

    def test_parse_direct_array(self, tmp_path):
        """Parse JSON that is directly an array."""
        json_data = [{"ref": "R1", "value": "10k"}, {"ref": "R2", "value": "20k"}]
        json_file = tmp_path / "array.json"
        json_file.write_text(json.dumps(json_data))

        components, format_info = _parse_json_bom(json_file)

        assert len(components) == 2


class TestCategoryExtraction:
    """Tests for reference designator category extraction."""

    def test_extract_resistor_category(self):
        """Extract resistor category from R designator."""
        import pandas as pd
        refs = pd.Series(["R1", "R2", "R3"])

        categories = _extract_categories_from_refs(refs)

        assert categories.get("Resistors") == 3

    def test_extract_capacitor_category(self):
        """Extract capacitor category from C designator."""
        import pandas as pd
        refs = pd.Series(["C1", "C2"])

        categories = _extract_categories_from_refs(refs)

        assert categories.get("Capacitors") == 2

    def test_extract_multiple_categories(self):
        """Extract multiple categories."""
        import pandas as pd
        refs = pd.Series(["R1", "C1", "U1", "D1"])

        categories = _extract_categories_from_refs(refs)

        assert categories.get("Resistors") == 1
        assert categories.get("Capacitors") == 1
        assert categories.get("ICs") == 1
        assert categories.get("Diodes") == 1

    def test_extract_comma_separated_refs(self):
        """Handle comma-separated references."""
        import pandas as pd
        refs = pd.Series(["R1, R2, R3"])

        categories = _extract_categories_from_refs(refs)

        assert categories.get("Resistors") == 3

    def test_extract_multichar_prefix(self):
        """Handle multi-character prefixes like SW, TP, LED."""
        import pandas as pd
        refs = pd.Series(["SW1", "TP1", "LED1"])

        categories = _extract_categories_from_refs(refs)

        assert categories.get("Switches") == 1
        assert categories.get("Test Points") == 1
        assert categories.get("LEDs") == 1


class TestAnalyzeBomData:
    """Tests for BOM data analysis."""

    def test_analyze_empty_bom(self):
        """Analyze empty BOM returns defaults."""
        analysis = analyze_bom_data([])

        assert analysis["total_components"] == 0
        assert analysis["unique_components"] == 0

    def test_analyze_component_count(self, sample_csv_bom):
        """Analyze counts components correctly."""
        components, _ = parse_bom_file(str(sample_csv_bom))
        analysis = analyze_bom_data(components)

        assert analysis["unique_components"] == 5

    def test_analyze_categories(self):
        """Analyze extracts categories."""
        components = [
            {"Reference": "R1", "Value": "10k"},
            {"Reference": "R2", "Value": "10k"},
            {"Reference": "C1", "Value": "100nF"},
        ]

        analysis = analyze_bom_data(components)

        assert "Resistors" in analysis["categories"]
        assert "Capacitors" in analysis["categories"]

    def test_analyze_most_common_values(self):
        """Analyze finds most common values."""
        components = [
            {"Reference": "R1", "Value": "10k"},
            {"Reference": "R2", "Value": "10k"},
            {"Reference": "R3", "Value": "10k"},
            {"Reference": "R4", "Value": "1k"},
        ]

        analysis = analyze_bom_data(components)

        assert len(analysis["most_common_values"]) > 0
        assert analysis["most_common_values"][0]["value"] == "10k"
        assert analysis["most_common_values"][0]["count"] == 3


class TestExportBomSummary:
    """Tests for BOM export functionality."""

    def test_export_json_summary(self, tmp_path):
        """Export BOM summary as JSON."""
        components = [
            {"Reference": "R1", "Value": "10k"},
            {"Reference": "C1", "Value": "100nF"},
        ]
        output_path = tmp_path / "summary.json"

        result = export_bom_summary(components, str(output_path))

        assert result is True
        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)
        assert "components" in data
        assert len(data["components"]) == 2

    def test_export_csv_summary(self, tmp_path):
        """Export BOM summary as CSV."""
        components = [
            {"Reference": "R1", "Value": "10k"},
            {"Reference": "C1", "Value": "100nF"},
        ]
        output_path = tmp_path / "summary.csv"

        result = export_bom_summary(components, str(output_path))

        assert result is True
        assert output_path.exists()
