"""
Tests for Constraint Generator

Tests constraint generation logic for different dataset sizes.
"""

import pytest
from core.profiling.constraint_generator import ConstraintGenerator, QueryConstraints


def test_generator_initialization():
    """Generator initializes correctly"""
    generator = ConstraintGenerator()
    assert generator is not None


class TestTinyConstraints:
    """Test constraints for TINY datasets"""

    def setup_method(self):
        self.generator = ConstraintGenerator()

    def test_tiny_generates_strict_constraints(self):
        """TINY should have strictest constraints"""
        constraints = self.generator.generate("tiny")

        assert constraints.size_category == "tiny"
        assert constraints.requires_aggregation == True
        assert constraints.max_filter_complexity <= 1
        # Filters SHOULD be discouraged for tiny datasets
        assert len(constraints.discouraged_filters) > 0

    def test_tiny_allows_aggregations(self):
        """TINY should allow aggregation operations"""
        constraints = self.generator.generate("tiny")

        assert "COUNT" in constraints.allowed_operations
        assert "SUM" in constraints.allowed_operations
        assert "GROUP BY" in constraints.allowed_operations

    def test_tiny_preferred_strategies(self):
        """TINY should prefer safe strategies"""
        constraints = self.generator.generate("tiny")

        assert "temporal_grouping" in constraints.preferred_strategies
        assert "categorical_breakdown" in constraints.preferred_strategies


class TestSmallConstraints:
    """Test constraints for SMALL datasets"""

    def setup_method(self):
        self.generator = ConstraintGenerator()

    def test_small_moderate_constraints(self):
        """SMALL should have moderate constraints"""
        constraints = self.generator.generate("small")

        assert constraints.size_category == "small"
        assert constraints.requires_aggregation == False  # Not required
        assert constraints.max_filter_complexity == 2  # Simple filters OK

    def test_small_discouraged_filters(self):
        """SMALL should discourage some filters"""
        constraints = self.generator.generate("small")

        assert len(constraints.discouraged_filters) > 0


class TestMediumConstraints:
    """Test constraints for MEDIUM datasets"""

    def setup_method(self):
        self.generator = ConstraintGenerator()

    def test_medium_relaxed_constraints(self):
        """MEDIUM should have relaxed constraints"""
        constraints = self.generator.generate("medium")

        assert constraints.size_category == "medium"
        assert constraints.requires_aggregation == False
        assert constraints.max_filter_complexity == 10
        assert len(constraints.discouraged_filters) == 0  # No restrictions


class TestLargeConstraints:
    """Test constraints for LARGE datasets"""

    def setup_method(self):
        self.generator = ConstraintGenerator()

    def test_large_minimal_constraints(self):
        """LARGE should have minimal constraints"""
        constraints = self.generator.generate("large")

        assert constraints.size_category == "large"
        assert len(constraints.discouraged_filters) == 0
        assert constraints.max_filter_complexity >= 10


class TestHugeConstraints:
    """Test constraints for HUGE datasets"""

    def setup_method(self):
        self.generator = ConstraintGenerator()

    def test_huge_performance_focused(self):
        """HUGE should focus on performance"""
        constraints = self.generator.generate("huge")

        assert constraints.size_category == "huge"
        assert (
            "optimization_critical" in constraints.preferred_strategies
            or "sampling" in constraints.preferred_strategies
        )


class TestMultipleDatasets:
    """Test constraint generation for multiple datasets"""

    def setup_method(self):
        self.generator = ConstraintGenerator()

    def test_multiple_uses_smallest(self):
        """Multiple datasets should use smallest size"""
        constraints = self.generator.generate_for_multiple(["tiny", "large", "medium"])

        assert constraints.size_category == "tiny"

    def test_multiple_all_large(self):
        """All large datasets"""
        constraints = self.generator.generate_for_multiple(["large", "large"])

        assert constraints.size_category == "large"

    def test_multiple_empty_list(self):
        """Empty list defaults to tiny"""
        constraints = self.generator.generate_for_multiple([])

        assert constraints.size_category == "tiny"


class TestConstraintSerialization:
    """Test constraint serialization"""

    def setup_method(self):
        self.generator = ConstraintGenerator()

    def test_to_dict(self):
        """Constraints can be serialized to dict"""
        constraints = self.generator.generate("tiny")
        data = constraints.to_dict()

        assert isinstance(data, dict)
        assert data["size_category"] == "tiny"
        assert "allowed_operations" in data
        assert "discouraged_filters" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
