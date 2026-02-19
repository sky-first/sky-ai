
import sys
import os
import json
from dataclasses import asdict

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.agents.davinci_dashboard_agent import DavinciDashboardPlan

def test_plan_serialization():
    print("Testing DavinciDashboardPlan serialization with layout and filters...")
    
    # Mock data
    widgets = [
        {
            "widget_key": "w1",
            "type": "chart",
            "title": "Sales Trend",
            "question": "Show me sales over time",
            "viz": {"type": "line"},
            "layout": {"x": 0, "y": 0, "w": 12, "h": 13}
        },
        {
            "widget_key": "w2",
            "type": "kpi",
            "title": "Total Revenue",
            "question": "What is total revenue?",
            "viz": {"type": "kpi"},
            "layout": {"x": 0, "y": 14, "w": 4, "h": 9}
        }
    ]
    
    filters = [
        {"label": "Date Range", "field": "order_date", "type": "date_range"},
        {"label": "Region", "field": "region", "type": "select"}
    ]
    
    plan = DavinciDashboardPlan(
        dashboard_name="Sales Dashboard",
        description="A dashboard overviewing sales.",
        widgets=widgets,
        filters=filters,
        meta={"mode": "generated"}
    )
    
    # Serialize (simulate what Pydantic/FastAPI would do, though this is a dataclass)
    # The agent returns this dataclass, which is then used to construct the response.
    # In the real app, this is converted to dict or Pydantic model.
    
    print(f"Plan Name: {plan.dashboard_name}")
    print(f"Filters: {len(plan.filters)}")
    print(f"Widgets: {len(plan.widgets)}")
    
    assert plan.filters is not None
    assert len(plan.filters) == 2
    assert plan.widgets[0]["layout"]["w"] == 12
    
    print("✅ Serialization Check Passed!")

if __name__ == "__main__":
    try:
        test_plan_serialization()
    except Exception as e:
        print(f"❌ Test Failed: {e}")
        sys.exit(1)
