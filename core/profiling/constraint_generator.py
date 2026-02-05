"""
Query Constraint Generator

Generates execution constraints based on dataset size.
Provides rules for safe query generation on small/large datasets.
"""
from __future__ import annotations
from typing import Set, List, Dict
from dataclasses import dataclass
from core.profiling.dataset_profiler import DatasetSize


@dataclass
class QueryConstraints:
    """
    Constraints for query generation based on dataset size.
    
    Attributes:
        size_category: Dataset size (tiny/small/medium/large/huge)
        allowed_operations: Set of allowed SQL operations
        discouraged_filters: Set of filter patterns to avoid
        preferred_strategies: List of recommended query strategies
        requires_aggregation: Whether aggregation is mandatory
        max_filter_complexity: Maximum allowed filter complexity
    """
    size_category: DatasetSize
    allowed_operations: Set[str]
    discouraged_filters: Set[str]
    preferred_strategies: List[str]
    requires_aggregation: bool = False
    max_filter_complexity: int = 10
    
    def to_dict(self) -> Dict:
        """Convert to dict for logging/serialization"""
        return {
            "size_category": self.size_category,
            "allowed_operations": list(self.allowed_operations),
            "discouraged_filters": list(self.discouraged_filters),
            "preferred_strategies": self.preferred_strategies,
            "requires_aggregation": self.requires_aggregation,
            "max_filter_complexity": self.max_filter_complexity,
        }


class ConstraintGenerator:
    """
    Generates query constraints based on dataset size.
    
    Strategy:
    - TINY: Strict constraints, avoid filters, require aggregations
    - SMALL: Moderate constraints, prefer aggregations
    - MEDIUM: Relaxed constraints, most queries safe
    - LARGE/HUGE: Minimal constraints, optimize for performance
    """
    
    def generate(self, size_category: DatasetSize) -> QueryConstraints:
        """
        Generate constraints for a given dataset size.
        
        Args:
            size_category: Dataset size category
            
        Returns:
            QueryConstraints instance with appropriate rules
        """
        if size_category == "tiny":
            return self._tiny_constraints()
        elif size_category == "small":
            return self._small_constraints()
        elif size_category == "medium":
            return self._medium_constraints()
        elif size_category == "large":
            return self._large_constraints()
        else:  # huge
            return self._huge_constraints()
    
    def _tiny_constraints(self) -> QueryConstraints:
        """
        Constraints for TINY datasets (< 100 rows).
        
        Strategy: Avoid filters entirely, use aggregations and groupings
        """
        return QueryConstraints(
            size_category="tiny",
            allowed_operations={
                "COUNT", "SUM", "AVG", "MIN", "MAX",
                "GROUP BY", "ORDER BY", "LIMIT"
            },
            discouraged_filters={
                "WHERE date >",
                "WHERE date <",
                "WHERE status =",
                "WHERE amount >",
                "WHERE amount <",
                "WHERE [column] =",  # Any equality filter
                "WHERE [column] IN",  # Any IN filter
                "HAVING",  # Post-aggregation filters
            },
            preferred_strategies=[
                "temporal_grouping",  # GROUP BY month/year
                "categorical_breakdown",  # GROUP BY category/status
                "ranking",  # TOP N queries
                "proportion_analysis",  # Percentage breakdowns
                "comparative_metrics",  # Avg by segment
            ],
            requires_aggregation=True,
            max_filter_complexity=0,  # No filters
        )
    
    def _small_constraints(self) -> QueryConstraints:
        """
        Constraints for SMALL datasets (100-1000 rows).
        
        Strategy: Prefer aggregations, allow simple filters cautiously
        """
        return QueryConstraints(
            size_category="small",
            allowed_operations={
                "COUNT", "SUM", "AVG", "MIN", "MAX",
                "GROUP BY", "ORDER BY", "LIMIT",
                "CASE WHEN",  # Conditional logic
            },
            discouraged_filters={
                "WHERE date > recent",  # Recent time filters risky
                "WHERE amount > high_threshold",  # High thresholds risky
                "HAVING COUNT(*) <",  # Post-aggregation filters
            },
            preferred_strategies=[
                "temporal_grouping",
                "categorical_breakdown",
                "ranking",
                "segmentation",  # Divide into segments
            ],
            requires_aggregation=False,  # Recommended but not required
            max_filter_complexity=2,  # Simple filters only
        )
    
    def _medium_constraints(self) -> QueryConstraints:
        """
        Constraints for MEDIUM datasets (1k-100k rows).
        
        Strategy: Most queries safe, minimal restrictions
        """
        return QueryConstraints(
            size_category="medium",
            allowed_operations={
                "COUNT", "SUM", "AVG", "MIN", "MAX",
                "GROUP BY", "ORDER BY", "LIMIT",
                "WHERE", "HAVING", "CASE WHEN",
                "DISTINCT", "JOIN",
            },
            discouraged_filters=set(),  # No restrictions
            preferred_strategies=[
                "any",  # All strategies acceptable
            ],
            requires_aggregation=False,
            max_filter_complexity=10,  # Complex filters OK
        )
    
    def _large_constraints(self) -> QueryConstraints:
        """
        Constraints for LARGE datasets (100k-10M rows).
        
        Strategy: All queries safe, focus on optimization
        """
        return QueryConstraints(
            size_category="large",
            allowed_operations={
                "COUNT", "SUM", "AVG", "MIN", "MAX",
                "GROUP BY", "ORDER BY", "LIMIT",
                "WHERE", "HAVING", "CASE WHEN",
                "DISTINCT", "JOIN", "WINDOW FUNCTIONS",
            },
            discouraged_filters=set(),
            preferred_strategies=[
                "any",
                "optimization_aware",  # Consider indexes
            ],
            requires_aggregation=False,
            max_filter_complexity=20,  # Very complex filters OK
        )
    
    def _huge_constraints(self) -> QueryConstraints:
        """
        Constraints for HUGE datasets (>= 10M rows).
        
        Strategy: All queries safe, emphasize performance
        """
        return QueryConstraints(
            size_category="huge",
            allowed_operations={
                "COUNT", "SUM", "AVG", "MIN", "MAX",
                "GROUP BY", "ORDER BY", "LIMIT",
                "WHERE", "HAVING", "CASE WHEN",
                "DISTINCT", "JOIN", "WINDOW FUNCTIONS",
                "PARTITION BY",
            },
            discouraged_filters=set(),
            preferred_strategies=[
                "any",
                "optimization_critical",  # Indexes mandatory
                "sampling",  # Consider LIMIT for exploration
            ],
            requires_aggregation=False,
            max_filter_complexity=50,  # Any complexity OK
        )
    
    def generate_for_multiple(self, size_categories: List[DatasetSize]) -> QueryConstraints:
        """
        Generate constraints for multiple tables.
        
        Uses the SMALLEST dataset size to ensure safety across all tables.
        
        Args:
            size_categories: List of size categories
            
        Returns:
            Constraints based on smallest dataset
        """
        if not size_categories:
            return self._tiny_constraints()  # Conservative default
        
        # Order of sizes (smallest to largest)
        size_order = ["tiny", "small", "medium", "large", "huge"]
        
        # Find minimum
        min_size = "huge"
        for size in size_categories:
            current_idx = size_order.index(size)
            min_idx = size_order.index(min_size)
            if current_idx < min_idx:
                min_size = size
        
        return self.generate(min_size)
