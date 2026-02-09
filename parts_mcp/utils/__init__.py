"""Utilities module for parts-mcp."""

from .api_client import (
    SourcePartsAPIError,
    SourcePartsAuthError,
    SourcePartsClient,
    SourcePartsRateLimitError,
    close_client,
    get_client,
)
from .bom_parser import analyze_bom_data, export_bom_summary, parse_bom_file
from .cache import (
    cache_delete,
    cache_get,
    cache_part_details,
    cache_search_results,
    cache_set,
    cached,
    clear_all_cache,
    clear_cache_prefix,
    get_cache_stats,
)
from .component_matcher import MatchResult, MatchStatistics, match_component, match_components_batch
from .footprint_matcher import (
    ParsedFootprint,
    footprints_compatible,
    get_equivalent_sizes,
    normalize_footprint,
    parse_footprint,
)
from .kicad_utils import (
    extract_project_info,
    find_kicad_cli,
    find_kicad_projects,
    generate_bom_from_schematic,
    generate_netlist,
    get_kicad_version,
    get_project_files,
    run_kicad_cli,
    validate_kicad_installation,
)
from .value_parser import ParsedValue, normalize_value, parse_value, values_match

__all__ = [
    # API Client
    "SourcePartsClient",
    "SourcePartsAPIError",
    "SourcePartsAuthError",
    "SourcePartsRateLimitError",
    "get_client",
    "close_client",
    # BOM Parser
    "parse_bom_file",
    "analyze_bom_data",
    "export_bom_summary",
    # Cache
    "cached",
    "cache_get",
    "cache_set",
    "cache_delete",
    "clear_cache_prefix",
    "clear_all_cache",
    "get_cache_stats",
    "cache_search_results",
    "cache_part_details",
    # Value Parser
    "parse_value",
    "normalize_value",
    "values_match",
    "ParsedValue",
    # Footprint Matcher
    "parse_footprint",
    "footprints_compatible",
    "normalize_footprint",
    "get_equivalent_sizes",
    "ParsedFootprint",
    # Component Matcher
    "match_component",
    "match_components_batch",
    "MatchResult",
    "MatchStatistics",
    # KiCad Utils
    "find_kicad_projects",
    "get_project_files",
    "extract_project_info",
    "find_kicad_cli",
    "run_kicad_cli",
    "get_kicad_version",
    "generate_bom_from_schematic",
    "generate_netlist",
    "validate_kicad_installation",
]
