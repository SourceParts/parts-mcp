"""
Unit tests for component matching utilities.
"""
import pytest

from parts_mcp.utils.component_matcher import (
    MATCH_WEIGHTS,
    MatchResult,
    MatchStatistics,
    match_component,
    match_components_batch,
)


@pytest.fixture
def sample_bom_component():
    """Sample BOM component for testing."""
    return {
        "Reference": "R1",
        "Value": "10k",
        "Footprint": "0603",
        "MPN": "RC0603FR-0710KL",
        "Manufacturer": "Yageo"
    }


@pytest.fixture
def sample_candidates():
    """Sample candidate parts for matching."""
    return [
        {
            "part_number": "RC0603FR-0710KL",
            "manufacturer": "Yageo",
            "category": "Resistors",
            "value": "10k",
            "package": "0603",
            "description": "RES SMD 10K OHM 1% 0.1W 0603"
        },
        {
            "part_number": "CRCW060310K0FKEA",
            "manufacturer": "Vishay",
            "category": "Resistors",
            "value": "10k",
            "package": "0603",
            "description": "RES SMD 10K OHM 1% 0.1W 0603"
        },
        {
            "part_number": "RC0805FR-0710KL",
            "manufacturer": "Yageo",
            "category": "Resistors",
            "value": "10k",
            "package": "0805",
            "description": "RES SMD 10K OHM 1% 0.125W 0805"
        }
    ]


class TestMatchComponent:
    """Tests for match_component function."""

    def test_exact_mpn_match(self, sample_bom_component, sample_candidates):
        """Exact MPN match gives high confidence."""
        result = match_component(sample_bom_component, sample_candidates)

        assert result.matched_part is not None
        assert result.matched_part["part_number"] == "RC0603FR-0710KL"
        assert result.confidence >= 0.9

    def test_no_candidates_returns_no_match(self, sample_bom_component):
        """No candidates returns no match."""
        result = match_component(sample_bom_component, [])

        assert result.matched_part is None
        assert result.confidence == 0.0
        assert result.is_no_match

    def test_partial_match_gives_lower_confidence(self):
        """Partial match gives lower confidence than exact."""
        bom_component = {
            "Value": "10k",
            "Footprint": "0603"
        }
        candidates = [
            {
                "value": "20k",  # Different value
                "package": "0603",
                "part_number": "GENERIC20K"
            }
        ]

        result = match_component(bom_component, candidates)

        assert result.matched_part is not None
        assert result.confidence > 0
        assert result.confidence < 1.0

    def test_wrong_footprint_lowers_confidence(self, sample_candidates):
        """Wrong footprint lowers confidence."""
        bom_component = {
            "Value": "10k",
            "Footprint": "0402",  # Different from candidates
            "MPN": "GENERIC"
        }

        result = match_component(bom_component, sample_candidates)

        # Should still match on value but footprint mismatch lowers score
        assert result.match_details.get("footprint", 0) < 0.5

    def test_match_details_populated(self, sample_bom_component, sample_candidates):
        """Match details contain scoring breakdown."""
        result = match_component(sample_bom_component, sample_candidates)

        assert "mpn" in result.match_details or "value" in result.match_details
        assert all(0 <= v <= 1 for v in result.match_details.values())


class TestMatchResult:
    """Tests for MatchResult class."""

    def test_high_confidence_threshold(self):
        """High confidence is >= 80%."""
        result = MatchResult(
            bom_component={},
            matched_part={"id": 1},
            confidence=0.85,
            match_details={}
        )
        assert result.is_high_confidence
        assert not result.is_medium_confidence
        assert not result.is_low_confidence

    def test_medium_confidence_threshold(self):
        """Medium confidence is 50-79%."""
        result = MatchResult(
            bom_component={},
            matched_part={"id": 1},
            confidence=0.65,
            match_details={}
        )
        assert not result.is_high_confidence
        assert result.is_medium_confidence
        assert not result.is_low_confidence

    def test_low_confidence_threshold(self):
        """Low confidence is < 50%."""
        result = MatchResult(
            bom_component={},
            matched_part={"id": 1},
            confidence=0.35,
            match_details={}
        )
        assert not result.is_high_confidence
        assert not result.is_medium_confidence
        assert result.is_low_confidence

    def test_no_match(self):
        """No match when matched_part is None."""
        result = MatchResult(
            bom_component={},
            matched_part=None,
            confidence=0,
            match_details={}
        )
        assert result.is_no_match


class TestMatchComponentsBatch:
    """Tests for batch matching."""

    def test_batch_returns_statistics(self):
        """Batch matching returns statistics."""
        bom_components = [
            {"Value": "10k", "MPN": "TEST1"},
            {"Value": "100nF", "MPN": "TEST2"}
        ]

        def mock_search(query):
            return [{"value": "10k", "part_number": query}]

        results, stats = match_components_batch(bom_components, mock_search)

        assert len(results) == 2
        assert isinstance(stats, MatchStatistics)
        assert stats.total == 2

    def test_batch_handles_search_failure(self):
        """Batch handles search function failures."""
        bom_components = [{"Value": "10k"}]

        def failing_search(query):
            raise Exception("Search failed")

        results, stats = match_components_batch(bom_components, failing_search)

        assert len(results) == 1
        assert results[0].is_no_match
        assert "Search failed" in results[0].warnings[0]


class TestMatchStatistics:
    """Tests for MatchStatistics."""

    def test_statistics_calculation(self):
        """Statistics are calculated correctly."""
        stats = MatchStatistics(
            total=10,
            high_confidence=5,
            medium_confidence=3,
            low_confidence=1,
            no_match=1,
            average_confidence=0.72
        )

        assert stats.total == 10
        assert stats.high_confidence == 5
        assert stats.average_confidence == 0.72


class TestMatchWeights:
    """Tests for match weight configuration."""

    def test_default_weights_sum_to_one(self):
        """Default weights sum to 1.0."""
        total = sum(MATCH_WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_custom_weights_used(self, sample_bom_component, sample_candidates):
        """Custom weights affect scoring."""
        # Weight MPN very heavily
        custom_weights = {
            'mpn': 0.90,
            'value': 0.05,
            'footprint': 0.02,
            'manufacturer': 0.02,
            'description': 0.01
        }

        result = match_component(
            sample_bom_component,
            sample_candidates,
            weights=custom_weights
        )

        # With heavy MPN weight, should get very high confidence on exact match
        assert result.confidence >= 0.85
