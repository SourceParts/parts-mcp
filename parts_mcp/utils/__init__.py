"""Utilities module for parts-mcp."""

from .api_client import (
    SourcePartsClient,
    SourcePartsAPIError,
    SourcePartsAuthError,
    SourcePartsRateLimitError,
    get_client,
    close_client
)

from .bom_parser import (
    parse_bom_file,
    analyze_bom_data,
    export_bom_summary
)

from .cache import (
    cached,
    cache_get,
    cache_set,
    cache_delete,
    clear_cache_prefix,
    clear_all_cache,
    get_cache_stats,
    cache_search_results,
    cache_part_details
)

from .value_parser import (
    parse_value,
    normalize_value,
    values_match,
    ParsedValue
)

from .footprint_matcher import (
    parse_footprint,
    footprints_compatible,
    normalize_footprint,
    get_equivalent_sizes,
    ParsedFootprint
)

from .component_matcher import (
    match_component,
    match_components_batch,
    MatchResult,
    MatchStatistics
)

from .kicad_utils import (
    find_kicad_projects,
    get_project_files,
    extract_project_info,
    find_kicad_cli,
    run_kicad_cli,
    get_kicad_version,
    generate_bom_from_schematic,
    generate_netlist,
    validate_kicad_installation
)

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
