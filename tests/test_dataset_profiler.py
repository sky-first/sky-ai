"""
Tests for Dataset Profiler

Tests size classification and profiling logic.
"""
import pytest
from core.profiling.dataset_profiler import DatasetProfiler, DatasetProfile


def test_profiler_initialization():
    """Profiler initializes correctly"""
    profiler = DatasetProfiler()
    assert profiler is not None
    assert profiler.TINY_THRESHOLD == 100
    assert profiler.SMALL_THRESHOLD == 1_000


class TestSizeClassification:
    """Test size classification logic"""
    
    def setup_method(self):
        self.profiler = DatasetProfiler()
    
    def test_tiny_classification(self):
        """< 100 rows should be TINY"""
        assert self.profiler.classify_size(0) == "tiny"
        assert self.profiler.classify_size(50) == "tiny"
        assert self.profiler.classify_size(99) == "tiny"
    
    def test_small_classification(self):
        """100-999 rows should be SMALL"""
        assert self.profiler.classify_size(100) == "small"
        assert self.profiler.classify_size(500) == "small"
        assert self.profiler.classify_size(999) == "small"
    
    def test_medium_classification(self):
        """1k-99k rows should be MEDIUM"""
        assert self.profiler.classify_size(1_000) == "medium"
        assert self.profiler.classify_size(50_000) == "medium"
        assert self.profiler.classify_size(99_999) == "medium"
    
    def test_large_classification(self):
        """100k-10M rows should be LARGE"""
        assert self.profiler.classify_size(100_000) == "large"
        assert self.profiler.classify_size(5_000_000) == "large"
        assert self.profiler.classify_size(9_999_999) == "large"
    
    def test_huge_classification(self):
        """>= 10M rows should be HUGE"""
        assert self.profiler.classify_size(10_000_000) == "huge"
        assert self.profiler.classify_size(50_000_000) == "huge"
        assert self.profiler.classify_size(1_000_000_000) == "huge"


class TestTableProfiling:
    """Test profiling individual tables"""
    
    def setup_method(self):
        self.profiler = DatasetProfiler()
    
    def test_profile_single_table(self):
        """Profile a single table correctly"""
        metadata = {"name": "customers", "row_count": 50}
        profile = self.profiler.profile_table(metadata)
        
        assert profile.table_name == "customers"
        assert profile.row_count == 50
        assert profile.size_category == "tiny"
    
    def test_profile_missing_row_count(self):
        """Handle missing row_count gracefully"""
        metadata = {"name": "products"}
        profile = self.profiler.profile_table(metadata)
        
        assert profile.table_name == "products"
        assert profile.row_count == 0
        assert profile.size_category == "tiny"  # Default to tiny
    
    def test_profile_zero_rows(self):
        """Handle zero rows"""
        metadata = {"name": "empty_table", "row_count": 0}
        profile = self.profiler.profile_table(metadata)
        
        assert profile.size_category == "tiny"
    
    def test_profile_multiple_tables(self):
        """Profile multiple tables"""
        tables = [
            {"name": "customers", "row_count": 50},
            {"name": "orders", "row_count": 500},
            {"name": "products", "row_count": 5000},
        ]
        
        profiles = self.profiler.profile_tables(tables)
        
        assert len(profiles) == 3
        assert profiles[0].size_category == "tiny"
        assert profiles[1].size_category == "small"
        assert profiles[2].size_category == "medium"


class TestSmallestSize:
    """Test getting smallest size from profiles"""
    
    def setup_method(self):
        self.profiler = DatasetProfiler()
    
    def test_smallest_size_single(self):
        """Smallest size with single profile"""
        profiles = [
            DatasetProfile("table1", 50, "tiny")
        ]
        assert self.profiler.get_smallest_size(profiles) == "tiny"
    
    def test_smallest_size_multiple(self):
        """Smallest size with multiple profiles"""
        profiles = [
            DatasetProfile("table1", 50, "tiny"),
            DatasetProfile("table2", 5000, "medium"),
            DatasetProfile("table3", 500, "small"),
        ]
        assert self.profiler.get_smallest_size(profiles) == "tiny"
    
    def test_smallest_size_all_large(self):
        """All large datasets"""
        profiles = [
            DatasetProfile("table1", 100_000, "large"),
            DatasetProfile("table2", 500_000, "large"),
        ]
        assert self.profiler.get_smallest_size(profiles) == "large"
    
    def test_smallest_size_empty_list(self):
        """Empty list defaults to tiny"""
        assert self.profiler.get_smallest_size([]) == "tiny"


class TestStatistics:
    """Test statistics generation"""
    
    def setup_method(self):
        self.profiler = DatasetProfiler()
    
    def test_statistics_generation(self):
        """Generate statistics correctly"""
        profiles = [
            DatasetProfile("table1", 50, "tiny"),
            DatasetProfile("table2", 50, "tiny"),
            DatasetProfile("table3", 5000, "medium"),
            DatasetProfile("table4", 100_000, "large"),
        ]
        
        stats = self.profiler.get_size_statistics(profiles)
        
        assert stats["total_tables"] == 4
        assert stats["total_rows"] == 105_100
        assert stats["by_size"]["tiny"] == 2
        assert stats["by_size"]["small"] == 0
        assert stats["by_size"]["medium"] == 1
        assert stats["by_size"]["large"] == 1
        assert stats["smallest_size"] == "tiny"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
