"""
Component matching utilities for BOM processing.

This module provides component matching with confidence scoring.

Architecture:
- By default, matching is offloaded to the Source Parts API
- Local matching is available as a fallback when API is unavailable
- Lightweight utilities (value_parser, footprint_matcher) remain local

Usage:
    # API-based matching (preferred)
    result = match_component_via_api(component)
    results, stats = match_components_batch_via_api(components)

    # Local matching (fallback)
    result = match_component_local(component, candidates)
"""
import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from .footprint_matcher import footprints_compatible, parse_footprint
from .value_parser import parse_value, values_match

logger = logging.getLogger(__name__)

# Flag to control whether to use API or local matching
USE_API_MATCHING = True


# ============================================================================
# API-Based Matching (Preferred)
# ============================================================================

def match_component_via_api(
    component: dict[str, Any],
    max_results: int = 5,
    search_depth: str = "standard"
) -> "MatchResult":
    """Match a component using the Source Parts API.

    This offloads confidence scoring and matching logic to the API.

    Args:
        component: Component data with reference, value, footprint, manufacturer
        max_results: Maximum number of matches to return
        search_depth: Search depth: "quick", "standard", or "deep"

    Returns:
        MatchResult with best match and confidence score
    """
    from .api_client import SourcePartsAPIError, get_client

    try:
        client = get_client()
        response = client.match_component(component, max_results, search_depth)

        # Convert API response to MatchResult
        matches = response.get("matches", [])
        if matches:
            best = matches[0]
            return MatchResult(
                bom_component=component,
                matched_part=best.get("part"),
                confidence=best.get("confidence", 0.0),
                match_details=best.get("match_breakdown", {}),
                warnings=best.get("warnings", [])
            )
        else:
            return MatchResult(
                bom_component=component,
                matched_part=None,
                confidence=0.0,
                match_details={},
                warnings=["No matches found"]
            )

    except SourcePartsAPIError as e:
        logger.warning(f"API matching failed, falling back to local: {e}")
        # Fallback to local matching is handled by caller
        raise


def match_components_batch_via_api(
    components: list[dict[str, Any]],
    search_depth: str = "standard"
) -> tuple[list["MatchResult"], "MatchStatistics"]:
    """Batch match components using the Source Parts API.

    This offloads batch matching and confidence scoring to the API.

    Args:
        components: List of components with reference, value, footprint, manufacturer
        search_depth: Search depth: "quick", "standard", or "deep"

    Returns:
        Tuple of (match results, statistics)
    """
    from .api_client import SourcePartsAPIError, get_client

    try:
        client = get_client()
        response = client.match_components_batch(components, search_depth)

        # Convert API response to MatchResult list
        results = []
        api_matches = response.get("matches", [])

        for match_data in api_matches:
            bom_component = match_data.get("component", {})
            matched_part = match_data.get("matched_part")
            confidence = match_data.get("confidence", 0.0)
            breakdown = match_data.get("match_breakdown", {})
            warnings = match_data.get("warnings", [])

            results.append(MatchResult(
                bom_component=bom_component,
                matched_part=matched_part,
                confidence=confidence,
                match_details=breakdown,
                warnings=warnings
            ))

        # Convert API statistics
        api_stats = response.get("statistics", {})
        stats = MatchStatistics(
            total=api_stats.get("total", len(results)),
            high_confidence=api_stats.get("high_confidence", 0),
            medium_confidence=api_stats.get("medium_confidence", 0),
            low_confidence=api_stats.get("low_confidence", 0),
            no_match=api_stats.get("no_match", 0),
            average_confidence=api_stats.get("average_confidence", 0.0)
        )

        return results, stats

    except SourcePartsAPIError as e:
        logger.warning(f"API batch matching failed: {e}")
        raise


# ============================================================================
# Wrapper Functions (Use API or Local based on configuration)
# ============================================================================

def match_component(
    bom_component: dict[str, Any],
    candidate_parts: list[dict[str, Any]] | None = None,
    weights: dict[str, float] | None = None,
    use_api: bool | None = None
) -> "MatchResult":
    """Match a BOM component to database parts.

    By default, uses the API for matching. Falls back to local matching
    if API is unavailable or if candidate_parts are provided.

    Args:
        bom_component: The BOM component to match
        candidate_parts: Optional list of candidate parts (forces local matching)
        weights: Optional custom weights for scoring factors (local only)
        use_api: Override USE_API_MATCHING setting

    Returns:
        MatchResult with best match and confidence score
    """
    should_use_api = use_api if use_api is not None else USE_API_MATCHING

    # If candidate_parts provided, must use local matching
    if candidate_parts is not None:
        return match_component_local(bom_component, candidate_parts, weights)

    # Try API matching
    if should_use_api:
        try:
            return match_component_via_api(bom_component)
        except Exception as e:
            logger.warning(f"API matching failed, no fallback candidates: {e}")
            return MatchResult(
                bom_component=bom_component,
                matched_part=None,
                confidence=0.0,
                match_details={},
                warnings=[f"API matching failed: {str(e)}"]
            )

    # No candidates and API disabled
    return MatchResult(
        bom_component=bom_component,
        matched_part=None,
        confidence=0.0,
        match_details={},
        warnings=["No candidate parts and API matching disabled"]
    )


def match_components_batch(
    bom_components: list[dict[str, Any]],
    search_func=None,
    weights: dict[str, float] | None = None,
    use_api: bool | None = None
) -> tuple[list["MatchResult"], "MatchStatistics"]:
    """Match a batch of BOM components.

    By default, uses the API for batch matching. Falls back to local matching
    if API is unavailable or if search_func is provided.

    Args:
        bom_components: List of BOM components to match
        search_func: Optional search function (forces local matching)
        weights: Optional custom weights for scoring (local only)
        use_api: Override USE_API_MATCHING setting

    Returns:
        Tuple of (match results, statistics)
    """
    should_use_api = use_api if use_api is not None else USE_API_MATCHING

    # If search_func provided, must use local matching
    if search_func is not None:
        return match_components_batch_local(bom_components, search_func, weights)

    # Try API matching
    if should_use_api:
        try:
            return match_components_batch_via_api(bom_components)
        except Exception as e:
            logger.warning(f"API batch matching failed: {e}")
            # Return empty results with error
            results = [
                MatchResult(
                    bom_component=comp,
                    matched_part=None,
                    confidence=0.0,
                    match_details={},
                    warnings=[f"API matching failed: {str(e)}"]
                )
                for comp in bom_components
            ]
            stats = _calculate_statistics(results)
            return results, stats

    # No search_func and API disabled
    results = [
        MatchResult(
            bom_component=comp,
            matched_part=None,
            confidence=0.0,
            match_details={},
            warnings=["No search function and API matching disabled"]
        )
        for comp in bom_components
    ]
    stats = _calculate_statistics(results)
    return results, stats


# ============================================================================
# Local Matching (Fallback)
# ============================================================================

# Confidence score weights for different match factors
MATCH_WEIGHTS = {
    'mpn': 0.40,           # Manufacturer Part Number (most important)
    'value': 0.25,         # Component value
    'footprint': 0.20,     # Package/footprint
    'manufacturer': 0.10,  # Manufacturer name
    'description': 0.05,   # Description similarity
}


@dataclass
class MatchResult:
    """Result of matching a BOM component to a database part."""
    bom_component: dict[str, Any]
    matched_part: dict[str, Any] | None
    confidence: float
    match_details: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_high_confidence(self) -> bool:
        """Check if this is a high-confidence match (>= 80%)."""
        return self.confidence >= 0.80

    @property
    def is_medium_confidence(self) -> bool:
        """Check if this is a medium-confidence match (50-79%)."""
        return 0.50 <= self.confidence < 0.80

    @property
    def is_low_confidence(self) -> bool:
        """Check if this is a low-confidence match (< 50%)."""
        return self.confidence < 0.50 and self.matched_part is not None

    @property
    def is_no_match(self) -> bool:
        """Check if no match was found."""
        return self.matched_part is None


@dataclass
class MatchStatistics:
    """Statistics for a batch matching operation."""
    total: int
    high_confidence: int
    medium_confidence: int
    low_confidence: int
    no_match: int
    average_confidence: float


def match_component_local(
    bom_component: dict[str, Any],
    candidate_parts: list[dict[str, Any]],
    weights: dict[str, float] | None = None
) -> MatchResult:
    """Match a BOM component against a list of candidate parts (local matching).

    Calculates a confidence score based on multiple factors:
    - MPN match (40%)
    - Value match (25%)
    - Footprint compatibility (20%)
    - Manufacturer match (10%)
    - Description similarity (5%)

    Note: This is the local fallback. Prefer match_component() which uses the API.

    Args:
        bom_component: The BOM component to match
        candidate_parts: List of candidate parts from database
        weights: Optional custom weights for scoring factors

    Returns:
        MatchResult with best match and confidence score
    """
    if not candidate_parts:
        return MatchResult(
            bom_component=bom_component,
            matched_part=None,
            confidence=0.0,
            match_details={},
            warnings=["No candidate parts provided"]
        )

    weights = weights or MATCH_WEIGHTS

    # Extract component fields
    bom_mpn = _get_mpn(bom_component)
    bom_value = _get_value(bom_component)
    bom_footprint = _get_footprint(bom_component)
    bom_manufacturer = _get_manufacturer(bom_component)
    bom_description = _get_description(bom_component)

    best_match = None
    best_score = 0.0
    best_details = {}
    warnings = []

    for candidate in candidate_parts:
        score, details = _calculate_match_score(
            bom_mpn=bom_mpn,
            bom_value=bom_value,
            bom_footprint=bom_footprint,
            bom_manufacturer=bom_manufacturer,
            bom_description=bom_description,
            candidate=candidate,
            weights=weights
        )

        if score > best_score:
            best_score = score
            best_match = candidate
            best_details = details

    # Add warnings for partial matches
    if best_match and best_score < 0.80:
        if best_details.get('mpn', 0) < 0.5 and bom_mpn:
            warnings.append(f"MPN '{bom_mpn}' did not match exactly")
        if best_details.get('footprint', 0) < 0.5 and bom_footprint:
            warnings.append(f"Footprint '{bom_footprint}' may not be compatible")
        if best_details.get('value', 0) < 0.5 and bom_value:
            warnings.append(f"Value '{bom_value}' did not match")

    return MatchResult(
        bom_component=bom_component,
        matched_part=best_match,
        confidence=best_score,
        match_details=best_details,
        warnings=warnings
    )


def match_components_batch_local(
    bom_components: list[dict[str, Any]],
    search_func,
    weights: dict[str, float] | None = None
) -> tuple[list[MatchResult], MatchStatistics]:
    """Match a batch of BOM components using a local search function.

    Note: This is the local fallback. Prefer match_components_batch() which uses the API.

    Args:
        bom_components: List of BOM components to match
        search_func: Function that takes a query and returns candidate parts
        weights: Optional custom weights for scoring

    Returns:
        Tuple of (match results, statistics)
    """
    results = []

    for component in bom_components:
        # Build search query from component data
        query = _build_search_query(component)

        if not query:
            results.append(MatchResult(
                bom_component=component,
                matched_part=None,
                confidence=0.0,
                match_details={},
                warnings=["Could not build search query"]
            ))
            continue

        # Search for candidates
        try:
            candidates = search_func(query)
        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            results.append(MatchResult(
                bom_component=component,
                matched_part=None,
                confidence=0.0,
                match_details={},
                warnings=[f"Search failed: {str(e)}"]
            ))
            continue

        # Match against candidates (use local matching)
        result = match_component_local(component, candidates, weights)
        results.append(result)

    # Calculate statistics
    stats = _calculate_statistics(results)

    return results, stats


def _calculate_match_score(
    bom_mpn: str | None,
    bom_value: str | None,
    bom_footprint: str | None,
    bom_manufacturer: str | None,
    bom_description: str | None,
    candidate: dict[str, Any],
    weights: dict[str, float]
) -> tuple[float, dict[str, float]]:
    """Calculate match score between BOM component and candidate part."""
    details = {}
    total_weight = 0.0
    total_score = 0.0

    # MPN match
    if bom_mpn:
        candidate_mpn = _get_mpn(candidate)
        if candidate_mpn:
            mpn_score = _string_similarity(bom_mpn, candidate_mpn)
            details['mpn'] = mpn_score
            total_score += mpn_score * weights['mpn']
            total_weight += weights['mpn']

    # Value match
    if bom_value:
        candidate_value = _get_value(candidate)
        if candidate_value:
            value_score = 1.0 if values_match(bom_value, candidate_value, tolerance_pct=5.0) else 0.0
            # Partial credit for close matches
            if value_score == 0.0:
                parsed_bom = parse_value(bom_value)
                parsed_cand = parse_value(candidate_value)
                if parsed_bom.numeric_value and parsed_cand.numeric_value:
                    ratio = min(parsed_bom.numeric_value, parsed_cand.numeric_value) / \
                            max(parsed_bom.numeric_value, parsed_cand.numeric_value)
                    if ratio > 0.5:
                        value_score = ratio * 0.5  # Partial credit
            details['value'] = value_score
            total_score += value_score * weights['value']
            total_weight += weights['value']

    # Footprint match
    if bom_footprint:
        candidate_footprint = _get_footprint(candidate)
        if candidate_footprint:
            footprint_score = 1.0 if footprints_compatible(bom_footprint, candidate_footprint) else 0.0
            details['footprint'] = footprint_score
            total_score += footprint_score * weights['footprint']
            total_weight += weights['footprint']

    # Manufacturer match
    if bom_manufacturer:
        candidate_mfr = _get_manufacturer(candidate)
        if candidate_mfr:
            mfr_score = _string_similarity(bom_manufacturer, candidate_mfr)
            details['manufacturer'] = mfr_score
            total_score += mfr_score * weights['manufacturer']
            total_weight += weights['manufacturer']

    # Description match
    if bom_description:
        candidate_desc = _get_description(candidate)
        if candidate_desc:
            desc_score = _string_similarity(bom_description, candidate_desc)
            details['description'] = desc_score
            total_score += desc_score * weights['description']
            total_weight += weights['description']

    # Normalize score
    final_score = total_score / total_weight if total_weight > 0 else 0.0

    return final_score, details


def _string_similarity(s1: str, s2: str) -> float:
    """Calculate similarity between two strings."""
    if not s1 or not s2:
        return 0.0

    # Normalize strings
    s1 = s1.upper().strip()
    s2 = s2.upper().strip()

    # Exact match
    if s1 == s2:
        return 1.0

    # Use SequenceMatcher for similarity
    return SequenceMatcher(None, s1, s2).ratio()


def _get_mpn(component: dict[str, Any]) -> str | None:
    """Extract MPN from component data."""
    for key in ['mpn', 'MPN', 'Mpn', 'part_number', 'Part Number',
                'manufacturer_part_number', 'Manufacturer Part Number']:
        if key in component and component[key]:
            return str(component[key]).strip()
    return None


def _get_value(component: dict[str, Any]) -> str | None:
    """Extract value from component data."""
    for key in ['value', 'Value', 'VALUE', 'comment', 'Comment']:
        if key in component and component[key]:
            return str(component[key]).strip()
    return None


def _get_footprint(component: dict[str, Any]) -> str | None:
    """Extract footprint from component data."""
    for key in ['footprint', 'Footprint', 'FOOTPRINT',
                'package', 'Package', 'case', 'Case']:
        if key in component and component[key]:
            return str(component[key]).strip()
    return None


def _get_manufacturer(component: dict[str, Any]) -> str | None:
    """Extract manufacturer from component data."""
    for key in ['manufacturer', 'Manufacturer', 'MANUFACTURER',
                'mfr', 'Mfr', 'mfg', 'Mfg']:
        if key in component and component[key]:
            return str(component[key]).strip()
    return None


def _get_description(component: dict[str, Any]) -> str | None:
    """Extract description from component data."""
    for key in ['description', 'Description', 'DESCRIPTION',
                'desc', 'Desc']:
        if key in component and component[key]:
            return str(component[key]).strip()
    return None


def _build_search_query(component: dict[str, Any]) -> str | None:
    """Build a search query from component data."""
    # Try MPN first (most specific)
    mpn = _get_mpn(component)
    if mpn:
        return mpn

    # Try value + footprint combination
    value = _get_value(component)
    footprint = _get_footprint(component)

    if value:
        query_parts = [value]
        if footprint:
            # Add just the size part of footprint
            parsed_fp = parse_footprint(footprint)
            if parsed_fp.size_imperial:
                query_parts.append(parsed_fp.size_imperial)
        return ' '.join(query_parts)

    # Fall back to description
    description = _get_description(component)
    if description:
        return description

    return None


def _calculate_statistics(results: list[MatchResult]) -> MatchStatistics:
    """Calculate statistics from match results."""
    total = len(results)
    if total == 0:
        return MatchStatistics(
            total=0,
            high_confidence=0,
            medium_confidence=0,
            low_confidence=0,
            no_match=0,
            average_confidence=0.0
        )

    high_conf = sum(1 for r in results if r.is_high_confidence)
    med_conf = sum(1 for r in results if r.is_medium_confidence)
    low_conf = sum(1 for r in results if r.is_low_confidence)
    no_match = sum(1 for r in results if r.is_no_match)

    avg_conf = sum(r.confidence for r in results) / total

    return MatchStatistics(
        total=total,
        high_confidence=high_conf,
        medium_confidence=med_conf,
        low_confidence=low_conf,
        no_match=no_match,
        average_confidence=avg_conf
    )
