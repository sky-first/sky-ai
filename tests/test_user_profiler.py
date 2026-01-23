# tests/test_user_profiler.py
"""
Tests for the User Profiler module.
"""
import pytest
from unittest.mock import MagicMock, patch
from core.rag.user_profiler import (
    get_user_table_profile,
    format_profile_for_prompt,
    get_user_recent_queries,
)


class TestGetUserTableProfile:
    """Tests for get_user_table_profile function."""
    
    def test_returns_empty_dict_when_no_user_id(self):
        """Should return empty dict when user_id is None or empty."""
        db = MagicMock()
        
        result = get_user_table_profile(db, user_id=None)
        assert result == {}
        
        result = get_user_table_profile(db, user_id="")
        assert result == {}
    
    def test_returns_empty_dict_on_db_error(self):
        """Should return empty dict and log error on database exception."""
        db = MagicMock()
        db.execute.side_effect = Exception("DB Error")
        
        with patch("core.rag.user_profiler.log_event") as mock_log:
            result = get_user_table_profile(db, user_id="test-user")
            
            assert result == {}
            mock_log.assert_called()
            # Check that error was logged
            call_args = mock_log.call_args_list[-1]
            assert call_args[0][0] == "user_profiler_error"
    
    def test_aggregates_table_counts_correctly(self):
        """Should aggregate table counts from query results."""
        db = MagicMock()
        
        # Mock database result
        mock_result = [
            MagicMock(table_name="invoices", usage_count=25),
            MagicMock(table_name="payments", usage_count=10),
            MagicMock(table_name="customers", usage_count=5),
        ]
        db.execute.return_value = mock_result
        
        with patch("core.rag.user_profiler.log_event"):
            result = get_user_table_profile(db, user_id="test-user")
        
        assert result == {
            "invoices": 25,
            "payments": 10,
            "customers": 5,
        }


class TestFormatProfileForPrompt:
    """Tests for format_profile_for_prompt function."""
    
    def test_returns_empty_string_for_empty_profile(self):
        """Should return empty string when profile is empty."""
        result = format_profile_for_prompt({})
        assert result == ""
    
    def test_formats_single_table_correctly(self):
        """Should format single table profile correctly."""
        profile = {"invoices": 10}
        result = format_profile_for_prompt(profile)
        
        assert "USER PREFERENCE PROFILE:" in result
        assert "invoices (10x)" in result
        assert "prefer these tables as defaults" in result
    
    def test_formats_multiple_tables_correctly(self):
        """Should format multiple tables in descending order."""
        profile = {
            "customers": 5,
            "invoices": 25,
            "payments": 10,
        }
        result = format_profile_for_prompt(profile)
        
        assert "USER PREFERENCE PROFILE:" in result
        # Should be ordered by count descending
        assert "invoices (25x)" in result
        assert "payments (10x)" in result
        assert "customers (5x)" in result
    
    def test_respects_max_tables_limit(self):
        """Should limit number of tables in output."""
        profile = {
            "table1": 100,
            "table2": 90,
            "table3": 80,
            "table4": 70,
            "table5": 60,
            "table6": 50,  # Should be excluded with max_tables=5
        }
        result = format_profile_for_prompt(profile, max_tables=5)
        
        assert "table1 (100x)" in result
        assert "table5 (60x)" in result
        assert "table6" not in result


class TestGetUserRecentQueries:
    """Tests for get_user_recent_queries function."""
    
    def test_returns_empty_list_when_no_user_id(self):
        """Should return empty list when user_id is None or empty."""
        db = MagicMock()
        
        result = get_user_recent_queries(db, user_id=None)
        assert result == []
        
        result = get_user_recent_queries(db, user_id="")
        assert result == []
    
    def test_returns_empty_list_on_db_error(self):
        """Should return empty list on database exception."""
        db = MagicMock()
        db.execute.side_effect = Exception("DB Error")
        
        with patch("core.rag.user_profiler.log_event"):
            result = get_user_recent_queries(db, user_id="test-user")
        
        assert result == []
    
    def test_returns_recent_queries(self):
        """Should return formatted recent queries."""
        db = MagicMock()
        
        mock_result = [
            MagicMock(
                question="What is monthly revenue?",
                chosen_tables=["invoices"],
            ),
            MagicMock(
                question="Show top customers",
                chosen_tables=["customers", "invoices"],
            ),
        ]
        db.execute.return_value = mock_result
        
        with patch("core.rag.user_profiler.log_event"):
            result = get_user_recent_queries(db, user_id="test-user")
        
        assert len(result) == 2
        assert result[0]["question"] == "What is monthly revenue?"
        assert result[0]["tables"] == ["invoices"]
        assert result[1]["tables"] == ["customers", "invoices"]
