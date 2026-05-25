from typing import Any, Dict, Optional


class WidgetDesigner:
    """
    Agnostic Designer that strictly follows Data-Driven UX rules.
    Decides 'HOW' to visualize based on 'WHAT' data is provided.

    Philosophy:
    - Time + Number = Line Chart
    - Category + Number = Bar Chart (default)
    - Category + Number (Intent: Distribution) = Pie Chart
    - Single Number = KPI
    - List/Details = Table
    """

    @staticmethod
    def detect_column_type(col_name: str, col_meta: Dict[str, Any]) -> str:
        """
        Returns: 'time', 'numeric', 'category', 'unknown'
        """
        if not col_name:
            return "unknown"

        ctype = str(col_meta.get("type", "")).upper()

        # 1. Time
        if any(t in ctype for t in ["DATE", "TIME", "TIMESTAMP"]):
            return "time"

        # 2. Numeric
        if any(
            t in ctype for t in ["INT", "FLOAT", "NUMERIC", "DECIMAL", "DOUBLE", "REAL"]
        ):
            # Check if it looks like an ID
            if col_name.lower().endswith("id"):
                return "category"
            return "numeric"

        # 3. Text/Category (Default)
        return "category"

    @classmethod
    def choose_viz(
        cls,
        intent: str,
        x_col: str,
        y_col: str,
        x_meta: Dict[str, Any],
        y_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Deterministically selects the visualization configuration.
        """
        intent = (intent or "").lower()
        x_type = cls.detect_column_type(x_col, x_meta)
        y_type = cls.detect_column_type(y_col, y_meta)

        # Scenario 0: Explicit "List" intent or no Metrics -> Table
        if intent in ["list", "ranking", "details"] or not y_col:
            return {"type": "table"}

        # Scenario 1: KPI (Single Metric, No Dimensions or explicit KPI intent)
        if not x_col and y_type == "numeric":
            return {"type": "kpi"}

        if intent == "kpi":
            return {"type": "kpi"}

        # Scenario 2: Time Analysis or Trend Intent -> Line or Area
        if (
            x_type == "time" or intent in ["trend", "growth", "evolution"]
        ) and y_type == "numeric":
            # If intent is explicit cumulative or area
            if "composition" in intent or "area" in intent:
                return {"type": "area", "mapping": {"x": x_col, "y": y_col}}
            return {"type": "line", "mapping": {"x": x_col, "y": y_col}}

        # Scenario 3: Distribution -> Pie
        if intent in ["distribution", "composition", "share", "breakdown"]:
            if x_type == "category" and y_type == "numeric":
                return {"type": "pie", "mapping": {"x": x_col, "y": y_col}}

        # Scenario 4: Correlation -> Scatter
        if intent == "correlation" or (x_type == "numeric" and y_type == "numeric"):
            return {"type": "scatter", "mapping": {"x": x_col, "y": y_col}}

        # Scenario 5: Default Comparison -> Bar
        # This covers (Category + Numeric) and fallbacks
        if y_col:
            return {"type": "bar", "mapping": {"x": x_col or "category", "y": y_col}}

        # Fallback
        return {"type": "table"}
