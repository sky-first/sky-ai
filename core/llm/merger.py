from __future__ import annotations

import re
import pandas as pd
from typing import Dict, List, Any, Optional

from core.agents.generic_sql_agent import AgentState, AgentConfig
from core.llm.providers import LLMProvider
from core.logging_utils import log_event

def _generate_merger_prompt(
    question: str,
    partial_results: List[Dict[str, Any]],
    plan: str
) -> List[Dict[str, str]]:
    """
    Creates the prompt for the Merger agent.
    Describes the partial data available and asks for Python pandas code.
    """
    
    # Summarize checks
    data_summary = []
    for i, res in enumerate(partial_results):
        meta = res.get("metadata", {})
        rows = res.get("data", [])
        columns = []
        if rows and len(rows) > 0:
            columns = list(rows[0].keys())
        
        summary = (
            f"--- DATASET {i+1} ---\n"
            f"Source: {meta.get('source', 'Unknown')}\n"
            f"Title: {meta.get('title', 'Unknown')}\n"
            f"Dialect: {meta.get('dialect', 'Unknown')}\n"
            f"Columns: {columns}\n"
            f"Row Count: {len(rows)}\n"
            f"Sample Data: {rows[:2]}\n"
        )
        data_summary.append(summary)

    data_block = "\n".join(data_summary)

    system_msg = {
        "role": "system",
        "content": (
            "You are a Data Engineer Expert in Python and Pandas.\n"
            "You have received multiple datasets (lists of dictionaries) from different sources.\n"
            "Your task is to write a PYTHON SCRIPT to merge/join/aggregate these datasets to answer the user's question.\n\n"
            "Technical Requirements:\n"
            "1. You have a list of DataFrames named `dfs`, where `dfs[0]` corresponds to DATASET 1, `dfs[1]` to DATASET 2, etc.\n"
            "2. You must process them using pandas.\n"
            "3. The final result must be stored in a variable named `final_df`.\n"
            "4. Output ONLY valid Python code block (```python ... ```). NO explanations.\n"
            "5. Do NOT try to read files. Use the variables provided.\n"
            "6. Handle potential missing data or type mismatches gracefully.\n"
            "7. If the question asks to compare, ensure the final format makes comparison easy.\n"
        )
    }

    user_msg = {
        "role": "user",
        "content": (
            f"User Question: {question}\n\n"
            f"Plan Context: {plan}\n\n"
            f"Available Data:\n{data_block}\n\n"
            "Generate the Python Pandas code to produce `final_df`."
        )
    }

    return [system_msg, user_msg]

def _extract_python_code(text: str) -> str:
    """Extracts code from ```python ... ``` blocks."""
    match = re.search(r"```python\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()

def run_merger(
    state: AgentState,
    agent_config: AgentConfig,
    llm: LLMProvider
) -> AgentState:
    """
    Merger Node:
    - Consolidates partial_results from multiple Specialists.
    - Uses LLM to generate Python/Pandas code.
    - Executes the code to produce the final dataset.
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

    # 1. Generate Python Logic
    prompt = _generate_merger_prompt(question, partial_results, plan)
    try:
        response = llm.invoke(prompt)
        text_response = response.content if hasattr(response, "content") else str(response)
        code = _extract_python_code(text_response)
    except Exception as e:
        state["error"] = f"Merger LLM generation failed: {str(e)}"
        return state

    # 2. Execute Python Logic
    try:
        # Prepare DataFrames
        dfs = []
        for res in partial_results:
            dfs.append(pd.DataFrame(res.get("data", [])))
        
        # Execution Environment
        local_scope = {"dfs": dfs, "pd": pd}
        
        # Executing...
        exec(code, {}, local_scope)
        
        final_df = local_scope.get("final_df")
        
        if final_df is None:
            raise ValueError("Python script did not define 'final_df'.")
            
        if not isinstance(final_df, pd.DataFrame):
            # Attempt to convert simple types to DF
            final_df = pd.DataFrame(final_df)

        # 3. Store Result
        # Convert back to list of dicts for the Formatter (and JSON serializability)
        # Handle NaN/Inf for JSON safety via fillna and to_dict
        clean_df = final_df.fillna("").replace([float("inf"), float("-inf")], 0)
        final_data = clean_df.to_dict(orient="records")
        
        state["data"] = final_data
        state["generated_title"] = f"Consolidated Report ({len(dfs)} Sources)"
        
        log_event(
            "merger_success",
            {
                "final_rows": len(final_data),
                "code_preview": code[:100]
            }
        )

    except Exception as e:
        state["error"] = f"Merger Python execution failed: {str(e)}"
        log_event(
            "merger_execution_error",
            {
                "error": str(e),
                "code": code
            }
        )

    return state
