"""
Shared fixtures and configuration for parts-mcp tests.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List

# Test data directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ============================================================================
# Mock API Response Factory
# ============================================================================

class MockAPIResponse:
    """Factory for creating mock API responses."""

    @staticmethod
    def success(data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a successful API response envelope."""
        return {"status": "success", "data": data}

    @staticmethod
    def error(message: str, status_code: int = 400) -> Dict[str, Any]:
        """Create an error API response."""
        return {"status": "error", "error": message}

    @staticmethod
    def search_results(
        parts: List[Dict[str, Any]],
        total: int = None,
        query: str = "test",
        limit: int = 25,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Create a search results response."""
        return MockAPIResponse.success({
            "parts": parts,
            "total": total if total is not None else len(parts),
            "limit": limit,
            "offset": offset,
            "query": query
        })

    @staticmethod
    def part_details(
        part_number: str = "STM32F407VGT6",
        manufacturer: str = "STMicroelectronics",
        category: str = "Microcontrollers",
        **kwargs
    ) -> Dict[str, Any]:
        """Create a part details response."""
        part_data = {
            "part_number": part_number,
            "manufacturer": manufacturer,
            "category": category,
            "description": f"{category} component",
            **kwargs
        }
        return MockAPIResponse.success(part_data)

    @staticmethod
    def inventory(
        part_number: str = "STM32F407VGT6",
        quantity: int = 100,
        minimum_quantity: int = 10,
        location: str = "Bin A-12"
    ) -> Dict[str, Any]:
        """Create an inventory response."""
        return MockAPIResponse.success({
            "part_number": part_number,
            "quantity": quantity,
            "minimum_quantity": minimum_quantity,
            "location": location
        })

    @staticmethod
    def pricing(
        part_number: str = "STM32F407VGT6",
        price_breaks: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a pricing response."""
        if price_breaks is None:
            price_breaks = [
                {"quantity": 1, "unit_price": 15.50},
                {"quantity": 10, "unit_price": 14.00},
                {"quantity": 100, "unit_price": 12.50}
            ]
        return MockAPIResponse.success({
            "part_number": part_number,
            "currency": "USD",
            "price_breaks": price_breaks
        })


# ============================================================================
# Sample Part Data
# ============================================================================

@pytest.fixture
def sample_parts():
    """Sample part data for testing."""
    return [
        {
            "part_number": "STM32F407VGT6",
            "manufacturer": "STMicroelectronics",
            "category": "Microcontrollers",
            "description": "ARM Cortex-M4 32-bit MCU",
            "package": "LQFP100"
        },
        {
            "part_number": "LM7805",
            "manufacturer": "Texas Instruments",
            "category": "Voltage Regulators",
            "description": "5V Linear Regulator",
            "package": "TO-220"
        },
        {
            "part_number": "RC0603FR-0710KL",
            "manufacturer": "Yageo",
            "category": "Resistors",
            "description": "10k Ohm 1% 0603",
            "value": "10k",
            "package": "0603"
        }
    ]


@pytest.fixture
def mock_api_response():
    """Provide the MockAPIResponse factory."""
    return MockAPIResponse


# ============================================================================
# Mock HTTP Client
# ============================================================================

@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx client."""
    with patch('parts_mcp.utils.api_client.httpx.Client') as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_api_client(mock_httpx_client, mock_api_response):
    """Create a mock SourcePartsClient with mocked HTTP."""
    from parts_mcp.utils.api_client import SourcePartsClient

    # Configure the mock client
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_api_response.search_results([])
    mock_httpx_client.request.return_value = mock_response

    # Create client with test API key
    with patch.dict('os.environ', {'SOURCE_PARTS_API_KEY': 'test-api-key'}):
        client = SourcePartsClient(api_key='test-api-key')
        client._mock_http = mock_httpx_client
        client._mock_response = mock_response
        yield client


# ============================================================================
# Sample BOM Data
# ============================================================================

@pytest.fixture
def sample_csv_bom(tmp_path):
    """Create a sample CSV BOM file."""
    bom_content = """Reference,Value,Footprint,Quantity,Manufacturer,MPN
R1,10k,0603,1,Yageo,RC0603FR-0710KL
R2,10k,0603,1,Yageo,RC0603FR-0710KL
C1,100nF,0603,1,Murata,GRM188R71H104KA93D
C2,10uF,0805,1,Samsung,CL21A106KAYNNNE
U1,STM32F407VGT6,LQFP100,1,STMicroelectronics,STM32F407VGT6
"""
    bom_file = tmp_path / "test_bom.csv"
    bom_file.write_text(bom_content)
    return bom_file


@pytest.fixture
def sample_json_bom(tmp_path):
    """Create a sample JSON BOM file."""
    bom_data = {
        "components": [
            {
                "reference": "R1",
                "value": "10k",
                "footprint": "0603",
                "quantity": 1,
                "mpn": "RC0603FR-0710KL"
            },
            {
                "reference": "C1",
                "value": "100nF",
                "footprint": "0603",
                "quantity": 1,
                "mpn": "GRM188R71H104KA93D"
            }
        ]
    }
    bom_file = tmp_path / "test_bom.json"
    bom_file.write_text(json.dumps(bom_data, indent=2))
    return bom_file


@pytest.fixture
def sample_xml_bom(tmp_path):
    """Create a sample XML BOM file."""
    bom_content = """<?xml version="1.0" encoding="UTF-8"?>
<bom>
    <component reference="R1">
        <value>10k</value>
        <footprint>0603</footprint>
        <mpn>RC0603FR-0710KL</mpn>
    </component>
    <component reference="C1">
        <value>100nF</value>
        <footprint>0603</footprint>
        <mpn>GRM188R71H104KA93D</mpn>
    </component>
</bom>
"""
    bom_file = tmp_path / "test_bom.xml"
    bom_file.write_text(bom_content)
    return bom_file


# ============================================================================
# Cache Fixtures
# ============================================================================

@pytest.fixture
def clean_cache():
    """Ensure cache is clean before and after tests."""
    from parts_mcp.utils.cache import clear_all_cache
    clear_all_cache()
    yield
    clear_all_cache()


@pytest.fixture
def mock_cache(tmp_path):
    """Use a temporary cache directory for tests."""
    import diskcache
    test_cache = diskcache.Cache(str(tmp_path / "test_cache"))
    with patch('parts_mcp.utils.cache.cache', test_cache):
        yield test_cache
    test_cache.close()


# ============================================================================
# KiCad Fixtures
# ============================================================================

@pytest.fixture
def sample_kicad_project(tmp_path):
    """Create a minimal KiCad project structure."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    # Create a minimal .kicad_pro file
    pro_file = project_dir / "test_project.kicad_pro"
    pro_file.write_text('{"meta": {"version": 1}}')

    # Create a minimal .kicad_sch file
    sch_file = project_dir / "test_project.kicad_sch"
    sch_file.write_text('(kicad_sch (version 20230121) (generator eeschema))')

    return project_dir


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def fixtures_dir():
    """Return the path to the fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the API client singleton between tests."""
    import parts_mcp.utils.api_client as api_client
    api_client._client_instance = None
    yield
    api_client._client_instance = None
