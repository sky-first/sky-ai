# core/agents/universe/estrategista.py
from typing import List, Dict, Optional
import json
from core.llm.providers import LLMProvider
from core.agents.generic_sql_agent import TableSchema

class HypothesisGenerator:
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def _format_schema(self, db_schema: List[TableSchema]) -> str:
        schema_text = ""
        for table in db_schema:
            cols = ", ".join([f"{c['name']} ({c['type']})" for c in table.columns[:10]])
            schema_text += f"- Tabela: {table.logical_name} ({table.physical_name})\n"
            schema_text += f"  Colunas: {cols}\n"
            if table.description:
                schema_text += f"  Descrição: {table.description}\n"
        return schema_text

    async def generate_general_hypothesis(
        self, 
        empresa_contexto: str, 
        objetivos_estrategicos: List[str], 
        db_schema: List[TableSchema]
    ) -> str:
        """Generates an internal question for broad discovery."""
        
        prompt = f"""
You are the Strategic Agent of Universe Intelligence. Your mission is to be proactive and find valuable insights in the company's data.

COMPANY CONTEXT:
{empresa_contexto}

STRATEGIC OBJECTIVES (OKRs/Pillars/Risks):
{json.dumps(objetivos_estrategicos, indent=2)}

AVAILABLE TABLE METADATA:
{self._format_schema(db_schema)}

INVESTIGATION LOGIC:
1. Analyze what is crucial for the company's success at this moment.
2. Identify which tables might contain "clues" of problems or opportunities.
3. Generate a direct internal question that can be answered via SQL.
Example: "Has there been a drop in profit margin in the last 3 days?" or "Which customers in sector X have stopped buying recently?"

IMPORTANT:
- Focus on trends, anomalies, or significant variations.
- Consider how the mentioned RISKS or PILLARS can be validated or mitigated by the data.
- The question must be clear and executable by a SQL specialist.
- IMPORTANT: ALWAYS GENERATE THE INTERNAL QUESTION IN ENGLISH AND ALWAYS USE PHYSICAL TABLE NAMES (e.g., silver_customers_enriquecido) to ensure compatibility.

Return ONLY the internal question in ENGLISH, without explanations.
"""
        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": "Generate the next business investigation question."}]
        response = self.llm.invoke(messages)
        return response.content.strip()

    async def generate_mission_hypothesis(
        self, 
        mission_description: str,
        expected_results: str,
        db_schema: List[TableSchema]
    ) -> str:
        """Generates an internal question focused on the targets of a specific Mission."""
        
        prompt = f"""
You are the Strategic Agent focused on monitoring MISSIONS.

MISSION DESCRIPTION:
{mission_description}

EXPECTED RESULT BY THE USER:
{expected_results}

AVAILABLE TABLE METADATA:
{self._format_schema(db_schema)}

YOUR TASK:
Generate an internal question that validates if the mission is being fulfilled or if there have been deviations in the monitored indicators.
The question should be focused EXCLUSIVELY on the tables related to this mission.
IMPORTANT: ALWAYS GENERATE THE INTERNAL QUESTION IN ENGLISH AND ALWAYS USE PHYSICAL TABLE NAMES to ensure compatibility.

Return ONLY the internal question in ENGLISH.
"""
        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": "Generate the mission validation question."}]
        response = self.llm.invoke(messages)
        return response.content.strip()
