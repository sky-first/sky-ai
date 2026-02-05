import re
import json
from typing import Dict, Any, Optional, List
from core.agents.generic_sql_agent import AgentState
from core.llm.providers import LLMProvider
from core.contracts.analysis_context import AnalysisContext
from core.context.analysis_session_store import AnalysisSessionStore
from core.logging_utils import log_event

def _extract_metric_dimension_from_sql(sql: str) -> Dict[str, Optional[str]]:
    """
    Deterministically extracts primary metric and dimension from SQL.
    Simple heuristic:
    - Metric: First aggregated column (SUM, COUNT, AVG, etc.)
    - Dimension: First column in GROUP BY or first non-aggregated column
    """
    sql = sql.lower()
    
    # 1. Extract SELECT clause
    select_match = re.search(r"select\s+(.*?)\s+from", sql, re.DOTALL)
    if not select_match:
        return {"metric": None, "dimension": None}
    
    select_part = select_match.group(1).strip()
    columns = [c.strip() for c in select_part.split(",")]
    
    metric = None
    dimension = None
    
    # regex for aggregation
    agg_pattern = re.compile(r"(sum|count|avg|min|max)\s*\(", re.IGNORECASE)
    
    for col in columns:
        # Check if it's an aggregation
        if agg_pattern.search(col):
            if not metric:
                # Clean up alias (AS ...)
                metric = re.split(r"\s+as\s+", col, flags=re.IGNORECASE)[-1].strip()
        else:
            if not dimension and "*" not in col:
                 # Clean up alias
                dimension = re.split(r"\s+as\s+", col, flags=re.IGNORECASE)[-1].strip()
                # Remove table prefix if present
                if "." in dimension:
                    dimension = dimension.split(".")[-1]
    
    # Fallback if no specific dimension found but group by exists
    if not dimension:
        group_match = re.search(r"group\s+by\s+(.+?)(\s+order|\s+limit|$)", sql, re.DOTALL | re.IGNORECASE)
        if group_match:
            # use first group by col
            dimension = group_match.group(1).split(",")[0].strip()
            
    return {"metric": metric, "dimension": dimension}

def _infer_analysis_type_via_llm(llm: LLMProvider, question: str, sql: str) -> Dict[str, Any]:
    """
    Uses LLM to classify analysis type and refine intent.
    """
    system_prompt = (
        "You are an expert Data Analyst. Analyze the User Question and generated SQL.\n"
        "Determine the 'analysis_type'.\n"
        "Valid types: 'trend' (time-series), 'distribution' (categories), 'kpi' (single value), "
        "'comparison' (ranking/diff), 'list' (raw data), 'other'.\n\n"
        "Also identify the likely 'time_column' used in the query, if any.\n"
        "Output JSON only: {\"analysis_type\": \"...\", \"time_column\": \"...\"}"
    )
    
    user_msg = f"Question: {question}\nSQL: {sql}"
    
    try:
        # Use invoke instead of generate_response
        response = llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ])
        
        # Determine content from response object
        if hasattr(response, "content"):
            content = response.content
        elif isinstance(response, str):
            content = response
        else:
            content = str(response)
            
        # Parse JSON
        if "```" in content:
            content = re.sub(r"```(json)?", "", content).strip()
        
        return json.loads(content)
    except Exception as e:
        log_event("context_inference_error", {"error": str(e)})
        return {"analysis_type": "other", "time_column": None}

def generate_and_save_analysis_context(state: AgentState, llm: LLMProvider) -> None:
    """
    Main entry point. Extracts context from state/SQL and saves to session store.
    """
    # 1. Validate inputs
    if not state.get("sql") or not state.get("user_id"):
        return

    try:
        sql = state.get("sql")
        question = state.get("question")
        user_id = state.get("user_id")
        # Connection ID is not explicitly in AgentState, we typically use 'default' or derive from agent_config if available.
        # Ideally, we should pass agent_config here, but for now let's use a default or assume single connection scope.
        # Wait, AnalysisSessionStore needs connection_id. 
        # In generic_sql_agent, scope might be implied. Let's use 'default' or a placeholder if missing.
        # Or better: derive from chosen_table schema if possible.
        connection_id = "default" 
        
        # 2. Deterministic Extraction
        det_data = _extract_metric_dimension_from_sql(sql)
        
        # 3. LLM Inference
        llm_data = _infer_analysis_type_via_llm(llm, question, sql)
        
        # 4. Construct Context
        # Validated tables
        tables = state.get("chosen_tables") or ([state.get("chosen_table")] if state.get("chosen_table") else [])
        
        # Primary Entity: usually the main table or derived from dimension
        primary_entity = tables[0] if tables else "unknown"
        
        context = AnalysisContext(
            version=1,
            primary_entity=primary_entity,
            primary_metric=det_data["metric"] or "count", # default to count if None/count(*)
            primary_dimension=det_data["dimension"],
            time_column=llm_data.get("time_column"),
            detected_analysis_type=llm_data.get("analysis_type", "other"),
            validated_tables=tables,
            validated_columns=[] # Extracting all columns from SQL regex is complex, leave empty or improve later
        )
        
        # 5. Save
        AnalysisSessionStore.save(user_id, connection_id, context)
        
        log_event("analysis_context_generated", {
            "user_id": user_id,
            "type": context.detected_analysis_type,
            "metric": context.primary_metric
        })
        
    except Exception as e:
        log_event("analysis_context_generation_failed", {"error": str(e)})
