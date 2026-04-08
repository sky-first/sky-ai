import re
from typing import Dict, List, Any, Optional
from datetime import datetime

class DavinciPlanValidator:
    """
    Validates a generated Dashboard Plan against the actual schema metadata.
    Detects hallucinations (invented columns) and ungrounded claims.
    """
    
    def __init__(self, table_metadata: List[Dict[str, Any]]):
        self.table_metadata = table_metadata
        # Build lookup maps for fast validation
        self._schema_map = {} # logic_name -> {col_name}
        
        for t in table_metadata:
            # Normalize table names
            t_name = t.get("name", "").lower()
            t_schema = t.get("schema", "").lower()
            full_name = f"{t_schema}.{t_name}" if t_schema else t_name
            
            # Extract columns
            cols = {c.get("name", "").lower() for c in t.get("columns", [])}
            
            # Store by both full name and simple name to cover aliases
            self._schema_map[full_name] = cols
            self._schema_map[t_name] = cols

    def validate_plan(self, plan: Dict[str, Any], context_provided: bool = False) -> Dict[str, Any]:
        """
        Runs all checks and returns a validation report.
        """
        issues = []
        
        # 1. Check Schema Consistency (Hallucinated Columns)
        schema_issues = self._check_schema_consistency(plan)
        issues.extend(schema_issues)
        
        # 2. Check for Ungrounded Claims (Hallucinated Facts)
        claim_issues = self._check_ungrounded_claims(plan, context_provided)
        issues.extend(claim_issues)

        # 3. Check Temporal Agreement (Hallucinated Trends)
        temporal_issues = self._check_temporal_agreement(plan)
        issues.extend(temporal_issues)
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "score": max(0, 100 - (len(issues) * 15)) # Adjusted scoring
        }

    def _check_temporal_agreement(self, plan: Dict[str, Any]) -> List[str]:
        """
        Check if claims about time match the actual depth of data available.
        """
        issues = []
        
        # Calculate max time range across all tables
        min_date_found = None
        max_date_found = None
        
        for t in self.table_metadata:
            for c in t.get("columns", []):
                try:
                    c_min = c.get("min_date")
                    c_max = c.get("max_date")
                    if c_min:
                        # Convert to datetime if it's a string
                        if isinstance(c_min, str): c_min = datetime.fromisoformat(c_min.split(' ')[0])
                        if not min_date_found or c_min < min_date_found: min_date_found = c_min
                    if c_max:
                        if isinstance(c_max, str): c_max = datetime.fromisoformat(c_max.split(' ')[0])
                        if not max_date_found or c_max > max_date_found: max_date_found = c_max
                except: continue
        
        if not min_date_found or not max_date_found:
            return issues # No date metadata to verify against

        days_covered = (max_date_found - min_date_found).days
        
        # Logic: If AI claims "Yearly trend" but we have < 365 days -> Issue
        # If AI claims "Monthly trend" but we have < 30 days -> Issue
        
        narrative = f"{plan.get('verdict', '')} {plan.get('diagnostic', '')}".lower()
        
        if "yearly" in narrative or "last year" in narrative or "year-over-year" in narrative:
            if days_covered < 365:
                issues.append(f"Temporal Hallucination: Plan mentions 'yearly' trends, but data only covers {days_covered} days.")
        
        if "months" in narrative or "monthly" in narrative:
            # Check for specific count e.g. "last 12 months"
            match = re.search(r"last (\d+) months", narrative)
            if match:
                months_claimed = int(match.group(1))
                if days_covered < (months_claimed * 28):
                    issues.append(f"Temporal Hallucination: Claimed '{months_claimed} months' of history, but data only covers {days_covered} days.")
            elif days_covered < 20: 
                # General mentions of 'monthly' should have at least some weeks of data
                issues.append(f"Temporal Hallucination: Mentions 'monthly' performance, but data only covers {days_covered} days.")

        return issues

    def _check_schema_consistency(self, plan: Dict[str, Any]) -> List[str]:
        issues = []
        descriptive = plan.get("descriptive", {})
        
        # Collect all widgets aimed at data
        widgets = descriptive.get("charts", []) + descriptive.get("kpis", [])
        
        for i, w in enumerate(widgets):
            title = w.get("title", f"Widget {i+1}")
            reqs = w.get("data_requirements", {})
            
            # Check explicit columns if provided by LLM in data_requirements
            # (Note: Davinci v2 prompts ask for x_axis/y_axis but not fully qualified cols always)
            
            # Heuristic: Check x_axis, y_axis values if they look like columns
            # This is tricky because LLM might say "Revenue" (friendly name) vs "amount" (col name)
            # We only validate strictly if 'data_requirements' keys exist with column names
            
            for key in ["x_axis_column", "y_axis_column", "date_column"]:
                col_ref = reqs.get(key)
                if col_ref:
                    # We don't verify WHICH table it comes from here (complex), 
                    # just that it exists in AT LEAST ONE table in the scope.
                    # Ideally Davinci should specify table, but it often infers.
                    if not self._column_exists_anywhere(col_ref):
                        issues.append(f"Widget '{title}': Column '{col_ref}' not found in any logical table.")

        return issues

    def _check_ungrounded_claims(self, plan: Dict[str, Any], context_provided: bool) -> List[str]:
        """
        If no initial context was provided (e.g. no previous analysis),
        the Plan should NOT contain specific numbers or trends in the Verdict/Narrative.
        It should formulate QUESTIONS, not ANSWERS.
        """
        issues = []
        if context_provided:
            return issues # Trust that context justifies the claims
            
        # Regex to find specific numbers/trends
        # e.g. "5%", "$10k", "increased by", "dropped"
        # If found in Verdict/Diagnostic -> Hallucination Risk
        
        risk_patterns = [
            r"\d+%",          # Percentages (e.g., 5%)
            r"\$\d+",         # Money (e.g., $100)
            r"increased by",  
            r"decreased by",
            r"dropped",
            r"grew",
            r"surge",
            r"plunge"
        ]
        
        sections = ["verdict", "diagnostic", "predictive"]
        for section in sections:
            text = plan.get(section, "")
            if not text: continue
            
            for pattern in risk_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    issues.append(f"Potential Hallucination within '{section}': Found specific claim '{pattern}' without prior data context.")
                    break # One per section is enough warning

        return issues

    def _column_exists_anywhere(self, col_name: str) -> bool:
        col_name = col_name.lower().strip()
        for table_cols in self._schema_map.values():
            if col_name in table_cols:
                return True
        return False
