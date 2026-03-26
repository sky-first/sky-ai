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
        output_format: str = "text",   # "text" | "mix"
    ) -> Dict[str, Any]:
        """
        Consumes the hypothesis, executes the SQL, and creates a Preliminary Insight with a 'Tchan' tone.
        output_format:
          - "text" → short text only, no chart_data
          - "mix"  → text + chart_data (structured series for chart rendering in the UI)
        """
        
        # 1. Execute the standard Query flow (NLP -> SQL -> Data)
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

        # 2. Build prompt based on output_format
        data_sample = json.dumps(final_state["data"][:10], indent=2)
        is_mix = output_format == "mix"

        chart_data_instruction = ""
        chart_data_field = ""
        if is_mix:
            chart_data_instruction = """
CHART DATA (only for mix format):
If the raw data contains a numeric series (time-series, ranking, or grouped values), extract it as chart_data.
chart_data format: [{"label": "string (date, name, or category)", "value": number}, ...]
If there is no meaningful series to chart, set chart_data to null."""
            chart_data_field = '  "chart_data": [{"label": "...", "value": 0}] | null'
        else:
            chart_data_field = '  "chart_data": null'

        prompt = f"""
You are the Analyst Agent of Universe Intelligence. You received the raw data below as a response for the investigation: "{hypothesis}".

RAW DATA (Sample):
{data_sample}

YOUR TASK:
Interpret the numbers and create a "Preliminary Insight".
Use the "Tchan" voice tone: intuitive, impactful, direct, and creating curiosity or a sense of urgency.
Do not just report facts; explain WHY this matters.
{chart_data_instruction}
IMPORTANT: THE ENTIRE RESPONSE MUST BE IN ENGLISH.

OUTPUT FORMAT (JSON):
{{
  "title": "Short and Impactful Title",
  "insight": "Your explanation with Tchan tone (2-3 sentences max)",
  "impact_level": "low|medium|high",
  "suggested_action": "What should the user do about it?",
  "source_tables": ["list", "of", "tables"],
{chart_data_field}
}}
"""
        messages = [{"role": "system", "content": prompt}]
        response = self.llm_formatter.invoke(messages)
        
        try:
            raw = response.content.strip()
            # strip markdown code blocks if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            insight_json = json.loads(raw.strip())
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
                    "source_tables": final_state.get("chosen_tables", []),
                    "chart_data": None
                },
                "raw_data": final_state["data"],
                "sql": final_state.get("sql")
            }
