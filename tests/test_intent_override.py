"""
Tests for Intent Override Logic

Tests detection of explicit user filter intent.
"""
import pytest
from core.profiling.intent_override import IntentOverride


def test_override_initialization():
    """Override initializes correctly"""
    override = IntentOverride()
    assert override is not None
    assert len(override.compiled_patterns) > 0


class TestFilterIntentDetection:
    """Test detection of explicit filter intent"""
    
    def setup_method(self):
        self.override = IntentOverride()
    
    def test_status_filters(self):
        """Detects status-based filters"""
        assert self.override.detect_filter_intent("show me failed payments") == True
        assert self.override.detect_filter_intent("approved orders") == True
        assert self.override.detect_filter_intent("pending transactions") == True
        assert self.override.detect_filter_intent("cancelled requests") == True
    
    def test_amount_filters(self):
        """Detects amount/value filters"""
        assert self.override.detect_filter_intent("high value transactions") == True
        assert self.override.detect_filter_intent("payments over $1000") == True
        assert self.override.detect_filter_intent("orders below 50") == True
    
    def test_time_filters(self):
        """Detects time-based filters"""
        assert self.override.detect_filter_intent("last month sales") == True
        assert self.override.detect_filter_intent("recent orders") == True
        assert self.override.detect_filter_intent("sales in January") == True
        assert self.override.detect_filter_intent("data from 2024") == True
        assert self.override.detect_filter_intent("this week's revenue") == True
    
    def test_category_filters(self):
        """Detects category/type filters"""
        assert self.override.detect_filter_intent("type of products") == True
        assert self.override.detect_filter_intent("for customers in Brazil") == True
    
    def test_explicit_where_language(self):
        """Detects WHERE-like language"""
        assert self.override.detect_filter_intent("where status is failed") == True
        assert self.override.detect_filter_intent("with amount over 100") == True
    
    def test_no_filter_intent(self):
        """Non-filter queries return False"""
        assert self.override.detect_filter_intent("total sales") == False
        assert self.override.detect_filter_intent("count of customers") == False
        assert self.override.detect_filter_intent("revenue by region") == False


class TestFilterHintExtraction:
    """Test extraction of filter hints"""
    
    def setup_method(self):
        self.override = IntentOverride()
    
    def test_extract_hints(self):
        """Extracts matched filter patterns"""
        hints = self.override.extract_filter_hints("show me failed payments over $500")
        assert len(hints) >= 1  # Should match at least one pattern
    
    def test_no_hints(self):
        """No hints for generic queries"""
        hints = self.override.extract_filter_hints("total revenue")
        assert len(hints) == 0


class TestShouldAllowFilters:
    """Test filter allowance decision logic"""
    
    def setup_method(self):
        self.override = IntentOverride()
    
    def test_medium_always_allows(self):
        """MEDIUM+ datasets always allow filters"""
        allowed, reason = self.override.should_allow_filters(
            goal="any query",
            dataset_size="medium",
            base_constraints={"max_filter_complexity": 0}
        )
        assert allowed == True
        assert "permits" in reason.lower()
    
    def test_tiny_with_intent_allows(self):
        """TINY + explicit intent = allow"""
        allowed, reason = self.override.should_allow_filters(
            goal="show me failed payments",
            dataset_size="tiny",
            base_constraints={"max_filter_complexity": 0}
        )
        assert allowed == True
        assert "explicit intent" in reason.lower()
    
    def test_tiny_without_intent_blocks(self):
        """TINY + no intent = block"""
        allowed, reason = self.override.should_allow_filters(
            goal="total sales",
            dataset_size="tiny",
            base_constraints={"max_filter_complexity": 0}
        )
        assert allowed == False
        assert "no explicit" in reason.lower()
    
    def test_small_with_relaxed_constraints_allows(self):
        """SMALL + relaxed constraints = allow"""
        allowed, reason = self.override.should_allow_filters(
            goal="any query",
            dataset_size="small",
            base_constraints={"max_filter_complexity": 2}
        )
        assert allowed == True
        assert "base constraints" in reason.lower()


class TestEdgeCases:
    """Test edge cases"""
    
    def setup_method(self):
        self.override = IntentOverride()
    
    def test_empty_goal(self):
        """Empty goal returns False"""
        assert self.override.detect_filter_intent("") == False
        assert self.override.detect_filter_intent(None) == False
    
    def test_case_insensitive(self):
        """Detection is case-insensitive"""
        assert self.override.detect_filter_intent("FAILED PAYMENTS") == True
        assert self.override.detect_filter_intent("Failed Payments") == True
        assert self.override.detect_filter_intent("failed payments") == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
