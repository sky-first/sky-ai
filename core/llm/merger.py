from __future__ import annotations

import re
from typing import Dict, List, Any, Optional

from core.agents.generic_sql_agent import AgentState, AgentConfig
from core.llm.providers import LLMProvider
from core.logging_utils import log_event
from core.data_manager.duck_engine import DuckEngine

def _generate_merger_prompt(
    question: str,
    partial_results: List[Dict[str, Any]],
    plan: str
) -> List[Dict[str, str]]:
    """
    Creates the prompt for the Merger agent.
    Describes the partial data (tables) and asks for DuckDB SQL.
    """
    
    # Summarize checks
    data_summary = []
    for i, res in enumerate(partial_results):
        meta = res.get("metadata", {})
        rows = res.get("data", [])
        
        # Determine table name alias
        alias = f"dataset_{i+1}"
        
        columns = []
        row_count = 0
        sample_data = []

        is_arrow = False
        try:
            import pyarrow as pa
            if isinstance(rows, pa.Table):
                is_arrow = True
                columns = rows.column_names
                row_count = rows.num_rows
                sample_data = rows.slice(0, 2).to_pylist()
        except ImportError:
            pass

        if not is_arrow:
            # Fallback List[Dict]
            row_count = len(rows)
            if rows and len(rows) > 0:
                columns = list(rows[0].keys())
            sample_data = rows[:2]
        
        summary = (
            f"--- TABLE '{alias}' ---\n"
            f"Original Source: {meta.get('source', 'Unknown')}\n"
            f"Title: {meta.get('title', 'Unknown')}\n"
            f"Columns: {columns}\n"
            f"Row Count: {row_count}\n"
            f"Sample Data: {sample_data}\n"
        )
        data_summary.append(summary)

    data_block = "\n".join(data_summary)

    system_msg = {
        "role": "system",
        "content": (
            "You are a Data Engineer Expert specializing in DuckDB SQL.\n"
            "You have multiple in-memory tables loaded with data from different sources.\n"
            "Your task is to write a single DuckDB SQL query to join/aggregate these tables to answer the user's question.\n\n"
            "Technical Requirements:\n"
            "1. Use the table names provided (e.g., `dataset_1`, `dataset_2`).\n"
            "2. Ensure all column names referenced actually exist in the tables.\n"
            "3. Output ONLY the valid SQL query (inside ```sql ... ```). No explanations.\n"
            "4. Start with `SELECT`.\n"
            "5. Handle type mismatches (e.g., cast string to int if needed) using DuckDB syntax.\n"
        )
    }

    user_msg = {
        "role": "user",
        "content": (
            f"User Question: {question}\n\n"
            f"Plan Context: {plan}\n\n"
            f"Available Tables (DuckDB):\n{data_block}\n\n"
            "Generate the DuckDB SQL query."
        )
    }

    return [system_msg, user_msg]

def _extract_sql_code(text: str) -> str:
    """Extracts code from ```sql ... ``` blocks."""
    match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Fallback: if no markdown, just return text if it starts with select
    cleaned = text.strip()
    if cleaned.lower().startswith("select"):
        return cleaned
    return cleaned

def run_merger(
    state: AgentState,
    agent_config: AgentConfig,
    llm: LLMProvider
) -> AgentState:
    """
    Merger Node:
    - Consolidates partial_results from multiple Specialists.
    - Uses LLM to generate DuckDB SQL.
    - Executes the SQL using DataManager (DuckEngine).
    """
    question = state.get("question", "")
    partial_results = state.get("partial_results", [])
    plan = state.get("plan", "")

    log_event(
        "merger_start",
        {
            "agent_id": agent_config.id,
            "num_datasets": len(partial_results),
            "question": question[:100]
        }
    )

    if not partial_results:
        state["error"] = "Merger received no partial results."
        return state

    # 1. Generate SQL Logic
    prompt = _generate_merger_prompt(question, partial_results, plan)
    try:
        response = llm.invoke(prompt)
        text_response = response.content if hasattr(response, "content") else str(response)
        sql_query = _extract_sql_code(text_response)
    except Exception as e:
        state["error"] = f"Merger LLM generation failed: {str(e)}"
        return state

    # 2. Execute SQL via DuckEngine
    engine = None
    try:
        engine = DuckEngine()
        
        # Register tables
        for i, res in enumerate(partial_results):
            alias = f"dataset_{i+1}"
            data = res.get("data", [])
            engine.register_data(alias, data)
        
        # Execute Query
        print(f"[Merger] Executing SQL: {sql_query}")
        final_data = engine.execute(sql_query)
        
        state["data"] = final_data
        state["generated_title"] = f"Consolidated Report ({len(partial_results)} Sources)"
        state["sql"] = sql_query  # Save the merger SQL for debugging/explanation
        
        log_event(
            "merger_success",
            {
                "final_rows": len(final_data),
                "sql": sql_query
            }
        )

    except Exception as e:
        state["error"] = f"Merger DuckDB execution failed: {str(e)}"
        log_event(
            "merger_execution_error",
            {
                "error": str(e),
                "sql": sql_query
            }
        )
    finally:
        if engine:
            engine.close()

    return state
