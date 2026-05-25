"""
Tests for Dashboard Intent Detector

Tests semantic pattern matching for dashboard generation intent.
"""

import pytest
from core.intent.detector import DashboardIntentDetector


def test_detector_initialization():
    """Detector initializes correctly"""
    detector = DashboardIntentDetector()
    assert detector is not None
    assert len(detector.positive_regex) > 0
    assert len(detector.negative_regex) > 0


class TestDashboardIntentDetection:
    """Test cases for positive dashboard intent detection"""

    def setup_method(self):
        self.detector = DashboardIntentDetector()

    def test_create_dashboard_explicit(self):
        """Direct 'create dashboard' should be detected"""
        assert self.detector.detect("create a sales dashboard") == True
        assert self.detector.detect("Create a dashboard for revenue") == True
        assert self.detector.detect("create dashboard") == True

    def test_build_generate_variants(self):
        """Alternative creation verbs should work"""
        assert self.detector.detect("build a dashboard") == True
        assert self.detector.detect("generate a dashboard about customers") == True
        assert self.detector.detect("make me a dashboard") == True

    def test_dashboard_for_pattern(self):
        """'dashboard for/about/of' patterns"""
        assert self.detector.detect("dashboard for sales analysis") == True
        assert self.detector.detect("dashboard about revenue") == True
        assert self.detector.detect("dashboard of customer metrics") == True

    def test_need_want_expressions(self):
        """Need/want dashboard expressions"""
        assert self.detector.detect("I need a dashboard") == True
        assert self.detector.detect("I want a dashboard with KPIs") == True
        assert self.detector.detect("would like a dashboard") == True

    def test_show_give_me_patterns(self):
        """Show/give me dashboard patterns"""
        assert self.detector.detect("show me a dashboard") == True
        assert self.detector.detect("show me a dashboard with sales data") == True
        assert self.detector.detect("give me a dashboard for performance") == True

    def test_visual_analytics_patterns(self):
        """Visual/analytics keywords"""
        assert self.detector.detect("visual overview of sales") == True
        assert self.detector.detect("KPI dashboard") == True
        assert self.detector.detect("analytics dashboard for revenue") == True

    def test_case_insensitive(self):
        """Should work regardless of case"""
        assert self.detector.detect("CREATE A DASHBOARD") == True
        assert self.detector.detect("Show Me A Dashboard") == True
        assert self.detector.detect("kpi dashboard") == True


class TestNonDashboardQueries:
    """Test cases that should NOT trigger dashboard intent"""

    def setup_method(self):
        self.detector = DashboardIntentDetector()

    def test_normal_data_questions(self):
        """Regular data questions should NOT trigger"""
        assert self.detector.detect("how many sales") == False
        assert self.detector.detect("show me the revenue") == False
        assert self.detector.detect("what is the total amount") == False

    def test_existing_dashboard_questions(self):
        """Questions about existing dashboards"""
        assert self.detector.detect("what's on my dashboard?") == False
        assert self.detector.detect("what is on the dashboard") == False

    def test_dashboard_state_issues(self):
        """Dashboard problems/state should not trigger"""
        assert self.detector.detect("my dashboard is empty") == False
        assert self.detector.detect("the dashboard is slow") == False
        assert self.detector.detect("dashboard error") == False

    def test_dashboard_navigation(self):
        """Dashboard UI/navigation questions"""
        assert self.detector.detect("where is my dashboard") == False
        assert self.detector.detect("how do I open the dashboard") == False

    def test_empty_or_whitespace(self):
        """Edge cases: empty input"""
        assert self.detector.detect("") == False
        assert self.detector.detect("   ") == False
        assert self.detector.detect(None) == False


class TestComplexCases:
    """Complex/edge case scenarios"""

    def setup_method(self):
        self.detector = DashboardIntentDetector()

    def test_negative_takes_priority(self):
        """Negative patterns should override positive"""
        # Contains "dashboard" but asking ABOUT existing dashboard
        assert self.detector.detect("what's on my dashboard with sales?") == False

    def test_long_sentences(self):
        """Dashboard request in longer sentence"""
        assert (
            self.detector.detect(
                "Can you please create a dashboard showing sales by region?"
            )
            == True
        )

        assert (
            self.detector.detect(
                "I would like to analyze performance, can you build a dashboard?"
            )
            == True
        )

    def test_typos_and_variations(self):
        """Some common variations"""
        assert (
            self.detector.detect("dashbord for sales") == False
        )  # typo not caught (acceptable)
        assert self.detector.detect("a dashboard showing revenue") == True


class TestDebugHelper:
    """Test the debug/introspection methods"""

    def setup_method(self):
        self.detector = DashboardIntentDetector()

    def test_get_matched_patterns(self):
        """get_matched_patterns returns pattern info"""
        positive, negative = self.detector.get_matched_patterns("create a dashboard")
        assert len(positive) > 0
        assert len(negative) == 0

        positive, negative = self.detector.get_matched_patterns(
            "what's on my dashboard"
        )
        assert len(positive) == 0
        assert len(negative) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
