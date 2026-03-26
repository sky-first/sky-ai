# core/agents/universe/juiz.py
from typing import Dict, Any, List, Optional
import json
import hashlib
from core.llm.providers import LLMProvider

class JudgeAgent:
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def generate_content_hash(self, title: str, insight: str) -> str:
        content = f"{title.strip().lower()}|{insight.strip().lower()}"
        return hashlib.md5(content.encode()).hexdigest()

    async def verify_insight(
        self,
        insight_preliminar: Dict[str, Any],
        raw_data: List[Dict[str, Any]],
        recent_hashes: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Validates if the insight is relevant, useful, and not duplicated.
        """
        
        # 1. Checa duplicidade básica por hash
        current_hash = self.generate_content_hash(
            insight_preliminar.get("title", ""), 
            insight_preliminar.get("insight", "")
        )
        
        if current_hash in recent_hashes:
            return None # Rejected due to duplication

        # 2. Deep validation via LLM (Significance and Utility)
        prompt = f"""
You are the Judge Agent of Universe Intelligence. Your role is to be EXTREMELY RIGOROUS.
It is better to send NOTHING than to send something obvious, irrelevant, or noisy.

INSIGHT FOR EVALUATION:
{json.dumps(insight_preliminar, indent=2)}

RAW DATA THAT GENERATED THE INSIGHT:
{json.dumps(raw_data[:20], indent=2)}

FILTER CRITERIA:
1. SIGNIFICANCE: Is the variation found statistically relevant (e.g., +10%, sharp drop) or just normal fluctuation (noise)?
2. UTILITY: Does this help the user make a strategic decision or is it just a curious but useless fact?
3. OBVIOUS FACT: Is this something everyone already knows? (e.g., "We sell more on weekends"). If it is obvious, reject it.

CLASSIFICATION RULES (only if approved=true):
- "risk"        → negative anomaly, drop, churn risk, overdue payments, alert, loss.
- "opportunity" → growth potential, recoverable inactive customer, optimization, upsell.
- "insight"     → relevant but neutral fact, confirmed trend, statistical pattern.

IMPORTANT: THE ENTIRE RESPONSE MUST BE IN ENGLISH.

DECISION:
Return a JSON:
{{
  "approved": true | false,
  "reason": "Brief explanation of your decision",
  "category": "insight" | "opportunity" | "risk"
}}
"""
        messages = [{"role": "system", "content": prompt}]
        response = self.llm.invoke(messages)
        
        try:
            decision = json.loads(response.content.strip())
            if decision.get("approved"):
                insight_preliminar["content_hash"] = current_hash
                insight_preliminar["category"] = decision.get("category", "insight")
                return insight_preliminar
            return None
        except Exception:
            # On parse error, reject by default for safety
            return None
