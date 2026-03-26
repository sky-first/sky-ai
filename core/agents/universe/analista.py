# core/agents/universe/analista.py
from typing import List, Dict, Any, Optional
import json
from core.llm.providers import LLMProvider
from core.agents.generic_sql_agent import run_agent_once, AgentConfig, AgentState
from core.auth.models import UserContext
from core.data_sources.base import BaseDataSource
from core.rag.embeddings import EmbeddingProvider
from sqlalchemy.orm import Session

class DataAnalystAgent:
    def __init__(self, llm_orchestrator: LLMProvider, llm_specialist: LLMProvider, llm_formatter: LLMProvider):
        self.llm_orchestrator = llm_orchestrator
        self.llm_specialist = llm_specialist
        self.llm_formatter = llm_formatter

    async def analyze_hypothesis(
        self,
        hypothesis: str,
        user_ctx: UserContext,
        agent_config: AgentConfig,
        data_source: BaseDataSource,
        db_session_factory: Any,
        embedding_provider: EmbeddingProvider,
    ) -> Dict[str, Any]:
        """
        Consumes the hypothesis, executes the SQL, and creates a Preliminary Insight with a 'Tchan' tone.
        """
        
        # 1. Execute the standard Query flow (NLP -> SQL -> Data)
        # Specific dataset hint for BigQuery if detected
        table_prefix_hint = "IMPORTANT: Use the prefix 'billing_silver.' on all tables (e.g., billing_silver.table)." if agent_config.dialect == "bigquery" else ""
        
        sql_instr = f"""
{table_prefix_hint}
- You must generate a SQL that exactly answers the technical hypothesis in English.
- Prioritize JOINs if necessary to cross-reference data.
"""
        
        final_state = run_agent_once(
            question=hypothesis,
            user_ctx=user_ctx,
            agent_config=agent_config,
            data_source=data_source,
            db_session_factory=db_session_factory,
            embedding_provider=embedding_provider,
            llm_orchestrator=self.llm_orchestrator,
            llm_specialist=self.llm_specialist,
            llm_formatter=self.llm_formatter,
            sql_instructions=sql_instr
        )

        if final_state.get("error") or not final_state.get("data"):
            return {
                "success": False,
                "error": final_state.get("error", "No data found for this hypothesis"),
                "raw_state": final_state
            }

        # 2. Create the Preliminary Insight with an impactful voice tone (Tchan)
        data_sample = json.dumps(final_state["data"][:10], indent=2)
        
        prompt = f"""
You are the Analyst Agent of Universe Intelligence. You received the raw data below as a response for the investigation: "{hypothesis}".

RAW DATA (Sample):
{data_sample}

YOUR TASK:
Interpret the numbers and create a "Preliminary Insight".
Use the "Tchan" voice tone: intuitive, impactful, direct, and creating curiosity or a sense of urgency.
Do not just report facts; explain WHY this matters.
IMPORTANT: THE ENTIRE RESPONSE MUST BE IN ENGLISH.

OUTPUT FORMAT (JSON):
{{
  "title": "Short and Impactful Title",
  "insight": "Your explanation with Tchan tone",
  "impact_level": "low|medium|high",
  "suggested_action": "What should the user do about it?",
  "source_tables": ["list", "of", "tables"]
}}
"""
        messages = [{"role": "system", "content": prompt}]
        response = self.llm_formatter.invoke(messages)
        
        try:
            insight_json = json.loads(response.content.strip())
            return {
                "success": True,
                "insight": insight_json,
                "raw_data": final_state["data"],
                "sql": final_state.get("sql")
            }
        except Exception:
            # Fallback format if the LLM fails JSON parsing
            return {
                "success": True,
                "insight": {
                    "title": "New Discovery found",
                    "insight": response.content,
                    "impact_level": "medium",
                    "suggested_action": "Check the detailed data.",
                    "source_tables": final_state.get("chosen_tables", [])
                },
                "raw_data": final_state["data"],
                "sql": final_state.get("sql")
            }
