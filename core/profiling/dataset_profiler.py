"""
Dataset Profiling Module

Classifies datasets by size and generates execution constraints.
Used to adapt query strategies based on dataset characteristics.
"""
from __future__ import annotations
from typing import Literal, List, Dict, Optional
from dataclasses import dataclass


# Type alias for size categories
DatasetSize = Literal["tiny", "small", "medium", "large", "huge"]


@dataclass
class DatasetProfile:
    """Profile of a single table/dataset"""
    table_name: str
    row_count: int
    size_category: DatasetSize
    
    def __repr__(self) -> str:
        return f"DatasetProfile({self.table_name}: {self.row_count} rows, {self.size_category})"


class DatasetProfiler:
    """
    Classifies datasets by size for adaptive query generation.
    
    Size categories based on row count:
    - TINY: < 100 rows (very limited data, avoid filters)
    - SMALL: < 1,000 rows (limited data, prefer aggregations)
    - MEDIUM: < 100,000 rows (moderate data, most queries safe)
    - LARGE: < 10,000,000 rows (large data, all queries safe)
    - HUGE: >= 10,000,000 rows (very large, optimize queries)
    """
    
    # Size thresholds
    TINY_THRESHOLD = 100
    SMALL_THRESHOLD = 1_000
    MEDIUM_THRESHOLD = 100_000
    LARGE_THRESHOLD = 10_000_000
    
    def classify_size(self, row_count: int) -> DatasetSize:
        """
        Classify dataset size based on row count.
        
        Args:
            row_count: Number of rows in the table
            
        Returns:
            Size category (tiny/small/medium/large/huge)
        """
        if row_count < self.TINY_THRESHOLD:
            return "tiny"
        elif row_count < self.SMALL_THRESHOLD:
            return "small"
        elif row_count < self.MEDIUM_THRESHOLD:
            return "medium"
        elif row_count < self.LARGE_THRESHOLD:
            return "large"
        else:
            return "huge"
    
    def profile_table(self, table_metadata: Dict) -> DatasetProfile:
        """
        Create profile for a single table.
        
        Args:
            table_metadata: Table metadata dict with 'name' and 'row_count'
            
        Returns:
            DatasetProfile instance
        """
        table_name = table_metadata.get("name", "unknown")
        row_count = int(table_metadata.get("row_count", 0))
        
        # Handle missing or zero row counts
        if row_count == 0:
            # Default to tiny if no data
            size_category = "tiny"
        else:
            size_category = self.classify_size(row_count)
        
        return DatasetProfile(
            table_name=table_name,
            row_count=row_count,
            size_category=size_category
        )
    
    def profile_tables(self, tables_metadata: List[Dict]) -> List[DatasetProfile]:
        """
        Create profiles for multiple tables.
        
        Args:
            tables_metadata: List of table metadata dicts
            
        Returns:
            List of DatasetProfile instances
        """
        return [self.profile_table(table) for table in tables_metadata]
    
    def get_smallest_size(self, profiles: List[DatasetProfile]) -> DatasetSize:
        """
        Get the smallest dataset size from a list of profiles.
        
        This is used to determine the most conservative strategy
        when dealing with multiple tables.
        
        Args:
            profiles: List of DatasetProfile instances
            
        Returns:
            Smallest size category
        """
        if not profiles:
            return "tiny"  # Conservative default
        
        # Order of sizes (smallest to largest)
        size_order = ["tiny", "small", "medium", "large", "huge"]
        
        # Find minimum
        min_size = "huge"
        for profile in profiles:
            current_idx = size_order.index(profile.size_category)
            min_idx = size_order.index(min_size)
            if current_idx < min_idx:
                min_size = profile.size_category
        
        return min_size
    
    def get_size_statistics(self, profiles: List[DatasetProfile]) -> Dict:
        """
        Get statistics about dataset sizes.
        
        Returns:
            Dict with counts per size category and other stats
        """
        stats = {
            "total_tables": len(profiles),
            "total_rows": sum(p.row_count for p in profiles),
            "by_size": {
                "tiny": 0,
                "small": 0,
                "medium": 0,
                "large": 0,
                "huge": 0,
            },
            "smallest_size": self.get_smallest_size(profiles) if profiles else "tiny",
        }
        
        for profile in profiles:
            stats["by_size"][profile.size_category] += 1
        
        return stats
